#!/usr/bin/env python3
"""Run a small subset of the Route 3 (global_search) question bank against a deployed Hybrid API.

- Pulls selected Q-* items from QUESTION_BANK_5PDFS_2025-12-24.md
- Calls POST /hybrid/query with force_route=global_search
- Prints latency, HTTP status, theme-term presence (for Q-G4/Q-G5), and a short answer preview

Usage:
  ./scripts/run_route3_question_bank_subset.py \
    --base-url "https://<app>.azurecontainerapps.io" \
    --group-id "<group>" \
    --qids Q-G4,Q-G5 \
    --repeats 1 \
    --timeout-sec 180

Notes:
- Uses only Python stdlib (no requests dependency).
- Intended for fast validation of retrieval fixes (e.g., keyword boost).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]

_CANDIDATES = [
    _ROOT / "QUESTION_BANK_5PDFS_2025-12-24.md",
    _ROOT / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md",
]


def _find_question_bank() -> Path:
    for p in _CANDIDATES:
        if p.exists():
            return p
    return _CANDIDATES[0]


QUESTION_BANK_PATH = _find_question_bank()


EXPECTED_TERMS: dict[str, list[str]] = {
    "Q-G4": ["pumper", "county", "monthly statement", "income", "expenses", "volumes"],
    "Q-G5": ["arbitration", "binding", "small claims", "legal fees", "contractor", "default"],
}


def _extract_questions(md_text: str) -> list[tuple[str, str]]:
    """Return [(qid, question_text)] for Q-* items in file order."""
    # Matches: 1. **Q-G4:** question...
    pattern = re.compile(r"^\s*\d+\.\s+\*\*(Q-[A-Z]\d+):\*\*\s*(.+?)\s*$", re.MULTILINE)
    out: list[tuple[str, str]] = []
    for m in pattern.finditer(md_text):
        qid = (m.group(1) or "").strip()
        q = (m.group(2) or "").strip()
        if qid and q:
            out.append((qid, q))
    return out


def _post_json(url: str, headers: dict[str, str], payload: dict, timeout_sec: int) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body


def _extract_citation_ids(resp: object) -> list[str]:
    if not isinstance(resp, dict):
        return []
    citations = resp.get("citations")
    if not isinstance(citations, list):
        return []
    ids: list[str] = []
    for c in citations:
        if isinstance(c, str):
            ids.append(c)
        elif isinstance(c, dict):
            for key in ("id", "source_id", "doc_id", "document_id", "source", "uri", "url", "chunk_id"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    ids.append(v.strip())
                    break
    return ids


def _extract_evidence_path(resp: object) -> list[str]:
    if not isinstance(resp, dict):
        return []
    path = resp.get("evidence_path")
    if not isinstance(path, list):
        return []
    out: list[str] = []
    for item in path:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            v = item.get("entity") or item.get("name") or item.get("id")
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def _contains_term(text: str, term: str) -> bool:
    # Cheap robustness: ignore whitespace differences.
    t = "".join((text or "").lower().split())
    q = "".join((term or "").lower().split())
    return bool(q) and q in t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://graphrag-orchestration....azurecontainerapps.io")
    ap.add_argument("--group-id", required=True, help="Value for X-Group-ID header")
    ap.add_argument("--timeout-sec", type=int, default=180)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--response-type", default="summary", choices=["summary", "detailed_report", "nlp_audit", "nlp_connected"])
    ap.add_argument("--qids", default="Q-G4,Q-G5", help="Comma-separated list, e.g. Q-G4,Q-G5")
    ap.add_argument("--show-citations", type=int, default=3, help="Print first N citations with section metadata")
    ap.add_argument("--show-metadata", action="store_true", help="Print selected metadata keys (section boost/debug)")
    args = ap.parse_args()

    if not QUESTION_BANK_PATH.exists():
        print(f"ERROR: Question bank not found at {QUESTION_BANK_PATH}", file=sys.stderr)
        return 2

    wanted = {q.strip() for q in (args.qids or "").split(",") if q.strip()}
    if not wanted:
        print("ERROR: No qids requested", file=sys.stderr)
        return 2

    md = QUESTION_BANK_PATH.read_text(encoding="utf-8", errors="replace")
    all_qs = _extract_questions(md)
    picked = [(qid, q) for (qid, q) in all_qs if qid in wanted]

    if not picked:
        print(f"ERROR: Did not find requested qids in question bank: {sorted(wanted)}", file=sys.stderr)
        return 2

    endpoint = args.base_url.rstrip("/") + "/hybrid/query"
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": args.group_id,
    }

    print(f"Endpoint: {endpoint}")
    print(f"Group:    {args.group_id}")
    print(f"Timeout:  {args.timeout_sec}s")
    print(f"Repeats:  {args.repeats}")
    print(f"QIDs:     {', '.join(q for q, _ in picked)}")
    if args.show_citations:
        print(f"Citations to show: {args.show_citations}")
    if args.show_metadata:
        print("Metadata: enabled")
    print("")

    ok = True
    for qid, question in picked:
        print(f"=== {qid} ===")
        print(question)

        for ri in range(int(args.repeats)):
            payload = {
                "query": question,
                "force_route": "global_search",
                "response_type": args.response_type,
            }

            t0 = time.time()
            status, body = _post_json(endpoint, headers=headers, payload=payload, timeout_sec=args.timeout_sec)
            dt = time.time() - t0

            resp: dict = {}
            try:
                resp = json.loads(body) if body else {}
            except Exception:
                resp = {}

            text = str(resp.get("response") or "").strip()
            preview = text.replace("\n", " ")
            if len(preview) > 220:
                preview = preview[:220] + "..."

            citations = _extract_citation_ids(resp)
            ev_path = _extract_evidence_path(resp)

            print(f"run {ri}: HTTP {status} in {dt:.1f}s | citations={len(citations)} | evidence_path={len(ev_path)}")

            if args.show_metadata and isinstance(resp, dict):
                md = resp.get("metadata")
                if isinstance(md, dict) and md:
                    keys = [
                        "ppr_detail_recovery",
                        "section_boost",
                        "keyword_boost",
                        "route3_section_boost_semantic",
                        "route3_section_boost",
                        "route3_strict_high_quality",
                        "seed_candidates",
                        "semantic_section_ids",
                        "top_sections",
                        "boost_added",
                        "boost_added_count",
                    ]
                    printed_any = False
                    for k in keys:
                        if k in md:
                            printed_any = True
                            v = md.get(k)
                            if isinstance(v, (list, dict)):
                                s = json.dumps(v, ensure_ascii=False)
                                if len(s) > 500:
                                    s = s[:500] + "..."
                                print(f"  metadata.{k}: {s}")
                            else:
                                print(f"  metadata.{k}: {v}")
                    if not printed_any:
                        print("  metadata: (no section-boost keys present)")

            # Show section metadata from first few citations
            raw_cits = resp.get("citations") if isinstance(resp, dict) else None
            if args.show_citations and isinstance(raw_cits, list) and raw_cits:
                print(f"  first {min(args.show_citations, len(raw_cits))} citations (section metadata):")
                for i, c in enumerate(raw_cits[: max(0, int(args.show_citations))], 1):
                    if not isinstance(c, dict):
                        continue
                    section = c.get("section", "") or ""
                    chunk_id = c.get("chunk_id", "") or c.get("id", "")
                    entity = c.get("entity", "")
                    doc = c.get("document", "") or c.get("source", "") or c.get("document_title", "")
                    preview = (c.get("text_preview", "") or "")[:120]
                    print(f"    [{i}] section={section!r} | chunk={chunk_id[:30]} | entity={entity} | doc={str(doc)[:60]}")
                    if preview:
                        print(f"        text: {preview}...")

            if qid in EXPECTED_TERMS and text:
                missing = [t for t in EXPECTED_TERMS[qid] if not _contains_term(text, t)]
                matched = [t for t in EXPECTED_TERMS[qid] if t not in missing]
                print(f"theme: matched={len(matched)}/{len(EXPECTED_TERMS[qid])} | missing={missing}")

            print(preview)
            if status >= 400:
                ok = False

        print("")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
