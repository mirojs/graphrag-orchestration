# Group ID & SID Isolation Audit

**Date:** 2026-02-12  
**Scope:** All Neo4j queries across `lazygraphrag_pipeline.py`, `neo4j_store.py`, `async_neo4j_service.py`, `text_store.py`, `hipporag_retriever.py`, `community_matcher.py`, `enhanced_graph_retriever.py`  
**Goal:** Verify strict multi-tenant isolation via `group_id` and session-scoped `sid` in every Cypher query.

---

## 1. Executive Summary

**Overall result: group_id isolation is well-maintained, with 7 specific violations found.**

The codebase consistently passes `group_id` through all major code paths (indexing, query routes, retrieval). Most Cypher queries properly filter on `{group_id: $group_id}` or `WHERE n.group_id = $group_id`. However, several queries match nodes by internal Neo4j `id()` or by deterministic `{id: $id}` without also requiring `group_id`, creating theoretical cross-tenant leakage vectors.

There is **no `sid` (session ID)** concept in the current architecture — all isolation is tenant-level via `group_id`. This is by design (single-session-per-group model).

---

## 2. Violations Found

### 2.1 🔴 CRITICAL: `get_entities_by_raptor_context()` — No group_id Filter

**File:** `neo4j_store.py` L1125-1152  
**Severity:** High (query-time, cross-tenant data leakage)

```python
query = """
MATCH (r:RaptorNode {id: $raptor_id})
MATCH (r)<-[:SUMMARIZES*1..]-(c:TextChunk)
MATCH (c)-[:MENTIONS]->(e:Entity)
RETURN DISTINCT e
LIMIT $limit
"""
```

**Problem:** Neither `RaptorNode`, `TextChunk`, nor `Entity` are filtered by `group_id`. If two tenants have RAPTOR nodes with colliding IDs (or share the same Neo4j database), this query returns entities from ANY tenant.

**Note:** The method signature accepts `group_id` but **never uses it** in the query.

**Fix:**
```python
query = """
MATCH (r:RaptorNode {id: $raptor_id, group_id: $group_id})
MATCH (r)<-[:SUMMARIZES*1..]-(c:TextChunk {group_id: $group_id})
MATCH (c)-[:MENTIONS]->(e:Entity {group_id: $group_id})
RETURN DISTINCT e
LIMIT $limit
"""
```

---

### 2.2 🔴 CRITICAL: `get_communities_by_raptor_context()` — Partial group_id Filter

**File:** `neo4j_store.py` L1153-1185  
**Severity:** High (query-time, cross-tenant data leakage)

```python
query = """
MATCH (r:RaptorNode)
WHERE r.id IN $raptor_ids
MATCH (r)<-[:SUMMARIZES*1..]-(c:TextChunk)
MATCH (c)-[:MENTIONS]->(e:Entity)
MATCH (e)-[:BELONGS_TO]->(comm:Community)
WHERE comm.group_id = $group_id AND comm.level = 0
...
"""
```

**Problem:** `RaptorNode`, `TextChunk`, and `Entity` nodes are NOT filtered by `group_id`. Only the final `Community` node has the filter. A cross-tenant `RaptorNode` with a matching ID could leak entities into the traversal path. The `group_id` filter on `Community` partially mitigates this but entities from another tenant could still appear in intermediate steps.

**Fix:** Add `{group_id: $group_id}` to `RaptorNode`, `TextChunk`, and `Entity` matches.

---

### 2.3 🟡 MEDIUM: GDS KNN Edge Materialisation — `id()` Match Without group_id

**File:** `lazygraphrag_pipeline.py` L2394-2415  
**Severity:** Low-Medium (indexing-time only, GDS projection is group-scoped)

```python
MATCH (n1), (n2) 
WHERE id(n1) = $node1 AND id(n2) = $node2
  AND id(n1) < id(n2)
MERGE (n1)-[r:SEMANTICALLY_SIMILAR]->(n2)
SET r.score = $similarity, r.method = 'gds_knn', r.group_id = $group_id, ...
```

**Problem:** The `MATCH` uses internal Neo4j `id()` without `group_id`. While the GDS projection upstream already filters by `group_id` (so the IDs should be valid), this relies on the projection being correct rather than defense-in-depth.

**Mitigating factor:** The edge itself does get `r.group_id = $group_id` set. The projection query at L2330-2340 correctly filters `WHERE n.group_id = "{escaped_group_id}"`.

**Risk:** Low in practice (GDS returns IDs from a group-scoped projection), but violates defense-in-depth principle.

---

### 2.4 🟡 MEDIUM: Louvain Community Write-Back — `id()` Match Without group_id

**File:** `lazygraphrag_pipeline.py` L2433-2436  
**Severity:** Low-Medium (indexing-time only)

```python
MATCH (n) WHERE id(n) = $nodeId
SET n.community_id = $communityId
```

**Problem:** Same pattern as 2.3 — writes to any node with matching internal Neo4j ID, regardless of group.

**Mitigating factor:** GDS projection is group-scoped, so returned IDs should be valid. But a race condition with concurrent indexing of another group could theoretically write to wrong nodes.

---

### 2.5 🟡 MEDIUM: PageRank Score Write-Back — `id()` Match Without group_id

**File:** `lazygraphrag_pipeline.py` L2452-2454  
**Severity:** Low-Medium (indexing-time only)

```python
MATCH (n) WHERE id(n) = $nodeId
SET n.pagerank = $score
```

**Problem:** Identical to 2.4.

---

### 2.6 🟡 MEDIUM: Figure Embedding Update — Match by `{id: $id}` Only

**File:** `lazygraphrag_pipeline.py` L2183-2188

```python
MATCH (f:Figure {id: $id})
SET f.embedding_v2 = $embedding
```

**Problem:** No `group_id` filter. If two tenants have a Figure node with the same deterministic ID, the wrong tenant's node could be updated.

**Mitigating factor:** Figure IDs are generated via `_stable_figure_id(group_id, ...)` which includes group_id in the hash, making collisions extremely unlikely.

---

### 2.7 🟡 MEDIUM: KVP Embedding Update — Match by `{id: $id}` Only

**File:** `lazygraphrag_pipeline.py` L2199-2204

```python
MATCH (k:KeyValuePair {id: $id})
SET k.embedding_v2 = $embedding
```

**Problem:** Same as 2.6 — no `group_id` filter on the MATCH.

**Mitigating factor:** KVP IDs are generated via `_stable_kvp_id(group_id, ...)` which includes group_id.

---

### 2.8 🟡 MEDIUM: Section Embedding Update — Match by `{id: u.id}` Only

**File:** `lazygraphrag_pipeline.py` L3215-3220

```python
UNWIND $updates AS u
MATCH (s:Section {id: u.id})
SET s.embedding = u.embedding
```

**Problem:** No `group_id` filter. Section IDs include group_id in the deterministic hash, but defense-in-depth is missing.

---

### 2.9 🟡 MEDIUM: KVP Key Embedding Update — Match by `{id: u.id}` Only

**File:** `lazygraphrag_pipeline.py` L3422-3426

```python
UNWIND $updates AS u
MATCH (kv:KeyValue {id: u.id})
SET kv.key_embedding = u.key_embedding
```

**Problem:** Same pattern — no `group_id` on update queries.

---

### 2.10 ℹ️ LOW: ExtractionCache — No group_id at All

**File:** `neo4j_store.py` L402-463

```python
MERGE (c:ExtractionCache {key: item.key})
...
```

**Problem:** ExtractionCache is a **global** cache shared across all tenants. The cache key typically includes the model, parameters hash, and input text — but not explicitly `group_id`.

**Impact:** This is actually **intentional** — the same extraction result for the same input text should be reusable across tenants (efficiency optimization). Not a data leakage risk since the cached data is the LLM's extraction output from the input text, not tenant-specific data.

**Verdict:** ✅ Acceptable — by design.

---

## 3. Well-Isolated Areas (No Issues Found)

### 3.1 async_neo4j_service.py — All Query-Time Methods ✅

Every async method properly filters by `group_id`:

| Method | Isolation Pattern |
|---|---|
| `get_entities_by_importance()` | `WHERE e.group_id = $group_id` |
| `get_entities_by_names()` | All 5 strategies filter `AND e.group_id = $group_id` |
| `get_entities_by_vector_similarity()` | Post-filter `WHERE node.group_id = $group_id` after vector index |
| `expand_neighbors()` | `seed.group_id = $group_id` AND `neighbor.group_id = $group_id` |
| `get_entity_relationships()` | Both `e.group_id` and `other.group_id` filtered |
| `personalized_pagerank_native()` | `seed.group_id = $group_id` AND all path nodes filtered |
| `semantic_multihop_beam()` | `neighbor.group_id = $group_id` per hop + vector post-filter |
| `get_community_peers()` | `seed.group_id` and `peer.group_id` filtered |
| `get_chunks_for_entities()` | Both entity and chunk filtered |
| `check_field_exists_in_document()` | `c.group_id = $group_id` |
| `check_field_pattern_in_document()` | `c.group_id = $group_id` |
| `check_pattern_in_docs_by_keyword()` | `c.group_id = $group_id` (both primary and fallback) |
| `detect_embedding_version()` | `WHERE e.group_id = $group_id` |
| `get_entity_document_coverage()` | Triple-filtered (entity, document, and alias match) |

### 3.2 neo4j_store.py — Entity/Relationship/Community CRUD ✅

All major CRUD operations use `{group_id: $group_id}` in MERGE or MATCH:

| Method | Filter |
|---|---|
| `upsert_entity()` | `MERGE (e:__Entity__ {id: $id, group_id: $group_id})` |
| `upsert_entities_batch()` | `MERGE (entity:__Entity__ {id: e.id, group_id: $group_id})` |
| `aupsert_entities_batch()` | `MERGE (entity:Entity {id: e.id, group_id: $group_id})` |
| `upsert_relationship()` | Both source and target `{id: $id, group_id: $group_id}` |
| `upsert_relationships_batch()` | Both source and target `{group_id: $group_id}` |
| `upsert_community()` | `MERGE (c:Community {id: $id, group_id: $group_id})` |
| `update_community_summary()` | `MATCH (c:Community {id: $id, group_id: $group_id})` |
| `update_community_embedding()` | `MATCH (c:Community {id: $id, group_id: $group_id})` |
| `get_communities_by_level()` | `MATCH (c:Community {group_id: $group_id, level: $level})` |
| `upsert_raptor_node()` | `MERGE (r:RaptorNode {id: $id, group_id: $group_id})` |
| `upsert_raptor_nodes_batch()` | `MERGE (r:RaptorNode {id: n.id, group_id: $group_id})` |
| `search_raptor_by_embedding()` | `MATCH (r:RaptorNode {group_id: $group_id})` |
| `upsert_text_chunks_batch()` | SET `t.group_id = $group_id` + MATCH Document with group_id |
| `upsert_sentences_batch()` | SET `sent.group_id = $group_id` + MATCH chunk/doc with group_id |
| `upsert_document()` | `MERGE (d:Document {id: $id, group_id: $group_id})` |
| `delete_group_data()` | All 8 node types filtered by `{group_id: $group_id}` before DELETE |

### 3.3 lazygraphrag_pipeline.py — Most Indexing Queries ✅

| Operation | Filter |
|---|---|
| Sentence KNN cleanup | `MATCH (:Sentence {group_id: $group_id})` |
| Sentence fetch for KNN | `MATCH (s:Sentence {group_id: $group_id})` |
| Barcode creation | `MERGE (b:Barcode {id: bc.id}) SET b.group_id = bc.group_id` + `MATCH (d:Document {id: ..., group_id: ...})` |
| Figure creation | Same pattern |
| KVP creation | Same pattern |
| Language update | `MATCH (d:Document {id: $doc_id, group_id: $group_id})` |
| GDS projection | `WHERE n.group_id = "{escaped_group_id}"` |
| Community grouping | `MATCH (e:Entity {group_id: $group_id})` |
| Community summarisation | `MATCH (e1:Entity {group_id: $group_id})...` |
| Section creation | `SET sec.group_id = s.group_id` |
| Section HAS_SECTION | `MATCH (d:Document {id: ..., group_id: $group_id})` |
| Section similarity edges | `MATCH (s1:Section {id: ..., group_id: $group_id})` on both sides |
| Foundation edges | All 3 queries filter entity, source, section, and document by `group_id` |
| Connectivity edges | All nodes filtered by `group_id` |

### 3.4 text_store.py ✅

All queries use `self._group_id` which is set at construction:

| Method | Filter |
|---|---|
| `get_target_doc_ids()` | Both entity and document filtered by `group_id` |
| `_keyword_search()` | `WHERE c.group_id = $group_id` + `MATCH (d:Document {group_id: $group_id})` |
| Entity search | `WHERE e.group_id = $group_id` |

### 3.5 Route Files ✅

| File | Isolation Method |
|---|---|
| `route_2_local.py` | `self.group_id` passed to all Neo4j queries, vector index post-filtered |
| `route_3_global.py` | Uses `self.pipeline.community_matcher` which holds group_id |
| `route_4_drift.py` | Delegates to `async_neo4j_service` methods which all filter by `group_id` |
| `community_matcher.py` | `self.group_id` used in all ~15 Cypher queries |
| `enhanced_graph_retriever.py` | `self.group_id` used in all entity/chunk queries |
| `hipporag_retriever.py` | `self.group_id` used everywhere, including vector post-filters |

---

## 4. Vector Index Post-Filtering Pattern

A notable pattern across the codebase: **Neo4j vector indexes are global** (not group-scoped), so all vector searches use a two-step pattern:

```python
CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k, $embedding)
YIELD node, score
WHERE node.group_id = $group_id  -- Post-filter
```

This is correct but has a subtle implication: the vector index returns `$top_k` results globally, then filters by group_id. If one tenant has many more entities than another, the smaller tenant may get fewer results. The code mitigates this with oversampling (`top_k_oversample = top_k * 3`).

**Verdict:** ✅ Acceptable pattern given Neo4j's vector index limitations. No data leakage.

---

## 5. SID (Session ID) Isolation

**Finding: There is no `sid` concept in the current architecture.**

All isolation is tenant-level via `group_id`. Within a group, all queries and sessions share the same graph data. There is no per-query or per-session scoping.

This is appropriate for the current deployment model (single user per tenant group). If multi-user support within a group is needed in the future, `sid` filtering on edges/nodes would need to be added.

---

## 6. Fix Priority

| # | Issue | Severity | Effort | Priority |
|---|---|---|---|---|
| 1 | `get_entities_by_raptor_context()` — no group_id | 🔴 High | 5 min | **P0** |
| 2 | `get_communities_by_raptor_context()` — partial group_id | 🔴 High | 5 min | **P0** |
| 3 | GDS KNN edge write-back — `id()` without group_id | 🟡 Medium | 10 min | P1 (combine with UNWIND batch fix) |
| 4 | Louvain write-back — `id()` without group_id | 🟡 Medium | 5 min | P1 (combine with UNWIND batch fix) |
| 5 | PageRank write-back — `id()` without group_id | 🟡 Medium | 5 min | P1 (combine with UNWIND batch fix) |
| 6-9 | Embedding updates — match by `{id: $id}` only | 🟡 Medium | 10 min | P2 (low collision risk due to group_id in hash) |

Items 3-5 should be combined with the UNWIND batch optimisation from `ANALYSIS_NEO4J_PARALLELISM_IMPROVEMENT_2026-02-12.md` — both fixes address the same code blocks.
