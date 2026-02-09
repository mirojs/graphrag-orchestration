# Design & Implementation Plan: GDS Louvain → LazyGraphRAG Community Summarization

**Date:** 2026-02-09  
**Status:** Design Complete → Ready for Implementation  
**Scope:** Indexing pipeline Step 8b + CommunityMatcher upgrade  
**Affects:** Route 3 (Global Search) primarily; Route 4 (DRIFT) secondarily  

---

## 1. Problem Statement

### 1.1 The Symptom

Route 3 (Global Search) suffers from poor theme coverage on thematic queries. From the Feb 8, 2026 benchmarks:

- **56.5% of all chunks** sent to the synthesis LLM are exact duplicates
- **Q-G5** ("dispute resolution terms"): All 5 models miss `default` — present only as a bare heading `4. Customer Default`
- **Q-G6** ("key parties involved"): All 5 models miss `pumper` — despite 26 occurrences, all are form labels (`Pumper's Name:`, `Pumper's Signature`)
- Average theme coverage across 10 questions: **69.8%** (should be ~95%+)

### 1.2 The Root Cause

Route 3's entry point (`CommunityMatcher`) uses an **ad-hoc, fragile 4-level fallback cascade** to generate entity clusters at query time:

```
1. Embedding similarity search on entity nodes (threshold > 0.35)
2. Keyword matching on entity names/descriptions
3. Multi-document sampling (top entities per document)
4. Degree-based fallback (highest-connected entities)
```

**Code:** `app/hybrid_v2/pipeline/community_matcher.py` → `_generate_communities_from_query()` (lines 230-540)

This cascade has three fundamental weaknesses:

**A. No topological awareness.** Ad-hoc clusters are formed by text similarity, not graph structure. Entities that co-occur densely in the same contract clauses (e.g., `Pumper`, `Holding Tank Owner`, `pumping equipment`) may not be textually similar to the query keywords, so they get missed.

**B. No semantic summaries.** The dynamic "community" is returned with a placeholder summary (`"Dynamically generated community for query: ..."`) — there is no meaningful semantic description that the LLM can reason about. The hub entities are selected purely by which entities the cascade found, not by understanding what the cluster represents.

**C. Non-deterministic.** The same query can produce different entity clusters depending on which fallback level triggers, which Neo4j query returns first, and how embedding similarity breaks ties. This violates the architecture's determinism principle.

### 1.3 Meanwhile, Two Powerful Tools Sit Unused

The codebase already has two GDS-powered capabilities that are **computed at index time but never consumed at query time**:

| Tool | Computed? | Used at Query Time? | Location |
|------|-----------|---------------------|----------|
| **GDS Louvain** | ✅ Yes — Step 8 writes `community_id` integer on every node | ❌ No — `CommunityMatcher` never reads `community_id` | `lazygraphrag_pipeline.py` L1800-1815 |
| **GDS KNN** | ✅ Yes — Step 8 creates `SEMANTICALLY_SIMILAR` edges | ⚠️ Partial — PPR Path 3 traverses them, but benefit is limited by downstream score discarding | `lazygraphrag_pipeline.py` L1755-1790 |

The Louvain `community_id` property is the critical wasted asset. It encodes **graph topology** — which entities form densely connected subgraphs — information that text embeddings alone cannot capture.

### 1.4 The Architectural Insight

**LazyGraphRAG communities** and **GDS Louvain clusters** serve different purposes that naturally compose:

| Concern | Best Tool | Why |
|---------|-----------|-----|
| **Which entities belong together?** (boundary definition) | GDS Louvain | Fast, deterministic, captures graph topology — entities that co-occur in same clauses form a cluster regardless of name similarity |
| **What does this cluster mean?** (semantic summary) | LazyGraphRAG LLM summarization | Generates human-readable descriptions that CommunityMatcher can do semantic search against |

**Neither tool alone solves the problem:**
- Louvain without summaries → communities exist but can't be matched to queries (no semantic bridge)
- Summaries without Louvain → summaries describe ad-hoc clusters that may not reflect real graph structure

**Together:** Louvain defines the subgraph boundaries → LazyGraphRAG summarizes each subgraph → CommunityMatcher semantically matches queries to these summaries.

---

## 2. Solution Design

### 2.1 Architecture Overview

```
INDEX TIME (Step 8 — already runs):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 8a: GDS KNN → SEMANTICALLY_SIMILAR edges          [EXISTING]
  Step 8b: GDS Louvain → node.community_id = integer      [EXISTING]
  Step 8c: GDS PageRank → node.pagerank = float            [EXISTING]

INDEX TIME (Step 9 — NEW):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 9a: Group entities by community_id                  [NEW]
  Step 9b: Create Community nodes + BELONGS_TO edges       [NEW — uses existing neo4j_store.upsert_community()]
  Step 9c: Generate LLM summary per community              [NEW — LLM call]
  Step 9d: Embed community summaries (Voyage)              [NEW — embedder call]
  Step 9e: Store embeddings on Community nodes              [NEW]


QUERY TIME (Route 3):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Stage 3.1: CommunityMatcher.match_communities()
    OLD: 4-level fallback cascade → synthetic community
    NEW: Load Community nodes from Neo4j → semantic match on summary embeddings
         → fallback to ad-hoc if no communities found (backward compatible)

  Stage 3.2+: Hub entity extraction, PPR, synthesis       [UNCHANGED]
```

### 2.2 Alignment with Framework Principles

| Principle | How This Design Aligns |
|-----------|----------------------|
| **LazyGraphRAG "lazy indexing"** | Louvain is seconds, not expensive. LLM summaries are per-community (~10-30 communities), not per-entity (~hundreds). Total added indexing time: ~30-60s. This is NOT the Microsoft GraphRAG heavy community pipeline. |
| **HippoRAG 2 PPR** | Unchanged. PPR still traverses the same 5 paths. Communities feed the entry point (hub entity selection), not the traversal algorithm. |
| **Determinism** | Louvain is deterministic. Summaries are generated once. Same query → same community match → same hub entities → same PPR. |
| **Backward compatibility** | If `Community` nodes don't exist (older index), CommunityMatcher falls back to the existing ad-hoc cascade. Zero breakage. |

### 2.3 Data Flow Detail

#### Step 9a: Group Entities by `community_id`

After Step 8 completes, query Neo4j for entities with `community_id`:

```cypher
MATCH (e:Entity {group_id: $group_id})
WHERE e.community_id IS NOT NULL
RETURN e.community_id AS community_id,
       collect({name: e.name, id: e.id, description: e.description,
                degree: coalesce(e.degree, 0),
                pagerank: coalesce(e.pagerank, 0.0)}) AS members
ORDER BY community_id
```

Expected output for a 5-document corpus: ~10-30 communities, each with 3-50 entity members.

**Small community handling:** Communities with <3 entities are merged into an "other" community or skipped (they don't carry enough semantic signal for a meaningful summary).

#### Step 9b: Create Community Nodes

For each community, call the existing `neo4j_store.upsert_community()`:

```python
from app.hybrid_v2.services.neo4j_store import Community

community = Community(
    id=f"louvain_{group_id}_{community_id}",
    level=0,  # Single-level Louvain (no hierarchy)
    title="",  # Will be set by LLM in Step 9c
    summary="",  # Will be set by LLM in Step 9c
    rank=avg_pagerank,  # Average PageRank of member entities
    entity_ids=[m["id"] for m in members],
)
neo4j_store.upsert_community(group_id, community)
```

This creates `:Community` nodes and `:BELONGS_TO` edges — **using the existing method** that's already tested.

#### Step 9c: Generate LLM Summary Per Community

For each community, build a prompt from its member entities and their relationships:

```python
# Fetch relationships between community members
MATCH (e1:Entity {group_id: $group_id})-[r]->(e2:Entity {group_id: $group_id})
WHERE e1.community_id = $community_id
  AND e2.community_id = $community_id
  AND NOT type(r) IN ['MENTIONS', 'SEMANTICALLY_SIMILAR', 'BELONGS_TO']
RETURN e1.name AS source, type(r) AS rel_type, e2.name AS target,
       coalesce(r.description, '') AS description
LIMIT 50
```

**LLM Prompt:**

```
You are analyzing a group of related entities from a knowledge graph of legal/business documents.

ENTITIES IN THIS CLUSTER:
{entity_list_with_descriptions}

RELATIONSHIPS BETWEEN THEM:
{relationship_list}

Based on these entities and their relationships, provide:
1. TITLE: A short descriptive title for this cluster (5-10 words)
2. SUMMARY: A 2-3 sentence summary describing what this group represents,
   what topics/themes it covers, and what types of questions it could help answer.

Format:
TITLE: <title>
SUMMARY: <summary>
```

**LLM model:** Use `self.llm` (the same LLM used for entity extraction in the pipeline — typically gpt-4o). This is a simple summarization task — no need for gpt-5.1.

**Parallelism:** Summarize communities in parallel (asyncio.gather) since they're independent. For 15 communities, this takes ~10-15s with gpt-4o.

**Concurrency guard:** All parallel LLM calls are bounded by `asyncio.Semaphore(5)` to avoid saturating the Azure OpenAI TPM quota with simultaneous requests. This prevents 429 rate-limit errors even when community count grows.

#### Step 9d-9e: Embed and Store Community Summaries

```python
# Embed all community summaries in one batch call
summary_texts = [f"{c.title}. {c.summary}" for c in communities]
embeddings = await self.embedder.aget_text_embedding_batch(summary_texts)

# Store embeddings on Community nodes
for community, embedding in zip(communities, embeddings):
    neo4j_store.update_community_embedding(group_id, community.id, embedding)
```

Requires a new method `update_community_embedding()` on `neo4j_store` (simple SET of embedding property).

### 2.4 CommunityMatcher Upgrade

The existing `CommunityMatcher` already has two modes:
1. **Pre-computed:** If `self._communities` is loaded, use `_semantic_match()` (cosine similarity)
2. **On-the-fly:** If no communities, use `_generate_communities_from_query()` (4-level cascade)

The upgrade adds a **third mode** as the primary path, inserted before the two existing modes:

```python
async def match_communities(self, query, top_k=3):
    # MODE 1 (NEW): Load from Neo4j Community nodes (Louvain-backed)
    if not self._loaded:
        await self._load_from_neo4j()  # NEW: loads Community nodes + embeddings

    # If Neo4j communities loaded, use semantic match
    if self._communities and len(self._communities) > 0:
        results = await self._semantic_match(query, top_k)  # EXISTING method
        if results:
            return results

    # MODE 2 (EXISTING): Load from JSON file (backward compat)
    if not self._loaded:
        await self.load_communities()  # EXISTING file-based loading
    ...

    # MODE 3 (EXISTING): On-the-fly generation (final fallback)
    dynamic_communities = await self._generate_communities_from_query(query, top_k)
    ...
```

The new `_load_from_neo4j()` method:

```python
async def _load_from_neo4j(self):
    """Load Louvain-backed communities from Neo4j Community nodes."""
    if not self.neo4j_service:
        return

    query = """
    MATCH (c:Community {group_id: $group_id})
    WHERE c.summary IS NOT NULL AND c.summary <> ''
    OPTIONAL MATCH (e:Entity {group_id: $group_id})-[:BELONGS_TO]->(c)
    RETURN c.id AS id, c.title AS title, c.summary AS summary,
           c.rank AS rank, c.embedding AS embedding,
           collect(DISTINCT e.name) AS entities
    ORDER BY c.rank DESC
    """
    async with self.neo4j_service._get_session() as session:
        result = await session.run(query, group_id=self.group_id)
        records = await result.data()

    if not records:
        return  # No communities — will fall through to existing modes

    self._communities = []
    self._community_embeddings = {}

    for r in records:
        community = {
            "id": r["id"],
            "title": r["title"],
            "summary": r["summary"],
            "entities": r["entities"],
        }
        self._communities.append(community)
        if r.get("embedding"):
            self._community_embeddings[r["id"]] = r["embedding"]

    self._loaded = True
    logger.info("communities_loaded_from_neo4j",
               num_communities=len(self._communities),
               has_embeddings=len(self._community_embeddings))
```

**Key:** This reuses the existing `_semantic_match()` method — it already computes cosine similarity between query embedding and community embeddings. Zero new matching logic needed.

---

## 3. Impact Analysis

### 3.1 Route 3 (Global Search) — Transformative

**Before:** CommunityMatcher generates a single ad-hoc cluster of ~10 entities via 4-level cascade. The "community" has a placeholder summary. Hub entities are selected from this fragile, non-deterministic cluster.

**After:** CommunityMatcher semantically matches the query against ~10-30 pre-computed community summaries. Returns top-3 communities, each with a stable membership and a meaningful description. Hub entities are drawn from topologically grounded clusters.

**Expected improvements on Feb 8 benchmark failures:**

| Question | Current Issue | How This Fixes It |
|----------|--------------|-------------------|
| Q-G6 ("key parties") | `pumper` missed — 26 form-label occurrences but no semantic bridge | Louvain clusters `Pumper`, `Holding Tank Owner`, `pumping equipment` into one community. LLM summary describes the pumper-owner relationship. CommunityMatcher matches "key parties" → this community. |
| Q-G5 ("dispute resolution") | `default` missed — bare heading only | Louvain clusters `Customer Default`, `Payment Terms`, `Legal Fees` together (same contract section). Summary mentions "default remedies." CommunityMatcher surfaces this cluster. |
| Q-G4 ("financial terms") | `expenses`/`income` missed by 2/5 models | Financial entities form a Louvain cluster. Summary describes income/expense accounting terms directly. |

### 3.2 Route 4 (DRIFT) — Moderate Benefit

Route 4's sub-question decomposition could use community summaries for smarter entity seeding (future enhancement). Not in this implementation scope.

### 3.3 Route 2 (Local Search) — No Direct Impact

Route 2 starts from NER-extracted entities, not communities. No change needed.

### 3.4 Indexing Time Impact

| Step | Time Estimate | Cost |
|------|---------------|------|
| Step 9a: Group entities by community_id | <1s (single Cypher query) | Zero |
| Step 9b: Create Community nodes | <1s (batch Cypher) | Zero |
| Step 9c: LLM summaries (~15 communities) | ~15-30s (parallel gpt-4o calls) | ~$0.02 (short prompts + short completions) |
| Step 9d-9e: Embed summaries | ~2s (one batch Voyage call) | ~$0.001 |
| **Total** | **~20-35s** | **~$0.02** |

This is negligible compared to the existing indexing pipeline (entity extraction: ~60-120s, chunk embedding: ~30s, GDS algorithms: ~15s).

---

## 4. Implementation Plan

### 4.1 Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `app/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Add Step 9: `_materialize_louvain_communities()` method + call it after Step 8 |
| 2 | `app/hybrid_v2/services/neo4j_store.py` | Add `update_community_embedding()` method |
| 3 | `app/hybrid_v2/pipeline/community_matcher.py` | Add `_load_from_neo4j()` method + update `match_communities()` flow |

### 4.2 Step-by-Step Implementation

#### Step 1: Add `update_community_embedding()` to Neo4j Store

**File:** `app/hybrid_v2/services/neo4j_store.py`  
**Location:** After existing `upsert_community()` method (~line 930)  
**Effort:** ~15 lines

```python
def update_community_embedding(self, group_id: str, community_id: str, embedding: List[float]) -> None:
    """Store embedding vector on a Community node for semantic matching."""
    query = """
    MATCH (c:Community {id: $community_id, group_id: $group_id})
    SET c.embedding = $embedding
    """
    with self.driver.session(database=self.database) as session:
        session.run(query, community_id=community_id, group_id=group_id, embedding=embedding)
```

Also add a method to update community title/summary after LLM generation:

```python
def update_community_summary(self, group_id: str, community_id: str, title: str, summary: str) -> None:
    """Update Community node with LLM-generated title and summary."""
    query = """
    MATCH (c:Community {id: $community_id, group_id: $group_id})
    SET c.title = $title, c.summary = $summary, c.updated_at = datetime()
    """
    with self.driver.session(database=self.database) as session:
        session.run(query, community_id=community_id, group_id=group_id, title=title, summary=summary)
```

#### Step 2: Add `_materialize_louvain_communities()` to Indexing Pipeline

**File:** `app/hybrid_v2/indexing/lazygraphrag_pipeline.py`  
**Location:** New method after `_run_gds_graph_algorithms()` (~line 1860)  
**Effort:** ~150 lines

This method performs Steps 9a-9e:

```python
async def _materialize_louvain_communities(
    self,
    *,
    group_id: str,
    min_community_size: int = 3,
) -> Dict[str, int]:
    """Materialize GDS Louvain clusters into Community nodes with LLM summaries.

    This bridges GDS Louvain (structural clustering) with LazyGraphRAG (semantic
    summarization):
    1. Read community_id assignments from Step 8 (already on Entity nodes)
    2. Create :Community nodes and :BELONGS_TO edges via neo4j_store
    3. Generate LLM summary for each community from its entity/relationship context
    4. Embed summaries and store on Community nodes for semantic matching

    Args:
        group_id: Tenant group identifier
        min_community_size: Skip communities with fewer than this many entities

    Returns:
        Stats dict with communities_created, summaries_generated, embeddings_stored
    """
    stats = {"communities_created": 0, "summaries_generated": 0, "embeddings_stored": 0}

    # Guard: skip if LLM or embedder unavailable (both are Optional in pipeline)
    if not self.llm or not self.embedder:
        logger.warning("Skipping community materialization: llm=%s, embedder=%s",
                       bool(self.llm), bool(self.embedder))
        return stats

    # 9a) Group entities by community_id
    # ... (Cypher query to group entities)

    # 9b) Create Community nodes + BELONGS_TO edges
    # ... (loop calling neo4j_store.upsert_community())

    # 9c) Generate LLM summaries (parallel)
    # ... (fetch relationships per community, build prompt, call LLM)

    # 9d-9e) Embed summaries and store
    # ... (batch embed, store on Community nodes)

    return stats
```

**LLM access pattern:** The pipeline already has `self.llm` (a LlamaIndex LLM instance). For community summarization, we'll use it via `self.llm.achat()` or build an Azure OpenAI client similar to the native extractor pattern at line 744.

**Detailed sub-steps within the method:**

**9a — Query community assignments:**
```python
community_query = """
MATCH (e:Entity {group_id: $group_id})
WHERE e.community_id IS NOT NULL
WITH e.community_id AS cid,
     collect({
         name: e.name,
         id: e.id,
         description: coalesce(e.description, ''),
         degree: coalesce(e.degree, 0),
         pagerank: coalesce(e.pagerank, 0.0)
     }) AS members
WHERE size(members) >= $min_size
RETURN cid, members
ORDER BY size(members) DESC
"""
```

**9b — Create Community nodes:**
```python
for cid, members in community_groups:
    avg_pagerank = sum(m["pagerank"] for m in members) / len(members)
    community = Community(
        id=f"louvain_{group_id}_{cid}",
        level=0,
        title="",  # Placeholder — LLM fills this in 9c
        summary="",
        rank=avg_pagerank,
        entity_ids=[m["id"] for m in members],
    )
    self.neo4j_store.upsert_community(group_id, community)
    stats["communities_created"] += 1
```

**9c — Generate LLM summaries (parallel):**
```python
async def _summarize_one_community(self, group_id, community_id, members, relationships):
    """Generate title + summary for one community via LLM."""
    # Build entity list
    entity_lines = []
    for m in sorted(members, key=lambda x: x["pagerank"], reverse=True):
        desc = f" — {m['description']}" if m["description"] else ""
        entity_lines.append(f"- {m['name']}{desc}")

    # Build relationship list
    rel_lines = []
    for r in relationships[:30]:
        desc = f" ({r['description']})" if r.get("description") else ""
        rel_lines.append(f"- {r['source']} → {r['rel_type']} → {r['target']}{desc}")

    prompt = f"""You are analyzing a group of related entities from a knowledge graph of legal/business documents.

ENTITIES IN THIS CLUSTER ({len(members)} entities):
{chr(10).join(entity_lines[:30])}

RELATIONSHIPS BETWEEN THEM ({len(relationships)} relationships):
{chr(10).join(rel_lines) if rel_lines else '(No explicit relationships extracted)'}

Based on these entities and their relationships, provide:
1. TITLE: A short descriptive title for this cluster (5-10 words)
2. SUMMARY: A 2-3 sentence summary describing what this group of entities represents, what topics or themes it covers, and what types of questions it could help answer. Be specific about the domain terms and party names.

Format your response exactly as:
TITLE: <title>
SUMMARY: <summary>"""

    # Call LLM
    response = await self._call_llm_for_summary(prompt)

    # Parse response
    title, summary = self._parse_community_summary(response)
    return title, summary
```

**9c parallel execution:**
```python
import asyncio

tasks = []
for cid, members in community_groups:
    # Fetch relationships for this community
    rels = self._get_intra_community_relationships(group_id, cid)
    tasks.append(self._summarize_one_community(group_id, cid, members, rels))

# Bounded parallelism — avoid saturating LLM TPM quota
sem = asyncio.Semaphore(5)
async def _guarded(coro):
    async with sem:
        return await coro

results = await asyncio.gather(*[_guarded(t) for t in tasks], return_exceptions=True)

for (cid, _), result in zip(community_groups, results):
    if isinstance(result, Exception):
        logger.warning(f"Community {cid} summarization failed: {result}")
        continue
    title, summary = result
    community_id = f"louvain_{group_id}_{cid}"
    self.neo4j_store.update_community_summary(group_id, community_id, title, summary)
    stats["summaries_generated"] += 1
```

**9d-9e — Embed and store:**
```python
# Collect all summaries for batch embedding
summary_texts = []
community_ids = []
for cid, members in community_groups:
    community_id = f"louvain_{group_id}_{cid}"
    # Re-read from Neo4j to get the LLM-generated summary
    # (or cache from step 9c results)
    summary_texts.append(f"{title}. {summary}")
    community_ids.append(community_id)

if summary_texts and self.embedder:
    embeddings = await self.embedder.aget_text_embedding_batch(summary_texts)
    for community_id, embedding in zip(community_ids, embeddings):
        self.neo4j_store.update_community_embedding(group_id, community_id, embedding)
        stats["embeddings_stored"] += 1
```

#### Step 3: Call Step 9 from `index_documents()`

**File:** `app/hybrid_v2/indexing/lazygraphrag_pipeline.py`  
**Location:** After the Step 8 try/except block (~line 370, before `stats["elapsed_s"]`)

```python
# 9) Materialize Louvain communities with LLM summaries (NEW)
# This bridges GDS Louvain clusters with LazyGraphRAG community summarization:
# Louvain defines structural boundaries → LLM generates semantic summaries →
# CommunityMatcher uses summaries for semantic query matching at query time.
try:
    if stats.get("gds_communities", 0) > 0:
        logger.info("📝 Materializing Louvain communities with LLM summaries...")
        community_stats = await self._materialize_louvain_communities(
            group_id=group_id,
            min_community_size=3,
        )
        stats["communities_materialized"] = community_stats.get("communities_created", 0)
        stats["community_summaries"] = community_stats.get("summaries_generated", 0)
        stats["community_embeddings"] = community_stats.get("embeddings_stored", 0)
        logger.info(
            f"✅ Communities: {stats['communities_materialized']} created, "
            f"{stats['community_summaries']} summarized, "
            f"{stats['community_embeddings']} embedded"
        )
    else:
        logger.info("⏭️  No Louvain communities detected — skipping community materialization")
        stats["communities_materialized"] = 0
        stats["community_summaries"] = 0
        stats["community_embeddings"] = 0
except Exception as e:
    logger.warning(f"⚠️  Community materialization failed: {e}")
    stats["communities_materialized"] = 0
    stats["community_summaries"] = 0
    stats["community_embeddings"] = 0
```

#### Step 4: Update CommunityMatcher to Load from Neo4j

**File:** `app/hybrid_v2/pipeline/community_matcher.py`  
**Changes:**
1. Add `_load_from_neo4j()` method (~40 lines)
2. Update `match_communities()` to try Neo4j loading first

The `load_communities()` method is modified to try Neo4j first, then file-based, preserving full backward compatibility:

```python
async def load_communities(self) -> bool:
    """Load community data and embeddings.

    Priority:
    1. Neo4j Community nodes (Louvain-backed, from Step 9)
    2. JSON file (legacy pre-computed communities)
    3. Return False → match_communities() will use on-the-fly generation
    """
    if self._loaded:
        return True

    # Try Neo4j first (Louvain-backed communities with LLM summaries)
    if await self._load_from_neo4j():
        return True

    # Fallback to JSON file (legacy path)
    if self.communities_path and self.communities_path.exists():
        try:
            with open(self.communities_path) as f:
                data = json.load(f)
            self._communities = data.get("communities", [])
            self._community_embeddings = data.get("embeddings", {})
            self._loaded = True
            logger.info("communities_loaded_from_file",
                       num_communities=len(self._communities))
            return True
        except Exception as e:
            logger.error("community_load_failed", error=str(e))
            return False

    logger.warning("no_community_data_found",
                  path=str(self.communities_path))
    return False
```

---

## 5. Neo4j Schema Changes

### 5.1 New Properties on `:Community` Nodes

| Property | Type | Source | Purpose |
|----------|------|--------|---------|
| `embedding` | `List[float]` (2048-dim Voyage) | Step 9d | Semantic matching in CommunityMatcher |
| `title` | `String` | Step 9c (LLM) | Short descriptive label |
| `summary` | `String` | Step 9c (LLM) | 2-3 sentence semantic description |
| `id` | `String` | Step 9b (`louvain_{group}_{cid}`) | Unique identifier |
| `level` | `Integer` (always 0) | Step 9b | Single-level Louvain |
| `rank` | `Float` | Step 9b (avg PageRank) | Community importance |
| `group_id` | `String` | Step 9b | Multi-tenancy |

### 5.2 New Edges

| Edge | Type | Source | Purpose |
|------|------|--------|---------|
| `(:Entity)-[:BELONGS_TO]->(:Community)` | Existing type | Step 9b (via `upsert_community()`) | Community membership |

### 5.3 New Vector Index (Optional, For Future Optimization)

```cypher
CREATE VECTOR INDEX community_embedding IF NOT EXISTS
FOR (c:Community) ON (c.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 2048, `vector.similarity_function`: 'cosine'}}
```

This enables `db.index.vector.queryNodes('community_embedding', ...)` for fast vector search. Not required for v1 (cosine similarity computed in Python for <30 communities), but useful as the corpus grows.

---

## 6. Error Handling & Graceful Degradation

| Failure Scenario | Behavior |
|------------------|----------|
| GDS Louvain produced 0 communities | Step 9 skipped entirely. CommunityMatcher uses existing ad-hoc cascade. |
| `self.llm` or `self.embedder` is None | Step 9 skipped with warning log. Communities not materialized. Query falls back to ad-hoc cascade. |
| LLM summarization fails for some communities | Those communities get empty summary. CommunityMatcher skips them (WHERE c.summary <> ''). |
| All LLM summaries fail | CommunityMatcher finds no Neo4j communities with summaries → falls through to ad-hoc cascade. |
| Embedder unavailable | Communities created without embeddings → CommunityMatcher falls back to keyword matching on summaries. |
| Neo4j Community nodes don't exist (old index) | `_load_from_neo4j()` returns empty → existing file/ad-hoc paths used. |
| Indexing interrupted after Step 8 but before Step 9 | `community_id` exists on nodes but no Community nodes. Next query uses ad-hoc cascade. Reindex fixes it. |

---

## 7. Testing Plan

### 7.1 Unit Tests

| Test | Validates |
|------|-----------|
| `test_materialize_communities_basic` | Step 9a-9b: entities with `community_id` → Community nodes + BELONGS_TO |
| `test_materialize_communities_min_size` | Communities with <3 members are skipped |
| `test_community_summary_prompt` | Prompt includes entities and relationships, response parsed correctly |
| `test_community_summary_parse` | Handles well-formed and malformed LLM responses |
| `test_community_embedding_stored` | Embedding vector stored on Community node |
| `test_community_matcher_neo4j_loading` | CommunityMatcher loads from Neo4j when communities exist |
| `test_community_matcher_fallback` | Falls back to ad-hoc when no Neo4j communities |
| `test_community_matcher_semantic_match` | Semantic match against community embeddings returns ranked results |

### 7.2 Integration Tests

| Test | Validates |
|------|-----------|
| `test_full_indexing_with_communities` | End-to-end: index 5 PDFs → verify Community nodes exist with summaries + embeddings |
| `test_route3_with_louvain_communities` | Route 3 query → CommunityMatcher loads from Neo4j → correct hub entities extracted |

### 7.3 Benchmark Regression

After implementation, rerun:
1. **Route 3 synthesis model comparison** (`benchmark_synthesis_model_comparison.py`) — verify theme coverage improves
2. **Route 3 global search benchmark** (`benchmark_route3_global_search.py`) — full 10-question positive + negative suite
3. **Cross-route regression** — Routes 2 and 4 should be unaffected (no code changes in their paths)

### 7.4 Key Metrics to Measure

| Metric | Current (Feb 8) | Target |
|--------|-----------------|--------|
| Route 3 avg theme coverage (10 questions) | 69.8% | >85% |
| Q-G5 theme coverage (5 models) | 63.3% | >80% |
| Q-G6 theme coverage (5 models) | 62.5% | >80% |
| Added indexing time | 0 | <60s |
| Number of Community nodes created | 0 | 10-30 |

---

## 8. Rollback Strategy

- **Environment variable:** `LOUVAIN_COMMUNITY_SUMMARIZATION=1` (default ON). Set to `0` to skip Step 9 entirely.
- **CommunityMatcher fallback:** If no Community nodes exist in Neo4j, the existing 4-level cascade runs unchanged.
- **Data cleanup:** `MATCH (c:Community {group_id: $gid}) DETACH DELETE c` removes all materialized communities for a group.
- **No changes to existing methods:** `upsert_community()`, `_semantic_match()`, `_keyword_match()` are unchanged. Only new methods are added; no existing behavior modified.

---

## 9. Future Enhancements (Out of Scope)

These are natural follow-ons but not part of this implementation:

1. **Hierarchical Louvain:** Use `includeIntermediateCommunities=True` for multi-level communities. Level 0 = fine-grained, Level 1 = coarse. Could improve Route 3 for both specific and broad queries.

2. **Community-aware PPR in Route 3:** After CommunityMatcher selects top-3 communities, bias PPR seeds toward entities in those communities. Currently hub entities are selected by degree; community membership would be a stronger signal.

3. **Community-aware token budget:** In `synthesize_with_graph_context()`, ensure chunks from different communities get fair representation before the token budget truncates.

4. **Route 4 sub-question community routing:** Each DRIFT sub-question matched to its most relevant community → more focused entity seeding per sub-question.

5. **Incremental community updates:** When new documents are added, mark communities as stale → re-run Louvain only on affected subgraph → regenerate summaries only for changed communities.

6. **Community vector index with auto-switch:** Create a Neo4j vector index on `(:Community).embedding` for fast $O(\log n)$ retrieval. **Scaling rule:** when `community_count > 500`, `_load_from_neo4j()` should switch from loading all communities into memory to issuing a `db.index.vector.queryNodes('community_embedding', $query_embedding, 10)` call. This keeps query-time latency constant regardless of corpus size.
