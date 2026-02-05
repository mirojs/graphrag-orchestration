# Route 3 (Global Search / LazyGraphRAG) Test Results

**Date:** 2026-02-05  
**Benchmark:** `route3_global_search_20260205T154441Z`  
**Group:** `test-5pdfs-v2-fix2` (5 PDFs indexed)

## Summary

| Category | Result |
|----------|--------|
| **Positive Tests (Q-G1-G10)** | 10/10 with **100% theme coverage** |
| **Negative Tests (Q-N1-N10)** | 9/9 **PASS** |
| **Citation Stability** | 1.00 Jaccard (fully stable) |
| **Pass Rate** | **100%** (19/19 questions) |

## Bug Fix Applied

**Issue:** `NameError: name 'chunk_id' is not defined`

**Root Cause:** In `src/worker/hybrid_v2/pipeline/enhanced_graph_retriever.py` line ~1044, a Cypher query inside an f-string used single braces `{chunk_id: t.id}` instead of double braces `{{chunk_id: t.id}}`. Python interpreted `{chunk_id}` as a format placeholder, causing the NameError at runtime.

**Fix:** Escaped the braces in the fallback_query f-string:
```python
# Before (broken)
collect({
    chunk_id: t.id,
    ...
})

# After (fixed)
collect({{
    chunk_id: t.id,
    ...
}})
```

## Detailed Results

### Positive Tests (Q-G1 to Q-G10)

All positive tests achieved **100% theme coverage**:

| Question | Theme Coverage | p50 Latency | Containment |
|----------|---------------|-------------|-------------|
| Q-G1 | 100% (7/7) | 33.0s | 0.95 |
| Q-G2 | 100% (5/5) | 23.0s | 0.65 |
| Q-G3 | 100% (8/8) | 40.6s | - |
| Q-G4 | 100% (6/6) | 24.2s | 0.72 |
| Q-G5 | 100% (6/6) | 52.1s | 0.95 |
| Q-G6 | 100% (8/8) | 45.4s | 0.82 |
| Q-G7 | 100% (5/5) | 43.8s | 0.88 |
| Q-G8 | 100% (6/6) | 37.6s | 0.68 |
| Q-G9 | 100% (6/6) | 29.3s | 0.73 |
| Q-G10 | 100% (6/6) | 11.8s | - |

### Negative Tests (Q-N1 to Q-N10)

All negative tests correctly returned "not found" responses:

| Question | Result | p50 Latency |
|----------|--------|-------------|
| Q-N1 | PASS | 3.9s |
| Q-N2 | PASS | 3.6s |
| Q-N3 | PASS | 4.0s |
| Q-N5 | PASS | 3.7s |
| Q-N6 | PASS | 6.0s |
| Q-N7 | PASS | 4.3s |
| Q-N8 | PASS | 3.5s |
| Q-N9 | PASS | 4.4s |
| Q-N10 | PASS | 6.3s |

## Configuration

- **Endpoint:** `/hybrid/query` with `force_route=global_search`
- **Response Type:** `summary`
- **Repeats:** 3
- **Timeout:** 180s

## Output Files

- JSON: `benchmarks/route3_global_search_20260205T154441Z.json`
- Markdown: `benchmarks/route3_global_search_20260205T154441Z.md`
