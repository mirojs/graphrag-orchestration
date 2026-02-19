# Route 3 LazyGraphRAG Deviation Analysis & Route 6 Plan

**Date**: 2026-02-19
**Context**: Route 5 is being repositioned to entity search. We need Route 6 for concept search. Before building Route 6, we evaluated whether to copy Route 3 or start fresh, which led to a deep analysis of Route 3's deviations from the LazyGraphRAG framework.

---

## 1. Can LazyGraphRAG Do Concept Search By Itself?

**Short answer**: Yes, architecturally. No, in our current implementation.

LazyGraphRAG's core mechanism — community summaries + MAP-REDUCE synthesis — is purpose-built for concept search. The design:

1. **Index time**: Louvain community detection groups semantically related entities. LLM generates summaries capturing thematic relationships.
2. **Query time**: Query embedding is compared via cosine similarity against community summary embeddings. Top-matching communities provide thematic context for synthesis.

This is fundamentally a **concept-level retrieval system** — communities represent themes/concepts, not individual facts. The framework should handle questions like "What are the key financial risks?" by matching to communities about financial risk factors.

**Why it fails in practice**: Three critical issues prevent this from working in our implementation:
- Community matching is broken (returns 0.0 scores for all queries)
- Communities are built on entity co-occurrence, not semantic themes
- 5 lossy abstraction layers between raw text and final answer

---

## 2. Route 3 Deviations from LazyGraphRAG Framework

We identified **4 deviations** from the original LazyGraphRAG design. Not all are negative.

### Deviation 1: MAP Claims Extraction (Slightly Negative)

**What LazyGraphRAG does**: Passes community summaries directly to a REDUCE synthesizer.

**What Route 3 does**: Adds a MAP phase — for each matched community, an LLM call extracts "claims" from the community summary, then REDUCE synthesizes across claims.

**Impact on concept search**: Slightly negative.
- Adds latency (N parallel LLM calls before synthesis)
- Adds a lossy abstraction layer — the MAP prompt can distort or drop thematic context
- For concept search, the community summary IS the relevant context; re-extracting "claims" from it is redundant

### Deviation 2: Sentence Search Bolt-on (Positive)

**What LazyGraphRAG does**: Relies entirely on community summaries for retrieval.

**What Route 3 does**: Adds parallel sentence vector search with denoising and reranking, merged with community results before synthesis.

**Impact on concept search**: Positive.
- Provides grounding — community summaries are LLM-generated abstractions; sentence evidence provides actual source text
- Compensates for community matching failures by providing a working retrieval path
- This is actually the part of Route 3 that works well today

### Deviation 3: Broken Community Matching (Critically Negative)

**What LazyGraphRAG does**: Cosine similarity between query embedding and community summary embeddings to find thematically relevant communities.

**What Route 3 does**: Same intent, but the implementation is broken:
- Communities get fallback embeddings at creation time (embedded from entity names, not summaries)
- When LLM summaries are later added, `_ensure_embeddings()` does NOT re-embed because the existing embedding has correct dimensions (2048-dim Voyage)
- Result: All community embeddings encode entity name lists, not summary content
- Cosine similarity returns near-0.0 for all queries
- Community matching contributes nothing to retrieval

**Impact on concept search**: Critically negative. This breaks the entire LazyGraphRAG premise. Without working community matching, the framework's core value proposition — theme-level retrieval — is disabled.

### Deviation 4: No Iterative Deepening (Moderately Negative)

**What LazyGraphRAG does**: If initial community matches don't provide sufficient coverage, iteratively widen the search by lowering the similarity threshold or exploring adjacent communities.

**What Route 3 does**: Single-pass matching with a fixed threshold. No fallback if results are poor.

**Impact on concept search**: Moderately negative. For broad concept queries, a single pass may miss relevant communities at the boundary of the similarity threshold.

---

## 3. Route 3's Six Problems (Pre-Fix)

1. **Broken community matching** — stale embeddings from entity names, not summaries (FIXED — see Phase 1)
2. **5 lossy abstraction layers** — raw text → chunks → entities → communities → MAP claims → REDUCE synthesis. Each layer loses information.
3. **Expensive MAP phase** — N LLM calls per query for claim extraction, adding latency without proportional value
4. **No token budget** — no control over how much context is passed to synthesis
5. **Coverage gaps** — communities built from entity co-occurrence miss concepts that span entity boundaries
6. **Dead PPR path** — PersonalizedPageRank code exists but is disconnected from the pipeline

---

## 4. What We Fixed (Phase 1)

### Phase 1A: Stale-Embedding Detection in `community_matcher.py`

Added hash-based content tracking to `_ensure_embeddings()`:
- Each community's embedding source text is hashed (SHA-256, truncated to 16 chars)
- Hash is stored in Neo4j as `c.embedding_text_hash`
- On load, if the hash of current summary text differs from stored hash, the embedding is marked stale and re-embedded
- Three conditions now trigger re-embedding: (1) no embedding, (2) wrong dimensions, (3) hash mismatch

### Phase 1B: Embedding Invalidation in `materialize_communities.py`

- Added `clear_community_embeddings()` function to wipe embeddings + hashes
- Added `--regenerate-embeddings` CLI flag
- Auto-clearing after `generate_llm_summaries()` succeeds — ensures stale embeddings are wiped when summaries change

### Phase 2A: Unit Tests

12 tests added to `test_community_materialization.py`:
- Discriminative scoring with distinct embeddings
- Different queries selecting different communities
- Threshold filtering (scores below 0.05)
- Dimension mismatch handling
- Hash computation (summary vs fallback text)
- Stale content detection and re-embedding
- Cosine similarity correctness

All 12 tests pass.

---

## 5. Route 6 Design Rationale

Route 6 should restore the LazyGraphRAG insight while keeping Route 3's positive deviation (sentence search). The key architectural decision: **no MAP phase**.

### Route 6 Pipeline (Planned)

```
Step 1: Parallel community match + sentence search
Step 2: Resolve community members → PPR seed entities (optional)
Step 3: Concept-weighted PPR traversal (optional, skip if no seeds)
Step 4: Merge PPR evidence + sentence evidence + community summaries
Step 5: Single LLM synthesis call
```

### Key Differences from Route 3

| Aspect | Route 3 | Route 6 |
|--------|---------|---------|
| Community summaries | MAP-extracted claims (lossy) | Passed directly to synthesis |
| LLM calls per query | N (MAP) + 1 (REDUCE) | 1 (synthesis only) |
| Sentence search | Yes (bolt-on) | Yes (integrated) |
| PPR traversal | Dead code | Optional, concept-weighted |
| Token budget | None | Planned |
| Abstraction layers | 5 | 3 (sentences + communities + synthesis) |

### Why Not Just Fix Route 3?

Route 3's MAP-REDUCE architecture is load-bearing — removing the MAP phase changes the entire pipeline structure, prompt design, and result merging logic. It's cleaner to build Route 6 with the right architecture than to surgically remove MAP from Route 3.

Route 3 continues to serve as the existing global search route. Route 6 is purpose-built for concept search with a streamlined pipeline.

---

## 6. Benchmark Results (Pre-Fix Baseline, 2026-02-19)

Benchmarks ran against the **cloud API** which does NOT yet have our community matching fix deployed. This establishes a pre-fix baseline. Communities currently have **0 LLM summaries** — community matching contributes nothing.

### Route 3 (Global Search) — Q-G questions

| QID | Theme Coverage | Containment | Latency (ms) |
|-----|---------------|-------------|--------------|
| Q-G1 | 100% (7/7) | 0.98 | 9,765 |
| Q-G2 | 100% (5/5) | 1.00 | 5,993 |
| Q-G3 | 100% (8/8) | 0.78 | 7,104 |
| Q-G4 | 100% (6/6) | 0.84 | 4,613 |
| Q-G5 | 100% (6/6) | 0.55 | 10,915 |
| Q-G6 | 88% (7/8) | 0.86 | 6,808 |
| Q-G7 | 80% (4/5) | 0.88 | 7,386 |
| Q-G8 | 100% (6/6) | 0.82 | 7,538 |
| Q-G9 | 100% (6/6) | 0.94 | 5,035 |
| Q-G10 | 83% (5/6) | 0.66 | 5,880 |
| **Average** | **95%** | **0.83** | **7,104** |

- Negative tests: **9/9 PASS**

### Route 4 (Drift Multi-Hop) — Q-D questions, LLM Judge Eval

| QID | LLM Score | Containment | Latency (ms) |
|-----|-----------|-------------|--------------|
| Q-D1 | 3/3 | 1.00 | 39,357 |
| Q-D2 | 3/3 | 1.00 | 41,417 |
| Q-D3 | 2/3 | 0.90 | 70,344 |
| Q-D4 | 3/3 | 1.00 | 37,849 |
| Q-D5 | 3/3 | 1.00 | 76,692 |
| Q-D6 | 3/3 | 0.90 | 38,953 |
| Q-D7 | 3/3 | 1.00 | 2,048 |
| Q-D8 | 2/3 | 0.84 | 36,962 |
| Q-D9 | 3/3 | 0.96 | 73,629 |
| Q-D10 | **1/3** | 0.97 | 107,540 |
| **Average** | **53/57 (93%)** | **0.96** | **52,479** |

- Negative tests: **9/9 PASS** (all 3/3)
- Pass rate (score >= 2): **94.7%** (18/19)
- Q-D10 is the only fail — cross-document thematic synthesis without community context

### Key Insight: Sentence Search Carries Route 3

Route 3 achieves 95% theme coverage and 83% containment **with community matching contributing 0%**. All retrieval comes from the sentence search bolt-on:

1. Query → Voyage embedding → `sentence_embeddings_v2` vector index (Neo4j)
2. Top-k sentences with prev/next context expansion
3. Document diversification (min 2 per qualifying doc)
4. Denoise → Rerank (Voyage rerank-2.5)
5. Merged with (empty) community claims → REDUCE synthesis

This is effectively **vector RAG on sentence nodes**, not the LazyGraphRAG community pipeline. The community path (LazyGraphRAG's core mechanism) is dead weight in the current system.

### What This Means

1. **Route 3's accuracy is real but not from communities** — sentence search is a strong retrieval mechanism on its own
2. **Community matching fix is necessary but not sufficient** — we also need LLM summaries for communities before any improvement will show
3. **Q-D10 (cross-doc thematic synthesis) is the canary** — currently the weakest result, and exactly the question type where working community matching should help
4. **Route 6 must keep sentence search as primary retrieval** — it's proven. Community context should augment, not replace it

### Fix Chain (Completed — With Critical Finding)

Steps completed:

1. **Generate LLM summaries** for all 27 communities ✅ (27/27 generated, 35.9s)
2. **Clear stale embeddings** ✅ (27 embeddings + hashes cleared in Neo4j)
3. **Re-run benchmarks** ✅ — Results **identical** to pre-fix baseline

**Why no improvement:** The cloud server's `CommunityMatcher` has an in-memory cache
(`self._loaded = True`). It loaded communities once at startup — before we generated
summaries. On subsequent requests it skips Neo4j and uses stale cached data:

```
match_communities() → self._loaded is True → skip Neo4j load → use old cache
  → old entity-name titles, empty summaries, old entity-name embeddings
  → MAP phase: summary.strip() == "" → return (title, [])  # zero claims
  → all_claims = []
  → REDUCE prompt: "(No community claims extracted)" + sentence evidence
  → LLM synthesizes from sentence evidence ONLY
```

Evidence: pre-fix and post-fix community paths are **byte-identical** across all
10 questions — same communities, same order, same titles. The server never saw our changes.

**To actually test:** Server restart required to invalidate in-memory cache, pick up
new summaries from Neo4j, and re-embed with summary text.

### Confirmed: Route 3 Runs on Sentence Search Only

The MAP phase produces zero claims because all community summaries are empty strings
in the server cache. The REDUCE prompt receives `(No community claims extracted)` for
the community section. All accuracy — 95% theme coverage, 83% containment — comes
entirely from the sentence evidence path.

Route 3 is functionally a **sentence vector RAG system** with a no-op community pipeline.
The LazyGraphRAG community matching → MAP → REDUCE architecture contributes 0% to accuracy.

### Post-Restart Benchmark: Communities Actually Working (Server Restarted)

After restarting the cloud server to force reload from Neo4j, community matching
now uses real LLM summaries. Example: query "What are the termination clauses?"
matched "Agreement Termination and Owner Responsibilities" (score 0.52), and
MAP extracted 4 claims. `total_claims` went from 0 to 5+.

**Route 3 results with working communities vs baseline (no communities):**

| QID | Baseline Contain | Working Contain | Delta | Latency Delta |
|-----|-----------------|-----------------|-------|---------------|
| Q-G1 | 0.98 | 0.98 | +0.00 | -2,242ms |
| Q-G2 | 1.00 | 1.00 | +0.00 | +2,824ms |
| Q-G3 | 0.78 | 0.78 | +0.00 | +3,307ms |
| Q-G4 | 0.84 | **0.92** | **+0.08** | +2,419ms |
| Q-G5 | 0.55 | 0.60 | +0.05 | +8,375ms |
| Q-G6 | 0.86 | **0.95** | **+0.09** | +9,231ms |
| Q-G7 | 0.88 | 0.88 | +0.00 | +1,824ms |
| Q-G8 | 0.82 | 0.82 | +0.00 | -1,572ms |
| Q-G9 | 0.94 | 0.94 | +0.00 | +1,450ms |
| Q-G10 | 0.66 | **0.51** | **-0.14** | +3,873ms |
| **Avg** | **0.83** | **0.84** | **+0.01** | **+2,949ms (+41%)** |

**Citations added:** 0 community citations (baseline) → **39 community citations** (fixed).
Document citations stayed at 38 — communities are additive, not replacing.

**What improved (3 questions):**
- **Q-G4** (+0.08): Community "Property Inspection and Reporting Process" surfaced
  inspection/reporting details not in sentence evidence. Response grew +537 chars.
- **Q-G6** (+0.09): Biggest win. 8 community citations added entity-document
  mappings. Response grew +3,172 chars (1,480→4,652). Communities helped enumerate
  named parties across documents.
- **Q-G5** (+0.05): Minor improvement, response grew +664 chars.

**What regressed (1 question):**
- **Q-G10** (-0.14): "Summarize each document's main purpose in one sentence."
  10 community citations injected too much detail. The LLM got distracted from
  concise summaries and wrote verbose paragraphs (1,202→2,420 chars). MAP claims
  **actively hurt** by diluting focus.

**What didn't change (6 questions):**
- Q-G1, Q-G2, Q-G3, Q-G7, Q-G8, Q-G9: Sentence evidence already covered everything.
  Community claims were redundant padding.

**Route 4 unchanged** (as expected — drift doesn't use community matching):
- LLM Judge total: 52/57 (91%), within variance of baseline 53/57 (93%)
- Q-D10 still fails at 1/3 — this question needs Route 6's architecture

### Conclusion: MAP-REDUCE Is the Wrong Consumer for Community Summaries

Community summaries have real value — they captured thematic structure (Q-G4, Q-G6).
But the MAP extraction layer is the wrong way to consume them:

1. **Lossy**: MAP extracts "claims" from summaries, losing thematic framing
2. **Expensive**: N extra LLM calls per query (+41% latency for +1% containment)
3. **Can regress**: MAP claims can dilute focus when the query needs conciseness (Q-G10)
4. **Redundant**: 6/10 questions — sentence evidence already had the same information

Route 6's design (pass summaries directly to synthesis as thematic context, no MAP)
should capture the upside (Q-G4, Q-G6) while avoiding the downside (Q-G10 regression,
+41% latency).

---

## 7. Route 6 Design Rationale

Route 6 should restore the LazyGraphRAG insight while keeping Route 3's positive deviation (sentence search). The key architectural decision: **no MAP phase**.

### Route 6 Pipeline (Planned)

```
Step 1: Parallel community match + sentence search
Step 2: Resolve community members → PPR seed entities (optional)
Step 3: Concept-weighted PPR traversal (optional, skip if no seeds)
Step 4: Merge PPR evidence + sentence evidence + community summaries
Step 5: Single LLM synthesis call
```

### Key Differences from Route 3

| Aspect | Route 3 | Route 6 |
|--------|---------|---------|
| Community summaries | MAP-extracted claims (lossy) | Passed directly to synthesis |
| LLM calls per query | N (MAP) + 1 (REDUCE) | 1 (synthesis only) |
| Sentence search | Yes (bolt-on) | Yes (integrated) |
| PPR traversal | Dead code | Optional, concept-weighted |
| Token budget | None | Planned |
| Abstraction layers | 5 | 3 (sentences + communities + synthesis) |

### Why Not Just Fix Route 3?

Route 3's MAP-REDUCE architecture is load-bearing — removing the MAP phase changes the entire pipeline structure, prompt design, and result merging logic. It's cleaner to build Route 6 with the right architecture than to surgically remove MAP from Route 3.

Route 3 continues to serve as the existing global search route. Route 6 is purpose-built for concept search with a streamlined pipeline.
