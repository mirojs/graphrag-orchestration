# Route 3 (Global Search / LazyGraphRAG) Test Results

**Date:** 2026-02-06
**Benchmark:** `route3_global_search_20260206T093824Z`
**Group:** `test-5pdfs-v2-fix2` (5 PDFs indexed)

## Summary

| Category | Result |
|----------|--------|
| **Positive Tests (Q-G1-G10)** | 10/10 with **100% theme coverage** |
| **Negative Tests (Q-N1-N10)** | 9/9 **PASS** |
| **Citation Stability** | 1.00 Jaccard (9/10 questions perfect, Q-G4 at 0.67) |
| **Pass Rate** | **100%** (19/19 questions) |

## Configuration

- **Endpoint:** `/hybrid/query` with `force_route=global_search`
- **Response Type:** `summary`
- **Repeats:** 3
- **Timeout:** 180s
- **URL:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

## Output Files

- JSON: `benchmarks/route3_global_search_20260206T093824Z.json`
- Markdown: `benchmarks/route3_global_search_20260206T093824Z.md`

## Comparison vs Earlier Feb 6 Run (20260206T063218Z)

**Summary:** Coverage, pass rate, and citation stability are unchanged. The main differences are in p50 latencies, which vary across questions.

### Positive Tests (p50 Latency)

| Question | 063218Z p50 (ms) | 093824Z p50 (ms) | Delta (ms) |
|----------|-------------------|-------------------|------------|
| Q-G1 | 27505 | 29608 | +2103 |
| Q-G2 | 20337 | 24280 | +3943 |
| Q-G3 | 34766 | 35107 | +341 |
| Q-G4 | 15735 | 22795 | +7060 |
| Q-G5 | 35762 | 34839 | -923 |
| Q-G6 | 28837 | 34831 | +5994 |
| Q-G7 | 35217 | 51011 | +15794 |
| Q-G8 | 27038 | 25740 | -1298 |
| Q-G9 | 23797 | 23166 | -631 |
| Q-G10 | 9416 | 10199 | +783 |

### Negative Tests (p50 Latency)

| Question | 063218Z p50 (ms) | 093824Z p50 (ms) | Delta (ms) |
|----------|-------------------|-------------------|------------|
| Q-N1 | 4506 | 4528 | +22 |
| Q-N2 | 4233 | 4523 | +290 |
| Q-N3 | 4274 | 4198 | -76 |
| Q-N5 | 3940 | 4104 | +164 |
| Q-N6 | 6190 | 5175 | -1015 |
| Q-N7 | 4085 | 3436 | -649 |
| Q-N8 | 5160 | 4690 | -470 |
| Q-N9 | 3452 | 4416 | +964 |
| Q-N10 | 4970 | 4383 | -587 |

## Detailed Results

### Positive Tests (Q-G1 to Q-G10)

All positive tests achieved **100% theme coverage**:

| Question | Theme Coverage | p50 Latency (ms) | Containment | Citation Jaccard |
|----------|---------------|------------------|-------------|------------------|
| Q-G1 | 100% (7/7) | 29608 | 0.93 | 1.00 |
| Q-G2 | 100% (5/5) | 24280 | 0.71 | 1.00 |
| Q-G3 | 100% (8/8) | 35107 | - | 1.00 |
| Q-G4 | 100% (6/6) | 22795 | 0.72 | 0.67 |
| Q-G5 | 100% (6/6) | 34839 | 0.70 | 1.00 |
| Q-G6 | 100% (8/8) | 34831 | 0.82 | 1.00 |
| Q-G7 | 100% (5/5) | 51011 | 0.88 | 1.00 |
| Q-G8 | 100% (6/6) | 25740 | 0.74 | 1.00 |
| Q-G9 | 100% (6/6) | 23166 | 0.93 | 1.00 |
| Q-G10 | 100% (6/6) | 10199 | - | 1.00 |

### Negative Tests (Q-N1 to Q-N10)

All negative tests correctly returned "not found" responses:

| Question | Result | p50 Latency (ms) | Repeatability |
|----------|--------|------------------|---------------|
| Q-N1 | PASS | 4528 | exact=1.00 |
| Q-N2 | PASS | 4523 | exact=1.00 |
| Q-N3 | PASS | 4198 | exact=1.00 |
| Q-N5 | PASS | 4104 | exact=1.00 |
| Q-N6 | PASS | 5175 | exact=1.00 |
| Q-N7 | PASS | 3436 | exact=1.00 |
| Q-N8 | PASS | 4690 | exact=1.00 |
| Q-N9 | PASS | 4416 | exact=1.00 |
| Q-N10 | PASS | 4383 | exact=1.00 |

**Negative Detection:** All 9 negative queries achieved perfect repeatability (exact=1.00).
