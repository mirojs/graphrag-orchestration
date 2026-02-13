# Route 3 (Global Search) — Deep Diagnosis & Route 2-Inspired Architecture

**Date:** 2026-02-13  
**Context:** Route 3 v2 map-reduce benchmarks plateau at ~60% average theme coverage. Route 2 extraction prompt optimization achieved 100% accuracy (8/8, avg 30 chars). This analysis examines WHY Route 2 succeeded, WHY Route 3 is stuck, and how Route 2's architectural principles can be transplanted.

---

## 1. Current State — The Numbers

Route 3 v2 (map-reduce over community summaries) stabilized at **59.5% average theme coverage** (latest run: `20260213T120105Z`). The baseline (old single-shot architecture) scored **37.5%**, so v2 nearly doubled coverage, but still misses ~40% of expected themes.

### Per-Question Coverage (latest benchmark)

| Q | Theme | Coverage | Found | Missed | Missed Themes |
|---|-------|----------|-------|--------|---------------|
| T-1 | Common themes across contracts | **100%** | 5 | 0 | — |
| T-2 | Party relationships | **75%** | 3 | 1 | clients |
| T-3 | Financial terms & payment structures | **75%** | 3 | 1 | invoicing |
| T-4 | Risk management & liability | **75%** | 3 | 1 | indemnification |
| T-5 | Dispute resolution mechanisms | **60%** | 3 | 2 | mediation, litigation |
| T-6 | Confidentiality & data protection | **0%** | 0 | 4 | NDA provisions, data handling, privacy, disclosure limitations |
| T-7 | Key obligations & responsibilities | **100%** | 4 | 0 | — |
| T-8 | Termination & cancellation provisions | **50%** | 2 | 2 | notice periods, survival clauses |
| T-9 | Insurance & indemnification | **0%** | 0 | 4 | coverage types, minimum amounts, certificate requirements, named insureds |
| T-10 | Key dates & time-sensitive provisions | **60%** | 3 | 2 | expiration, response times |

**Two questions score 0%** (T-6, T-9). These aren't edge cases — they're fundamental clause-level themes that exist in the documents but are architecturally invisible to Route 3.

---

## 2. The Devastating Diagnosis

### 2.1 Community Matching Has ZERO Query Discrimination

**All 10 questions return the EXACT SAME 10 communities.** The community matcher returns the same top-10 out of 37 communities regardless of the query:

```
T-1 communities == T-6 communities == T-9 communities == ... (all identical)
```

The same 10 communities:
1. Home Appliances, Equipment, and Warranty Law Relationships (rank 0.59)
2. Common Material Defects in Building Construction (rank 0.38)
3. Home Construction Warranty Agreement Between Contoso and Fabrikam (rank 0.36)
4. Holding Tank Service Contracts and Regulatory Compliance (rank 0.35)
5. Arbitration, Remedies, and Claims in Idaho Legal Proceedings (rank 0.30)
6. Agreement Duration and Renewal Terms Cluster (rank 0.29)
7. Rental Unit Advertising Methods and Channels (rank 0.28)
8. Elevator Access Features and Hall Call Station Configuration (rank 0.28)
9. Arbitration and Dispute Resolution in Construction Contracts (rank 0.28)
10. Causes and Exclusions of Home Construction Defects (rank 0.27)

**Community scores for ALL queries: 0.0000.** The semantic matching either computes zero cosine similarity or falls through to a rank-ordered fallback — either way, the result is a static, query-independent community list.

### 2.2 The Right Communities EXIST but Never Get Selected

The corpus has 37 communities. Communities that would directly answer the 0%-coverage questions:

| Community (rank) | Would Answer | In Top 10? |
|-----------------|-------------|-----------|
| **Liability Insurance Coverage and Bodily Injury Minimum Limits** (0.24) | T-9 ✓ | ❌ No (rank 16) |
| **Insurance Documentation and Agent Coverage Requirements** (0.22) | T-9 ✓ | ❌ No (rank 27) |
| **Agreement Termination and Reservation Obligations** (0.21) | T-8 ✓ | ❌ No (rank 29) |

These communities contain exactly the content needed. For example, community "Liability Insurance Coverage" says:
> *"This cluster represents the relationship between liability insurance coverage and the statutory or policy-imposed minimum limits for bodily injury claims, specifically a $300,000 threshold. It covers topics such as insurance requirements, legal compliance, and risk management..."*

This would answer T-9 ("insurance and indemnification requirements") perfectly. But it sits at rank 16/37 and never enters the top-10 because community matching is ordered by **rank** (entity-degree-based), not by **query relevance**.

### 2.3 The Source Content EXISTS in Sentences

Direct keyword search against the 177 Sentence nodes confirms the content is in the graph:

| Theme | Sentences Found | Example |
|-------|----------------|---------|
| Confidentiality | **6** | "Each Party agrees to keep all Disputes and arbitration proceedings strictly confidential, except for disclosures..." |
| Insurance | **3** | "Provide Liability Insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000..." |
| Indemnification | **3** | "The Agent shall be named as additional insured and shall be furnished with a copy of the insurance policy..." |
| Mediation | **0** | (Not in documents — fair miss) |

For T-6 and T-9, the source text **physically exists** as Sentence nodes with vector embeddings — Route 2's skeleton enrichment would find them instantly.

---

## 3. Why Route 2 Succeeded — The Architectural Lesson

Route 2's extraction prompt optimization achieved **100% accuracy, avg 30 chars**. But the prompt was only the final 10% of the win. The real triumph was the **architecture**:

### Route 2's Data Flow (What Works)
```
Query → Voyage Embed → Sentence Vector Search (177 nodes)
                             ↓
                      Seed sentences (top-k by cosine sim)
                             ↓
                 RELATED_TO traversal (cross-chunk semantic links)
                             ↓
                    NEXT/PREV traversal (context window)
                             ↓
                       Coherent multi-sentence passages
                             ↓
                      LLM Extraction (v1_concise)
                             ↓
                        Direct answer
```

**Key properties:**
1. **Direct path from query to source text** — zero information-losing intermediate layers
2. **Sentence-level granularity** — 177 sentences with 2048-dim Voyage embeddings, vector-indexed
3. **Graph expansion for context** — RELATED_TO (semantic), NEXT/PREV (positional) → coherent passages
4. **Minimal LLM load** — the LLM receives precise evidence, not pre-distilled abstractions

### Route 3's Data Flow (What Fails)
```
Query → Community Embedding Match (broken: returns same 10 for all queries)
                             ↓
              10 community summaries (~420 chars each)
                             ↓
            MAP: Extract claims per community (10 LLM calls)
                             ↓
                    Claim list (~22 claims total)
                             ↓
            REDUCE: Synthesize claims into response (1 LLM call)
                             ↓
                    Thematic report (~4000 chars)
```

**Key failure points:**
1. **Information bottleneck** — 177 sentences × ~80 chars = ~14K chars of source content → compressed into 37 community summaries × ~430 chars = ~16K chars. But only 10 communities are selected → **4,300 chars of summary reach the LLM**, discarding 70% of indexed knowledge
2. **No direct path** — query never touches source text. Every fact must survive: source → entity extraction → Louvain clustering → LLM summary → MAP claim extraction → REDUCE synthesis. That's **5 lossy abstraction layers**
3. **Entity-cluster bias** — Louvain clusters entities by co-occurrence. Contractual clauses (confidentiality, insurance) aren't entity clusters — they're document structure. Community summaries naturally emphasize entity relationships, not clause provisions
4. **Static retrieval** — community selection is rank-ordered, not query-relevant. A question about insurance gets the same communities as a question about common themes

### The Principle

> **Route 2's architecture lets the LLM see the source material. Route 3's architecture makes the LLM look through 5 layers of pre-distilled abstractions.**

The fix is not more prompt tuning. The fix is architectural: **give Route 3 a direct path from query to source text**, exactly like Route 2.

---

## 4. The Route 2-Inspired Fix: Sentence-Enriched Global Search

### 4.1 Core Idea

Keep community structure for **thematic organization** (it's good at grouping related facts across documents). Add sentence-level retrieval for **evidence coverage** (it guarantees every theme in the source text has a retrieval path).

This is architecturally identical to Route 2's design:
- **Route 2:** Entity-graph retrieval (PPR) + Sentence enrichment (skeleton) → Extraction
- **Route 3 v3:** Community-graph retrieval (MAP) + Sentence enrichment (skeleton) → Global Synthesis

### 4.2 Route 3 v3 Architecture

```
                    ┌─────────────────────────────┐
                    │           QUERY              │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    Community Match (top-10)          Sentence Vector Search
    (thematic scaffold)               (evidence retrieval)
              │                                 │
              ▼                                 │
    MAP: claims per community                   │
    (entity-relationship themes)                │
              │                                 │
              ▼                                 ▼
    ┌──────────────────────────────────────────────┐
    │  REDUCE: synthesize claims + sentence       │
    │  evidence into global response              │
    │                                             │
    │  Community claims → thematic structure       │
    │  Sentence evidence → factual coverage        │
    └──────────────────────────────────────────────┘
              │
              ▼
        Global Response
```

### 4.3 Implementation: Three Steps

#### Step A: Fix Community Matching (~50 lines)

**Problem:** Semantic match returns 0.0 similarity for all communities. Same 10 returned regardless of query.

**Fix:** The `_semantic_match()` function in `community_matcher.py` (L225-L262) computes cosine similarity between query embedding and community embeddings. Debug: are community embeddings the right dimensionality? Is the similarity computation correct? If embeddings were generated with a different model than the query embedding model, dimensions may mismatch silently (cosine returns 0).

**Fallback fix:** If community embeddings are unfixable, replace semantic match with **MAP-first scoring**: call MAP on ALL 37 communities, rank by claim count, keep top-10. This guarantees query-relevant communities are selected. Cost: 37 LLM calls instead of 10 (but with gpt-4.1-mini at ~4K tokens each, this is ~$0.03 total).

**Expected impact:** T-9 gets "Liability Insurance Coverage" community → MAP extracts claims → +50-100% coverage for insurance themes.

#### Step B: Add Sentence Enrichment (Borrow Route 2's Skeleton Search) (~100 lines)

**The same infrastructure Route 2 uses is available for Route 3.** The graph already has:
- 177 Sentence nodes with `embedding_v2` (Voyage 2048-dim)
- `sentence_embeddings_v2` vector index
- 24 RELATED_TO edges (cross-chunk semantic links)  
- 334 NEXT edges (positional context)

**Implementation:** In `route_3_global.py`, after community matching (Step 1), add a parallel sentence retrieval step:

```python
# Step 1B: Sentence Enrichment (parallel with MAP)
# Reuse Route 2's skeleton search — same Cypher, same index
sentence_evidence = await self._retrieve_sentences(query, top_k=30)
```

The `_retrieve_sentences()` method is essentially Route 2's `_retrieve_skeleton_sentences()` (Strategy A) or `_retrieve_skeleton_graph_traversal()` (Strategy B). Can be extracted into a shared utility.

**Key design choice: scope vs. breadth.**
- Route 2 skeleton search is entity-scoped (find sentences related to specific entities)
- Route 3 needs **query-scoped** search (find sentences relevant to the thematic question)
- Query-scoped is actually simpler: just vector-search with the query embedding, no entity filtering

**Feed into REDUCE:**
```python
# Step 3: REDUCE with both sources
response = await self._reduce_claims_with_evidence(
    query, response_type, 
    community_claims=all_claims,          # from MAP
    sentence_evidence=sentence_evidence,   # from Step 1B
)
```

**Expected impact:** T-6 sentence search finds 6 confidentiality sentences → REDUCE synthesizes them → +100% coverage. T-9 finds 3 insurance sentences → +75-100% coverage.

#### Step C: Enhanced REDUCE Prompt (~30 lines)

**Current REDUCE prompt** sees only community claims. **New REDUCE prompt** sees both:

```
**Task**: Synthesize the following into a comprehensive {response_type}.

**Source 1: Community-Level Themes** (thematic structure)
{community_claims}

**Source 2: Direct Document Evidence** (sentence-level facts)
{sentence_evidence}

**Instructions**:
1. Use community themes for the response's organizational structure
2. Use sentence evidence to fill gaps and add specific details
3. If sentence evidence covers a theme NOT in community claims, include it as an additional section
4. Preserve specific details: entity names, amounts, dates, conditions
```

This mirrors Route 2's approach: graph-structural retrieval provides the scaffold, sentence evidence provides the content.

### 4.4 Expected Coverage After All Three Steps

| Question | Current | After Step A | After A+B | After A+B+C |
|----------|---------|-------------|-----------|-------------|
| T-1 Common themes | 100% | 100% | 100% | 100% |
| T-2 Party relationships | 75% | 75% | 100% | 100% |
| T-3 Financial terms | 75% | 75% | 100% | 100% |
| T-4 Risk management | 75% | 100% | 100% | 100% |
| T-5 Dispute resolution | 60% | 80% | 80% | 80% |
| T-6 Confidentiality | **0%** | 0% | **75–100%** | **100%** |
| T-7 Key obligations | 100% | 100% | 100% | 100% |
| T-8 Termination | 50% | **75%** | 75% | 75% |
| T-9 Insurance | **0%** | **75%** | **100%** | **100%** |
| T-10 Key dates | 60% | 60% | 80% | 80% |
| **Average** | **59.5%** | **~74%** | **~91%** | **~94%** |

Notes:
- T-5 mediation/litigation: 0 sentences in corpus mentioning these terms. Genuine content gap, not a retrieval failure.
- T-8 "survival clauses": depends on whether these terms appear literally in the documents.

---

## 5. Why This is Route 2's Pattern, Not Just "Add More Stuff"

The improvement isn't about bolting on more retrieval. It's about **the same architectural principle that made Route 2 perfect**: minimizing abstraction layers between the query and the source text.

| Property | Route 2 (100% accuracy) | Route 3 Current (59.5%) | Route 3 v3 (projected ~94%) |
|----------|------------------------|------------------------|---------------------------|
| Query → Source text path | **1 hop** (vector search) | **5 hops** (embed → match → MAP → claims → REDUCE) | **1 hop** (vector search) + community scaffold |
| LLM sees source text? | **Yes** — actual sentences | **No** — community summary claims | **Yes** — sentences + claims |
| Retrieval is query-relevant? | **Yes** — cosine similarity | **No** — static rank order | **Yes** — cosine similarity |
| Graph used for | Expansion (RELATED_TO, NEXT) | Clustering (Louvain) | Both — clustering for structure, expansion for coverage |
| Information loss layers | 1 (LLM extraction) | 5 (entity → cluster → summary → MAP → REDUCE) | 2 (community MAP + REDUCE with sentence evidence) |

The graph is most valuable when it's used for **expansion and connection** (find related evidence), not for **compression and abstraction** (summarize everything into community reports). Route 2 proved this. Route 3 can learn from it.

---

## 6. Implementation Priorities

| Priority | Change | Lines | Impact | Risk |
|----------|--------|-------|--------|------|
| **P0** | Fix community matching (debug 0.0 scores, enable query discrimination) | ~50 | +15% avg coverage | Low |
| **P1** | Add sentence vector search (reuse Route 2 skeleton Cypher) | ~100 | +20% avg coverage | Low — infrastructure already exists |
| **P2** | Enhanced REDUCE prompt (accept both claims + sentence evidence) | ~30 | +5% avg coverage | Low |
| **P3** | Remove negative detection for global search (T-6/T-9 hit false negatives) | ~10 | +5% for 0%-coverage questions | Low |
| Total | | ~190 lines | **59.5% → ~94%** | |

All four changes can be implemented and tested in a single session. The sentence vector search infrastructure is **already built and indexed** — Route 2 uses it every query. Route 3 just needs to call the same code.

---

## 7. Beyond Route 3: The Sentence-First Architecture

Route 2's success and Route 3's diagnosis point to a broader architectural principle for the entire system:

> **The sentence layer is the universal retrieval primitive.** Community summaries, entity graphs, and chunk hierarchies are organizational scaffolds — useful for structure and expansion, but not for primary retrieval. Every route should have a direct sentence-vector-search path from query to source text.

This means:
- **Route 2** (entity-focused): Already does this ✓ — skeleton enrichment provides sentence-level evidence
- **Route 3** (global thematic): Needs sentence enrichment alongside community MAP (this analysis)
- **Route 4** (multi-hop reasoning): Should add sentence retrieval at each beam search hop to prevent drift
- **Future routes**: Sentence vector search as default first retrieval, with route-specific graph expansion on top

The graph's value is in **RELATED_TO edges** (semantic cross-document links), **NEXT/PREV edges** (positional context), and **community structure** (thematic grouping) — not in replacing source text with summaries.

---

## 8. Benchmark Progression Reference

| Run | Timestamp | Avg Theme Coverage | Notes |
|-----|-----------|-------------------|-------|
| Baseline | Feb 12 07:34 | **37.5%** | Old single-shot architecture |
| V2 run 1 | Feb 12 10:43 | **10.5%** | Initial v2 — broken |
| V2 runs 2–6 | Feb 12 15:48–19:07 | **13–22%** | Iterative fixes, plateau at ~22% |
| V2 run 11 | Feb 12 19:55 | **66.0%** | Major breakthrough (code fix) |
| V2 latest | Feb 13 12:01 | **59.5%** | Stabilized |
| V3 target | — | **~94%** | With Steps A+B+C |

---

## 9. Graph Inventory (test-5pdfs-v2-fix2)

| Node Type | Count | Vector Index | Notes |
|-----------|-------|-------------|-------|
| Sentence | **177** | `sentence_embeddings_v2` (Voyage 2048-dim) | Route 2 already queries this |
| TextChunk | 18 | — | Coarse-grained, used by legacy paths |
| Community | 37 | Community embeddings (Voyage 2048-dim) | Matching broken (0.0 cosine) |
| Entity | ~90+ | Entity embeddings | Used by PPR/NER |
| Document | 5 | — | 5 PDFs |
| RELATED_TO | 24 | — | Cross-chunk semantic links (knn_sentence) |
| NEXT | 334 | — | Positional sentence ordering |

The entire Route 3 v3 improvement uses infrastructure that **already exists and is already indexed**. No re-indexing required.

---

## 10. Key Takeaway

Route 3's 60% ceiling is not a quality problem — it's an architecture problem. The pipeline interposes 5 lossy abstraction layers between the query and the source text, then tries to recover lost information through prompt engineering. Route 2 showed that the right architecture is **direct sentence retrieval + graph expansion for context**. Applying the same principle to Route 3 — keeping community MAP for thematic structure but adding sentence search for evidence coverage — should push coverage from 59.5% to ~94% with ~190 lines of code changes and zero re-indexing.
