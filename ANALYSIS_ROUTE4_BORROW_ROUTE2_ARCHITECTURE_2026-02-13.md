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
---

## 10. Reassessment: HippoRAG 2 Backbone & Purpose Gap

Two objections to the "borrow Route 2" thesis deserve serious examination:

1. **Route 4's backbone is HippoRAG 2** — will Route 2 improvements mis-align with the framework?
2. **Route 2 and Route 4 serve different purposes** — local vs DRIFT search. Can the same medicine work?

### 10.1 Objection 1: HippoRAG 2 Alignment

**Route 4 already departed from HippoRAG 2.**

The architecture doc records this explicitly:

> **Jan 10, 2026:** "Keep as optional/experimental. Default pipeline remains PPR-based per HippoRAG 2 design."
> **Jan 30, 2026:** Semantic beam search wired as Route 4's primary path. PPR (`trace()`) is now dead code in Route 4.

| HippoRAG 2 Core Component | Route 2 Status | Route 4 Status |
|---------------------------|----------------|----------------|
| Knowledge graph construction | **Uses** | **Uses** |
| PPR 5-path traversal | **Uses** (via `trace()`) | **Replaced** by `trace_semantic_beam()` |
| Seed resolution (NER → graph) | **Uses** (2 NER seeds → graph) | **Uses** (but via decomposed sub-questions) |
| Community detection (Louvain) | Not used | Not used (community augmentation is dead code) |
| Score propagation to synthesis | **Route 2 implemented this** | Route 4 inherits same code path |

Route 4's traversal engine is a **custom cosine-guided beam search**, not PPR. So the question is not "will Route 2 improvements break HippoRAG 2?" but "which improvements are traversal-algorithm-specific vs pipeline-general?"

**Sorting the improvements:**

| Improvement | Where It Acts | HippoRAG 2 Dependent? | Route 4 Compatible? |
|------------|---------------|----------------------|---------------------|
| MD5 chunk dedup | Post-retrieval | No — any retriever | **Yes** |
| Token budget (32K cap) | Post-retrieval | No — any retriever | **Yes** |
| Score-weighted allocation | Post-retrieval scoring | Depends on score type | **Yes, with recalibration** |
| Community filter (0.3× penalty) | Post-retrieval scoring | Uses Louvain `community_id` | **Yes** — same graph property |
| Score-gap pruning (0.5 threshold) | Post-retrieval scoring | Calibrated to PPR decay | **Needs recalibration** for beam cosine scores |
| Semantic dedup (Jaccard 0.92) | Post-retrieval | No — any retriever | **Yes** |
| NER-first (skip decomposition) | Pre-retrieval seed strategy | Affects HippoRAG 2's seed input | **See 10.2 below** |

**Verdict on HippoRAG 2 alignment:** 6 of 7 improvements are POST-retrieval. They sit downstream of the graph backbone — whether that backbone is PPR or semantic beam or anything else. They don't touch the HippoRAG 2 framework at all. They're **pipeline hygiene**, not framework changes.

The one improvement that touches the backbone — NER-first vs decompose-first — is examined below.

### 10.2 Objection 2: Local Search ≠ DRIFT Search

This is the stronger objection. The query types are genuinely different:

**Route 2 queries (local search):**
- "Who is the Agent in the property management agreement?" → NER extracts "Agent", "property management agreement"
- "What is the invoice amount for transaction TX-12345?" → NER extracts "TX-12345", "invoice"
- Every query mentions its target entities BY NAME

**Route 4 queries (DRIFT search):**
- "Compare time windows across the set and list all explicit day-based timeframes" → NER extracts... "time windows"? "timeframes"? These are CONCEPTS, not entity names in the graph.
- "Analyze our risk exposure through subsidiaries" → NER extracts "risk exposure", "subsidiaries" — abstract concepts, not graph entities.
- "If a pipe burst on Sunday, is certified mail valid notice?" → Requires conditional reasoning across clauses

**The DRIFT pattern exists precisely because direct NER fails on these queries.** The LLM decomposes the vague question into concrete sub-questions that ARE entity-extractable:

```
Vague:    "Compare time windows across the set"
          → NER: "time windows" (not a graph entity)

DRIFT:    Sub-Q1: "What are the day-based deadlines in the warranty?"
          → NER: "warranty" (exists in graph ✓)
          
          Sub-Q2: "What notice periods exist in the property management agreement?"
          → NER: "property management agreement" (exists in graph ✓)
```

**This means the Section 8 recommendation — "use Route 2's NER directly on the original query, decompose only for synthesis" — is wrong for genuine DRIFT queries.** If the original query has no extractable entities, NER-first produces nothing, and there are no seeds to trace.

### 10.3 Revised Assessment: Which Improvements Still Apply?

| # | Improvement | Applies to Route 4? | Why |
|---|------------|---------------------|-----|
| 1 | **Chunk dedup** | ✅ YES | Universal. Route 4 has 56.5% duplication — same root cause as Route 2 pre-fix |
| 2 | **Token budget** | ✅ YES | Universal. Route 4 context can hit 100K-460K tokens — worse than Route 2 |
| 3 | **Score-weighted chunk allocation** | ✅ YES, with recalibration | Beam cosine scores have different distributions than PPR scores. `SCORE_GAP_THRESHOLD=0.5` needs benchmarking with beam scores |
| 4 | **Community filter** | ✅ YES | Same Louvain `community_id` on same entity graph. Filter logic is framework-agnostic |
| 5 | **Score-gap pruning** | ⚠️ YES, with new threshold | PPR creates natural score cliffs at community boundaries. Beam search cosine scores are flatter — the 0.5 threshold may over-prune. Needs empirical calibration |
| 6 | **Semantic dedup** (Jaccard 0.92) | ✅ YES | Content-level filter, retriever-agnostic |
| 7 | **NER-first (skip decomposition)** | ❌ NO for genuine DRIFT queries | Vague/comparative queries have no extractable entities without decomposition |
| 8 | **Parse don't guess** (Azure DI sentences) | ✅ YES | Universal. Sentence-level evidence helps any synthesis task |

**Score: 6 of 8 improvements fully apply, 1 applies with recalibration, 1 does NOT apply to DRIFT.**

### 10.4 What DRIFT Genuinely Needs That Route 2 Doesn't

Route 4's purpose (cross-document reasoning) creates requirements that don't exist for Route 2:

| DRIFT-Specific Need | Why Route 2 Doesn't Need This | Current Implementation |
|---------------------|------------------------------|----------------------|
| Query decomposition | Route 2 queries already name their entities | `_drift_decompose()` — sound in principle |
| Multi-document coverage | Route 2 answers from 1-2 documents | Coverage gap fill — but 200 lines is too complex |
| Confidence assessment | Route 2 doesn't need to validate coverage breadth | `_compute_subgraph_confidence()` — reasonable |
| Structured multi-part output | Route 2 outputs single facts (avg 30 chars) | Sub-question-guided synthesis — valuable |

**These are legitimate architectural components that Route 2 doesn't possess and shouldn't.** The previous analysis overreached by suggesting Route 4 should be restructured to look like Route 2's "disambiguate → trace → synthesize" pipeline.

### 10.5 The Correct Improvement Strategy

The right approach is NOT "make Route 4 look like Route 2" but rather:

**A. Import Route 2's post-retrieval hygiene (items 1-6) verbatim.**
These are retriever-agnostic. They clean up the output of ANY retrieval pipeline — PPR, beam search, vector search, or DRIFT decomposition. This is not "borrowing from Route 2"; this is fixing shared infrastructure that Route 2 happened to fix first.

**B. Keep DRIFT decomposition for retrieval — but fix the seed dilution.**
DRIFT decomposition is correct for its purpose. The real problem is that decomposed sub-questions produce mutated entity names. The fix is not to remove decomposition but to:

```python
# Current (broken): NER runs on LLM-rephrased sub-questions
sub_qs = await _drift_decompose(query)
for sub_q in sub_qs:
    entities = await disambiguate(sub_q)          # LLM-rephrased text produces bad entity names
    seeds.extend(entities)

# Fixed: NER runs on BOTH original + sub-questions, deduplicated
original_entities = await disambiguate(query)     # Direct extraction — high precision
sub_qs = await _drift_decompose(query)
for sub_q in sub_qs:
    sub_entities = await disambiguate(sub_q)      # Also extract — covers concepts after decomposition
    seeds.extend(sub_entities)
seeds = deduplicate_by_graph_id(original_entities + sub_entities)  # Union, no duplication
```

This preserves DRIFT's ability to extract entities from vague sub-questions while adding Route 2's "extract from exact query text" as a high-precision baseline. The union is always ≥ either alone.

**C. Fix the double tracing.**
Reuse Stage 4.2 discovery evidence in the consolidated trace. This doesn't change the DRIFT architecture — it's a pure efficiency fix:

```python
# Current: discovery evidence discarded
discovery_evidence = {}
for sub_q, sub_seeds in sub_question_entities.items():
    traces = await tracer.trace_semantic_beam(sub_q, sub_seeds, top_k=5)
    # traces used ONLY for confidence counting, then lost
    
# Consolidated trace starts from scratch
all_evidence = await tracer.trace_semantic_beam(query, all_seeds, top_k=30)

# Fix: carry discovery evidence forward
all_evidence = merge(discovery_evidence, consolidated_trace)
```

**D. Simplify coverage gap fill.**
The 200-line BM25 reranker exists because primary retrieval misses documents. With fixes A+B (cleaner seeds, denoised context), fewer documents will be missed. The gap fill can be reduced to a simple "fetch 1-2 chunks from any document not yet represented" — ~20 lines instead of 200.

**E. Recalibrate score thresholds for beam cosine scores.**
Route 2's thresholds (`SCORE_GAP_THRESHOLD=0.5`, `SCORE_GAP_MIN_KEEP=6`) were tuned for PPR score distributions. Beam search cosine scores have different characteristics:

| Property | PPR Scores | Beam Cosine Scores |
|----------|-----------|-------------------|
| Range | 0-1 (decay from seeds) | -1 to 1 (cosine similarity) |
| Distribution | Steep drop at community boundary | Gradual gradient, no structural cliff |
| Top-to-bottom ratio | 10-50× | 2-5× |
| Natural pruning point | Yes (community boundary cliff) | No clear cliff |

Score-gap pruning with 0.5 threshold may prune too aggressively (if beam scores cluster 0.7-0.9, a 0.5 threshold keeps everything) or too weakly (if beam scores cluster 0.3-0.5, it prunes nothing). Empirical benchmarking required.

### 10.6 Corrected Summary

| Previous Recommendation | Status After Reassessment |
|------------------------|--------------------------|
| "NER-first, decompose only for synthesis" | ❌ **Retracted** — defeats DRIFT's purpose for vague queries. Replaced with "NER on original+decomposed, union" |
| "Route 4 should look like Route 2's 3-stage pipeline" | ❌ **Retracted** — Route 4 needs decomposition, confidence loops, coverage fill. These are not defects for DRIFT |
| "DRIFT decomposition is a fundamental defect" | ⚠️ **Revised** — decomposition is architecturally necessary. The defect is entity name mutation, not decomposition itself |
| "Double tracing is wasteful" | ✅ **Confirmed** — still correct. Discovery evidence should be reused |
| "Coverage gap fill is a band-aid" | ⚠️ **Revised** — some coverage fill is structurally necessary for DRIFT (cross-document queries NEED multi-document coverage). But 200 lines of BM25 reranking is still too complex |
| "Enable Route 2's denoising stack" | ✅ **Confirmed** — post-retrieval hygiene is universal, not Route-2-specific. Threshold recalibration needed for beam scores |
| "HippoRAG 2 alignment concern" | ✅ **Resolved** — Route 4 already departed from HippoRAG 2 (semantic beam, not PPR). Post-retrieval improvements don't touch the backbone |

**Bottom line:** 6 of 7 concrete improvements still apply. The one correction is significant — DRIFT decomposition must be preserved for retrieval, not just synthesis — but the path forward is clear: fix the shared plumbing (denoising stack), fix the DRIFT-specific seed quality (union strategy), and recalibrate thresholds for beam scores.

---

## Section 11: PPR → Semantic Beam Switch Evaluation (HippoRAG 2 Alignment Analysis)
*Added 2026-02-13 — Evaluating whether the Jan 30 traversal algorithm switch was beneficial*

### 11.1 Background

Route 4 switched from PPR (`personalized_pagerank_native` via `tracer.trace()`) to semantic beam search (`semantic_multihop_beam` via `tracer.trace_semantic_beam()`) on ~Jan 30 2026. The stated motivation was to provide "multi-hop reasoning capability" aligned with DRIFT's cross-document purpose.

This section evaluates: **was that switch a net positive or negative?**

### 11.2 Benchmark Timeline (Route 4 Only)

| Date | Traversal | Test Set | Score | Notes |
|------|-----------|----------|-------|-------|
| Dec 31 | PPR (basic) | 19 questions (Q-D1-D10 + Q-N1-N9) | exact_avg = 0.333 | Early pipeline, no denoising, basic NER |
| Jan 19 | PPR + entity aliases | 19 questions | 93% (53/57) | Major jump from alias resolution |
| Jan 28 | PPR + GDS V2 index (506 KNN edges) | 19 questions | **98.2% (56/57)** | Near-perfect. Peak PPR score |
| ~Jan 30 | **Switch to semantic beam** | — | — | No A/B benchmark at switch point |
| Feb 5 | Beam (beam_width=30, max_hops=3) | **11 of 19 questions** | 97% (32/33) | Only 58% of test set; not comparable to Jan 28 |
| Feb 7 | Beam | Invoice consistency test | 75% (gpt-5.1) / 56% (gpt-4.1) | Different test methodology, but significantly lower |

**Critical observation:** There is **no controlled A/B test** comparing PPR and beam on the same test set, same index, same pipeline. The Jan 28 → Feb 5 comparison is confounded by:
1. Different test sets (19 vs 11 questions)
2. Different pipeline versions (synthesis changes between dates)
3. Possible index changes

### 11.3 How The Two Algorithms Work

**PPR (`personalized_pagerank_native`, L569-780 in `async_neo4j_service.py`):**
- Seeds: disambiguated entities from query
- Traversal: 5 parallel paths — (1) entity edges, (2) section similarity, (3) KNN similarity edges, (4) SHARES_ENTITY relationships, (5) hub entity expansion
- Scoring: Sum of weighted path contributions with damping=0.85, max_iterations=20
- Score distribution: steep decay from seeds, natural cliff at community boundary
- Result: Returns `List[Tuple[str, float]]` — (entity_name, PPR_score)

**Semantic beam (`semantic_multihop_beam`, L1286-1520 in `async_neo4j_service.py`):**
- Seeds: same disambiguated entities
- Traversal: At each hop (0 to max_hops=3), expand neighbors, compute `vector.similarity.cosine(entity.embedding, query_embedding)`, keep top `beam_width=30`
- **Hop-0 vector injection**: Before any graph traversal, runs a vector similarity search across ALL entities and injects those with score ≥ threshold at 0.9× — **these entities may have zero graph connectivity to the seed entities**
- Score: accumulated_cosine × damping^hop
- Score distribution: gradual gradient (cosine 0.3-0.9 range), no structural cliff, top-to-bottom ratio 2-5×

### 11.4 Three Problems Introduced by the Switch

#### Problem 1: Hop-0 Vector Injection Bypasses Graph Structure

The beam search's hop-0 step finds entities by **vector similarity to the query**, not by graph connectivity:

```python
# From semantic_multihop_beam() — hop-0 expansion
vector_similar = await session.run("""
    MATCH (e:Entity)
    WHERE vector.similarity.cosine(e.embedding, $query_embedding) >= $threshold
    RETURN e.name, vector.similarity.cosine(e.embedding, $query_embedding) AS score
""")
for entity_name, score in vector_similar:
    beam_scores[entity_name] = score * 0.9  # Injected at 0.9× with NO graph path
```

This means entities can enter the result set with **no graph relationship to the seed entities**. PPR, by contrast, can only reach entities that are graph-connected (through one of 5 traversal paths) to the seeds. The hop-0 injection effectively makes beam search a **hybrid of graph traversal and vector search** — which may explain why `comprehensive_sentence` mode (pure vector, bypasses graph entirely) achieves 100% accuracy: the graph layer may be adding noise, not signal.

#### Problem 2: Score Distribution Mismatch with Denoising Stack

Route 2's denoising stack was calibrated for PPR score distributions:
- `SCORE_GAP_THRESHOLD=0.5` — works because PPR creates natural 10-50× score gaps at community boundaries
- `SCORE_GAP_MIN_KEEP=6` — tuned for PPR's typical 15-30 entity result sets

Beam cosine scores cluster in a narrower band (0.3-0.9) with 2-5× top-to-bottom ratios. The 0.5 gap threshold either:
- Over-keeps (if scores are 0.7-0.9, no gap exceeds 0.5 → everything kept)
- Over-prunes (if scores are 0.3-0.5, first gap may hit threshold → too few kept)

**This is fixable** (recalibrate thresholds), but it means that when/if the denoising stack IS enabled for Route 4, it will behave unpredictably with beam scores out of the box.

#### Problem 3: Coverage Loss

Jan 28 (PPR) tested all 19 questions → 56/57 sub-answers correct (98.2%).
Feb 5 (beam) tested only 11 questions → 32/33 sub-answers correct (97%).
The 8 dropped questions were never re-tested with beam search. We don't know if beam handles those 8 questions well or poorly — and their omission makes the 97% figure misleadingly comparable to 98.2%.

### 11.5 The `comprehensive_sentence` Mode Signal

A key data point from the architecture docs: `comprehensive_sentence` mode — which **bypasses the graph entirely** and retrieves chunks via pure vector similarity — achieves **100% accuracy** on containment questions. This suggests:

1. The vector embeddings (Voyage voyage-context-3, 2048-dim) are high quality
2. The knowledge graph layer may be **introducing noise** rather than providing precision
3. The graph's value may be limited to negative containment (knowing what's NOT there) rather than positive retrieval

If pure vector search achieves 100% and PPR achieves 98.2%, while beam search (a hybrid that mixes graph + vector) achieves ≤97%, then the beam search may be getting the **worst of both worlds** — graph noise without vector completeness.

### 11.6 Historical Decision Context

The architecture docs record a Jan 10 decision:

> "Keep semantic beam experimental; PPR remains the default traversal for production."

This was arguably the correct call. The Jan 30 reversal to make beam the default was done without:
- A controlled A/B benchmark on the full test set
- Score distribution analysis comparing beam vs PPR outputs
- Denoising stack compatibility testing
- Rollback criteria

### 11.7 Verdict

| Dimension | PPR | Semantic Beam | Winner |
|-----------|-----|---------------|--------|
| Best measured accuracy | 98.2% (56/57, full set) | 97% (32/33, partial set) | **PPR** (higher score, fuller test) |
| Graph structure fidelity | ✅ Only graph-connected entities | ⚠️ Hop-0 injects vector-only entities | **PPR** |
| Denoising compatibility | ✅ Calibrated thresholds | ⚠️ Score distribution mismatch | **PPR** |
| Multi-hop reasoning | Limited (walks graph, doesn't "hop" semantically) | ✅ Designed for multi-hop traversal | **Beam** |
| Controlled evidence | None (no direct comparison) | None (no direct comparison) | **Draw** — no A/B exists |

### 11.8 Recommendation: Clean First, Then Test

**Testing PPR vs beam right now is meaningless.** The shared pipeline has:
- 56.5% chunk duplication (no dedup)
- No token budget (context can hit 460K tokens)
- Evidence scores discarded before synthesis
- No score-gap pruning, no community filter, no semantic dedup

Any difference between PPR and beam scores is **drowned in pipeline noise**. A performance delta could be caused by the traversal algorithm OR by document duplication OR by context overflow OR by score information loss.

**The correct order:**
1. **Enable Route 2's denoising stack for Route 4** — this is retriever-agnostic and fixes the shared pipeline
2. **Re-benchmark on the clean pipeline** with the current beam search to get a fresh baseline
3. **A/B test**: Run the same 19 questions with (a) `tracer.trace()` (PPR) and (b) `tracer.trace_semantic_beam()` (beam) on the now-clean pipeline
4. **Measure**: accuracy, retrieval precision, token count, latency
5. **Decide** based on data, not architecture intuition

This isolates the traversal algorithm as the **sole variable**, eliminating the noise-on-noise problem that would confound any test run today.

### 11.9 Risk Note

If beam search is found to be inferior after cleaning, reverting to PPR is straightforward — `trace_semantic_beam()` already has a built-in fallback to `trace()`. The code change is a single function call swap in `route_4_drift.py`.

---

## Section 12: Denoising Stack Audit — Correction & Coverage Gap Bypass
*Added 2026-02-13 — Code audit reveals the denoising stack is ALREADY active for Route 4*

### 12.1 Previous Claim vs Reality

| What we believed | What the code shows |
|------------------|-------------------|
| "Route 4 has NO denoising" | ❌ **Wrong.** Route 4 calls `synthesize()` → `_retrieve_text_chunks()` which runs the FULL denoising stack |
| "56.5% chunk duplication" | This was measured from older benchmarks BEFORE the Feb 9-10 denoising additions |
| "Scores are discarded" | ❌ **Wrong.** Beam scores flow through as `evidence_nodes: List[Tuple[str, float]]` → `entity_scores` dict → `_entity_score` stamped on every chunk |

### 12.2 What IS Enabled (Verified by Code Reading)

`_retrieve_text_chunks()` in [synthesis.py](src/worker/hybrid_v2/pipeline/synthesis.py) runs these features for **all callers** (Route 2, Route 4, any route) with no route-specific gating:

| # | Feature | Location | Env Var | Default |
|---|---------|----------|---------|---------|
| 1 | Document scoping (IDF voting) | L1153-1167 | `DOC_SCOPE_ENABLED` | ON (`"1"`) |
| 2 | Community filter (Louvain penalty) | L1173-1214 | `DENOISE_COMMUNITY_FILTER` | ON (`"1"`) |
| 3 | Score-gap pruning | L1222-1268 | `DENOISE_SCORE_GAP` | ON (`"1"`) |
| 4 | Score-weighted chunk allocation | L1274-1295 | `DENOISE_SCORE_WEIGHTED` | ON (`"1"`) |
| 5 | Content-hash dedup (MD5) | L1376-1426 | `DENOISE_DISABLE_DEDUP` | ON (need `"1"` to disable) |
| 6 | Semantic near-dedup (Jaccard 0.92) | L1430-1493 | `DENOISE_SEMANTIC_DEDUP` | ON (`"1"`) |
| 7 | Noise filters (form labels, headings) | L1496-1505 | `DENOISE_DISABLE_NOISE` | ON (need `"1"` to disable) |
| 8 | Document-coherence penalty | L1509-1531 | `DENOISE_DOC_COHERENCE` | ON (`"1"`) |
| 9 | Token budget (32K) | L1714-1736 | `DENOISE_DISABLE_BUDGET` | ON (need `"1"` to disable) |

No `.env` files override any of these defaults. **All 9 denoising features are active for Route 4.**

### 12.3 The Real Problem: Coverage Gap Fill Bypass

After `_retrieve_text_chunks()` returns denoised chunks, Route 4's **coverage gap fill** injects additional chunks that **bypass the entire denoising stack**:

```python
# synthesis.py L237-242
text_chunks, entity_scores, retrieval_stats = await self._retrieve_text_chunks(evidence_nodes, query=query)

# Step 1.5: Merge coverage chunks if provided ← THIS IS THE BYPASS
if coverage_chunks:
    text_chunks.extend(coverage_chunks)  # Injected AFTER denoising
```

Coverage chunks created in `route_4_drift.py` L607-958:
- **No `_entity_score`** — defaults to 0.0 in downstream sorting
- **No MD5 dedup** against entity-retrieved chunks
- **No semantic dedup** — may duplicate entity-retrieved content
- **No community filter** — can come from any community
- **No score-gap pruning** — included regardless of relevance

For **comprehensive queries** (`"list all"`, `"compare across"`, etc.), the coverage gap fill uses `max_per_section=None` — fetching **ALL chunks from ALL sections**, potentially hundreds of chunks. These are then hybrid-reranked with a 200-line BM25+semantic scoring system, but NOT denoised.

### 12.4 Why This Matters Less Than Expected

The coverage chunks have an implicit safety net: the **token budget in `_build_cited_context()`** (L1714-1736) sorts ALL chunks (including coverage) by `_entity_score` descending and drops those exceeding 32K tokens. Since coverage chunks default to `_entity_score=0.0`, they sort **last** and are the first to be cut.

**In practice:**
- If entity retrieval produces enough chunks to fill 32K → coverage chunks are **entirely dropped** by the budget
- If entity retrieval produces few chunks → coverage chunks fill the remaining budget, but as the **lowest-priority** content
- The only scenario where coverage chunks cause real harm is when entity retrieval returns almost nothing (a common Route 4 failure mode with poorly-resolved seeds)

### 12.5 Revised Diagnosis: Why Is Route 4 Still Underperforming?

Since the denoising stack IS active, the problem isn't "no denoising." The likely causes are:

1. **Score-distribution mismatch**: The `SCORE_GAP_THRESHOLD=0.5` was tuned for PPR's steep decay curve. Beam cosine scores cluster in a narrower 0.3-0.9 band with 2-5× top-to-bottom ratios. The score-gap pruning may not fire at all (no gap exceeds 50% relative drop), leaving too many low-quality entities.

2. **Coverage gap fill noise injection**: For queries where entity retrieval is sparse (common in DRIFT), most of the context comes from un-denoised coverage chunks at score=0.0. The LLM sees a mix of high-quality denoised content and bulk un-filtered section dumps.

3. **Seed quality**: DRIFT decomposition mutates entity names (Section 10). Even with denoising, if the wrong entities are traced, the denoised chunks are still wrong-topic.

4. **Community filter mismatch**: DRIFT queries intentionally span multiple documents/communities. The community filter (which penalizes out-of-community entities by 0.3×) may be counterproductive for Route 4 — penalizing exactly the cross-document entities that DRIFT needs.

### 12.6 Revised Action Plan

Instead of "enable denoising" (already done), the correct actions are:

| # | Action | Rationale |
|---|--------|-----------|
| 1 | **Calibrate `SCORE_GAP_THRESHOLD` for beam scores** | Beam cosine scores have different distributions. Needs empirical profiling of typical beam output |
| 2 | **Consider disabling community filter for Route 4** | DRIFT intentionally spans communities. Penalizing cross-community entities defeats the purpose |
| 3 | **Apply denoising to coverage chunks** | Run the coverage chunks through at least MD5 dedup and semantic dedup before merging |
| 4 | **Stamp coverage chunks with meaningful scores** | Use the hybrid reranking score (already computed) as `_entity_score` so the token budget sorts them properly |
| 5 | **Fix seed quality** | NER on original + decomposed (union), as recommended in Section 10 |
| 6 | **Profile actual denoising behavior** | Run a benchmark and log the denoising stats to see what's actually happening (community filter counts, score-gap triggers, dedup ratios) |

### 12.7 Corrected Bottom Line

The denoising stack was never the missing piece — **it's been running all along.** The real issues are:
- **Calibration**: thresholds tuned for PPR, not beam cosine
- **Community filter**: potentially counterproductive for cross-document DRIFT queries
- **Coverage gap fill bypass**: un-denoised bulk chunks injected after the stack
- **Seed quality**: upstream entity resolution, not downstream denoising