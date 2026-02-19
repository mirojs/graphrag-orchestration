# Session Handover — 2026-02-19

## Objective

Use Route 6 (concept search) to improve or substitute Route 3 (global search).
Route 6 eliminates Route 3's MAP phase (N+1 LLM calls down to 1 LLM call) while
preserving community summaries as thematic context.

---

## What Was Done

### 1. Benchmark Infrastructure

- Added `concept_search` to `--force-route` choices in both benchmark scripts:
  - `scripts/benchmark_route3_global_search.py` (Q-G questions + theme coverage)
  - `scripts/benchmark_route4_drift_multi_hop.py` (Q-D questions)
- This allows running Route 3 and Route 4 benchmarks against Route 6.

### 2. Route 6 v1 Baseline (no section headings)

Ran Route 3 benchmark on Route 6 with 3 repeats.

| Metric | Route 3 | Route 6 v1 |
|--------|---------|------------|
| Avg theme coverage | 93.5% | **95.1%** |
| Avg containment | 0.839 | **0.851** |
| Avg latency (ms) | 10,053 | **6,787** |
| LLM calls | N+1 | **1** |

Q-G6 at 88% (missing "agent"), Q-G10 at 83% (missing "scope of work").

### 3. Root Cause Analysis (Q-G6 and Q-G10)

- **Q-G6 ("agent")**: Synthesis issue. "Agent" IS in the retrieved evidence
  (community summaries + sentences) but LLM chose "Principal Broker" instead.
- **Q-G10 ("scope of work")**: Retrieval gap. The phrase exists only as
  `EXHIBIT A - SCOPE OF WORK` section heading in the purchase contract.
  No sentence-level evidence contains the phrase.

### 4. Route 6 v2 — Section Heading Retrieval (regression)

Added `_retrieve_section_headings()` method to `route_6_concept.py`:
- Searches `Section.structural_embedding` (Voyage 2048d) via cosine similarity
- Added "Document Structure" block with full summaries to the synthesis prompt
- Wired as parallel task in Step 1 alongside community match + sentence search

**Result**: Q-G6 fixed (88% -> 100%), but Q-G10 regressed (83% -> 67%) and
Q-G5 regressed (100% -> 83%). Overall 93.0%.

**Root cause of regression**: LLM treated section headings (with full summaries)
as documents. 7/10 section headings came from Builder's Limited Warranty,
crowding out Holding Tank and Invoice documents.

### 5. Route 6 v3 — Compact Headings + Evidence Labels (section_path broken)

Two changes per user feedback ("you didn't mention it's header, each chunk
should've labelled the header"):

1. **Evidence formatting**: Changed from `[Source: {doc}, relevance: {score}]`
   to `[{doc} > {section_path}]` to label each evidence line with its section header.
2. **Section headings block**: Simplified from numbered list with summaries to
   compact bullet list of titles only, with prompt rule: "do NOT treat each
   heading as a separate finding."

**Result**: Q-G10 partially recovered (67% -> 83%), Q-G7 regressed (80% -> 60%).
Overall 92.6%.

**Root cause**: `sent.section_path` property on Sentence nodes was **empty/null**
for this dataset. The `[{doc} > {section_path}]` labels had no section info,
falling through to `[{doc}]` only. The changes had no actual effect on evidence.

### 6. Route 6 v4 — IN_SECTION Relationship Traversal (current)

Fixed the Cypher query to traverse `(sent)-[:IN_SECTION]->(sec:Section)` and
use `sec.path_key` instead of `sent.section_path` property, matching the pattern
used by Route 2 and Route 5:

```cypher
OPTIONAL MATCH (sent)-[:IN_SECTION]->(sec:Section)
...
RETURN sec.path_key AS section_key, ...
```

Evidence building now prefers `section_key` over `section_path`:
```python
"section_path": r.get("section_key") or r.get("section_path", ""),
```

Also added `section_path` to the API metadata for debugging (`include_context=true`).

Deployed via `deploy-graphrag.sh`, verified section_path now populated on all
evidence lines (e.g., `[BUILDERS LIMITED WARRANTY > BUILDERS LIMITED WARRANTY
WITH ARBITRATION > 1. Builder's Limited Warranty.]`).

---

## Current Benchmark Results (v4)

| QID | Route 3 | R6 v1 | R6 v2 | R6 v3 | R6 v4 | v4 vs R3 |
|-----|---------|-------|-------|-------|-------|----------|
| Q-G1 | 100% | 100% | 100% | 100% | 100% | = |
| Q-G2 | 80% | 100% | 100% | 100% | 100% | +20% |
| Q-G3 | 100% | 100% | 100% | 100% | 100% | = |
| Q-G4 | 100% | 100% | 100% | 100% | 100% | = |
| Q-G5 | 100% | 100% | 83% | 83% | 83% | -17% |
| Q-G6 | 75% | 88% | 100% | 100% | 88% | +13% |
| Q-G7 | 80% | 80% | 80% | 60% | 80% | = |
| Q-G8 | 100% | 100% | 100% | 100% | 100% | = |
| Q-G9 | 100% | 100% | 100% | 100% | 100% | = |
| Q-G10 | 100% | 83% | 67% | 83% | 83% | -17% |
| **AVG** | **93.5%** | **95.1%** | **93.0%** | **92.6%** | **93.4%** | **-0.1%** |

**Negative tests**: Route 3 = 9/9, R6 v4 = 8/9 (Q-N9 fails)
**Latency**: Route 3 = ~10,053ms, R6 v4 = ~7,481ms (**26% faster**)
**LLM calls**: Route 3 = N+1, Route 6 = 1

---

## Remaining Issues — Input vs Output Analysis

### Q-G5 (83%) — Missing "contractor"

- **Root cause**: `RETRIEVAL GAP`. All 10 evidence sentences come from Builder's
  Limited Warranty arbitration clauses. Purchase contract (which says "Contractor")
  is entirely crowded out. Query "What remedies / dispute-resolution mechanisms?"
  matches arbitration text too strongly.
- **Fix ideas**: Increase document diversity enforcement for dispute-related
  queries, or broaden sentence retrieval pool.

### Q-G6 (88%) — Missing "agent" in 1/3 runs

- **Root cause**: `LLM VARIANCE`. Evidence has "agent" in multiple places.
  Response includes "Agent" in 2/3 runs. One run's LLM phrasing dropped it.
- **Not actionable** — this is stochastic LLM behavior.

### Q-G10 (83%) — Missing "scope of work"

- **Root cause**: `HEADING-ONLY`. "EXHIBIT A - SCOPE OF WORK" appears as #1
  section heading match. But the sentence evidence from that section is labeled
  `PURCHASE CONTRACT` (parent section via IN_SECTION), not the subsection name.
  The LLM sees the heading in the compact reference list but follows the prompt
  rule to not treat headings as findings.
- **Fix ideas**: Traverse to the leaf-level section (subsection) instead of just
  the parent. Or include subsection path in the section_path label.

### Q-N9 — Negative test failure

- Route 6 hallucinates an answer for Q-N9 instead of saying "not found".
  Route 3 passes this test. Needs investigation.

---

## Files Modified

| File | Changes |
|------|---------|
| `scripts/benchmark_route3_global_search.py` | Added `concept_search` to `--force-route` choices |
| `scripts/benchmark_route4_drift_multi_hop.py` | Added `--force-route` param with `concept_search` |
| `src/worker/hybrid_v2/routes/route_6_prompts.py` | Prompt: compact headings block, `[Doc > Section]` label description, rule to not treat headings as findings |
| `src/worker/hybrid_v2/routes/route_6_concept.py` | `_retrieve_section_headings()` method; IN_SECTION traversal in Cypher; evidence formatting with `[doc > section_path]`; section_path in API metadata |

## Benchmark Result Files

All in `benchmarks/` directory:

| File | Description |
|------|-------------|
| `route3_global_search_20260219T144412Z.json` | Route 3 baseline (3 repeats) |
| `route6_global_search_20260219T160947Z.json` | Route 6 v1, 1 repeat |
| `route6_global_search_20260219T162054Z.json` | Route 6 v1, 3 repeats |
| `route6_global_search_20260219T171227Z.json` | Route 6 v2 (section summaries), 3 repeats |
| `route6_global_search_20260219T173754Z.json` | Route 6 v3 (compact headings, broken section_path), 3 repeats |
| `route6_global_search_20260219T182318Z.json` | Route 6 v4 (IN_SECTION traversal), 3 repeats |

---

## TODO — Next Steps

1. **Fix Q-G10 subsection resolution**: Traverse to leaf Section node
   (`SUBSECTION_OF` chain) instead of stopping at parent. The sentence's
   IN_SECTION points to `PURCHASE CONTRACT` but the actual subsection is
   `EXHIBIT A - SCOPE OF WORK`. Check if TextChunk -> IN_SECTION -> Section
   goes to the leaf or parent, and adjust accordingly.

2. **Fix Q-G5 document diversity for dispute queries**: 10/10 evidence sentences
   from one document. Document diversification code exists (score-gated per-doc
   reservations) but may not be aggressive enough. Consider lowering
   `ROUTE6_SENTENCE_SCORE_GATE` or increasing `ROUTE6_SENTENCE_MIN_PER_DOC`.

3. **Investigate Q-N9 negative test failure**: Route 6 hallucinates instead of
   saying "not found". May need prompt engineering or evidence-threshold gating.

4. **Consider removing section headings block entirely**: The compact heading
   list adds latency (structural_embedding search) but may not help much given
   that evidence now carries section labels. Compare v4 with headings disabled
   to see if quality holds.

5. **Evaluate whether Route 6 can replace Route 3**: At 93.4% vs 93.5% theme
   coverage with 26% faster latency and 1/(N+1) LLM calls, Route 6 is at
   near-parity. Fixing Q-G10 and Q-G5 could push it above Route 3.

---

## Key Architecture Reference

```
Route 6 Pipeline:
  Query -> [Parallel: Community Match + Sentence Search + Section Heading Search]
        -> Denoise + Rerank
        -> Single LLM Synthesis
        -> Response

Evidence format sent to LLM:
  1. [BUILDERS LIMITED WARRANTY > BUILDERS LIMITED WARRANTY WITH ARBITRATION] text...
  2. [purchase_contract > PURCHASE CONTRACT] text...

Section headings (compact list):
  - [purchase_contract] EXHIBIT A - SCOPE OF WORK
  - [BUILDERS LIMITED WARRANTY] 1. Builder's Limited Warranty.

IN_SECTION traversal in Cypher:
  OPTIONAL MATCH (sent)-[:IN_SECTION]->(sec:Section)
  RETURN sec.path_key AS section_key
  # Prefer section_key over sent.section_path
```
