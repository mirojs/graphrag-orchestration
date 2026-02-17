# Architecture Proposal: Route 5 — Unified HippoRAG Search

**Date:** 2026-02-16  
**Status:** Proposal  
**Origin:** Gemini discussion on HippoRAG 2 seed unification + Route 3/4 convergence analysis  
**Prerequisite reading:** HANDOVER_2026-02-15.md, ANALYSIS_ROUTE3_FURTHER_IMPROVEMENT_2026-02-13.md, ANALYSIS_ROUTE3_IMPROVEMENTS_BENEFIT_ROUTE4_2026-02-12.md

---

## 0. Executive Summary

Routes 3 and 4 have been converging architecturally: both now use sentence vector search as a parallel evidence path, both rely on the same graph infrastructure, and both suffer from the same seed quality problems. The Gemini discussion on HippoRAG 2 identifies a clean unification: **use community summaries + document headers as PPR seed sources** alongside entity NER, with seed weight distribution controlling whether the search behaves globally or locally.

Route 5 is **not a new pipeline** — it's the architectural merger of Route 3 and Route 4 into a single PPR-driven retrieval pass with configurable seed weighting. The router selects weights, not routes.

---

## 1. Why Route 3 and Route 4 Should Merge

### 1.1 The Convergence Already Happened

| Capability | Route 3 (v3.1) | Route 4 (DRIFT) | Shared? |
|---|---|---|---|
| Sentence vector search | ✅ Step 1B | ✅ Stage 4.S | Same infra |
| Voyage reranking | ✅ Step 2B | ✅ Stage 4.2 | Same code |
| Community data access | ✅ Step 1 (MAP) | ❌ Not used | Route 3 only |
| PPR graph traversal | ❌ Not used | ✅ Stage 4.3 | Route 4 only |
| NER entity extraction | ❌ Not used | ✅ Stage 4.2 | Route 4 only |
| Query decomposition | ❌ Not used | ✅ Stage 4.1 | Route 4 only |
| Confidence loop | ❌ Not used | ✅ Stage 4.3.5 | Route 4 only |
| Synthesis/REDUCE | ✅ Step 3 | ✅ Stage 4.4 | Same synth engine |

Route 3 does community MAP-REDUCE + sentence search.  
Route 4 does NER + PPR + sentence search.  
Neither uses the other's strengths. A unified route uses **all** of them.

### 1.2 The Problems Are Complementary

**Route 3's weakness** (diagnosed in ANALYSIS_ROUTE3_FURTHER_IMPROVEMENT_2026-02-13.md):
- Community matching returns the **same 10 communities for all queries** — zero query discrimination
- 5 lossy abstraction layers between query and source text
- 0% coverage on insurance (T-9) and confidentiality (T-6) because relevant communities rank 16th+ and never get selected
- No entity-level precision — can't answer "Who is the Agent?" type queries

**Route 4's weakness** (from handover/benchmark data):
- Seeds depend entirely on NER quality — **38% hallucination** rate on decomposed sub-questions  
- No thematic awareness — can't answer "What are the common themes?" without exhaustive section traversal
- No community structure awareness — PPR spreads activation blindly through entity graph
- Cross-group vector index bug caused 0 results for many entity lookups (now fixed via label archiving, but systemically fragile)

**The key insight:** Route 3 knows *what topics exist* but can't find specific evidence. Route 4 can find specific evidence but doesn't know *what topics to look for*.

### 1.3 The Seed Problem Is the Root of Both

From the Gemini discussion and handover_2026-02-15:

- Route 4's PPR seeds come from NER on decomposed sub-questions → **38% hallucinated entities**
- Route 3's "seeds" come from community rank ordering → **zero query relevance**
- Both routes independently add sentence search as a band-aid to compensate for poor seed quality

HippoRAG 2's insight: better seeds → better PPR → one retrieval pass handles both global and local queries.

---

## 2. Route 5 Architecture: Hierarchical Seed PPR

### 2.1 The Core Idea

Instead of choosing between community MAP (Route 3) or NER PPR (Route 4), Route 5 feeds **three tiers of seeds** into a single PPR pass. The weight distribution between tiers is the *only* knob that changes between "global" and "local" behavior.

```
                    ┌─────────────────────────────┐
                    │           QUERY              │
                    └──────────┬──────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   ┌──────────┐        ┌──────────────┐      ┌──────────────┐
   │ Tier 1   │        │   Tier 2     │      │   Tier 3     │
   │ Entity   │        │  Structural  │      │  Thematic    │
   │  Seeds   │        │   Seeds      │      │   Seeds      │
   │(NER→PPR) │        │(Header→PPR)  │      │(Community→   │
   │          │        │              │      │  PPR)        │
   │ w₁=0.5   │        │  w₂=0.3      │      │  w₃=0.2      │
   └────┬─────┘        └──────┬───────┘      └──────┬───────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  UNIFIED PPR      │    ← Single graph traversal
                    │  (weighted seeds) │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
      PPR-ranked         Sentence          Coverage
      entities          vector search     gap fill
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    ┌─────────────────┐
                    │   SYNTHESIS     │
                    │  (single LLM)  │
                    └─────────────────┘
```

### 2.2 The Three Seed Tiers

#### Tier 1: Entity Seeds (Drift/Facts) — w₁ default 0.5

**Source:** NER on original query (not decomposed sub-questions — decomposition hallucinates 38%).  
**Implementation:** Reuse `pipeline.disambiguator.disambiguate(query)` — already exists in Route 4.  
**Graph mapping:** Entity name → `:Entity` node (exact/fuzzy match).  
**PPR behavior:** High weight concentrates activation around specific entities → precise fact retrieval.

**Improvement over Route 4:** No decomposition hallucination. Original query NER is already done as the "NER union" step in Route 4 (Stage 4.2, line ~230 of route_4_drift.py). We just make it the *primary* seed source instead of a supplement.

#### Tier 2: Structural Seeds (Context Anchoring) — w₂ default 0.3

**Source:** Document section headers/titles — derived from sentence search results.  
**THIS IS THE NEW PIECE** from the Gemini discussion.

**Current state (from HANDOVER_2026-02-15):**
- `:Section` nodes exist with `title` field (12 in test group)
- `:Document` nodes exist with titles
- Every `:Sentence` node carries `section_path` metadata (e.g., `"Terms and Conditions > Manager Duties"`)
- **Section/Document nodes do NOT have `embedding_v2`** — confirmed "Document structure embeddings are missing"

##### Design Decision: Derived Seeds vs. Separate Title Embeddings

**We do NOT embed section titles separately.** This is a deliberate choice:

1. **Parse principle compliance:** ARCHITECTURE_HYBRID_SKELETON explicitly classifies section headings as *"Labels, not sentences — no semantic content alone → Store as Metadata Only."* Embedding short titles like "WARRANTY" or "INSURANCE" produces low-quality vectors — they lack enough semantic content for meaningful cosine similarity.

2. **Noise contamination risk:** A separate `section_title_embeddings_v2` vector index would mix title vectors with sentence vectors in query-time search, creating two competing vector spaces. The query "What are the warranty terms?" would get hits from both the title embedding ("WARRANTY") and the sentence embedding ("The warranty period shall be one year..."). These represent different granularities and would fight each other in PPR seed weighting.

3. **The metadata already exists:** Every Sentence node has `section_path` as a property. When sentence vector search returns the top-30 results, we already know *which sections* those sentences belong to.

**Instead: Derive structural seeds bottom-up from sentence search results.**

```python
async def derive_structural_seeds(
    sentence_evidence: List[Dict[str, Any]],
    min_sentences: int = 2,
) -> List[str]:
    """Extract section-level seeds from sentence search results.
    
    Instead of embedding section titles (noise-prone), we aggregate
    sentence search results by section_path. Sections that contribute
    multiple high-scoring sentences are strong structural anchors.
    
    This is the "bottom-up" approach: let sentence relevance determine
    section relevance, rather than matching query to title text.
    """
    section_scores: Dict[str, float] = defaultdict(float)
    section_counts: Dict[str, int] = defaultdict(int)
    
    for ev in sentence_evidence:
        sp = ev.get("section_path", "")
        if sp:
            section_scores[sp] += ev.get("score", 0)
            section_counts[sp] += 1
    
    # Sections with multiple matching sentences are structural anchors
    structural_seeds = [
        section for section, count in section_counts.items()
        if count >= min_sentences
    ]
    
    return structural_seeds
```

**How structural seeds enter PPR:** Section path strings are matched to `:Section` nodes via `title` property. Section nodes connect to entities via `IN_SECTION ← TextChunk → MENTIONS → Entity`. PPR activation flows: Section → chunks → entities.

**Why this is the "Goldilocks" level** (from Gemini discussion):
- Headers like "WARRANTY", "INSURANCE", "PAYMENT TERMS" emerge as structural seeds only when their child sentences score well — no false positives from title-only matching
- They map directly to the document skeleton hierarchy (Layer 1 in ARCHITECTURE_HYBRID_SKELETON)
- They provide "Content-Aware" context without a separate vector index
- Zero additional indexing cost — uses sentence search results that are already computed

**PPR behavior:** Seeds the graph at section/document-structure level. PPR activation flows from section headers through `IN_SECTION` edges to text chunks and then to entities. This gives the search "structural navigation" — it knows *where in the document* to look.

##### Edge Case: When Bottom-Up Fails

If query intent doesn't match any sentence well (very abstract queries like "What is this corpus about?"), zero sections emerge as structural anchors. In this case, Tier 3 (thematic/community seeds) carries the full structural load with w₃ automatically absorbing w₂'s weight share:

```python
# If no structural seeds found, redistribute weight to thematic tier
if not structural_seeds:
    effective_w2 = 0.0
    effective_w3 = w3 + w2  # Absorb structural weight
```

#### Tier 3: Thematic Seeds (Global Coverage) — w₃ default 0.2

**Source:** Community summaries matched to query.  
**Implementation:** Reuse `CommunityMatcher` — already exists in Route 3.

**Critical fix needed first:** Community matching currently returns the same 10 communities for all queries (0.0 similarity scores). This is the bug described in ANALYSIS_ROUTE3_FURTHER_IMPROVEMENT section 2.1. Community embeddings must be fixed or re-generated.

**PPR behavior:** Low weight provides broad activation across entity clusters. Prevents the search from being "trapped" in a single document when the query asks for cross-document themes.

**Graph mapping:** Community → `BELONGS_TO` → Entity nodes. These entities become additional PPR seeds with w₃ weight.

### 2.3 Seed Weight Profiles

The router doesn't choose a route — it chooses a **weight profile**:

| Query Type | w₁ (Entity) | w₂ (Structural) | w₃ (Thematic) | Example |
|---|---|---|---|---|
| Fact extraction | **0.6** | 0.3 | 0.1 | "Who is the Agent?" |
| Clause analysis | 0.3 | **0.5** | 0.2 | "What are the warranty terms?" |
| Cross-doc comparison | 0.2 | 0.3 | **0.5** | "Compare termination clauses across agreements" |
| Thematic survey | 0.1 | 0.2 | **0.7** | "What are the main themes across all documents?" |
| Multi-hop reasoning | **0.5** | 0.3 | 0.2 | "What inconsistencies exist between invoice and contract?" |

The router can be as simple as the existing keyword/embedding classifier — it just outputs 3 floats instead of a route name. Or it can be an LLM call that reasons about query intent.

### 2.4 The PPR Unification (from Gemini Discussion)

Once seeds are weighted, a single PPR pass handles everything:

```python
def build_unified_seeds(
    entity_seeds: List[str],       # From Tier 1 (NER)
    structural_seeds: List[str],   # From Tier 2 (Section titles)
    thematic_seeds: List[str],     # From Tier 3 (Community entities)
    w1: float = 0.5,
    w2: float = 0.3,
    w3: float = 0.2,
) -> Dict[str, float]:
    """Build weighted seed dictionary for PPR teleportation vector."""
    seeds: Dict[str, float] = {}
    
    # Normalize within each tier, then apply tier weight
    for entity in entity_seeds:
        seeds[entity] = seeds.get(entity, 0) + w1 / max(len(entity_seeds), 1)
    
    for header in structural_seeds:
        seeds[header] = seeds.get(header, 0) + w2 / max(len(structural_seeds), 1)
    
    for theme_entity in thematic_seeds:
        seeds[theme_entity] = seeds.get(theme_entity, 0) + w3 / max(len(thematic_seeds), 1)
    
    # Normalize to sum = 1.0 (valid probability distribution for PPR)
    total = sum(seeds.values())
    if total > 0:
        seeds = {k: v / total for k, v in seeds.items()}
    
    return seeds
```

This replaces:
- Route 3's community MAP step (10 parallel LLM calls × ~$0.003 each = ~$0.03)
- Route 4's decomposition + per-sub-question NER (1 decomposition LLM call + 3-5 NER calls)

With:
- 1 NER call + 1 section vector search + 1 community match → PPR → done

### 2.5 PPR Damping Factor as the Global/Drift Knob

From the Gemini discussion:
> *"A lower reset probability allows the search to 'drift' further into the graph for global discovery, while a higher reset probability keeps the reasoning focused and 'local' to the seeds."*

In our PPR implementation (`hipporag_retriever.py`), `damping_factor = 0.85` means 15% chance of teleporting back to seeds at each step.

- **Global queries (w₃ dominant):** Lower damping to 0.70-0.75 → more graph exploration, broader activation
- **Local queries (w₁ dominant):** Keep damping at 0.85-0.90 → tighter around seed entities

This can be set automatically based on the weight profile:

```python
# More thematic seeds → lower damping → broader exploration
damping = 0.70 + 0.20 * w1  # Range: 0.72 (global) to 0.90 (local)
```

---

## 3. Content-Aware Sentence Chunks as the Precision Layer

### 3.1 From the Gemini Discussion

> *"By adding content-aware sentence chunks, you provide the connective tissue that explains how entities relate to each other within a specific context."*

Our sentence infrastructure already does this (from ARCHITECTURE_HYBRID_SKELETON):
- 177 Sentence nodes with `embedding_v2` (Voyage 2048-dim)
- `sentence_embeddings_v2` vector index
- RELATED_TO edges (cross-chunk), NEXT edges (positional)
- spaCy sentence detection replaces DI regex (72% noise reduction)

### 3.2 "Breadcrumb" Enrichment (Already Partially Implemented)

The Gemini discussion suggests prepending each sentence with its structural context:

```
Raw:     "The company shifted operations to Hanoi."
Enriched: "[Title: 2024 Logistics][Header: SE Asia Expansion] The company shifted..."
```

Our system already has this metadata on Sentence nodes via `section_path`. The enrichment happens at synthesis time in `_build_cited_context()` (synthesis.py ~L1770).

**UPDATE 2026-02-17: Content-aware label prefix NOW IMPLEMENTED.** Both sentence and chunk embeddings are now computed with a `[Document: <title> | Section: <section_path>]` prefix prepended to the raw text before calling Voyage `contextualized_embed()`. The stored `.text` on Sentence/TextChunk nodes remains raw (clean for synthesis/citation). This is the Voyage/Anthropic "contextual retrieval" approach — explicit structural labels baked into the embedding vector. Requires re-indexing to take effect.

**Previous note (superseded):** ~~We should NOT re-embed sentences with breadcrumb context just for Tier 2 seeds.~~ The content-aware label prefix is now recognized as a foundational piece — the entire retrieval system (sentence search, structural seed derivation, PPR evidence quality) benefits from embeddings that are inherently document- and section-aware.

**Future consideration (Phase 1b only if needed):** If cross-document confusion persists (Q-D3/Q-D8 regressions), the label format can be tuned (e.g., adding page number or chunk index) and validated by ablation.

### 3.3 How Sentences Complement PPR Seeds

In Route 5, sentence search runs in parallel with PPR (same as Routes 3 and 4 already do):

```
Query → [Parallel]
         ├── Hierarchical Seed PPR (Tiers 1-3) → ranked entities → text chunks
         └── Sentence Vector Search           → ranked sentences → direct evidence
              → Denoise + Rerank
                         ↓
              Merged evidence set → Synthesis
```

The sentence path is the "insurance policy" — if PPR seeds miss something, sentence vector search (which is seed-independent) catches it. This is why both Route 3 and Route 4 independently added sentence search as a parallel path.

---

## 4. What Gets Eliminated

Route 5 removes several components that exist only because Routes 3 and 4 are separate:

| Removed Component | Current Route | Why Eliminated |
|---|---|---|
| MAP step (10 parallel LLM calls) | Route 3 Step 2 | PPR replaces claim extraction — entities from communities go directly to PPR seeds |
| Query decomposition (1 LLM call) | Route 4 Stage 4.1 | Source of 38% hallucinated NER. Original query NER is more reliable |
| Per-sub-question NER (3-5 calls) | Route 4 Stage 4.2 | Single NER on original query + structural seeds |
| Confidence loop re-decomposition | Route 4 Stage 4.3.5 | Better seeds → higher first-pass confidence → loop rarely triggers |
| Coverage gap fill | Route 4 Stage 4.3.6 | Thematic seeds (Tier 3) provide corpus-level coverage by default |
| Route selection decision | Router | Weight profile instead of binary route choice |
| Community rank-ordering fallback | Route 3 | Vector similarity to community embeddings (once fixed) |

**Net LLM calls eliminated:** 10-15 per query (MAP + decomposition + NER).  
**Net LLM calls in Route 5:** 1 (NER on original query) + 1 (synthesis) = 2.  
**Estimated latency reduction:** MAP step alone is ~2-4s. Decomposition + NER is ~2-3s. Route 5 saves 4-7s.

---

## 5. Implementation Plan

### Phase 0: Prerequisites (fix existing bugs)

1. **Fix community matching** — Community embeddings either missing or mismatched dimensionality. This is documented in HANDOVER_2026-02-12 Priority 2. Without this, Tier 3 seeds are useless.

2. **Re-run decomposition experiment** with fixed cross-group vector index (HANDOVER_2026-02-15 item 1). The Fs/Gs semantic resolution results are invalid.

3. **Production oversampling fix** — Fix cross-group vector index issue permanently (not just label archiving).

### Phase 1: Structural Seed Infrastructure (~1 day)

1. **Build `derive_structural_seeds()` function** — aggregates sentence search results by `section_path`, identifies sections with ≥2 matching sentences as structural anchors.

2. **Add Section node resolver** — maps `section_path` strings to `:Section` nodes, traverses `IN_SECTION ← TextChunk → MENTIONS → Entity` to find entities in those sections for PPR seeding:
   ```python
   async def resolve_section_entities(
       section_paths: List[str], group_id: str
   ) -> List[str]:
       """Find entities mentioned in chunks belonging to matched sections."""
       cypher = """
       UNWIND $paths AS path
       MATCH (s:Section {group_id: $group_id})
       WHERE s.title = path OR s.path_key CONTAINS path
       MATCH (chunk:TextChunk)-[:IN_SECTION]->(s)
       MATCH (chunk)<-[:MENTIONS]-(e:Entity {group_id: $group_id})
       RETURN DISTINCT e.name AS entity_name
       """
       # ... execute and return entity names
   ```

3. **No new vector indexes, no new embeddings, no re-indexing needed.** Structural seeds are derived entirely from existing sentence search results + existing graph relationships. This eliminates the indexing risk entirely.

4. **(Optional, Phase 1b):** If bottom-up derivation proves insufficient for very abstract queries, add a lightweight keyword match on Section.title as a fallback — not embedding, just `toLower(s.title) CONTAINS toLower(queryTerm)`. This matches the community matcher's keyword fallback pattern.

### Phase 2: Unified PPR with Weighted Seeds (~2 days)

1. **Build `unified_seed_resolver`** — orchestrates Tiers 1-3 in parallel, returns weighted seed dict.

2. **Modify PPR Cypher** in `async_neo4j_service.py` to accept weighted teleportation vector:
   ```cypher
   // Current: equal weight for all seeds
   WITH seed, 1.0 / $seedCount AS weight
   
   // Route 5: per-seed weight from unified resolver
   UNWIND $weightedSeeds AS ws
   MATCH (seed:Entity {name: ws.name, group_id: $group_id})
   WITH seed, ws.weight AS weight
   ```

3. **Add weight profile to router** — extend existing router to output `(w1, w2, w3)` instead of route name. Default profiles based on query classification.

4. **Dynamic damping** — adjust PPR damping factor based on weight profile.

### Phase 3: Route 5 Handler (~1 day)

1. **New handler class** `UnifiedSearchHandler(BaseRouteHandler)` in `route_5_unified.py`:
   - Parallel: NER + Section vector search + Community match + Sentence search
   - Unified PPR with weighted seeds
   - Single synthesis pass (reuse existing synth engine)

2. **Wire into orchestrator** — add `route_5_unified` as a new route option.

3. **Benchmark** against Route 3 + Route 4 separately on same question bank (T-1 through T-10 + Q-D1 through Q-D10).

### Phase 4: Deprecate Routes 3/4 (after benchmark validation)

Only after Route 5 matches or exceeds both routes' benchmark scores.

---

## 6. Risk Analysis

### 6.1 "Information Dilution" (from Gemini Discussion)

> *"If the community summaries are too vague, they can act as 'noise,' causing the PageRank to spread too thin."*

**Mitigation:** Tier 3 (thematic) has the lowest default weight (0.2). Community entities enter PPR with proportionally less initial mass. If community matching improves (Phase 0), the risk decreases further. Additionally, the damping factor adjustment means global queries intentionally spread more while local queries stay tight around Tier 1 entities.

### 6.2 Decomposition Loss

Route 4's decomposition does provide value for genuinely multi-hop queries ("Compare invoice vs contract"). Removing it may hurt complex reasoning.

**Mitigation:** Route 5 doesn't prevent decomposition — it just doesn't make it the default. For queries classified as multi-hop, the weight profile can include a "decomposition" flag that triggers sub-question generation as a preprocessing step. The difference is that decomposition feeds **additional** Tier 1 seeds rather than being the **only** seed source.

### 6.3 MAP Step Loss

Route 3's MAP step generates claim-level summaries per community. These are useful thematic scaffolding for the REDUCE synthesis.

**Mitigation:** The synthesis prompt can receive community summaries directly (without MAP extraction) as an optional context section. The community data is already loaded for Tier 3 seed generation — passing it to synthesis costs zero additional LLM calls. The trade-off: slightly less structured input to the REDUCE prompt vs. saving 10 LLM calls.

### 6.4 Structural Seed Derivation Quality

The bottom-up approach (derive sections from sentence hits) has a potential blind spot: if the query is too abstract for sentence search to return relevant hits, no structural seeds emerge. Mitigations:
1. **Weight redistribution:** When `structural_seeds` is empty, w₂ redistributes to w₃ (thematic tier)
2. **Keyword fallback:** Case-insensitive `Section.title CONTAINS queryTerm` as a cheap backup
3. **Minimum sentence threshold:** `min_sentences=2` prevents noise sections from single lucky hits
4. **Not a regression:** Current Routes 3/4 have zero structural awareness, so even partial derivation is a net gain

---

## 7. Expected Outcomes

| Metric | Route 3 (current) | Route 4 (current) | Route 5 (projected) |
|---|---|---|---|
| T-1 through T-10 avg | 66.0% (was 100% with v3.1) | N/A (not designed for thematic) | >85% (thematic seeds) |
| Q-D1 through Q-D10 avg | N/A | 0.81 containment | >0.85 (better seeds) |
| LLM calls per query | 12 (1 match + 10 MAP + 1 REDUCE) | 5-8 (1 decomp + 3-5 NER + 1 synth) | 2 (1 NER + 1 synth) |
| Latency (avg) | 8.2s | 33-54s | ~10-15s (no MAP, no decomp) |
| Cost per query | ~$0.04 (MAP heavy) | ~$0.06 (decomp + multi-NER) | ~$0.01 (2 LLM calls) |
| Negative test pass | 9/9 | 9/9 | 9/9 (same detection logic) |

---

## 8. Relationship to Existing Architecture

### What Route 5 Borrows

| From Route 2 | From Route 3 | From Route 4 | Novel (Route 5) |
|---|---|---|---|
| Skeleton enrichment | Community matching | PPR traversal | Weighted multi-tier seeds |
| Sentence vector search | Community summaries | NER disambiguation | Dynamic damping factor |
| Voyage reranking | Negative detection | Confidence metrics | Weight profiles from router |
| `_build_cited_context()` | REDUCE synthesis | Sentence merge (4.S) | Structural seed resolver |

### What Route 5 Replaces

| Component | Replaced By |
|---|---|
| Route 3 MAP step | Direct community→entity→PPR seed path |
| Route 4 decomposition | Original query NER (more reliable) |
| Route selection logic | Weight profile selection |
| Separate synthesis paths | Single unified synthesis |

### What Stays Unchanged

- Neo4j graph schema (Entity, Section, Document, Community, Sentence nodes)
- Voyage embedding infrastructure
- Reranking pipeline
- Synthesis engine (`synthesis.py`)
- Citation extraction
- Negative detection logic
- API contract (same request/response format)

---

## 9. Commentary on the Gemini Discussion

The Gemini conversation identifies several important principles that align with our measured data:

### 9.1 "Better Seeds" — Confirmed by Our Experiments

The HANDOVER_2026-02-15 reports that Phase 3 experiments (Teleportation, EPIC, adaptive weights) were **all invalidated** when tested with real NER instead of synthetic seeds. The cross-group vector index bug meant that `resolve_entities_semantic()` returned 0 results for many NER strings. The fundamental issue was seed quality, not PPR algorithm variants.

This directly validates Gemini's claim: *"A few High-Confidence seeds (Titles + Entities) outperform many Low-Confidence seeds."*

### 9.2 "Skip Paragraph Summaries" — Confirmed by Our Architecture

The Gemini discussion correctly notes that paragraph summaries are redundant when you have community summaries (global) + document headers (structural) + entity NER (precise). Our codebase confirms this:
- We experimented with containment-based dedup of sentence chunks vs. larger graph chunks (HANDOVER_2026-02-14). Removing paragraph-level overlap **improved** results because sentence chunks serve as "attention signals" — the LLM focuses on specifically-relevant sentences.
- Our content taxonomy (ARCHITECTURE_HYBRID_SKELETON) correctly lists section headings as "Store as Metadata Only." Route 5 respects this — section titles remain metadata, not independently embedded. Structural seeds are *derived* from sentence search results aggregated by `section_path`, not from title-level vector search. This keeps the metadata-only principle intact while still giving section structure query-time influence.

### 9.3 "Content-Aware Sentence Chunks" — Already Implemented

The Gemini discussion's "breadcrumb" enrichment pattern maps exactly to our `section_path` metadata on Sentence nodes. We already prepend structural context at synthesis time. The gap is that we don't use this context for **embedding** — which Route 5's Phase 1 step 4 addresses.

### 9.4 "Seed Weighting Formula" — New, Needs Validation

The `S_total = w₁(Entities) + w₂(Themes) + w₃(Titles)` formula from Gemini is the core of Route 5. The specific default weights (0.5/0.3/0.2) are initial guesses. These need ablation testing:
- Does w₃=0.7 actually improve thematic queries over w₃=0.2?
- At what w₁ threshold does fact-extraction performance degrade?
- Is the linear combination correct, or should we use multiplicative weighting?

### 9.5 Where Gemini Is Wrong: CatRAG Claim

Gemini mentions *"CatRAG (Context-Aware Traversal) — a 2026 improvement that builds on HippoRAG 2 to fix semantic drift in high-density graphs."* This appears to be a hallucination — there is no published work called CatRAG as of Feb 2026. The semantic drift problem is real (we measure it as Q-D3 regression: 0.85 → 0.67 when adding sentence search), but the solution is token budget management, not an external framework.

### 9.6 Where Gemini Oversimplifies: "Single Step Retrieval"

Gemini claims HippoRAG 2 *"achieves multi-hop in a single step."* Our experiments show this is only partially true. PPR does traverse the graph in one algorithmic pass, but seed quality determines whether that pass finds relevant evidence. With hallucinated seeds (38% rate from decomposition), a single PPR pass often misses critical paths. Route 5's multi-tier seeding addresses this by providing more entry points with less hallucination risk.

---

## 10. Decision Points for Discussion

1. **Should Route 5 fully replace Routes 3+4, or coexist as an option?**  
   Recommendation: Coexist initially. Route 5 runs alongside Routes 3/4 in benchmarks. Deprecate only after Route 5 matches or exceeds both on their respective question banks.

2. **Should decomposition be available as an opt-in for Route 5?**  
   Recommendation: Yes, as a weight profile flag. Multi-hop queries benefit from decomposition, but it should feed additional Tier 1 seeds rather than being the primary pipeline.

3. **Is the 0.5/0.3/0.2 default weight ratio correct?**  
   Recommendation: Unknown — needs ablation. Start with these defaults and run a 3×3 grid search across weight profiles on the combined question bank.

4. **Should community MAP extraction survive as an optional "deep mode"?**  
   Recommendation: No. If community-entity seeds via PPR provide sufficient thematic coverage, MAP adds cost without proportional value. Test this explicitly.

---

## Appendix A: File Impact Assessment

| File | Change Type | Description |
|---|---|---|
| `src/worker/hybrid_v2/routes/route_5_unified.py` | **NEW** | Route 5 handler |
| `src/worker/hybrid_v2/pipeline/seed_resolver.py` | **NEW** | Multi-tier seed resolver with weight profiles |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | **NO CHANGE** | Structural seeds derived at query time, no indexing changes |
| `src/worker/services/async_neo4j_service.py` | **MODIFY** | PPR Cypher to accept weighted teleportation vector |
| `src/worker/hybrid_v2/pipeline/community_matcher.py` | **MODIFY** | Fix 0.0 similarity bug (prerequisite) |
| `src/worker/hybrid_v2/orchestrator.py` | **MODIFY** | Add route_5 dispatch + weight profile routing |
| `scripts/benchmark_route5_unified.py` | **NEW** | Unified benchmark across thematic + factual questions |

---

## Appendix B: Relationship to ARCHITECTURE_HYBRID_SKELETON

The Skeleton architecture (2026-02-11) defines a three-layer model:
- Layer 1: Deterministic Skeleton (Document → Section → Paragraph → Sentence)
- Layer 2: Embeddings (Voyage 2048-dim vectors)
- Layer 3: Semantic (sparse RELATED_TO edges)

Route 5's Tier 2 (Structural Seeds) is the **query-time utilization** of Layer 1 — without modifying the index. Currently, Layer 1 exists in the graph but is only used for positional traversal (NEXT/PREV) and metadata labeling. Route 5 makes Layer 1 an active participant in retrieval by aggregating sentence search results by `section_path` to derive which sections are relevant, then feeding those sections' entities into PPR.

Critically, this respects the Skeleton architecture's content taxonomy: section titles remain **metadata only** (not independently embedded). The structural signal is derived bottom-up from sentence hit patterns, not top-down from title vector matching. This avoids creating a second vector embedding space that would compete with sentence embeddings and violate the principle that labels aren't semantic content.
