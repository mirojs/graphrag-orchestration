# Benchmark Executive Summary (2025-12-31)

This note summarizes the latest benchmark runs using the 5PDF question bank.

## Environment
- Base URL: https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- Group ID: `test-3072-clean`
- Question bank: [docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md](docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md)

## 1) Repeatability (Vector vs Local; dedicated sets)
**Run:** 10 repeats per question; 10 questions per route set.

- Report (MD): [benchmarks/route1_vector_vs_route2_local_repeat_qbank_20251231T065235Z.md](benchmarks/route1_vector_vs_route2_local_repeat_qbank_20251231T065235Z.md)
- Report (JSON): [benchmarks/route1_vector_vs_route2_local_repeat_qbank_20251231T065235Z.json](benchmarks/route1_vector_vs_route2_local_repeat_qbank_20251231T065235Z.json)

**Key outcome:** In this run, repeatability was perfect for both routes.
- Vector (`Q-V*` forced vector): all 10/10 questions had
  - normalized answer exact rate = 1.00
  - min normalized answer similarity = 1.00
  - min sources Jaccard vs first = 1.00
- Local (`Q-L*` forced local): same (all 1.00 across all 10/10 questions)

**Typical latency / sources (from per-question p50/p90 tables):**
- Vector: p50 roughly ~1.1s; avg sources ~3
- Local: p50 roughly ~1.3–1.7s; avg sources ~10

## 2) Basic 4-route test (10 positive + 10 negative per route)
**Run:** Each route ran its own 10 positives + 10 shared negatives (`Q-N*`).

- Report (MD): [benchmarks/all4_routes_posneg_qbank_20251231T072253Z.md](benchmarks/all4_routes_posneg_qbank_20251231T072253Z.md)
- Report (JSON): [benchmarks/all4_routes_posneg_qbank_20251231T072253Z.json](benchmarks/all4_routes_posneg_qbank_20251231T072253Z.json)

**Correctness checks (coarse):**
- HTTP: 100% 200s
- Negatives: 10/10 “not specified / not found” style responses for each route

**Performance & sources (positives p50/p90; avg sources):**
- vector: 1164/1682 ms; avg src 3.0
- local: 1559/1771 ms; avg src 10.0
- graph (global): 3442/6801 ms; avg src 5.0
- drift: 5982/6685 ms; avg src 0.0

## How to reproduce
Repeatability (dedicated sets):
- `python3 scripts/benchmark_route1_vector_vs_route2_local.py --suite repeat-qbank --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --repeats 10 --sleep 0.3`

Basic 4-route (pos/neg per route):
- `python3 scripts/benchmark_all4_routes_posneg_qbank.py --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --group-id test-3072-clean --sleep 0.1`
