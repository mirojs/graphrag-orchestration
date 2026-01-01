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

## 3) Repeatability (Graph vs Drift; dedicated sets)
**Run:** 10 repeats per question; 10 questions per route set.

- Report (MD): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T073137Z.md](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T073137Z.md)
- Report (JSON): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T073137Z.json](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T073137Z.json)

**Key outcomes (aggregates across all repeats):**
- Graph (`Q-G*` forced graph):
  - HTTP: 100/100 200s
  - p50/p90 latency: 3265/5640 ms
  - avg sources: 5.0 (stable; min sources Jaccard vs first = 1.00 for all questions)
  - avg normalized answer exact rate (per-question average): 0.44
- Drift (`Q-D*` forced drift):
  - HTTP: 100/100 200s
  - p50/p90 latency: 5138/6938 ms
  - avg sources: 0.0 (sources Jaccard is trivially 1.00 because sources are empty)
  - avg normalized answer exact rate (per-question average): 0.10

### 3a) Follow-up: Dedicated endpoints (more faithful sources/debug)
These runs use the dedicated endpoints instead of forcing routes through `/graphrag/v3/query`:
- graph → `/graphrag/v3/query/global`
- drift → `/graphrag/v3/query/drift`

#### repeats=2
- Report (MD): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T082150Z.md](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T082150Z.md)
- Report (JSON): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T082150Z.json](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T082150Z.json)
- Analysis (MD): [benchmarks/analysis_route3_route4_repeatability_dedicated_20260101T082150Z.md](benchmarks/analysis_route3_route4_repeatability_dedicated_20260101T082150Z.md)

**Key outcome (dedicated, `--no-synthesize`):**
- Graph: perfectly repeatable (exact=1.00; min similarity=1.00; sources Jaccard=1.00)
- Drift: sources are non-empty and repeatable (sources Jaccard=1.00), but answers are still variable (exact_avg=0.50; minsim_avg≈0.266)

#### repeats=2 (graph synthesize enabled)
- Report (MD): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T083616Z.md](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T083616Z.md)
- Report (JSON): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T083616Z.json](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T083616Z.json)
- Analysis (MD): [benchmarks/analysis_route3_route4_repeatability_dedicated_synthesize_true_20260101T083616Z.md](benchmarks/analysis_route3_route4_repeatability_dedicated_synthesize_true_20260101T083616Z.md)

**Key outcome (dedicated, `--synthesize`):**
- Graph: becomes non-repeatable while sources stay stable (sources Jaccard=1.00; exact_avg=0.70)
- Drift: remains non-repeatable; sources present but not perfectly stable (sources min Jaccard < 1.00 on some questions)

#### repeats=3 (dedicated comparison)
- No-synthesize:
  - Report (MD): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T085153Z.md](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T085153Z.md)
  - Report (JSON): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T085153Z.json](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T085153Z.json)
  - Analysis (MD): [benchmarks/analysis_route3_route4_repeat3_nosynth_20260101T085153Z.md](benchmarks/analysis_route3_route4_repeat3_nosynth_20260101T085153Z.md)
- Synthesize:
  - Report (MD): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T091704Z.md](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T091704Z.md)
  - Report (JSON): [benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T091704Z.json](benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T091704Z.json)
  - Analysis (MD): [benchmarks/analysis_route3_route4_repeat3_synth_20260101T091704Z.md](benchmarks/analysis_route3_route4_repeat3_synth_20260101T091704Z.md)

**Aggregate highlights (repeats=3):**
- Graph:
  - `--no-synthesize`: exact_avg=1.000; sources_min_jacc_avg=1.000
  - `--synthesize`: exact_avg=0.800; sources_min_jacc_avg=1.000
- Drift:
  - `--no-synthesize`: exact_avg=0.333; sources_min_jacc_avg=0.867
  - `--synthesize`: exact_avg=0.333; sources_min_jacc_avg=0.833

**Interpretation:** graph retrieval is stable; synthesis is the variability source for graph answers. Drift shows both answer variability and some source-set variability across repeats.

## How to reproduce
Repeatability (dedicated sets):
- `python3 scripts/benchmark_route1_vector_vs_route2_local.py --suite repeat-qbank --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --repeats 10 --sleep 0.3`

Repeatability (graph vs drift; dedicated sets):
- `python3 scripts/benchmark_route3_graph_vs_route4_drift.py --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --group-id test-3072-clean --repeats 10 --sleep 0.3`

Repeatability (graph vs drift; dedicated endpoints, investigation mode):
- `python3 scripts/benchmark_route3_graph_vs_route4_drift.py --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --group-id test-3072-clean --use-dedicated-endpoints --repeats 3 --sleep 0 --no-synthesize`
- `python3 scripts/benchmark_route3_graph_vs_route4_drift.py --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --group-id test-3072-clean --use-dedicated-endpoints --repeats 3 --sleep 0 --synthesize`

Basic 4-route (pos/neg per route):
- `python3 scripts/benchmark_all4_routes_posneg_qbank.py --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md --group-id test-3072-clean --sleep 0.1`
