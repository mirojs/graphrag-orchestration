# Route 4 Improvement — Borrowing Route 2's Architectural Principles

**Date:** 2026-02-13  
**Context:** Route 2 (Local Search) achieves perfect results: 10/10 containment, 9/9 negative rejection, stable F1 with 52% token reduction. Route 4 (DRIFT Multi-Hop) scores 56–75% depending on model/query complexity. This analysis identifies what made Route 2 succeed and how to transplant those principles into Route 4.

---

## 1. Route 2's Triumph: What Actually Won

Route 2's perfection isn't a single trick — it's the result of a **clean, simple, fundamentally sound architecture** at every layer. Three principles dominate:

### Principle 1: Sentence-Level Precision at the Edges

Route 2's denoising experiments proved that **chunk-level retrieval is inherently noisy**:
- 75.3% of raw chunks were exact duplicates (same content fetched via multiple entities)
- Even after dedup, near-duplicate chunks from overlapping windows survived
- The answer was always in the context — but buried under 37.8 chunks of noise

The fix wasn't more algorithms — it was **cleaning the data at the edges**:
- MD5 content-hash dedup (Step 4) → removes 75% duplicates
- Score-ranked ordering (Step 7) → best chunks first
- Token budget (Step 5) → hard cap on noise entering the LLM
- Score-gap pruning → natural cliff detection between relevant and irrelevant entities

**Key insight:** Route 2 proved that when the graph is clean and edges are precise, a simple pipeline (NER → PPR → score-ranked chunks → LLM) produces perfect results. No exotic algorithms needed.

### Principle 2: Parse, Don't Guess

Route 2's edges come from **deterministic parsing**, not algorithmic guessing:
- Entity edges from NER extraction (deterministic parse of text)
- Section hierarchy from Azure DI document structure (parsed, not inferred)
- MENTIONS edges from entity-text co-occurrence (factual, not probabilistic)
- Community structure from Louvain on a clean graph (math, not heuristics)

The denoising experiments showed that every **heuristic** addition (NER intent prompt, vector fallback) either hurt or added zero value, while every **structural** cleanup (dedup, score-gap, community filter) helped.

### Principle 3: Subtract, Don't Add

Route 2's improvement trajectory is a story of **removing noise**, not adding features:

| Improvement | What It Did | Net Effect |
|-------------|-------------|------------|
| MD5 dedup | Removed 75% duplicate chunks | +2 containment |
| Score-weighted allocation | Removed uniform entity budgets | −21% tokens |
| Community filter | Penalized off-topic entities | −8% tokens |
| Score-gap pruning | Removed tail entities below cliff | +0.009 F1, −48% raw chunks |
| Semantic dedup | Removed near-duplicate chunks | −27% tokens |
| NER prompt tuning | Tried to add "smarter" NER | ❌ −0.028 F1, broke containment |
| Vector safety net | Tried to add vector retrieval | ❌ 0 new chunks, +16% latency |

**The pattern is unmistakable:** Every subtraction improved Route 2. Every addition hurt it. The clean graph + simple pipeline was already sufficient — complexity was the enemy.

---

## 2. Route 4's Current State: Where the Gap Is

Route 4 scores **56–75%** on the invoice consistency benchmark (vs Route 2's effective 100% on local queries). The Feb 12 architecture assessment identified these issues:

| Problem | Root Cause | Severity |
|---------|-----------|----------|
| PPR scores discarded in chunk retrieval | `limit_per_entity=12` uniform for all entities | Critical |
| 56.5% chunk duplication | No `seen_chunk_ids` dedup | Critical |
| No token budget | 100K+ tokens possible | High |
| 6-layer seed resolution cascade | Layers 3–5 produce false positives | High |
| Double graph traversal | Discovery traces (4.2) discarded, re-traced (4.3) | Medium |
| Coverage gap fill compensating for weak retrieval | Band-aid for entity extraction gaps | Medium |
| Hop 0 vector expansion dilutes graph signal | Hybrid vector+graph without clear priority | Medium |

But the **deepest problem** isn't any single bug — it's that Route 4 uses a fundamentally different (and weaker) retrieval-to-synthesis path than Route 2:

### Route 2 Path (clean)
```
Query → NER → PPR (5-path, scored) → score-weighted chunk allocation
      → MD5 dedup → community filter → score-gap pruning → semantic dedup
      → token budget → scored, ranked context → LLM synthesis
```

### Route 4 Path (noisy)
```
Query → LLM decomposition → NER per sub-question → 6-layer seed resolution
      → semantic beam search (per sub-Q) → beam search (consolidated)
      → confidence check → optional re-decomposition
      → coverage gap fill → flat chunk retrieval (no dedup, no ranking, no budget)
      → LLM synthesis
```

Route 4 has **more steps** but **worse hygiene**. It adds complexity (decomposition, confidence loops, gap fill) without the fundamental cleanliness that makes Route 2 work.

---

## 3. The Route 2 Principles Applied to Route 4

### 3.1 Transplant: Sentence-Level Precision → Route 4 Edges

**What Route 2 proved:** The graph edge quality determines everything downstream. Clean edges → simple pipeline works. Noisy edges → no amount of downstream processing fixes it.

**What Route 4 needs:**

| Current Route 4 | Route 2 Equivalent | Change |
|----------------|-------------------|--------|
| RELATED_TO from 512-token chunk co-occurrence | RELATED_TO should be sentence-scoped co-occurrence | Phase B change (already designed) |
| 6-layer seed resolution with fuzzy matching | 2-layer: exact+alias → vector similarity | Collapse layers 3–5 |
| Generic aliases (`_generate_generic_aliases()`) | No aliases — clean entity names from sentence NER | Remove alias generation |
| NLP regex seed fallback | No fallback — trust the graph | Remove `_nlp_seed_entities()` |

**Impact estimate (from ANALYSIS_ROUTE3_IMPROVEMENTS_BENEFIT_ROUTE4):**
- Seed resolution false positives: ~15–25% → <5%
- RELATED_TO edge noise: ~30–50% false co-occurrences → ~5%
- Chunk duplication in synthesis: 56.5% → ~0% (1:1 sentence MENTIONS)
- Beam search precision: dramatically higher (fewer false neighbors per hop)

### 3.2 Transplant: Parse, Don't Guess → Route 4 Traversal

**What Route 2 proved:** The PPR 5-path traversal with deterministic edge types (MENTIONS, IN_SECTION, SEMANTICALLY_SIMILAR) produces clean, traceable retrieval. No heuristic rewriting needed.

**What Route 4 should adopt:**

#### A. Replace LLM decomposition with structured query understanding

Route 2 doesn't decompose the query — it extracts entities directly from the user's exact wording. Route 4's LLM decomposition **rephrases** the query into sub-questions, which:
- Changes entity names (losing exact-match resolution)
- Introduces hallucinated focus areas
- Scatters seed resolution across sub-questions

**Proposed change:** Keep decomposition for genuinely multi-hop queries (e.g., "Compare X in document A vs document B"), but for single-scope queries, **bypass decomposition** and use Route 2's direct NER path:

```python
# Adaptive decomposition gate
if query_requires_decomposition(query):  # multi-document comparison, multi-aspect
    sub_questions = await _drift_decompose(query)
else:
    sub_questions = [query]  # single pass, Route 2 style
```

This is the same "subtract, don't add" principle: decomposition is only useful when the query genuinely has multiple independent information needs.

#### B. Collapse seed resolution from 6 layers to 2

Route 2's denoising experiments showed that the NER → PPR pipeline already catches everything vector search would find (100% overlap in Improvement #5). The 6-layer cascade exists to compensate for a noisy entity graph. With sentence-based entity extraction (Phase B), layers 3–5 become harmful:

```
BEFORE (6 layers):
  exact → alias → KVP key → substring → token overlap → vector similarity
  
AFTER (2 layers — Route 2 style):
  exact+alias → vector similarity (using beam search query embedding, zero extra cost)
```

**Implementation:** `get_entities_by_names()` in `async_neo4j_service.py` — collapse the cascade. Route 4 already computes `query_embedding` for beam search; pass it to seed resolution for the vector fallback. Removes 4 sequential Cypher queries (20–25ms saved per sub-question).

### 3.3 Transplant: Subtract, Don't Add → Route 4 Pipeline

**What Route 2 proved:** The denoising stack (score-weighted allocation, community filter, score-gap pruning, semantic dedup, token budget) provides massive quality gains with zero accuracy loss.

**Route 4 currently has NONE of these.** The synthesis path in Route 4 calls `_retrieve_text_chunks()` without any of the denoising flags that Route 2 uses.

**Concrete transplants (ranked by Route 2's measured impact):**

| # | Denoising Stage | Route 2 Impact | Route 4 Change | LOC |
|---|----------------|---------------|----------------|-----|
| 1 | **MD5 chunk dedup** | +67% F1 (from pre-change baseline), +2 containment | Add `seen_chunk_ids: set` to Route 4's chunk retrieval | ~5 |
| 2 | **Score-gap pruning** | +0.009 F1, −48% raw chunks, −26% latency | Apply to beam search output (entities sorted by beam score, detect cliff) | ~30 |
| 3 | **Score-weighted chunk allocation** | −21% tokens, neutral F1 | Budget chunks proportional to beam score instead of uniform `limit_per_entity=12` | ~20 |
| 4 | **Token budget** | −52% input tokens cumulative | Cap Route 4 synthesis context at 32K tokens | ~15 |
| 5 | **Semantic near-dedup** | −27% tokens, neutral F1 | Jaccard word-similarity dedup after MD5 dedup | ~20 |
| 6 | **Community-aware entity filter** | −8% tokens, +0.012 recall | Penalize off-community entities by 0.3× before score allocation | ~25 |

**Total: ~115 lines of code.** These are proven improvements with measured impact on the same corpus. Route 4 can inherit them essentially for free.

### 3.4 New Principle: Use Beam Scores Like PPR Scores

Route 2's breakthrough was that **PPR scores create a natural ranking** — high-score entities are truly relevant, low-score entities are noise. The denoising stack amplifies this signal:

```
PPR scores → community penalty → score-gap detection → score-weighted allocation → ranked context
```

Route 4's semantic beam search produces **equivalent scores** (cosine similarity between entity embedding and query embedding at each hop). These scores are currently used for beam pruning but **discarded at synthesis time** — exactly the same bug Route 2 had before the Feb 10 deep dive fixed it.

**The fix is identical:** Feed beam scores into the same denoising pipeline that Route 2 uses.

```python
# Route 4 currently:
evidence_nodes = [(entity_name, beam_score), ...]
chunks = _retrieve_text_chunks(evidence_nodes)  # beam_score is IGNORED

# Route 4 should be (Route 2 style):
evidence_nodes = [(entity_name, beam_score), ...]
chunks = _retrieve_text_chunks(
    evidence_nodes,
    score_weighted=True,        # budget proportional to beam_score
    community_filter=True,      # penalize off-community entities
    score_gap_pruning=True,     # detect beam_score cliff
    semantic_dedup=True,        # remove near-duplicate chunks
    token_budget=32000          # hard cap
)
```

---

## 4. Implementation Plan: Route 2 → Route 4 Transfer

### Phase A: Zero-Risk Transplants (same code, enable toggles) — 1 day

Route 4 calls the same `_retrieve_text_chunks()` function in `synthesis.py` that Route 2 uses. The denoising stages are already implemented behind env var toggles. Route 4 just doesn't enable them.

| Step | Action | Risk |
|------|--------|------|
| A.1 | Ensure Route 4's `_retrieve_text_chunks()` path passes beam scores (not uniform) | None — data already available |
| A.2 | Enable `DENOISE_SCORE_WEIGHTED=1` for Route 4 | None — already proven on Route 2 |
| A.3 | Enable `DENOISE_COMMUNITY_FILTER=1` for Route 4 | Low — may need community_id on beam-traversed entities |
| A.4 | Enable `DENOISE_SCORE_GAP=1` for Route 4 | Low — beam scores may have different gap distribution than PPR |
| A.5 | Enable `DENOISE_SEMANTIC_DEDUP=1` for Route 4 | None — corpus-agnostic |
| A.6 | Verify token budget (`SYNTHESIS_TOKEN_BUDGET=32000`) applies to Route 4 | None — already in synthesis.py |

**Expected outcome:** Route 4 inherits Route 2's 52% token reduction and 7% precision improvement immediately. No new code needed — just ensure the flags are active on Route 4's code path.

### Phase B: Seed Resolution Simplification — 1 day

| Step | Action | Risk |
|------|--------|------|
| B.1 | Collapse seed resolution to 2-layer (exact+alias → vector) | Moderate — may lose some edge-case matches |
| B.2 | Pass `query_embedding` from beam search to vector seed resolution | None — embedding already computed |
| B.3 | Remove `_generate_generic_aliases()` | Low — only affects false matches |
| B.4 | Remove `_nlp_seed_entities()` regex fallback | Low — compensating mechanism for noisy graph |

**Expected outcome:** Seed resolution false positives drop from ~15–25% to <5%. Fewer false seeds → fewer wasted beam hops → cleaner evidence at synthesis.

### Phase C: Adaptive Decomposition Gate — 2 days

| Step | Action | Risk |
|------|--------|------|
| C.1 | Implement query complexity classifier (multi-doc/multi-aspect detector) | Moderate — needs clear heuristic |
| C.2 | Single-scope queries bypass decomposition (use direct NER like Route 2) | Moderate — removes Route 4's signature feature for simple queries |
| C.3 | Multi-scope queries keep decomposition but with Route 2-style denoising on each sub-question | Low — additive improvement |

**Expected outcome:** Simple queries (70%+ of Route 4 traffic) get Route 2's clean direct path. Complex queries keep decomposition benefits. Latency drops significantly for simple queries (no decomposition LLM call, no double tracing).

### Phase D: Reuse Discovery Traces — 1 day

| Step | Action | Risk |
|------|--------|------|
| D.1 | Store Stage 4.2 discovery evidence (not just seed entities) | None — data already computed |
| D.2 | Merge discovery evidence into Stage 4.3 consolidated trace (skip re-tracing for already-discovered entities) | Low — may change evidence ranking |

**Expected outcome:** −50% graph queries (3 discovery traces + 1 consolidated → 1 consolidated that reuses discovery data). Latency improvement without quality change.

---

## 5. What NOT to Do (Lessons from Route 2's Failures)

Route 2's ablation experiments produced two clear anti-patterns that Route 4 should avoid:

### ❌ Don't Add "Smarter" NER Prompts

Route 2 Improvement #3 (query-intent NER) tried to make NER "smarter" by reducing synonym seeds. Result: **−0.028 F1, lost containment.** The "redundant" synonyms were actually diversity signals that created clear score gaps for downstream pruning.

**Implication for Route 4:** Don't try to make the DRIFT decomposition "smarter" or reduce sub-question count. The current decomposition, despite its noise, creates diverse seed entry points. Clean up **downstream** (denoising) rather than **upstream** (NER/decomposition).

### ❌ Don't Add Vector Fallbacks

Route 2 Improvement #5 (vector chunk safety net) added KNN vector search as a fallback. Result: **100% overlap with graph path, 0 new chunks, +16% latency.** The graph-based pipeline already captures everything vector search finds.

**Implication for Route 4:** Don't add a separate vector retrieval path "just in case." If the seed resolution and beam traversal are clean (Phase B), the graph path is sufficient. The coverage gap fill stage (4.3.6) already serves as the safety net — fix the primary path rather than adding more fallbacks.

---

## 6. Expected Route 4 Quality Progression

| Phase | Expected Score | Basis |
|-------|---------------|-------|
| Current | 56–75% (model-dependent) | Feb 7 benchmark |
| After Phase A (denoising transplant) | 70–80% | Route 2's 7% precision gain + 52% token reduction applied to Route 4 |
| After Phase B (seed simplification) | 75–85% | Fewer false seeds → cleaner beam → better evidence |
| After Phase C (adaptive decomposition) | 80–90% | Simple queries get Route 2's proven-perfect path |
| After Phase D (trace reuse) | 80–90% (same quality, faster) | Latency improvement, no quality change |

---

## 7. Summary: The Route 2 Philosophy for Route 4

Route 2's success can be distilled into one sentence: **A clean graph with simple, principled retrieval beats a noisy graph with sophisticated algorithms.**

Applying this to Route 4 means:

1. **Clean the edges first** (sentence-level entity extraction, sentence-scoped RELATED_TO) — Phase B from the indexing improvements already in progress
2. **Transplant the proven denoising stack** (dedup, score-gap, community filter, token budget) — identical code, just enable the toggles
3. **Simplify the pipeline** (2-layer seed resolution, adaptive decomposition, reuse discovery traces) — remove compensating mechanisms that exist because the graph was noisy
4. **Resist adding complexity** — every Route 2 experiment that added a feature (smarter NER, vector fallback) made things worse

The path from 56% to 85%+ is not more algorithms — it's the same clean, sparse, structurally faithful architecture that made Route 2 perfect, applied to Route 4's multi-hop traversal.

---

## 8. Does Route 4 Have Fundamental Defects for DRIFT Search?

**Yes. Beyond the noise issues (fixable by subtraction), Route 4 has three structural defects in how it implements the DRIFT pattern itself.**

### Defect 1: The Two Code Copies Diverged — Production Uses Beam Search, Staging Uses PPR

There are two copies of Route 4 in the codebase:

| Path | Tracing Method | Status |
|------|---------------|--------|
| `src/worker/hybrid/routes/route_4_drift.py` | `trace_semantic_beam()` — query-aligned beam search | **Production** |
| `src/worker/hybrid_v2/routes/route_4_drift.py` | `trace_semantic_beam()` — same (with `knn_config`) | **Production v2** |
| `app/hybrid_v2/hybrid/routes/route_4_drift.py` | `tracer.trace()` — plain PPR (distance decay) | **Old staging copy** |

The staging copy calls `tracer.trace()` which goes through `_trace_with_async_neo4j()` → `personalized_pagerank_native()`. This is a simple distance-decay approximation, NOT real semantic beam search. The production code correctly uses `trace_semantic_beam()`.

**The defect:** The old staging copy's Route 4 is using the **wrong tracing algorithm** — it runs plain PPR without query-embedding alignment, which means the multi-hop traversal drifts away from the query at each hop. The semantic beam search in production is architecturally correct.

### Defect 2: DRIFT Decomposition Creates Seed Dilution (Fundamental to the Pattern)

This is the most important defect because it's **inherent to how DRIFT works**, not a bug:

```
Route 2 (working perfectly):
  Query → NER → seeds → PPR → evidence
  
Route 4 (DRIFT pattern):
  Query → LLM decomposition → sub-questions
    → NER per sub-question → partial seeds per sub-Q
    → partial trace per sub-Q (discovery, top_k=5)
    → ALL seeds collected → consolidated trace (top_k=30)
```

The DRIFT decomposition step has three compounding problems:

**A. Entity name mutation:** When the LLM rephrases the query into sub-questions, entity names change. "Property Management Agreement" becomes "management agreement terms" or "PMA provisions." These rephrased names resolve to different (often wrong) graph entities. Route 2 extracts entities directly from the user's exact words — no mutation.

**B. Seed union explosion:** Each sub-question produces 3–5 seeds. With 3 sub-questions, that's 9–15 seeds (after dedup typically ~8–12). Route 2 produces ~5 seeds. More seeds means more noise entities entering the consolidated trace, and the PPR/beam score distribution becomes flatter (less gap between signal and noise), which undermines score-gap pruning.

**C. Double tracing is wasteful and inconsistent:** Stage 4.2 runs a discovery trace per sub-question (top_k=5) to compute confidence metrics. Stage 4.3 re-traces with ALL seeds (top_k=30). The discovery results are **discarded as evidence** — they only inform the confidence score. This means 3 graph traversals are thrown away, and the consolidated trace starts from scratch with a noisier seed set.

**This is a DRIFT-specific problem.** The original DRIFT paper assumes a retriever that can handle sub-questions independently and merge results. But in a graph traversal context, decomposing the query before seed extraction is the wrong order of operations. The correct sequence is:

```
Correct for graph: Query → NER → seeds → trace → THEN decompose for synthesis
Wrong for graph:   Query → decompose → NER per sub-Q → merge seeds → trace
```

Route 2 accidentally does this right by not decomposing at all.

### Defect 3: Coverage Gap Fill Is a 200-Line Band-Aid for Broken Primary Retrieval

Route 4's `_apply_coverage_gap_fill()` is 200+ lines of complex code that:
- Detects "comprehensive" queries via keyword pattern matching
- Fetches ALL chunks from ALL sections for "list all" queries
- Runs a custom hybrid keyword+semantic reranking with BM25-style scoring
- Uses a hand-tuned `0.7 * keyword + 0.3 * semantic` weighting formula
- Computes per-chunk keyword scores with unit-qualifier detection, stop-word removal, and penalty calculations

This is **compensating complexity**. If the primary retrieval (NER → beam search → chunk retrieval) worked correctly, coverage gap fill would be unnecessary for most queries. It exists because:

1. The entity-based retrieval misses entire documents (seed dilution from decomposition)
2. Some documents have weak entity representation in the graph
3. The primary path produces (entity_name, score) tuples that the text_store can't always resolve to chunks

Route 2 doesn't need coverage gap fill because its clean NER → PPR → denoised chunk path already achieves 10/10 containment. The Route 2 vector fallback experiment (#5) confirmed this: the graph path already finds everything.

**The fix is not to improve coverage gap fill — it's to fix the primary retrieval so gap fill isn't needed.**

### Defect 4: Route 4 Doesn't Benefit from the Production Denoising Stack

Looking at the actual production code (`src/worker/hybrid_v2/pipeline/synthesis.py`), the denoising stack (community filter, score-gap pruning, score-weighted allocation, semantic dedup, token budget) is implemented in `_retrieve_text_chunks()` — the same function Route 2 calls. **Route 4 also calls this function**, so it should theoretically benefit.

But there's a structural mismatch: Route 4 traces with `trace_semantic_beam()` which produces beam scores (cosine similarity), while Route 2 traces with `trace()` which produces PPR scores (decay-based). The denoising stack was tuned for PPR score distributions:

| Denoising Stage | Tuned For | Works With Beam Scores? |
|----------------|-----------|------------------------|
| Community filter | PPR scores → 0.3× penalty creates cliff | Maybe — beam scores have different distribution |
| Score-gap pruning | PPR decay → natural cliff at community boundary | **Unknown** — beam cosine scores may be flatter, no clear gap |
| Score-weighted allocation | PPR score ratio → top entity gets 12, bottom gets 1–2 | Maybe — depends on beam score spread |
| `SCORE_GAP_THRESHOLD=0.5` | Calibrated to PPR community-penalty cliff (~0.52 or ~0.70) | **Likely wrong** — beam scores won't hit these exact ratios |
| `SCORE_GAP_MIN_KEEP=6` | Set to prevent over-pruning with 13 PPR entities | Maybe OK — beam search returns up to 30 entities |

**The denoising stack needs beam-score-specific calibration**, not just enabling. The thresholds that work perfectly for Route 2's PPR score distribution may over-prune or under-prune Route 4's beam score distribution.

---

## 9. Summary: Fundamental vs. Fixable

| Issue | Classification | Fix |
|-------|---------------|-----|
| No dedup, no token budget, no denoising | **Fixable (subtraction)** | Enable existing toggles |
| Decomposition before NER (seed dilution) | **Fundamental to DRIFT** | Adaptive gate: skip decomposition for simple queries |
| Entity name mutation in sub-questions | **Fundamental to DRIFT** | Use original query for NER, sub-questions only for synthesis |
| Double tracing (discovery discarded) | **Design defect** | Reuse discovery evidence in consolidated trace |
| Coverage gap fill complexity | **Compensating mechanism** | Fix primary retrieval, then simplify/remove |
| Denoising thresholds tuned for PPR | **Calibration gap** | Benchmark beam score distributions, adjust thresholds |
| Old staging copy uses wrong tracer | **Code hygiene** | Remove or update the staging copy |

**The honest answer:** Route 4's DRIFT pattern has a fundamental tension with graph-based retrieval. DRIFT was designed for document retrieval systems where sub-question independence is a feature. In a knowledge graph, decomposing the query *before* entity resolution scatters seed quality across sub-questions, creating a noisier seed set than a single direct extraction.

The fix that preserves DRIFT's value while avoiding its graph-specific weakness:

```python
# Proposed: Hybrid NER-first + decompose-for-synthesis
seeds = await disambiguator.disambiguate(original_query)  # Route 2 style: clean, direct
evidence = await tracer.trace_semantic_beam(query, seeds)  # One trace, not 4

# DRIFT decomposition used ONLY for synthesis guidance:
sub_questions = await _drift_decompose(query)
response = await synthesizer.synthesize(
    query, evidence,
    sub_questions=sub_questions,  # These structure the output, not the retrieval
)
```

This gives Route 4 the best of both worlds: Route 2's clean retrieval + DRIFT's structured synthesis.
