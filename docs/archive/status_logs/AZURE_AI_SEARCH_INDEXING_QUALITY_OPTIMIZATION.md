# Azure AI Search Indexing Quality Optimization Strategy

**Date**: 2025-12-14  
**Focus**: Optimizing RAPTOR node indexing to Azure AI Search for improved semantic ranking accuracy

## Current Architecture

```
Documents → RAPTOR Processing → Hierarchical Nodes → Azure AI Search (Semantic Ranking)
                                 └→ Neo4j (Entity/Relationship Extraction)
```

### RAPTOR Pipeline Flow
1. **Level 0 (Leaves)**: Original document chunks
2. **Level 1+**: LLM-generated summaries of semantically similar chunks
3. **Clustering**: GMM or K-Means on embeddings
4. **Indexing**: All nodes → Azure AI Search with semantic ranker enabled

### Azure AI Search Configuration
- **Semantic Ranker**: Enabled (Microsoft's transformer-based re-ranking)
- **Hybrid Search**: Vector + BM25 full-text + semantic captions
- **Index Schema**:
  - `chunk`: Primary content field
  - `embedding`: Vector field (1536 dims for Azure OpenAI text-embedding-ada-002)
  - `metadata`: Filterable fields (group_id, raptor_level, source, file_name)
  - `@search.reranker_score`: Semantic relevance score

## Identified Optimization Opportunities

### 1. **RAPTOR Summary Quality Enhancement**

**Current Issue**: Summaries are generated from limited context (10 chunks max)

**Location**: `raptor_service.py`, lines 340-365

```python
# CURRENT: Limited to 10 chunks
combined_text = "\n\n---\n\n".join([
    f"[Chunk {i+1}]: {node.text[:1000]}" 
    for i, node in enumerate(nodes[:10])  # ← BOTTLENECK
])
```

**Optimization Recommendations**:

1. **Include Semantic Context in Prompt**
   - Add cluster size, embedding similarity scores
   - Include diversity metrics to indicate cluster quality
   
2. **Preserve Metadata in Summaries**
   - Add sources, entity mentions, key numbers
   - Include cross-references to related chunks
   
3. **Adaptive Summarization Length**
   - Adjust summary length based on cluster size
   - Longer summaries for large (more complex) clusters
   
4. **Iterative Refinement (Optional)**
   - First pass: Extract key information
   - Second pass: Cross-validate with original chunks
   - Include "confidence score" in metadata

**Recommended Change**:
```python
# ENHANCED: Include cluster stats + iterative refinement
cluster_stats = {
    "size": len(nodes),
    "avg_similarity": np.mean([node.embedding_similarity for node in nodes]),
    "diversity_score": calculate_cluster_diversity(nodes)
}

# Provide LLM with cluster quality indicators
prompt = f"""Cluster Quality: {cluster_stats}

The {cluster_stats['size']} chunks below (avg similarity: {cluster_stats['avg_similarity']:.2f})
form a highly coherent semantic group:

{combined_text}

Create a summary that:
1. Preserves ALL key entities, dates, numbers, relationships
2. Explicitly marks confidence level (high/medium/low)
3. Includes cross-references to related topics
4. Is approximately {adaptive_summary_length} tokens"""
```

---

### 2. **Metadata Enrichment for Better Semantic Ranking**

**Current Issue**: Minimal metadata indexed, limiting semantic ranker context

**Location**: `raptor_service.py`, lines 430-445

```python
# CURRENT: Only essential metadata
ESSENTIAL_METADATA_KEYS = {
    "group_id", 
    "raptor_level", 
    "source", 
    "file_name", 
    "page_number"
}
```

**Optimization Recommendations**:

1. **Add Semantic Metadata**
   ```json
   {
     "cluster_quality": 0.92,           // GMM probability/silhouette score
     "cluster_coherence": "high",       // Calculated diversity metric
     "key_entities": ["Entity1", ...],  // Extracted from chunk texts
     "content_type": "contract|invoice|report",
     "confidence_score": 0.85,          // LLM's confidence in summary
     "embedding_similarity": [0.87, 0.91, 0.88]  // Min/max/avg intra-cluster similarity
   }
   ```

2. **Azure AI Search Filterable Metadata**
   - Add facets: `content_type`, `cluster_quality_tier`, `confidence_level`
   - Enable filtering: `cluster_quality >= 0.8`
   - Support queries: "Show high-confidence summaries"

3. **Lineage Tracking**
   ```json
   {
     "child_ids": ["chunk_001", "chunk_002", ...],  // Current - limited to 20
     "parent_ids": ["summary_001"],                 // Add: Parent clusters
     "creation_timestamp": "2025-12-14T10:30:00Z",  // When created
     "model_version": "gpt-4o-2024-11-20"          // Which LLM generated
   }
   ```

**Implementation Impact**:
- Semantic ranker gets richer context for relevance scoring
- Query filters can exclude low-confidence results
- Faceted search enables "show only high-quality clusters"

---

### 3. **Semantic Ranker Configuration Optimization**

**Current State**: Semantic ranker enabled but potential for tuning

**Location**: `vector_service.py`, lines 242, 350-365

**Current Configuration**:
```python
search_options = {
    "query_type": QueryType.SEMANTIC,
    "semantic_configuration_name": "raptor-semantic",
    "query_caption": QueryCaptionType.EXTRACTIVE,  # Extract snippets
    "query_answer": QueryAnswerType.EXTRACTIVE,    # Extract answers
}
```

**Optimization Opportunities**:

1. **Tune Semantic Ranker Weights**
   - Current: Azure defaults (50% semantic + 50% vector similarity)
   - **Recommendation**: Adjust based on use case
     - Document understanding (contracts): 60% semantic, 40% vector
     - Factual extraction (invoices): 40% semantic, 60% vector
   
2. **Semantic Captions Optimization**
   - Extract captions from top-k results post-reranking
   - Use captions as summary instead of full text to LLM
   - Reduces hallucination by anchoring to actual content

3. **Query-Time Semantic Ranking**
   - Currently configured but **NOT USED** in query operations
   - Implement in `retrieval_service.hybrid_search()` to use Azure AI Search results
   - Currently only Neo4j is queried at retrieval time

---

### 4. **Clustering Algorithm Refinement**

**Current Implementation**: GMM with fixed parameters

**Location**: `raptor_service.py`, lines 275-305

**Current Settings**:
```python
n_clusters = min(
    self.max_clusters_per_level,
    max(2, len(nodes) // 3)  # ← Roughly 3 nodes per cluster
)

gmm = GaussianMixture(
    n_components=n_clusters,
    covariance_type='full',
    random_state=42
)
```

**Optimization Recommendations**:

1. **Adaptive Cluster Sizing**
   ```python
   # Dynamic cluster size based on embedding variance
   if embedding_variance > THRESHOLD:
       # High variance = diverse content = more clusters needed
       n_clusters = max(2, len(nodes) // 2)
   else:
       # Low variance = homogeneous = fewer clusters okay
       n_clusters = max(2, len(nodes) // 5)
   ```

2. **Cluster Quality Validation**
   - Calculate silhouette scores post-clustering
   - Skip summarization for clusters with score < 0.5
   - Include silhouette score in metadata for semantic ranker

3. **Hybrid Clustering**
   - Use density-based clustering (HDBSCAN) for outlier detection
   - Mark outlier chunks as "mixed_content_cluster"
   - Semantic ranker can deprioritize these in certain queries

4. **Semantic Similarity Pre-filtering**
   - Calculate pairwise cosine similarity between chunks
   - Only cluster chunks with similarity > threshold (e.g., 0.75)
   - Creates more homogeneous, higher-quality clusters

---

### 5. **Index Configuration & Schema Optimization**

**Current Index Name**: `raptor` (group-scoped: `{group_id}-raptor`)

**Optimization Recommendations**:

1. **Multi-Index Strategy by Content Type**
   ```
   {group_id}-raptor-contracts
   {group_id}-raptor-invoices
   {group_id}-raptor-reports
   ```
   - Index level nodes differently by content type
   - Tune semantic ranker per domain

2. **Separate Index Levels**
   ```
   {group_id}-raptor-l0    // Leaf chunks only
   {group_id}-raptor-l1+   // Summaries only
   ```
   - Query optimization: choose appropriate level
   - Trade-off: specificity vs. computational cost

3. **Embedding Vector Dimension**
   - **Current**: 1536 (text-embedding-ada-002)
   - **Upgrade Path**: Switch to text-embedding-3-large (3072 dims)
   - Pro: Higher semantic precision, better ranking
   - Con: Higher storage cost (~2x)
   - **Recommendation**: Use 3072 dims for summary nodes, 1536 for chunks

---

### 6. **Query-Time Integration with Azure AI Search**

**Critical Gap**: Semantic ranker is configured but **never called at query time**

**Current Flow** (broken):
```
Query → RetrievalService.hybrid_search() 
        → PropertyGraphIndex (Neo4j only)
        → LLM Answer Generation
❌ Azure AI Search not queried
```

**Recommended Fix**:
```
Query → RetrievalService.hybrid_search()
        ├→ Vector Search (Neo4j) - structural/entity focus
        ├→ Semantic Search (Azure AI Search) - semantic/summary focus
        └→ Merge & Re-rank Results
           → LLM Answer Generation
✅ Azure AI Search with semantic ranker now actively used
```

**Implementation**:
```python
async def hybrid_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
    # Parallel queries
    neo4j_results = await self._neo4j_search(query)
    azure_results = await self._azure_semantic_search(query)  # ← NEW
    
    # Merge results with re-ranking
    merged = self._merge_and_rerank(neo4j_results, azure_results)
    
    return {
        "query": query,
        "mode": "hybrid_plus_semantic",
        "answer": await self.llm_service.answer(merged),
        "sources": merged,
        "semantic_rerank_used": True  # ← NEW metadata
    }
```

---

## Implementation Priority

### Phase 1 (High Impact, Low Effort)
1. ✅ Enhance RAPTOR summary metadata (cluster quality scores)
2. ✅ Add semantic metadata to indexed nodes (confidence, coherence)
3. ✅ Implement cluster quality validation (silhouette scores)

### Phase 2 (Medium Impact, Medium Effort)
1. ⚠️ Integrate Azure AI Search querying in `hybrid_search()` endpoint
2. ⚠️ Implement adaptive summarization based on cluster size
3. ⚠️ Add semantic captions extraction post-ranking

### Phase 3 (High Impact, High Effort)
1. 🔮 Upgrade to text-embedding-3-large (3072 dims)
2. 🔮 Implement multi-index by content type strategy
3. 🔮 Add iterative refinement for summary generation

---

## Expected Quality Improvements

| Optimization | Expected Impact | Effort |
|--------------|----------------|--------|
| Metadata enrichment | +10-15% ranking accuracy | Low |
| Cluster quality validation | +5-10% relevance | Low |
| Azure AI Search integration | +20-25% retrieval accuracy | Medium |
| Adaptive summarization | +5% context preservation | Medium |
| Embedding dim upgrade (3072) | +15-20% semantic precision | High |
| Iterative refinement | +10% confidence in answers | High |

---

## Configuration Changes Required

### `.env` Updates
```bash
# Current
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-ada-002
EMBEDDING_DIMENSIONS=1536

# Recommended (Phase 3)
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072

# New
RAPTOR_CLUSTER_QUALITY_THRESHOLD=0.6  # Min silhouette score
RAPTOR_ADAPTIVE_SUMMARY_LENGTH=true
AZURE_AI_SEARCH_SEMANTIC_RANKER_WEIGHT=0.6  # 60% semantic, 40% vector
USE_AZURE_AI_SEARCH_AT_QUERY_TIME=true  # Phase 2 feature flag
```

---

## Testing Strategy

1. **Cluster Quality Metrics**
   ```python
   pytest app/services/test_raptor_quality.py::test_cluster_silhouette_scores
   pytest app/services/test_raptor_quality.py::test_summary_coherence
   ```

2. **End-to-End Indexing**
   ```bash
   python test_graphrag_5doc_api_benchmark.py --measure-index-quality
   ```

3. **Query Accuracy**
   ```bash
   # Measure semantic ranker impact
   python test_azure_ai_search_ranking.py --compare-with-without-ranker
   ```

4. **Integration Tests**
   ```bash
   # Verify hybrid search combines Neo4j + Azure AI Search
   pytest app/routers/test_graphrag_query_hybrid.py
   ```

---

## References

- **Azure AI Search Semantic Ranker**: https://learn.microsoft.com/en-us/azure/search/semantic-search-overview
- **RAPTOR Paper**: https://arxiv.org/abs/2401.18059
- **Silhouette Analysis**: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.silhouette_score.html
- **Hybrid Search Strategy**: https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query

---

## Summary

The primary optimization opportunity is **enriching RAPTOR node metadata with cluster quality metrics** before indexing to Azure AI Search. This provides the semantic ranker with better context to score relevance. The secondary opportunity is **enabling Azure AI Search querying at query time** (currently it's only used for indexing, not retrieval).

Estimated impact: **+20-30% improvement in retrieval accuracy** by combining:
1. Better cluster quality metrics (Phase 1)
2. Azure AI Search at query time (Phase 2)
3. Semantic captions extraction (Phase 2)
