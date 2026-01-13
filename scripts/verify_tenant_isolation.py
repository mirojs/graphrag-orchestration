#!/usr/bin/env python3
"""Verify tenant (group) isolation for the Hybrid Route 3 endpoint.

This script calls the same endpoint twice with two different `X-Group-ID` headers
and compares the returned citations.

Why this is useful:
- If group A and group B have disjoint corpora, their citation sources should also
  be disjoint (or nearly so). Any overlap can indicate a missing `group_id` filter.

Example:
  python3 scripts/verify_tenant_isolation.py \
    --base-url https://<app-host> \
    --group-a tenantA --group-b tenantB \
    --query "What are the main compliance risks?" \
    --fail-on-overlap

Notes:
- Default endpoint path is `/hybrid/query`.
- Default request forces Route 3 global search via `force_route=global_search`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import socket
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _http_post_json(url: str, *, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"HTTP {e.code} calling {url}: {raw[:2000]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}") from e
    except (TimeoutError, socket.timeout) as e:
        raise RuntimeError(f"Timed out calling {url}: {e}") from e


def _pick_working_endpoint(
    *,
    base_url: str,
    candidate_paths: Sequence[str],
    group_id: str,
    payload: Dict[str, Any],
    timeout_s: float,
) -> str:
    """Pick the first endpoint that responds successfully.

    We treat 404/405 as "wrong path" and try the next candidate.
    Any other HTTP error likely indicates the route exists but the request failed,
    so we surface it to help debugging.
    """

    base = base_url.rstrip("/")
    last_404: Optional[Exception] = None

    for path in candidate_paths:
        path_norm = path if path.startswith("/") else f"/{path}"
        url = f"{base}{path_norm}"
        try:
            _http_post_json(
                url,
                headers={"X-Group-ID": group_id},
                payload=payload,
                timeout_s=timeout_s,
            )
            return path_norm
        except RuntimeError as e:
            msg = str(e)
            if "HTTP 404" in msg or "HTTP 405" in msg:
                last_404 = e
                continue
            raise

    if last_404:
        raise last_404
    raise RuntimeError("No candidate endpoints were provided")


def _looks_like_api_v1_is_present(base_url: str, timeout_s: float = 5.0) -> bool:
    """Heuristic: if /api/v1/openapi.json responds, assume paths are prefixed."""

    url = f"{base_url.rstrip('/')}/api/v1/openapi.json"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= int(getattr(resp, "status", 200)) < 400
    except Exception:
        return False


def _coalesce(*vals: Any) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return str(v)
    return None


def _iter_citations(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    citations = resp.get("citations")
    if isinstance(citations, list):
        return [c for c in citations if isinstance(c, dict)]
    return []


def _citation_source_key(c: Dict[str, Any]) -> str:
    # We try multiple common shapes; keep this stable so overlap checking is meaningful.
    meta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}

    key = _coalesce(
        c.get("source"),
        c.get("url"),
        c.get("document_id"),
        c.get("doc_id"),
        meta.get("source"),
        meta.get("url"),
        meta.get("document_id"),
        meta.get("doc_id"),
        meta.get("title"),
    )
    if key is None:
        # As a last resort, hash the first 80 chars of text.
        text = _coalesce(c.get("text"), meta.get("text"), "") or ""
        return f"text:{text[:80]}"

    # Normalize to reduce meaningless differences.
    return re.sub(r"\s+", " ", key.strip())


def _summarize(resp: Dict[str, Any]) -> Dict[str, Any]:
    citations = _iter_citations(resp)
    keys = [_citation_source_key(c) for c in citations]
    unique_keys = sorted(set(keys))

    return {
        "route_used": resp.get("route_used"),
        "citations": citations,
        "citation_keys": keys,
        "unique_citation_keys": unique_keys,
        "unique_citation_count": len(unique_keys),
        "citation_count": len(citations),
        "metadata": resp.get("metadata") if isinstance(resp.get("metadata"), dict) else {},
    }


def _matches_any(pattern: Optional[str], values: Sequence[str]) -> bool:
    if not pattern:
        return True
    rx = re.compile(pattern)
    return any(bool(rx.search(v)) for v in values)


def _matches_none(pattern: Optional[str], values: Sequence[str]) -> bool:
    if not pattern:
        return True
    rx = re.compile(pattern)
    return not any(bool(rx.search(v)) for v in values)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True, help="Base URL, e.g. https://<host>")
    p.add_argument(
        "--path",
        default=None,
        help="Endpoint path. If omitted, probes /hybrid/query then /api/v1/hybrid/query.",
    )
    p.add_argument("--group-a", required=True, help="Tenant/group ID for run A")
    p.add_argument("--group-b", required=True, help="Tenant/group ID for run B")
    p.add_argument("--query", required=True, help="Query text")
    p.add_argument("--response-type", default="summary", help="Hybrid response_type (default: summary)")
    p.add_argument("--force-route", default="global_search", help="force_route enum value (default: global_search)")
    p.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout seconds")

    # Validation knobs
    p.add_argument("--expect-a", default=None, help="Regex expected to appear in at least one A citation key")
    p.add_argument("--expect-b", default=None, help="Regex expected to appear in at least one B citation key")
    p.add_argument("--forbid-a", default=None, help="Regex that must NOT appear in any A citation key")
    p.add_argument("--forbid-b", default=None, help="Regex that must NOT appear in any B citation key")
    p.add_argument(
        "--fail-on-overlap",
        action="store_true",
        help="Fail (exit 2) if citation-key overlap is non-empty",
    )

    args = p.parse_args(argv)

    base = args.base_url.rstrip("/")

    payload = {
        "query": args.query,
        "response_type": args.response_type,
        "force_route": args.force_route,
    }

    if args.path:
        path = args.path if args.path.startswith("/") else f"/{args.path}"
    else:
        # Reliable auto-detection: check for API v1 prefix via OpenAPI URL.
        # Avoid POST-probing the query endpoint, which can be slow.
        if _looks_like_api_v1_is_present(base):
            path = "/api/v1/hybrid/query"
        else:
            path = "/hybrid/query"

    url = f"{base}{path}"
    print(f"[INFO] url={url}")

    def _call_both(u: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        a = _http_post_json(
            u,
            headers={"X-Group-ID": args.group_a},
            payload=payload,
            timeout_s=args.timeout,
        )
        b = _http_post_json(
            u,
            headers={"X-Group-ID": args.group_b},
            payload=payload,
            timeout_s=args.timeout,
        )
        return a, b

    try:
        resp_a, resp_b = _call_both(url)
    except RuntimeError as e:
        msg = str(e)
        # Some deployments expose OpenAPI under /api/v1 but routes at root.
        if ("HTTP 404" in msg or "HTTP 405" in msg) and args.path is None:
            alt_path = "/hybrid/query" if path.startswith("/api/") else "/api/v1/hybrid/query"
            alt_url = f"{base}{alt_path}"
            print(f"[WARN] {path} failed; retrying {alt_path}")
            resp_a, resp_b = _call_both(alt_url)
            url = alt_url
        else:
            raise

    sum_a = _summarize(resp_a)
    sum_b = _summarize(resp_b)

    keys_a = sum_a["unique_citation_keys"]
    keys_b = sum_b["unique_citation_keys"]
    overlap = sorted(set(keys_a) & set(keys_b))

    print("\n=== A ===")
    print(f"group={args.group_a} route_used={sum_a['route_used']} citations={sum_a['citation_count']} unique_sources={sum_a['unique_citation_count']}")
    for k in keys_a[:10]:
        print(f"  - {k}")

    print("\n=== B ===")
    print(f"group={args.group_b} route_used={sum_b['route_used']} citations={sum_b['citation_count']} unique_sources={sum_b['unique_citation_count']}")
    for k in keys_b[:10]:
        print(f"  - {k}")

    print("\n=== Overlap ===")
    print(f"overlap_count={len(overlap)}")
    for k in overlap[:30]:
        print(f"  - {k}")

    ok = True

    if not _matches_any(args.expect_a, keys_a):
        print(f"[FAIL] --expect-a pattern not found in group A citations: {args.expect_a}", file=sys.stderr)
        ok = False

    if not _matches_any(args.expect_b, keys_b):
        print(f"[FAIL] --expect-b pattern not found in group B citations: {args.expect_b}", file=sys.stderr)
        ok = False

    if not _matches_none(args.forbid_a, keys_a):
        print(f"[FAIL] --forbid-a pattern unexpectedly found in group A citations: {args.forbid_a}", file=sys.stderr)
        ok = False

    if not _matches_none(args.forbid_b, keys_b):
        print(f"[FAIL] --forbid-b pattern unexpectedly found in group B citations: {args.forbid_b}", file=sys.stderr)
        ok = False

    if args.fail_on_overlap and overlap:
        print("[FAIL] Citation overlap detected and --fail-on-overlap is set.", file=sys.stderr)
        return 2

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
