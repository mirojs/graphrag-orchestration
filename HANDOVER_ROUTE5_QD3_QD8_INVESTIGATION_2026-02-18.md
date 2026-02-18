# Route 5 Benchmark Investigation — Handover Document
**Date:** 2026-02-18  
**Context:** Route 4 benchmark questions (19 Q-D/Q-N) × 3 repeats on Route 5 (unified_search)

---

## Benchmark Results Summary

| Metric | Value |
|--------|-------|
| **LLM Eval Score** | 54/57 (94.7%) |
| **Questions Passing** | 18/19 |
| **Only Failure** | Q-D8 (1/3 runs passed) |
| **Close Call** | Q-D3 (2/3 runs passed, but missing timeframes in all) |

---

## Q-D8: Invoice Count Inconsistency

### Question
> "How many invoices has each company issued?"

### Ground Truth
> Fabrikam Construction Inc.: 4 invoices; Contoso Lifts LLC: 4 invoices (total 8)

### What Happens
- **Retrieval is 100% deterministic** — all 3 runs have identical NER entities, seed counts, evidence_path (Jaccard similarity = 1.0), and 24 text_chunks_used.
- **LLM synthesis is non-deterministic** — the LLM gives 3 different answers:
  - Run 1: Fabrikam=5, Contoso=4 ❌ (double-counts Fabrikam)
  - Run 2: Tied at 4 each ✅
  - Run 3: Fabrikam>3, Contoso=3 ❌ (miscounts both)

### Root Cause
**Entity disambiguation in the synthesis prompt.** The corpus contains "Fabrikam Construction" and "Fabrikam Inc." — the LLM inconsistently merges/splits these entities when counting invoices. This is NOT a retrieval problem; the correct chunks are always present.

### Fix Options (Not Yet Implemented)
1. **Prompt-level fix:** Add explicit entity disambiguation instructions to the synthesis prompt (e.g., "treat Fabrikam Construction and Fabrikam Inc. as the same entity")
2. **Metadata enrichment:** Include document→entity relationship mapping in the synthesis context so the LLM can see which invoices belong to which entity
3. **Pre-synthesis entity resolution:** Run entity co-reference resolution on retrieved chunks before synthesis

### Priority
Medium — this is a synthesis-layer issue, not architectural. The retrieval pipeline works correctly.

---

## Q-D3: Missing Purchase Contract Timeframes

### Question
> "Compare time windows, notification periods, and deadlines across all five documents."

### Ground Truth (6 required timeframes)
1. 10-year Builders Limited Warranty (1-year structural warranty within)
2. 90-day labor warranty (Purchase Contract)
3. 3 business day cancellation window (Purchase Contract)
4. 12-month Property Management Agreement term
5. 180-day notice to vacate (PM Agreement)
6. Holding Tank servicing schedule/deadlines

### What Happens
Even in "passing" runs, only 4-5 of 6 timeframes are found. **The 90-day labor warranty and 3-day cancellation window from the Purchase Contract are NEVER retrieved in ANY of the 3 runs.**

### Root Cause: Cascading Retrieval Failure

This is a **retrieval failure**, not a synthesis failure. The failure chain:

#### 1. NER Returns Empty
The abstract query "Compare time windows, notification periods, and deadlines" has no named entities → tier1=0 seeds. All weight redistributes to tier2.

#### 2. Over-Broad Section Matching (`resolve_section_entities`)
```sql
WHERE s.title = path
   OR path CONTAINS s.title    ← PROBLEMATIC
   OR s.title CONTAINS path
```
For `path = "PURCHASE CONTRACT"`, clause 2 matches ANY section whose title is a substring — e.g., a section titled just "CONTRACT" from Builders Limited Warranty. This pulls BLW entities into the pool under the Purchase Contract's name.

#### 3. Flat Weight Dilution
With 41 structural seeds, each gets `1.0 / 41 ≈ 0.024`. If Purchase Contract resolves only 3-5 entities but BLW resolves 25+, Purchase Contract gets ~12% teleportation mass vs ~73% for BLW.

#### 4. Community Penalty (synthesis.py)
Top-3 PPR entities (all BLW cluster) define the "target community." Purchase Contract entities in a different Louvain community get **0.3× penalty**.

#### 5. Score-Gap Pruning (synthesis.py)
Finds the largest relative score drop and prunes everything below it. After community penalty, Purchase Contract entities sit below the gap → **pruned entirely**.

#### 6. Score-Weighted Chunk Budget
Top PPR entity gets 12 chunks; low-score entities get 1. Even if a PC entity survives, it gets minimal chunk budget.

#### 7. Sentence Evidence Ranking
Sentence search hits (if any) get `min_entity_score × 0.5` — ranked below ALL entity-retrieved chunks, likely truncated from context window.

**Result:** ZERO Purchase Contract chunks in final context → LLM cannot answer the 90-day labor warranty or 3-day cancellation window.

### Evidence from Benchmark Data
- `structural_sections` includes "PURCHASE CONTRACT" in ALL 3 runs
- Citations across ALL 3 runs: only Warranty (8-10 chunks), Property Management (2-3 chunks), Holding Tank (1 chunk)
- ZERO purchase_contract chunks in ANY citation
- `evidence_path` contains Exhibit A entities (Savaria V1504 lift specs, "110 VAC 60 Hz" power details) instead of timeframe clauses

---

## Architecture Issues Identified

### Tier 2 Low-Signal Matching
- Section titles are short labels: `"2. Term."`, `"EXHIBIT A"`, `"INVOICE"`, `"PURCHASE CONTRACT"`
- `structural_embedding` was computed from **title + path_key only** — very low semantic signal
- Embedding cosine similarity barely clears 0.25 threshold for relevant sections
- LLM match compensates but introduces non-determinism (Run 2 missed "HOLDING TANK SERVICING CONTRACT")

### Tier 2 Hybrid Mode
- Default mode runs `match_sections_by_embedding` + `match_sections_by_llm` in parallel, unions results
- Embedding match: deterministic but low recall on short titles
- LLM match: better semantic understanding but non-deterministic
- **The Tier 2 mode is NOT the root cause of Q-D3's failure** — even with perfect section selection, the downstream PPR + community penalty + pruning pipeline still eliminates minority-document entities

### Missing Tier Contribution Visibility
- Current metadata reports only `tier1_seed_count`, `tier2_seed_count`, `tier3_seed_count`
- No visibility into which entities came from which tier, effective weights after redistribution, or per-tier contribution to the final PPR teleportation vector
- This makes it hard to diagnose whether the issue is in seed resolution vs PPR vs denoising

---

## Changes Made Today (2026-02-18)

### 1. Section Summary Generation (Ingestion)
**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

New method `_generate_section_summaries()` added as step 4.6.1:
- For each Section node with linked chunks, sends up to 6 chunk excerpts to LLM
- LLM produces 1-2 sentence summary capturing key topics, parties, time periods, obligations
- Stored as `Section.summary` property in Neo4j
- Idempotent — skips sections that already have summaries

### 2. Updated Structural Embedding (Ingestion)
**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

`_embed_section_structural()` now embeds `title + path_key + summary` instead of just `title + path_key`:
- Before: `"PURCHASE CONTRACT"` → low semantic signal
- After: `"PURCHASE CONTRACT — Covers the 3 business day cancellation window, 90-day labor warranty, and contractor obligations per the residential purchase agreement."` → rich semantic signal
- Falls back to title+path_key when no summary exists

### 3. Updated LLM Section Matching (Query Time)
**File:** `src/worker/hybrid_v2/pipeline/seed_resolver.py`

`match_sections_by_llm()` now includes summaries in the LLM prompt:
- Before: `"1. PURCHASE CONTRACT"`
- After: `"1. PURCHASE CONTRACT — Covers the 3 business day cancellation window..."`
- LLM can now make informed section selections based on actual content

### 4. Tier Contribution Metadata (Query Time)
**File:** `src/worker/hybrid_v2/pipeline/seed_resolver.py` + `src/worker/hybrid_v2/routes/route_5_unified.py`

New `tier_contribution` block in metadata:
- Reports per-tier entity IDs, effective weights after redistribution, total weight mass per tier
- Enables diagnosing whether retrieval failures are in seed resolution vs PPR vs denoising

---

## TODO — Remaining Work

### High Priority
- [ ] **Re-index with section summaries:** Run re-indexing on test-5pdfs-v2-fix2 to populate `Section.summary` and regenerate `structural_embedding` with enriched text. This is required before any section-summary-related improvements take effect.
- [ ] **Fix over-broad section matching:** Tighten the `path CONTAINS s.title` clause in `resolve_section_entities()` — require minimum title length (e.g., 4+ chars) or use exact-only matching to prevent generic titles like "CONTRACT" from cross-contaminating seed pools.
- [ ] **Per-section weight allocation:** Change `build_unified_seeds()` to distribute weight equally across *sections* first, then within each section across entities. Currently a section with 25 entities gets 25× the influence of a section with 1 entity.
- [ ] **Community penalty bypass for cross-doc queries:** When `structural_sections` span multiple documents, disable community penalty or run per-document PPR to ensure minority documents aren't systematically eliminated.
- [ ] **Re-run Route 5 benchmark** after re-indexing + fixes to validate improvements on Q-D3.

### Medium Priority
- [ ] **Q-D8 entity disambiguation:** Add synthesis prompt instructions for entity co-reference resolution, or pre-merge entity variants before counting.
- [ ] **Tier 2 mode evaluation:** Compare embedding-only vs LLM-only vs hybrid on full benchmark after section summaries are populated, to determine if LLM mode non-determinism is worth the recall improvement.
- [ ] **Sentence evidence ranking:** Consider giving sentence-search hits higher initial scores (currently capped at `min_entity_score × 0.5`), especially when NER is empty and sentence search is the only content-based signal.

### Low Priority / Investigation
- [ ] **Document scoping filter:** Investigate whether `DOC_SCOPE_ENABLED=1` is filtering out Purchase Contract chunks even when its entities survive PPR. The IDF-weighted entity→document voting may be biased toward BLW when BLW entities dominate.
- [ ] **Adaptive weight profiles:** For cross-document comparison queries (detected by structural_sections spanning 3+ documents), automatically switch to a profile with lower w1 / higher w2 to give structural seeds more influence.
- [ ] **Score-gap pruning threshold:** Evaluate whether `SCORE_GAP_THRESHOLD=0.5` is too aggressive for cross-doc queries where entities from different documents naturally form score gaps.

---

## Key File References

| File | Purpose |
|------|---------|
| `src/worker/hybrid_v2/pipeline/seed_resolver.py` | 3-tier seed resolution (NER, structural, thematic) |
| `src/worker/hybrid_v2/routes/route_5_unified.py` | Route 5 handler — orchestrates full pipeline |
| `src/worker/hybrid_v2/pipeline/synthesis.py` | Chunk retrieval, community penalty, score-gap pruning, synthesis |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Ingestion — section graph, summaries, embeddings |
| `scripts/benchmark_route5_unified_r4_questions.py` | Benchmark runner (Route 4 Qs on Route 5) |
| `scripts/evaluate_route4_reasoning.py` | LLM judge evaluation script |
