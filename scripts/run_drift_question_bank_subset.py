#!/usr/bin/env python3
"""Run a small subset of the DRIFT question bank against a deployed API.

- Pulls Q-D1..Q-D3 from QUESTION_BANK_5PDFS_2025-12-24.md
- Calls POST /graphrag/v3/query/drift
- Prints latency, HTTP status, answer preview, and sources count

Usage:
  ./scripts/run_drift_question_bank_subset.py \
    --base-url "https://<app>.azurecontainerapps.io" \
    --group-id "<group>" \
    --timeout-sec 120

Notes:
- Uses only Python stdlib (no requests dependency).
- Designed to be run after deploying code changes.
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


QUESTION_BANK_PATH = Path(__file__).resolve().parents[1] / "QUESTION_BANK_5PDFS_2025-12-24.md"


def _extract_drift_questions(md_text: str, *, max_items: int = 3) -> list[tuple[str, str]]:
    """Return [(qid, question_text)] for Q-D1.. in file order."""
    # Matches: 1. **Q-D1:** question...
    pattern = re.compile(r"^\s*\d+\.\s+\*\*(Q-D\d+):\*\*\s*(.+?)\s*$", re.MULTILINE)
    out: list[tuple[str, str]] = []
    for m in pattern.finditer(md_text):
        qid = (m.group(1) or "").strip()
        q = (m.group(2) or "").strip()
        if not qid.startswith("Q-D"):
            continue
        out.append((qid, q))
        if len(out) >= max_items:
            break
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://graphrag-orchestration....azurecontainerapps.io")
    ap.add_argument("--group-id", required=True, help="Value for X-Group-ID header")
    ap.add_argument("--timeout-sec", type=int, default=120)
    ap.add_argument("--max-iterations", type=int, default=2)
    ap.add_argument("--include-sources", action="store_true", default=True)
    ap.add_argument("--no-include-sources", action="store_false", dest="include_sources")
    ap.add_argument("--include-reasoning", action="store_true", default=True)
    ap.add_argument("--no-include-reasoning", action="store_false", dest="include_reasoning")
    args = ap.parse_args()

    if not QUESTION_BANK_PATH.exists():
        print(f"ERROR: Question bank not found at {QUESTION_BANK_PATH}", file=sys.stderr)
        return 2

    md = QUESTION_BANK_PATH.read_text(encoding="utf-8", errors="replace")
    qs = _extract_drift_questions(md, max_items=3)
    if not qs:
        print("ERROR: Could not find any Q-D questions in question bank", file=sys.stderr)
        return 2

    endpoint = args.base_url.rstrip("/") + "/graphrag/v3/query/drift"
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": args.group_id,
    }

    print(f"Endpoint: {endpoint}")
    print(f"Group:    {args.group_id}")
    print(f"Timeout:  {args.timeout_sec}s")
    print("")

    ok = True
    for qid, q in qs:
        payload = {
            "query": q,
            "max_iterations": args.max_iterations,
            "convergence_threshold": 0.8,
            "include_sources": bool(args.include_sources),
            "include_reasoning_path": bool(args.include_reasoning),
        }

        t0 = time.time()
        try:
            status, body = _post_json(endpoint, headers=headers, payload=payload, timeout_sec=args.timeout_sec)
            dt = time.time() - t0
        except Exception as e:
            dt = time.time() - t0
            print(f"{qid}: ERROR after {dt:.1f}s: {type(e).__name__}: {e}")
            ok = False
            continue

        answer_preview = ""
        sources_count = None
        try:
            j = json.loads(body) if body else {}
            answer_preview = str(j.get("answer") or j.get("response") or "").strip().replace("\n", " ")[:160]
            sources = j.get("sources")
            if isinstance(sources, list):
                sources_count = len(sources)
        except Exception:
            answer_preview = (body or "").strip().replace("\n", " ")[:160]

        sc = "?" if sources_count is None else str(sources_count)
        print(f"{qid}: HTTP {status} in {dt:.1f}s | sources={sc} | {answer_preview}")

        if status >= 400:
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
