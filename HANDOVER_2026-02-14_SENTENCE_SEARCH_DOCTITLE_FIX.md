# Handover — February 14, 2026

## Sentence Search + Doc-Title Fix: Status & Next Steps

---

## 1. What Was Done Today

### 1.1 Context Noise Investigation

After the sentence search + NER union feature landed (commits `9fe04596`, `272f0b0f`),
benchmarking showed a slight regression (mean containment 0.792 → 0.763).  We
investigated the **synthesis context** with `include_context: true` and found two
problems:

1. **"Unknown" document group** — 15 sentence chunks (7,835 chars, 24.3% of context)
   appeared under `=== DOCUMENT: Unknown ===` instead of their real document title.
2. **Redundant content** — those 15 sentence chunks duplicated text already present
   in graph-retrieved chunk [1] (PROPERTY MANAGEMENT AGREEMENT, 6,221 chars).

### 1.2 Root Cause: Doc-Title Key Mismatch

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py`, function `_build_cited_context()`

The grouping logic at ~line 1770 extracts `document_id` / `document_title` from
`chunk.get("metadata", {})` (a nested sub-dict).  Graph-retrieved chunks store
these keys inside `metadata`, but **sentence-search chunks** (created in
`route_4_drift.py` Stage 4.S, lines 376-388) put `document_title` and
`document_id` at the **top level** of the chunk dict — there is no `metadata`
sub-dict.

```
# Graph-retrieved chunk structure:
{"text": "...", "metadata": {"document_id": "doc_30b...", "document_title": "PROP..."}}

# Sentence-search chunk structure (Stage 4.S):
{"text": "...", "document_title": "PROP...", "document_id": "doc_30b...", ...}
```

So `meta = chunk.get("metadata", {})` → `{}`, and the fallback chain ended at
`chunk.get("source", "Unknown")` → `"Unknown"`.

### 1.3 Fix Applied (Uncommitted)

**Single fix in `synthesis.py`** — made `_build_cited_context()` check top-level
keys when `metadata` sub-dict keys are absent:

```python
# Before:
doc_key = meta.get("document_id")
...
raw_doc_key = meta.get("document_title") or chunk.get("source", "Unknown")

# After:
doc_key = meta.get("document_id") or chunk.get("document_id")
...
raw_doc_key = (
    meta.get("document_title")
    or chunk.get("document_title")
    or chunk.get("source", "Unknown")
)
```

This fix is applied in **two places** in `_build_cited_context()`: the initial
doc_groups loop (~line 1774) and the post-budget re-grouping (~line 1817).

### 1.4 Containment Dedup — Tried and Reverted

We also added a **containment-based dedup** (80% word-subset threshold) to the
coverage-chunk merge step (synthesis.py ~line 281).  This correctly filtered all
15 redundant sentence chunks as duplicates.

**However**, benchmarking showed it was **too aggressive** — Q-D6 dropped from
0.89 → 0.67 because sentence chunks serve as **attention signals** even when
their text is a subset of a larger graph chunk.  The LLM focuses on the
specifically-relevant sentences rather than scanning a 2000-word chunk.

**The containment dedup was removed.**  The code currently has only the doc-title
fix.

---

## 2. Benchmark Results (3-Way Comparison)

| Question | Baseline (no sentences) | + Sentences (broken doc_title) | + Doc-Title Fix | vs Baseline |
|----------|------------------------|-------------------------------|-----------------|-------------|
| Q-D1     | 0.93                   | 0.93                          | 0.93            | =           |
| Q-D2     | 1.00                   | 0.83                          | **1.00**        | = (restored)|
| Q-D3     | 0.85                   | 0.76                          | **0.67**        | **-0.18 ↓** |
| Q-D4     | 0.94                   | 0.94                          | 0.94            | =           |
| Q-D6     | 0.78                   | 0.89                          | **0.89**        | **+0.11 ↑** |
| Q-D7     | 0.22                   | 0.22                          | 0.22            | =           |
| Q-D8     | 0.83                   | 0.76                          | **0.76**        | **-0.07 ↓** |
| **MEAN** | **0.792**              | **0.763**                     | **0.773**       | **-0.019**  |

- **Negative tests:** 9/9 pass (all three runs)
- **Mean latency:** Baseline 21.6s → +Sentences 33.2s → +DocTitleFix 37.6s

### Benchmark files:
- Baseline (pre-sentence search): `benchmarks/route4_drift_multi_hop_20260213T164609Z.json`
- + Sentence search (broken doc_title): `benchmarks/route4_drift_multi_hop_20260214T082254Z.json`
- + Doc-title fix: `benchmarks/route4_drift_multi_hop_20260214T103148Z.json`

---

## 3. Remaining Regressions — Likely Root Causes

### Q-D3: "Compare time windows" (0.85 → 0.67, -0.18)

This is a multi-document cross-comparison question.  The sentence search adds
more context from specific documents, which may be **displacing** cross-document
chunks via the token budget.  The extra sentence chunks from the PROPERTY
MANAGEMENT AGREEMENT consume budget that previously went to chunks from other
documents containing timeframe data.

**Hypothesis:** Token budget displacement — sentence chunks (~15 chunks × ~500
chars) consume ~7,500 chars of the 32K budget, pushing out lower-scored but
relevant chunks from other documents.

### Q-D8: "Fabrikam vs Contoso document count" (0.83 → 0.76, -0.07)

Entity counting across documents.  Sentence search adds within-document
precision but may not help (and may hurt) cross-document entity comparison.

**Hypothesis:** Same token budget displacement, plus sentence chunks re-emphasize
one document's mentions above another, biasing the LLM's count.

### Latency increase (21.6s → 37.6s, +74%)

The sentence search pipeline itself is fast (~3.4s, runs parallel to NER).
The latency increase is **LLM synthesis time** from processing more context
tokens (sentence chunks add ~7,500 chars).

---

## 4. Uncommitted Changes

```
Modified files (git diff --stat HEAD):
 ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md     |  33 +++++++
 src/worker/hybrid_v2/pipeline/synthesis.py   | 136 +++++++++++++++++++++++++--
 src/worker/hybrid_v2/routes/route_2_local.py |  86 +++++++++++++++++
```

### synthesis.py changes:
- **Doc-title fix** (~line 1774, ~line 1817): Top-level key fallback for
  `document_id` and `document_title` — **KEEP THIS**
- **Doc-group gap pruning** (~line 1826+): A new block that scores document
  groups by entity PPR coverage and drops low-scoring ones — **REVIEW NEEDED**,
  this was added during an intermediate session and may contribute to the
  Q-D3 regression

### route_2_local.py changes:
- Route 2 parallelization changes (from a separate task) — **INDEPENDENT, can
  commit separately**

---

## 5. TODO List for Next Session

### Priority 1: Isolate the Q-D3/Q-D8 regressions

- [ ] **Check if doc-group pruning code is active** — the large diff in
  synthesis.py includes a "doc_group_pruning" block (~120 lines) that was added
  in an intermediate session.  This code drops entire document groups below a
  score threshold.  For Q-D3 (cross-doc comparison), this could be removing
  relevant documents.  **Try `DOC_GROUP_PRUNING_ENABLED=0` and re-benchmark.**

- [ ] **Run Q-D3 with `include_context: true`** to inspect what documents are
  in the LLM context before vs after the fix.  Compare against baseline to
  identify missing chunks.

- [ ] **Consider capping sentence chunks** — instead of allowing all 15 sentence
  chunks, limit to top-K (e.g., 5) by rerank score to reduce budget displacement.

### Priority 2: Latency

- [ ] **Evaluate whether sentence evidence should be limited by type** — for
  cross-document queries (Q-D3, Q-D8), sentence search may add noise.  Consider
  only injecting sentence evidence when the router confidence or query type
  suggests a single-document or fact-extraction query.

### Priority 3: Commit & clean up

- [ ] **Commit the doc-title fix** as a standalone commit (just the `or
  chunk.get("document_id")` / `chunk.get("document_title")` changes at lines
  1774 and 1817).
- [ ] **Review the doc-group pruning code** — decide whether to keep, tune, or
  revert.  It's a ~120-line addition that was written to address a different
  problem (irrelevant documents leaking through PPR).
- [ ] **Separate route_2_local.py changes** into their own commit.

### Priority 4: Re-benchmark

- [ ] After each change above, re-run with `--repeats 3` for statistical
  significance (single-repeat results are noisy for LLM synthesis).
- [ ] Compare against baseline: `benchmarks/route4_drift_multi_hop_20260213T164609Z.json`

---

## 6. Environment Notes

- **Server:** `uvicorn src.api_gateway.main:app --host 0.0.0.0 --port 8000`
- **Auth override:** Must set `GROUP_ID_OVERRIDE="test-5pdfs-v2-fix2"` (JWT
  group claim overrides X-Group-ID header)
- **Bearer token:** Refresh via:
  ```python
  from azure.identity import DefaultAzureCredential
  token = DefaultAzureCredential().get_token('https://cognitiveservices.azure.com/.default')
  # export AZURE_OPENAI_BEARER_TOKEN=<token.token>
  ```
  Token validity: ~60-85 minutes.
- **Benchmark command:**
  ```bash
  python3 scripts/benchmark_route4_drift_multi_hop.py \
    --url http://localhost:8000 \
    --group-id test-5pdfs-v2-fix2 \
    --repeats 1
  ```
- **Neo4j:** `neo4j+s://a86dcf63.databases.neo4j.io`, 177 sentences in group
  `test-5pdfs-v2-fix2`, all with correct `IN_DOCUMENT` and `PART_OF` relationships.

---

## 7. Route 2 — Skeleton Doc Filter & `doc_scope` Bug (February 14, 2026)

### 7.1 Skeleton Document Filter — Implemented & Measured

Route 2 skeleton enrichment (Stage 2.2.6) was dumping full document sections from ALL documents sharing any PPR entity, regardless of query relevance. For 4 of 5 benchmark queries, entity retrieval returned **zero chunks** — 100% of context came from unfiltered skeleton content (14–24K chars).

**Fix:** `_filter_skeleton_by_document()` added to `route_2_local.py` — groups skeleton chunks by `metadata.document_id`, scores each document by MAX `skeleton_score` (Voyage seed similarity), drops documents below `SKELETON_DOC_MIN_RATIO=0.90` of the top document's best score.

**Results (5-query benchmark on `test-5pdfs-v2-fix2`):**

| Query | Docs before | Chars before | Docs after | Chars after | Reduction | Answer |
|---|---|---|---|---|---|---|
| Who is the Agent? | 1 | 780 | 1 | 780 | — | identical |
| Address of the property? | 4 | 24,203 | 3 | 20,193 | -17% | identical |
| What is the warranty period? | 2 | 14,093 | 2 | 14,093 | — | identical |
| Who is the Owner? | 3 | 17,236 | **1** | **3,677** | **-79%** | identical |
| Monthly management fee? | 1 | 6,802 | 1 | 6,802 | — | identical |

**Latency:** Synthesis LLM time (gpt-4.1-mini) is 554–697ms across 3.7K–20K context chars (only 26% variation across 5.4× context range). Context reduction delivers **cost/token savings**, not speed improvement. Average Route 2 total: ~1,930ms unchanged.

### 7.2 `doc_scope` Seed Dilution Bug — Confirmed

`_resolve_target_documents()` in `synthesis.py` uses `total_seeds = len(seed_entities)` where `seed_entities` is the **PPR-expanded** entity list (13 entities after budget limit), not the original NER seeds (2 entities).

- **Current (broken):** `top_score / total_seeds = 5.833 / 13 = 0.449 < 0.5` → `skip_cross_document` (doc_scope never activates)
- **Correct:** `top_score / ner_seed_count = 5.833 / 2 = 2.917 >> 0.5` → doc_scope would activate

**Root cause chain:**
1. NER extracts 2 seed entities → PPR expands to 15 entity-score tuples
2. `_retrieve_text_chunks()` applies `relevance_budget` (0.8) → `budget_limit = int(15 * 0.8) + 1 = 13`
3. Passes `selected_entities[:13]` as `seed_entities` param to `_resolve_target_documents()`
4. `total_seeds = 13` — should be NER count (2)

**Impact:** `doc_scope` is dead code for Route 2 — it never activates. Fix requires passing original NER seed count from `route_2_local.py` through to synthesis.

### 7.3 Route 2 TODO List

- [ ] **Fix `doc_scope` seed dilution** — pass NER seed count through `synthesize()` → `_retrieve_text_chunks()` → `_resolve_target_documents()` as the denominator
- [ ] **"Address" query still 3 docs / 20K chars** — embedding-based filter can't distinguish generic domain terms ("property address") across real estate contracts; consider document-summary re-ranking at synthesis time
- [ ] **Verify Strategy A skeleton filter call** — `_filter_skeleton_by_document()` is a shared method; confirm Strategy A code path explicitly calls it
- [ ] **Commit all Route 2 changes** — skeleton doc filter (`route_2_local.py`), containment dedup + doc key fix + doc-group pruning (`synthesis.py`) are all uncommitted
