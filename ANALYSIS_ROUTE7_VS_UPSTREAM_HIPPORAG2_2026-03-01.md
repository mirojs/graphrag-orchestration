# Route 7 vs Upstream HippoRAG 2: Comprehensive Deviation Analysis

**Date:** 2026-03-01  
**Upstream ref:** [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) @ commit `d437bfb`  
**Route 7 ref:** `src/worker/hybrid_v2/routes/route_7_hipporag2.py` (v7.4)  
**Paper:** HippoRAG 2 (ICML '25) — [arXiv:2502.14802](https://arxiv.org/abs/2502.14802)

---

## Executive Summary

Route 7 is a faithful but **partial** implementation of HippoRAG 2. The core PPR-with-passage-nodes architecture matches upstream, and 7 out of 11 tunable parameters are aligned. However, **12 meaningful deviations** exist, ranging from critical seeding logic differences that skew the entity:passage ratio, to architectural additions (cross-encoder reranker, sentence KNN edges, entity-doc map) that have no upstream equivalent. The most impactful deviations are in entity seed weighting (missing IDF and mean-normalization) and recognition memory prompt quality (simple regex vs DSPy-optimized few-shot). Several "Gap fixes" from the existing gap analysis have been partially applied but introduced regressions.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                      UPSTREAM HippoRAG 2                            │
│                                                                      │
│  Query ──► Embed(query_to_fact) ──► dot(ALL fact embeddings)        │
│            Embed(query_to_passage)    ▼                              │
│                │                  min_max_normalize                   │
│                │                      ▼                              │
│                │                  Top-K facts (linking_top_k=5)      │
│                │                      ▼                              │
│                │              DSPy Recognition Memory Filter          │
│                │                      ▼                              │
│                │              Surviving facts → Entity seeds          │
│                │              (fact_score / entity_doc_freq,          │
│                │               averaged per entity, top-5 only)      │
│                ▼                      ▼                              │
│        DPR: ALL passages ──► passage_weights (score × 0.05)         │
│                                       ▼                              │
│              node_weights = phrase_weights + passage_weights          │
│                                       ▼                              │
│                    igraph PPR (prpack, damping=0.5)                  │
│                                       ▼                              │
│                        Top-200 passages → QA (top 5)                │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                         ROUTE 7 (v7.4)                              │
│                                                                      │
│  Query ──► Embed(Voyage) ─┬──► cosine(triple embeddings, top 5)     │
│                           │         ▼                                │
│                           │   Simple LLM Recognition Memory          │
│                           │         ▼                                │
│                           │   Surviving triples → Entity seeds       │
│                           │   (raw fact_score accumulated,           │
│                           │    NO IDF, NO mean-norm, NO top-K cap)   │
│                           │                                          │
│                           ├──► DPR: ALL passages (Neo4j vector)      │
│                           │         ▼                                │
│                           │   passage_seeds (score × 0.05)           │
│                           │                                          │
│                           ├──► [Phase 2] Structural seeds            │
│                           ├──► [Phase 2] Community seeds             │
│                           └──► [Phase 2] Sentence search             │
│                                       ▼                              │
│              Python power-iteration PPR (damping=0.5)                │
│                                       ▼                              │
│              Top-100 PPR passages                                    │
│                        ▼                                             │
│              voyage-rerank-2.5 (top 30) ◄── NOT IN UPSTREAM         │
│                        ▼                                             │
│              30 chunks → Synthesis LLM                               │
│                        ▼                                             │
│              [Optional] Entity-doc map for exhaustive queries        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Parameters That Match Upstream

| Parameter | Upstream Default | Route 7 | Source |
|-----------|-----------------|---------|--------|
| `passage_node_weight` | 0.05 | 0.05 | config_utils.py:72, route_7:277 |
| `damping` | 0.5 | 0.5 | config_utils.py:163, route_7:276 |
| `linking_top_k` / `triple_top_k` | 5 | 5 | config_utils.py:157, route_7:271 |
| `synonymy_edge_sim_threshold` | 0.8 | 0.8 | config_utils.py:124, hipporag2_ppr.py:129 |
| `is_directed_graph` | False | False (undirected) | config_utils.py:131, hipporag2_ppr.py:17-18 |
| RELATED_TO edge weight | `node_to_node_stats` (co-occurrence) | `coalesce(r.weight, 1.0)` | HippoRAG.py:add_fact_edges, hipporag2_ppr.py:240 |
| SEMANTICALLY_SIMILAR edge weight | cosine similarity | `s.similarity` | HippoRAG.py:add_synonymy_edges, hipporag2_ppr.py:282 |

---

## Detailed Deviations

### Deviation 1: Entity Seed Weighting — Missing IDF & Mean-Normalization ⚠️ CRITICAL

**Upstream** (`HippoRAG.py:graph_search_with_fact_entities`, lines ~780-830):

```python
# For each surviving fact triple:
fact_score = query_fact_scores[top_k_fact_indices[rank]]  # min-max normalized

for phrase in [subject_phrase, object_phrase]:
    weighted_fact_score = fact_score
    if len(self.ent_node_to_chunk_ids.get(phrase_key, set())) > 0:
        weighted_fact_score /= len(self.ent_node_to_chunk_ids[phrase_key])  # IDF
    
    phrase_weights[phrase_id] += weighted_fact_score
    number_of_occurs[phrase_id] += 1

phrase_weights /= number_of_occurs  # Average across facts per entity
```

**Route 7** (`route_7_hipporag2.py:396-398`):

```python
for triple, fact_score in surviving_triples:
    entity_seeds[triple.subject_id] = entity_seeds.get(triple.subject_id, 0) + fact_score
    entity_seeds[triple.object_id] = entity_seeds.get(triple.object_id, 0) + fact_score
```

**What's missing:**
1. **IDF weighting** — Upstream divides fact_score by the number of chunks the entity appears in (`ent_node_to_chunk_ids`). Entities in many documents get lower per-fact weight. Route 7 has no such weighting.
2. **Mean-normalization** — Upstream averages across all facts for the same entity (`phrase_weights /= number_of_occurs`). Route 7 sums them.
3. **Fact score normalization** — Upstream min-max normalizes all fact scores to [0,1] before use. Route 7 uses raw cosine similarity scores.

**Impact:** Without IDF, common entities (appearing in many documents) get disproportionately high seed weight, while rare but informative entities are underweighted. Without mean-normalization, entities that appear in multiple facts get cumulative advantage. This likely contributes to the entity-space dominance observed in PPR walks.

---

### Deviation 2: Entity Seed Top-K Filtering — Absent ⚠️ MEDIUM

**Upstream** (`HippoRAG.py`, after phrase_weights computed):

```python
if link_top_k:
    phrase_weights, linking_score_map = self.get_top_k_weights(
        link_top_k, phrase_weights, linking_score_map
    )
```

`get_top_k_weights` zeros out all entity weights **except the top-5** (by `linking_top_k`). Only 5 entities maximum seed PPR.

**Route 7:** All entities from all surviving triples become seeds. With 5 triples × 2 entities each, up to **10 unique entities** can seed PPR (minus overlap). No top-K filtering step.

**Impact:** Route 7 seeds more entities than upstream, which disperses PPR probability mass across more entity nodes. This could help for broad queries (more coverage) but hurt for focused queries (less concentration on the most relevant entities).

---

### Deviation 3: Passage Seeding — DPR Score Source ⚠️ MEDIUM

**Upstream** (`HippoRAG.py:dense_passage_retrieval`):

```python
query_doc_scores = np.dot(self.passage_embeddings, query_embedding.T)
query_doc_scores = min_max_normalize(query_doc_scores)
```

ALL passages scored via dot product, then **min-max normalized to [0,1]**. This spreads scores across the full range, giving even low-scoring passages a non-trivial weight relative to the highest-scoring passage.

**Route 7** (`route_7_hipporag2.py:_dpr_passage_search`):

Uses Neo4j `sentence_embeddings_v2` vector index cosine similarity scores directly. These are **raw cosine scores** (typically 0.1-0.9 range), NOT min-max normalized.

**Impact:** Raw cosine scores may cluster in a narrow band (e.g., 0.3-0.7 for many passages), resulting in less differentiation between passages. Min-max normalization spreads the range to [0,1], giving the top passage exactly 1.0 and the bottom passage exactly 0.0. This affects the relative contribution of passage seeds vs entity seeds in the PPR personalization vector.

---

### Deviation 4: Retrieval Top-K — 100 vs 200 ⚠️ LOW

**Upstream:** `retrieval_top_k = 200` — Top 200 passages from PPR go to QA.  
**Route 7:** `ppr_passage_top_k = 100` (was 20, recently increased).

After reranking, Route 7 sends up to 30 chunks to synthesis. Upstream sends `qa_top_k = 5` passages to QA. So while upstream *retrieves* more, it *reads* fewer — the 200 is a recall pool, not a synthesis input.

---

### Deviation 5: Recognition Memory (Reranker) Implementation ⚠️ SIGNIFICANT

**Upstream** (`rerank.py:DSPyFilter`):

- **Framework:** DSPy with optimized few-shot prompts loaded from JSON
- **Prompt:** System prompt + few-shot demos (question/fact_before_filter → fact_after_filter)
- **Input format:** JSON `{"fact": [[s, p, o], [s, p, o], ...]}`
- **Output format:** Structured `Fact` pydantic model with `fact_after_filter` field
- **Parsing:** Regex section extraction + JSON/ast.literal_eval + pydantic validation
- **Matching:** `difflib.get_close_matches()` to map generated facts back to candidates
- **Robustness:** Multiple fallback parsing strategies, fuzzy matching

**Route 7** (`triple_store.py:recognition_memory_filter`):

- **Framework:** Simple single-turn LLM call
- **Prompt:** Zero-shot, numbered list of triples, ask for comma-separated numbers
- **Input format:** `"1. subject predicate object\n2. ..."`
- **Output format:** Plain text `"1, 3, 5"` or `"NONE"`
- **Parsing:** `re.findall(r"\d+", text)` → integer list
- **Matching:** Direct index lookup
- **Robustness:** On failure, passes through all candidates (conservative fallback)

**Impact:** The DSPy-optimized prompt was trained/fine-tuned for this task and likely has higher precision at identifying relevant facts. Route 7's zero-shot approach may produce more false positives/negatives. However, Route 7's approach is simpler, faster (one LLM call vs. structured prompt chain), and has a safer fallback.

---

### Deviation 6: Post-PPR Cross-Encoder Reranking — Route 7 ADDITION ⚠️ SIGNIFICANT

**Upstream:** No post-PPR reranking. Top-K PPR passages go directly to QA reader.

**Route 7** (`route_7_hipporag2.py:500-525`):

```python
if rerank_enabled and passage_scores:
    reranked_ids = await self._rerank_passages(
        query, candidate_ids, top_k=rerank_top_k,
    )
```

Uses **voyage-rerank-2.5** cross-encoder to rerank PPR's top passages before synthesis. This is a major architectural addition that:
- Can identify conceptual matches that cosine similarity misses (e.g., "time windows" → "3 business days")
- Changes passage ordering from graph-based (PPR) to semantic (cross-encoder)
- Adds ~300-500ms latency

**Impact:** This significantly improves synthesis quality (56/57 with reranker vs 55/57 without) but it fundamentally changes the retrieval paradigm — PPR becomes a candidate selector, not the final ranker.

---

### Deviation 7: Sentence↔Sentence KNN Edges — Route 7 ADDITION ⚠️ MEDIUM

**Upstream:** Only three edge types: Entity↔Entity (fact co-occurrence), Passage↔Entity (mentions), Entity↔Entity (synonym similarity).

**Route 7** (`hipporag2_ppr.py:286-310`):

```python
# 5b. Sentence-Sentence edges via SEMANTICALLY_SIMILAR
# Created by step 4.2 sentence KNN — enables cross-document
# PPR traversal between similar sentences.
```

Loads `Sentence -[:SEMANTICALLY_SIMILAR]-> Sentence` edges into the PPR graph. These create **direct cross-document passage bridges** that upstream doesn't have.

**Impact:** These edges allow PPR probability mass to flow directly between similar sentences across documents, bypassing the Entity↔Entity bridge path. This should improve cross-document retrieval but may also introduce noise from false-positive similarity edges.

---

### Deviation 8: PPR Implementation — Power Iteration vs PRPACK ⚠️ LOW

**Upstream** (`HippoRAG.py:run_ppr`):

```python
pagerank_scores = self.graph.personalized_pagerank(
    vertices=range(len(self.node_name_to_vertex_idx)),
    damping=damping, directed=False,
    weights='weight', reset=reset_prob,
    implementation='prpack'
)
```

Uses igraph's PRPACK C implementation — an exact, highly optimized solver.

**Route 7** (`hipporag2_ppr.py:run_ppr`):

Custom Python power iteration with:
- L1 convergence threshold: 1e-6
- Max iterations: 50
- Dict-based adjacency (no numpy/C acceleration)

**Impact:** For the small graphs in this codebase (~300-500 nodes), both produce equivalent results. Route 7's implementation converges in 15-30 iterations. For larger graphs (10K+ nodes), igraph PRPACK would be significantly faster. The L1 threshold of 1e-6 is sufficiently tight to match PRPACK's output.

---

### Deviation 9: Embedding Model — NV-Embed-v2 vs Voyage ⚠️ MEDIUM

**Upstream:** `nvidia/NV-Embed-v2` (default) with instruction-prefixed encoding:
- `query_to_fact` instruction for fact matching
- `query_to_passage` instruction for passage retrieval

**Route 7:** Voyage AI embeddings (`voyage-3-lite` or `voyage-code-3`) for both query and triple embedding. Single embedding model, no task-specific instruction prefixes.

**Impact:** Different embedding spaces produce different similarity scores and rankings. NV-Embed-v2 is a 7.2B parameter model with instruction-following capability; Voyage models are smaller but well-suited for code and document retrieval. The instruction-specific encoding in upstream means fact matching and passage retrieval use different query representations, potentially improving both tasks.

---

### Deviation 10: Triple Source — OpenIE vs RELATED_TO Edges ⚠️ MEDIUM

**Upstream:** Dedicated OpenIE extraction at index time via LLM. Facts stored in `fact_embedding_store` as `str((subject, predicate, object))` tuples.

**Route 7:** Triples derived from `RELATED_TO` edges with `r.description` as predicate:

```python
cypher = """
MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
WHERE r.description IS NOT NULL AND r.description <> ''
RETURN e1.id AS subj_id, e1.name AS subj_name,
       r.description AS predicate, ...
"""
```

Triple text format: `"{subject_name} {predicate} {object_name}"` (Route 7) vs `str((s, p, o))` tuple representation (upstream).

**Impact:** The quality of triples depends on the extraction pipeline. Upstream's dedicated OpenIE may produce cleaner, more structured triples. Route 7's RELATED_TO descriptions come from the general entity extraction pipeline and may be noisier or more verbose.

---

### Deviation 11: Entity↔Entity Edge Semantics ⚠️ LOW

**Upstream:** Entity↔Entity edges via `add_fact_edges()` have weight = **co-occurrence count** (incremented by 1.0 for each fact/triple they share). Entities mentioned together in many facts get heavier edges.

**Route 7:** Entity↔Entity edges loaded from Neo4j `RELATED_TO` relationship with weight from `r.weight` property (default 1.0). The weight semantics depend on the indexing pipeline — typically 1.0 per relationship, not accumulating.

**Impact:** Upstream's co-occurrence counting creates heavier edges between frequently co-mentioned entities, while Route 7 treats each relationship equally. This affects PPR's random walk probabilities — heavily weighted edges attract more probability mass in upstream.

---

### Deviation 12: QA/Synthesis Input Size ⚠️ MEDIUM

**Upstream:** `qa_top_k = 5` — only 5 passages sent to the QA reader.  
**Route 7:** Up to 30 chunks sent to synthesis LLM (after reranking from top 100 PPR).

**Impact:** More chunks provide more context but risk diluting the signal. Route 7's synthesis LLM must handle 6× more text, which may cause it to miss specific facts in a sea of context. This is the likely cause of the Q-D3/Q-D10 regressions observed when PPR_TOP_K was increased to 100.

---

## Route 7-Only Features (No Upstream Equivalent)

| Feature | File/Lines | Purpose |
|---------|------------|---------|
| Cross-encoder reranking (voyage-rerank-2.5) | route_7:500-525 | Refines PPR ranking for synthesis |
| Sentence↔Sentence KNN edges | hipporag2_ppr.py:286-310 | Cross-document passage bridges |
| Entity-doc map (exhaustive enumeration) | route_7:545-630 | "List all entities" query support |
| Query mode presets | route_7:170-186 | Router-adaptive parameters |
| Structural seeds (section matching) | route_7:1225-1301 | Phase 2: section-based seeding |
| Community seeds | route_7:1307-1365 | Phase 2: community-based seeding |
| Sentence vector search (parallel) | route_7:1371-1468 | Phase 2: evidence augmentation |
| Section graph in PPR | hipporag2_ppr.py:315-383 | Phase 2: Section node traversal |
| Adjacent chunk merging | route_7:1158-1191 | Synthesis context consolidation |
| Negative detection fallback | route_7:446-448, 795-806 | Empty result when no seeds |
| DPR-only PPR fallback | route_7:461-464 | Bug 3: PPR produces no passages |
| Passage-only PPR | route_7:449-451 | Bug 13: no entity seeds |

---

## Summary Comparison Table

| Aspect | Upstream HippoRAG 2 | Route 7 | Match? |
|--------|---------------------|---------|--------|
| **Graph type** | Entity + Passage nodes, undirected | Entity + Passage + [Section] + [Sentence-Sentence KNN] | ⚠️ Extended |
| **PPR damping** | 0.5 | 0.5 | ✅ |
| **Passage node weight** | 0.05 | 0.05 | ✅ |
| **Triple top-K** | 5 | 5 | ✅ |
| **Synonym threshold** | 0.8 | 0.8 | ✅ |
| **Passage seeding scope** | ALL passages | ALL passages (Gap 1 fix applied) | ✅ Recently fixed |
| **Passage score normalization** | min-max to [0,1] | Raw cosine similarity | ❌ |
| **Entity seed weighting** | fact_score / IDF, averaged | Raw fact_score, summed | ❌ |
| **Entity seed top-K filter** | Top 5 entities only | All entities from triples | ❌ |
| **Recognition memory** | DSPy few-shot optimized | Zero-shot numbered list | ❌ |
| **Post-PPR reranking** | None | voyage-rerank-2.5 | ❌ Addition |
| **Retrieval top-K** | 200 | 100 | ⚠️ Half |
| **QA input size** | 5 passages | 30 chunks | ❌ 6× more |
| **PPR solver** | igraph PRPACK (C, exact) | Python power iteration | ⚠️ Equivalent |
| **Embedding model** | NV-Embed-v2 (7.2B) | Voyage AI | ❌ |
| **Triple source** | Dedicated OpenIE at index | RELATED_TO edge descriptions | ❌ |
| **Edge weight semantics** | Co-occurrence count | Relationship weight (typically 1.0) | ⚠️ Different |

---

## Priority Recommendations

### P0: Fix Entity Seed Weighting (Deviation 1)

Add IDF weighting and mean-normalization to match upstream. This is the highest-impact change because it directly fixes the entity:passage seed ratio imbalance (95:5 → ~30:70).

```python
# In route_7_hipporag2.py, step 3:
number_of_occurs = defaultdict(int)
for triple, fact_score in surviving_triples:
    for entity_id in [triple.subject_id, triple.object_id]:
        # IDF: divide by entity's document frequency
        doc_freq = await self._get_entity_doc_freq(entity_id)
        weighted = fact_score / max(doc_freq, 1)
        entity_seeds[entity_id] = entity_seeds.get(entity_id, 0) + weighted
        number_of_occurs[entity_id] += 1

# Mean-normalize: average across facts per entity
for eid in entity_seeds:
    if number_of_occurs[eid] > 1:
        entity_seeds[eid] /= number_of_occurs[eid]
```

### P1: Add DPR Score Min-Max Normalization (Deviation 3)

Normalize DPR passage scores to [0,1] before multiplying by `passage_node_weight`:

```python
if dpr_results:
    scores = [s for _, s in dpr_results]
    s_min, s_max = min(scores), max(scores)
    spread = s_max - s_min if s_max > s_min else 1.0
    for chunk_id, score in dpr_results:
        normalized = (score - s_min) / spread
        passage_seeds[chunk_id] = normalized * passage_node_weight
```

### P2: Add Entity Seed Top-K Filter (Deviation 2)

Match upstream's behavior of only keeping top-5 entity seeds:

```python
if len(entity_seeds) > triple_top_k:
    top_entities = sorted(entity_seeds.items(), key=lambda x: x[1], reverse=True)[:triple_top_k]
    entity_seeds = dict(top_entities)
```

### P3: Improve Recognition Memory Prompt (Deviation 5)

Consider adopting DSPy-style few-shot prompting or at minimum adding 2-3 in-context examples to the recognition memory prompt.

---

## Confidence Assessment

| Finding | Confidence | Basis |
|---------|------------|-------|
| Parameters match (damping, weights, thresholds) | **High** | Direct code comparison, line-by-line |
| Entity seed weighting deviation | **High** | Clear code difference: no IDF, no mean-norm in Route 7 |
| Passage seeding scope (Gap 1) | **High** | Gap 1 fix is in uncommitted code, explicitly tracked |
| Recognition memory deviation | **High** | Completely different implementation paradigms |
| Post-PPR reranker as addition | **High** | No such step anywhere in upstream code |
| Sentence KNN edges as addition | **High** | No `Sentence-SEMANTICALLY_SIMILAR-Sentence` in upstream |
| DPR score normalization | **High** | Upstream uses explicit `min_max_normalize`; Route 7 uses raw cosine |
| Edge weight semantics | **Medium** | Upstream co-occurrence counting vs Route 7's `r.weight` — depends on indexing pipeline details |
| PPR equivalence | **Medium** | Both should converge to same result for small graphs, but no empirical verification |
| Impact of embedding model difference | **Medium** | Different models, but both are high-quality — actual impact depends on corpus |
