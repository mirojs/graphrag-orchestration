# Neo4j Parallelism & Batch Processing Analysis

**Date:** 2026-02-12  
**Scope:** `lazygraphrag_pipeline.py`, `neo4j_store.py`, `async_neo4j_service.py`  
**Goal:** Audit current parallelism patterns, identify sequential bottlenecks, recommend improvements.

---

## 1. Current Parallel Patterns (Already Optimised)

### 1.1 GDS Algorithm Execution (Server-Side Parallel)

All three GDS algorithms run with `concurrency=4`, meaning Neo4j executes them across 4 server threads internally.

| Algorithm | Location | Call |
|---|---|---|
| KNN | `lazygraphrag_pipeline.py` L2371 | `gds.knn.stream(G, concurrency=4)` |
| Louvain | `lazygraphrag_pipeline.py` L2425 | `gds.louvain.stream(G, concurrency=4)` |
| PageRank | `lazygraphrag_pipeline.py` L2444 | `gds.pageRank.stream(G, concurrency=4)` |

**Verdict:** ✅ Good. These are CPU-bound graph algorithms; `concurrency=4` is appropriate for AuraDB.

### 1.2 Entity Extraction (LLM-Parallel)

The `LLMEntityRelationExtractor` is configured with `max_concurrency=4` in two call sites:

- **Sentence-level extraction** (`_extract_with_native_extractor_sentences`, L1053):  
  `LLMEntityRelationExtractor(llm=native_llm, create_lexical_graph=True, max_concurrency=4)`

- **Chunk-level extraction** (`_extract_with_native_extractor`, L1404):  
  `LLMEntityRelationExtractor(llm=native_llm, create_lexical_graph=True, max_concurrency=4)`

Both use `BATCH_SIZE=6` (sentences or chunks grouped per LLM call), with 4 batches processed concurrently.

**Verdict:** ✅ Good. Bounded by LLM rate limits; 4 is a safe default.

### 1.3 Community Summarisation (Async Semaphore)

```python
# lazygraphrag_pipeline.py L2567-2576
sem = asyncio.Semaphore(5)   # Bound parallel LLM calls to avoid 429s

async def _summarize_one(cid, members):
    async with sem:
        return await self._summarize_community(group_id, cid, members)

tasks = [_summarize_one(cid, members) for cid, members in community_groups]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Verdict:** ✅ Good. Classic bounded fan-out. 5 concurrent LLM calls is reasonable.

### 1.4 Embedding Generation (Batch API)

All embedding calls use `aget_text_embedding_batch()`:

| Call Site | Line |
|---|---|
| Entity embeddings | L613, L1205, L1321, L1607 |
| Sentence embeddings | L707 |
| KVP embeddings | L2173 |
| Community summary embeddings | L2600 |
| Section embeddings | L3202 |

**Verdict:** ✅ Good. Single batched API call per group. The Voyage API handles internal parallelism.

### 1.5 Neo4j Bulk Writes via UNWIND

The `neo4j_store.py` service uses `UNWIND` for all major upsert operations:

| Operation | Method | Pattern |
|---|---|---|
| Entity upsert | `upsert_entities_batch()` / `aupsert_entities_batch()` | `UNWIND $entities AS e` |
| Relationship upsert | `upsert_relationships_batch()` | `UNWIND $relationships AS rel` |
| RAPTOR node upsert | `upsert_raptor_nodes_batch()` | `UNWIND $nodes AS n` |
| Extraction cache | `aput_extraction_cache_batch()` | `UNWIND $items AS item` |
| Section creation | `_build_section_graph()` | `UNWIND $sections AS s` |
| IN_SECTION edges | `_build_section_graph()` | `UNWIND $edges AS e` (batch_size=1000) |
| Subsection edges | `_build_section_graph()` | `UNWIND $edges AS e` |
| Barcode nodes | L1915 | `UNWIND $barcodes AS bc` |
| Figure nodes | L1951 | `UNWIND $figures AS fig` |
| KVP nodes | L2057 | `UNWIND $kvps AS kvp` |

**Verdict:** ✅ Good. `UNWIND` is Neo4j's recommended bulk-write pattern — single transaction, server-side iteration.

### 1.6 Cypher 25 Parallel Runtime

`async_neo4j_service.py` uses a `CYPHER 25` prefix (L50-79) for query execution:

```python
CYPHER_25_PREFIX: str = "CYPHER 25\n"
```

This enables Neo4j 5's parallel runtime optimizations for declarative patterns (MergeUniqueNode, MergeInto, allReduce, parallel path evaluation).

**Verdict:** ✅ Good. Free performance uplift for compatible queries.

---

## 2. Sequential Bottlenecks (Need Fix)

### 2.1 🔴 KNN Edge Materialisation — Row-by-Row Session.run()

**Location:** `lazygraphrag_pipeline.py` L2381-2417

```python
with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    edges_created = 0
    for _, row in knn_df.iterrows():
        node1_id = int(row["node1"])
        node2_id = int(row["node2"])
        similarity = float(row["similarity"])
        
        if knn_config:
            result = session.run("""
                MATCH (n1), (n2) 
                WHERE id(n1) = $node1 AND id(n2) = $node2
                  AND id(n1) < id(n2)
                MERGE (n1)-[r:SEMANTICALLY_SIMILAR {knn_config: $knn_config}]->(n2)
                SET r.score = $similarity, r.method = 'gds_knn', ...
                RETURN count(r) AS cnt
            """, ...)
        else:
            result = session.run("""...""", ...)
        rec = result.single()
        if rec and rec["cnt"] > 0:
            edges_created += rec["cnt"]
```

**Problem:**  
- N separate `session.run()` calls, one per KNN pair.  
- For 1000 entities with `topK=10`, this is **~5000 individual Cypher round-trips** (after dedup).  
- Each round-trip incurs network latency (especially on AuraDB, where latency is ~5-15ms per call).  
- Estimated overhead: **25-75 seconds** for 5K edges vs <1 second with UNWIND.

**Fix — Convert to UNWIND batch:**

```python
# Collect all edges into a list of dicts
edge_batch = []
for _, row in knn_df.iterrows():
    n1, n2 = int(row["node1"]), int(row["node2"])
    if n1 < n2:  # Pre-filter to avoid server-side id(n1) < id(n2) check
        edge_batch.append({
            "node1": n1,
            "node2": n2,
            "similarity": float(row["similarity"]),
        })

# Single UNWIND query
with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    if knn_config:
        result = session.run("""
            UNWIND $edges AS e
            MATCH (n1), (n2)
            WHERE id(n1) = e.node1 AND id(n2) = e.node2
            MERGE (n1)-[r:SEMANTICALLY_SIMILAR {knn_config: $knn_config}]->(n2)
            SET r.score = e.similarity, r.method = 'gds_knn', r.group_id = $group_id,
                r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff, r.created_at = datetime()
            RETURN count(r) AS cnt
        """, edges=edge_batch, knn_config=knn_config, group_id=group_id,
            knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
    else:
        result = session.run("""
            UNWIND $edges AS e
            MATCH (n1), (n2)
            WHERE id(n1) = e.node1 AND id(n2) = e.node2
            MERGE (n1)-[r:SEMANTICALLY_SIMILAR]->(n2)
            SET r.score = e.similarity, r.method = 'gds_knn', r.group_id = $group_id,
                r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff, r.created_at = datetime()
            RETURN count(r) AS cnt
        """, edges=edge_batch, group_id=group_id,
            knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
    edges_created = result.single()["cnt"]
```

**Expected improvement:** 1 round-trip instead of N. ~50-100x faster for typical workloads.

---

### 2.2 🔴 Louvain Community ID Write-Back — Row-by-Row Session.run()

**Location:** `lazygraphrag_pipeline.py` L2427-2439

```python
with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    community_ids = set()
    for _, row in louvain_df.iterrows():
        node_id = int(row["nodeId"])
        community_id = int(row["communityId"])
        session.run("""
            MATCH (n) WHERE id(n) = $nodeId
            SET n.community_id = $communityId
        """, nodeId=node_id, communityId=community_id)
        community_ids.add(community_id)
```

**Problem:**  
- One `session.run()` per node. For 1000 entities → 1000 round-trips.  
- Estimated overhead: **5-15 seconds** vs <200ms with UNWIND.

**Fix — Convert to UNWIND batch:**

```python
# Build update list
updates = []
community_ids = set()
for _, row in louvain_df.iterrows():
    node_id = int(row["nodeId"])
    community_id = int(row["communityId"])
    updates.append({"nodeId": node_id, "communityId": community_id})
    community_ids.add(community_id)

with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    session.run("""
        UNWIND $updates AS u
        MATCH (n) WHERE id(n) = u.nodeId
        SET n.community_id = u.communityId
    """, updates=updates)
```

**Expected improvement:** 1 round-trip instead of N. ~50x faster.

---

### 2.3 🔴 PageRank Score Write-Back — Row-by-Row Session.run()

**Location:** `lazygraphrag_pipeline.py` L2446-2458

```python
with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    nodes_scored = 0
    for _, row in pagerank_df.iterrows():
        node_id = int(row["nodeId"])
        score = float(row["score"])
        session.run("""
            MATCH (n) WHERE id(n) = $nodeId
            SET n.pagerank = $score
        """, nodeId=node_id, score=score)
        nodes_scored += 1
```

**Problem:** Identical to Louvain — one round-trip per node.

**Fix — Convert to UNWIND batch:**

```python
updates = [
    {"nodeId": int(row["nodeId"]), "score": float(row["score"])}
    for _, row in pagerank_df.iterrows()
]

with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
    session.run("""
        UNWIND $updates AS u
        MATCH (n) WHERE id(n) = u.nodeId
        SET n.pagerank = u.score
    """, updates=updates)
    nodes_scored = len(updates)
```

**Expected improvement:** 1 round-trip instead of N. ~50x faster.

---

## 3. Impact Summary

| Bottleneck | Current Round-Trips | After Fix | Estimated Speedup |
|---|---|---|---|
| KNN edge materialisation | ~5000 (for 1K entities, topK=10) | 1 | **~50-100x** |
| Louvain community write-back | ~1000 (per entity) | 1 | **~50x** |
| PageRank score write-back | ~1000 (per entity) | 1 | **~50x** |

**Combined effect on `run_gds_algorithms()`:**  
For a 1000-entity graph, the current sequential write-backs add an estimated **35-100 seconds** of pure network latency (at 5-15ms per round-trip on AuraDB). Converting all three to UNWIND batches reduces this to **<500ms** (3 round-trips total).

The GDS algorithm execution itself (KNN, Louvain, PageRank) is already properly parallelised with `concurrency=4` and is not the bottleneck — the bottleneck is entirely in the result write-back loop.

---

## 4. Implementation Priority

1. **KNN edge materialisation** — Highest impact (most rows, most complex per-row query)
2. **Louvain write-back** — Easy win, same pattern
3. **PageRank write-back** — Easy win, same pattern

All three changes are independent and can be implemented together. Total code change: ~60 lines replaced. Zero risk to read paths — these only affect indexing write-back.

---

## 5. Items Already Well-Optimised (No Action Needed)

| Pattern | Why It's Fine |
|---|---|
| `neo4j_store` batch upserts | Already use `UNWIND` throughout |
| GDS `concurrency=4` | Server-side, appropriate for AuraDB |
| Entity extraction `max_concurrency=4` | LLM rate-limit bounded |
| Community summarisation `Semaphore(5)` | LLM rate-limit bounded |
| Embedding `aget_text_embedding_batch()` | Batched API call |
| `async_neo4j_service.batch_execute()` | Single-transaction multi-query |
| Cypher 25 prefix | Passive optimisation, no tuning needed |
| IN_SECTION edge creation | Already uses `UNWIND` with `batch_size=1000` |
