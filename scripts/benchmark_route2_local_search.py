#!/usr/bin/env python3

"""Repeatability benchmark for Route-2 (Local Search) via the Hybrid API.

This benchmark targets the *Local Search* "Route 2" implementation exposed through:
  POST /hybrid/query  (force_route=local_search)

Route 2 uses HippoRAG entity retrieval with LazyGraphRAG local search.

Scenario
- Uses response_type=summary (LLM synthesis, concise mode)
- Tests Q-L1-Q-L10 (positive: local/entity-focused questions)
- Tests Q-N1-Q-N10 (negative: should return "not found")

Outputs
- Writes JSON + MD into ./benchmarks/

Usage
  python3 scripts/benchmark_hybrid_route2_repeatability.py \
    --url https://...azurecontainerapps.io \
    --group-id <group> \
    --repeats 10

Dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class GroundTruth:
    """Ground truth answer from question bank."""
    qid: str
    question: str
    expected: str
    is_negative: bool  # True for Q-N questions

DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

DEFAULT_QUESTION_BANK = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    return "".join(
        [
            # prefer last_test_group_id.txt if available
            _read_text_maybe(Path(__file__).resolve().parents[1] / "last_test_group_id.txt")
            or ""
        ]
    ).strip() or "test-5pdfs-latest"


def _read_text_maybe(p: Path) -> Optional[str]:
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            return s or None
    except Exception:
        return None
    return None


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 $%./:-]", "", t)
    return t


def _extract_ground_truth(question_bank_path: Path) -> Dict[str, GroundTruth]:
    """Parse question bank to extract ground truth answers."""
    content = question_bank_path.read_text(encoding='utf-8')
    ground_truth: Dict[str, GroundTruth] = {}
    lines = content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^(\d+)\.\s+\*\*(Q-[A-Z]\d+):\*\*\s+(.+)', line)
        if match:
            qid = match.group(2).strip()
            question = match.group(3).strip()
            expected = ""
            is_negative = qid.startswith("Q-N")
            
            # For negative tests, expected answer is "not specified"
            if is_negative:
                expected = "not specified"
            else:
                # Look ahead for Expected field
                j = i + 1
                while j < len(lines) and not re.match(r'^\d+\.\s+\*\*Q-', lines[j]):
                    line_content = lines[j].strip()
                    exp_match = re.match(r'-\s+\*\*Expected:\*\*\s*(.*)$', line_content)
                    if exp_match:
                        expected = exp_match.group(1).strip() if exp_match.group(1) else ""
                        # Handle multi-line expected answers
                        k = j + 1
                        while k < len(lines):
                            next_line = lines[k].strip()
                            if re.match(r'-\s+\*\*(?:Source|Expected):', next_line):
                                break
                            if re.match(r'^\d+\.\s+\*\*Q-', next_line) or next_line.startswith('##'):
                                break
                            if not next_line:
                                if k + 1 < len(lines):
                                    peek = lines[k + 1].strip()
                                    if peek and not re.match(r'-\s+\*\*', peek) and not re.match(r'^\d+\.', peek):
                                        k += 1
                                        continue
                                break
                            if next_line.startswith('-'):
                                expected += ' ' + next_line[1:].strip()
                            else:
                                expected += ' ' + next_line
                            k += 1
                        break
                    j += 1
            
            # Clean up expected answer
            expected = re.sub(r'`', '', expected)
            expected = re.sub(r'\*\*', '', expected)
            expected = re.sub(r'\s+', ' ', expected).strip()
            
            if expected or is_negative:
                ground_truth[qid] = GroundTruth(
                    qid=qid,
                    question=question,
                    expected=expected,
                    is_negative=is_negative
                )
        i += 1
    
    return ground_truth


def _calculate_accuracy_metrics(expected: str, actual: str, is_negative: bool) -> Dict[str, Any]:
    """Calculate accuracy metrics comparing actual response to ground truth."""
    if is_negative:
        # For negative tests, check if response indicates "not found/specified"
        actual_lower = actual.lower()
        not_found_phrases = [
            'not specified', 'not found', 'not mentioned', 'not provided',
            'no information', 'not available', 'not included', 'not stated',
            'does not contain', 'not referenced', 'not present'
        ]
        passes_negative = any(phrase in actual_lower for phrase in not_found_phrases)
        
        return {
            'is_negative_test': True,
            'negative_test_pass': passes_negative,
            'exact_match': None,
            'fuzzy_score': None,
            'containment': None,
            'precision': None,
            'recall': None,
            'f1_score': None,
        }
    
    # Positive test: compare against ground truth
    expected_norm = _normalize_text(expected)
    actual_norm = _normalize_text(actual)
    
    # Exact match
    exact = expected_norm == actual_norm
    
    # Fuzzy match (string similarity)
    fuzzy = float(difflib.SequenceMatcher(None, expected_norm, actual_norm).ratio())
    
    # Containment (expected found in actual)
    contained = expected_norm in actual_norm if expected_norm else False
    
    # Token-level metrics
    expected_tokens = set(expected_norm.split())
    actual_tokens = set(actual_norm.split())
    
    if not expected_tokens or not actual_tokens:
        precision = recall = f1 = 0.0
    else:
        overlap = expected_tokens.intersection(actual_tokens)
        precision = len(overlap) / len(actual_tokens) if actual_tokens else 0.0
        recall = len(overlap) / len(expected_tokens) if expected_tokens else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        'is_negative_test': False,
        'negative_test_pass': None,
        'exact_match': exact,
        'fuzzy_score': round(fuzzy, 3),
        'containment': contained,
        'precision': round(precision, 3),
        'recall': round(recall, 3),
        'f1_score': round(f1, 3),
    }


def _similarity(a: str, b: str) -> float:
    return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())


def _percentile(values: List[int], p: float) -> int:
    if not values:
        return 0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    xs = sorted(values)
    k = int(round((p / 100.0) * (len(xs) - 1)))
    k = max(0, min(k, len(xs) - 1))
    return int(xs[k])


def _jaccard(a: List[str], b: List[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return float(len(sa & sb) / len(sa | sb))


def _http_post_json(
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_s: float,
) -> Tuple[int, Any, float, Optional[str]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.monotonic() - t0
            try:
                return int(resp.status), json.loads(raw), elapsed, None
            except Exception:
                return int(resp.status), {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = None
        return int(getattr(e, "code", 0) or 0), {"error": str(e), "body": body}, elapsed, str(e)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


def _read_question_bank(path: Path, *, positive_prefix: str = "Q-L", negative_prefix: str = "Q-N") -> List[BankQuestion]:
    """Read questions from question bank (positive + negative tests)."""
    questions: List[BankQuestion] = []
    
    # Read positive questions
    pattern_pos = re.compile(rf"\*\*({re.escape(positive_prefix)}\d+):\*\*\s*(.+?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern_pos.search(line)
        if m:
            qid, qtext = m.group(1).strip(), m.group(2).strip()
            if qid and qtext:
                questions.append(BankQuestion(qid=qid, query=qtext))
    
    # Read negative questions
    pattern_neg = re.compile(rf"\*\*({re.escape(negative_prefix)}\d+):\*\*\s*(.+?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern_neg.search(line)
        if m:
            qid, qtext = m.group(1).strip(), m.group(2).strip()
            if qid and qtext:
                questions.append(BankQuestion(qid=qid, query=qtext))
    
    if not questions:
        raise RuntimeError(f"No {positive_prefix}* or {negative_prefix}* questions found in {path}")
    return questions


def _extract_citation_ids(resp: Any) -> List[str]:
    if not isinstance(resp, dict):
        return []
    citations = resp.get("citations")
    if not isinstance(citations, list):
        return []
    ids: List[str] = []
    for c in citations:
        if isinstance(c, str):
            ids.append(c)
        elif isinstance(c, dict):
            # Prefer stable identifiers if present.
            for key in ("id", "source_id", "doc_id", "document_id", "source", "uri", "url", "chunk_id"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    ids.append(v.strip())
                    break
            else:
                # Fall back to a compact normalized string of the dict.
                try:
                    ids.append(json.dumps(c, sort_keys=True)[:200])
                except Exception:
                    pass
    return ids


def _extract_evidence_path(resp: Any) -> List[str]:
    if not isinstance(resp, dict):
        return []
    path = resp.get("evidence_path")
    if not isinstance(path, list):
        return []
    out: List[str] = []
    for item in path:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            v = item.get("entity") or item.get("name") or item.get("id")
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def _summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [r.get("text", "") for r in runs]
    texts_norm = [r.get("text_norm", "") for r in runs]
    ms = [int(r.get("elapsed_ms", 0)) for r in runs if isinstance(r.get("elapsed_ms"), int)]

    first_norm = texts_norm[0] if texts_norm else ""
    sims = [_similarity(first_norm, t) for t in texts_norm] if texts_norm else []

    exact_norm = sum(1 for t in texts_norm if t == first_norm)

    cite_sigs = [r.get("citations_sig", []) for r in runs]
    path_sigs = [r.get("evidence_path_sig", []) for r in runs]

    citations_jacc = []
    evidence_jacc = []
    if cite_sigs:
        base = cite_sigs[0]
        citations_jacc = [_jaccard(base, x) for x in cite_sigs[1:]]
    if path_sigs:
        base = path_sigs[0]
        evidence_jacc = [_jaccard(base, x) for x in path_sigs[1:]]

    return {
        "text_norm_exact_rate": float(exact_norm / len(runs)) if runs else 0.0,
        "text_norm_min_similarity": float(min(sims) if sims else 0.0),
        "citations_unique": len({json.dumps(x, sort_keys=True) for x in cite_sigs}),
        "evidence_path_unique": len({json.dumps(x, sort_keys=True) for x in path_sigs}),
        "citations_jaccard_min": float(min(citations_jacc) if citations_jacc else 1.0),
        "evidence_path_jaccard_min": float(min(evidence_jacc) if evidence_jacc else 1.0),
        "latency_ms_p50": _percentile(ms, 50),
        "latency_ms_p95": _percentile(ms, 95),
        "latency_ms_min": int(min(ms) if ms else 0),
        "latency_ms_max": int(max(ms) if ms else 0),
    }


def benchmark_scenario(
    *,
    api_base_url: str,
    group_id: str,
    questions: List[BankQuestion],
    scenario_name: str,
    response_type: str,
    repeats: int,
    timeout_s: float,
    ground_truth: Dict[str, GroundTruth],
) -> Dict[str, Any]:
    print(f"\n{'=' * 70}")
    print(f"Scenario: {scenario_name} (response_type={response_type})")
    print(f"Questions: {len(questions)}, Repeats: {repeats}")
    print(f"{'=' * 70}\n")

    url = f"{api_base_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}

    results: List[Dict[str, Any]] = []

    for q_obj in questions:
        qid, query = q_obj.qid, q_obj.query
        print(f"[{qid}] {query}")

        runs: List[Dict[str, Any]] = []
        for rep in range(1, repeats + 1):
            payload = {
                "query": query,
                "force_route": "local_search",  # Route 2
                "response_type": response_type,
            }

            status, resp, elapsed, err = _http_post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_s=timeout_s,
            )

            if status != 200:
                print(f"  [{rep}/{repeats}] HTTP {status} - {err or resp.get('error', 'unknown')}")
                continue

            answer = resp.get("response", "")
            text_norm = _normalize_text(answer)
            citations_sig = _extract_citation_ids(resp)
            evidence_path_sig = _extract_evidence_path(resp)
            elapsed_ms = int(elapsed * 1000)

            print(f"  [{rep}/{repeats}] {elapsed_ms}ms - {len(answer)} chars")

            runs.append(
                {
                    "run": rep,
                    "text": answer,
                    "text_norm": text_norm,
                    "citations_sig": citations_sig,
                    "evidence_path_sig": evidence_path_sig,
                    "elapsed_ms": elapsed_ms,
                    "full_response": resp,
                }
            )

        summary = _summarize_runs(runs) if runs else {}
        
        # Calculate accuracy metrics
        accuracy_metrics = {}
        if qid in ground_truth and runs:
            gt = ground_truth[qid]
            # Use first run for accuracy check (all repeats should be similar)
            actual_answer = runs[0].get("text", "")
            accuracy_metrics = _calculate_accuracy_metrics(
                expected=gt.expected,
                actual=actual_answer,
                is_negative=gt.is_negative
            )
            
            # Add to console output
            if gt.is_negative:
                passed = accuracy_metrics.get("negative_test_pass", False)
                print(f"  Accuracy: NEGATIVE_TEST {'PASS' if passed else 'FAIL'}")
            else:
                containment = accuracy_metrics.get("containment", 0.0)
                f1 = accuracy_metrics.get("f1_score", 0.0)
                print(f"  Accuracy: containment={containment:.2f}, f1={f1:.2f}")
        
        results.append(
            {
                "qid": qid,
                "query": query,
                "runs": runs,
                "summary": summary,
                "accuracy": accuracy_metrics,
            }
        )

        if summary:
            print(
                f"  Summary: exact={summary['text_norm_exact_rate']:.2f}, "
                f"min_sim={summary['text_norm_min_similarity']:.2f}, "
                f"latency_p50={summary['latency_ms_p50']}ms"
            )

    return {
        "scenario": scenario_name,
        "response_type": response_type,
        "questions": results,
    }


def _write_analysis_md(
    out_md: Path,
    timestamp: str,
    api_base_url: str,
    group_id: str,
    scenario_results: List[Dict[str, Any]],
):
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Route 2 (Local Search) Repeatability Benchmark\n\n")
        f.write(f"**Timestamp:** {timestamp}\n\n")
        f.write(f"**API Base URL:** `{api_base_url}`\n\n")
        f.write(f"**Group ID:** `{group_id}`\n\n")
        f.write(f"**Force Route:** `local_search`\n\n")
        f.write("---\n\n")

        for sc in scenario_results:
            f.write(f"## Scenario: {sc['scenario']}\n\n")
            f.write(f"**Response Type:** `{sc['response_type']}`\n\n")

            questions = sc["questions"]
            for q in questions:
                qid = q["qid"]
                query = q["query"]
                summary = q.get("summary", {})
                accuracy = q.get("accuracy", {})
                runs = q.get("runs", [])

                f.write(f"### {qid}: {query}\n\n")

                if not runs:
                    f.write("**No successful runs.**\n\n")
                    continue

                f.write(f"**Runs:** {len(runs)}\n\n")
                
                # Accuracy Metrics
                if accuracy:
                    f.write("**Accuracy Metrics:**\n\n")
                    f.write("| Metric | Value |\n")
                    f.write("|--------|-------|\n")
                    
                    if accuracy.get("is_negative", False):
                        passed = accuracy.get("negative_test_pass", False)
                        f.write(f"| Negative Test | {'✅ PASS' if passed else '❌ FAIL'} |\n")
                    else:
                        f.write(f"| Exact Match | {'✅' if accuracy.get('exact_match', False) else '❌'} |\n")
                        f.write(f"| Fuzzy Score | {accuracy.get('fuzzy_score', 0):.2f} |\n")
                        f.write(f"| Containment | {accuracy.get('containment', 0):.2f} |\n")
                        f.write(f"| Precision | {accuracy.get('precision', 0):.2f} |\n")
                        f.write(f"| Recall | {accuracy.get('recall', 0):.2f} |\n")
                        f.write(f"| F1 Score | {accuracy.get('f1_score', 0):.2f} |\n")
                    f.write("\n")
                
                # Repeatability Metrics
                f.write("**Repeatability Metrics:**\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(f"| Exact Match Rate | {summary.get('text_norm_exact_rate', 0):.2f} |\n")
                f.write(f"| Min Similarity | {summary.get('text_norm_min_similarity', 0):.2f} |\n")
                f.write(f"| Citations (Unique) | {summary.get('citations_unique', 0)} |\n")
                f.write(f"| Evidence Path (Unique) | {summary.get('evidence_path_unique', 0)} |\n")
                f.write(f"| Citations Jaccard (Min) | {summary.get('citations_jaccard_min', 0):.2f} |\n")
                f.write(f"| Evidence Path Jaccard (Min) | {summary.get('evidence_path_jaccard_min', 0):.2f} |\n")
                f.write(f"| Latency P50 (ms) | {summary.get('latency_ms_p50', 0)} |\n")
                f.write(f"| Latency P95 (ms) | {summary.get('latency_ms_p95', 0)} |\n")
                f.write(f"| Latency Min (ms) | {summary.get('latency_ms_min', 0)} |\n")
                f.write(f"| Latency Max (ms) | {summary.get('latency_ms_max', 0)} |\n")
                f.write("\n")

                # Show first two answers for comparison
                for r in runs[:2]:
                    ans = r.get("text", "")
                    f.write(f"**Run {r['run']} ({r.get('elapsed_ms', 0)}ms):**\n\n")
                    f.write(f"```\n{ans[:500]}{'...' if len(ans) > 500 else ''}\n```\n\n")

            f.write("---\n\n")


def main():
    parser = argparse.ArgumentParser(
        description="Route 2 (Local Search) repeatability benchmark via Hybrid API."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="API base URL (default: env GRAPHRAG_CLOUD_URL or internal default)",
    )
    parser.add_argument(
        "--group-id",
        default=_default_group_id(),
        help="The group_id to query (default: from env or last_test_group_id.txt)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of times to repeat each question (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="HTTP request timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--qbank",
        type=Path,
        default=DEFAULT_QUESTION_BANK,
        help="Path to question bank MD file (default: QUESTION_BANK_5PDFS_2025-12-24.md)",
    )

    args = parser.parse_args()

    qbank_path: Path = args.qbank
    if not qbank_path.exists():
        raise FileNotFoundError(f"Question bank not found: {qbank_path}")

    # Read questions (positive Q-L + negative Q-N)
    questions = _read_question_bank(qbank_path, positive_prefix="Q-L", negative_prefix="Q-N")
    print(f"Loaded {len(questions)} questions from {qbank_path.name}")
    
    positive_count = sum(1 for q in questions if q.qid.startswith("Q-L"))
    negative_count = sum(1 for q in questions if q.qid.startswith("Q-N"))
    print(f"  Positive tests (Q-L): {positive_count}")
    print(f"  Negative tests (Q-N): {negative_count}")
    
    # Load ground truth
    ground_truth = _extract_ground_truth(qbank_path)
    print(f"Loaded {len(ground_truth)} ground truth answers")

    # Single scenario: summary mode
    scenario_name = "hybrid_route2_summary"
    response_type = "summary"

    timestamp = _now_utc_stamp()

    result = benchmark_scenario(
        api_base_url=args.url,
        group_id=args.group_id,
        questions=questions,
        scenario_name=scenario_name,
        response_type=response_type,
        repeats=args.repeats,
        timeout_s=args.timeout,
        ground_truth=ground_truth,
    )

    # Write outputs
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_json = out_dir / f"route2_local_search_{timestamp}.json"
    out_md = out_dir / f"route2_local_search_{timestamp}.md"

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "api_base_url": args.url,
                "group_id": args.group_id,
                "force_route": "local_search",
                "response_type": response_type,
                "scenario": result,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    _write_analysis_md(
        out_md=out_md,
        timestamp=timestamp,
        api_base_url=args.url,
        group_id=args.group_id,
        scenario_results=[result],
    )

    print(f"\n{'=' * 70}")
    print(f"✅ Benchmark complete!")
    print(f"   JSON: {out_json}")
    print(f"   MD:   {out_md}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
