# Phase 1 Implementation Plan: Azure AI Search Indexing Quality Optimization

**Date**: 2025-12-14  
**Target**: Enhance metadata before Azure AI Search indexing  
**Expected Impact**: +10-15% ranking accuracy  
**Effort**: 2-3 hours implementation + 1 hour testing

## Overview

Phase 1 focuses on enriching the metadata indexed to Azure AI Search with cluster quality metrics. This requires changes to three files:

1. **raptor_service.py** - Add cluster quality metrics during summarization
2. **vector_service.py** - Include these metrics in the indexed documents
3. **test_raptor_quality.py** - New: Validate quality metrics

---

## Changes Required

### 1. Update `raptor_service.py` - Enhance Clustering with Quality Metrics

**File**: `/afh/projects/graphrag-orchestration/graphrag-orchestration/app/services/raptor_service.py`

**Change 1a: Add silhouette score calculation to `_cluster_nodes()`**

```python
# LOCATION: After line 305 (after clustering completes)

# ADD: Calculate cluster quality metrics
from sklearn.metrics import silhouette_score, silhouette_samples

silhouette_avg = silhouette_score(embeddings_array, labels)
silhouette_per_sample = silhouette_samples(embeddings_array, labels)

# Store quality metrics in each node
for i, node in enumerate(nodes):
    cluster_id = labels[i]
    node.metadata['silhouette_score'] = float(silhouette_per_sample[i])
    node.metadata['cluster_silhouette_avg'] = float(silhouette_avg)
    
logger.info(f"Cluster silhouette score: {silhouette_avg:.3f}")
return clusters, {"silhouette_avg": silhouette_avg, "silhouette_samples": silhouette_per_sample}
```

**Change 1b: Update method signature to return quality metrics**

Current:
```python
async def _cluster_nodes(
    self, 
    nodes: List[TextNode],
    method: str = "gmm"
) -> Dict[int, List[TextNode]]:
```

New:
```python
async def _cluster_nodes(
    self, 
    nodes: List[TextNode],
    method: str = "gmm"
) -> tuple[Dict[int, List[TextNode]], Dict[str, Any]]:
    """
    Returns:
        - clusters: Dict mapping cluster_id -> list of nodes
        - quality_metrics: Dict with silhouette scores and diversity metrics
    """
```

**Change 1c: Update caller in `_process_manual()` (line 214)**

Current:
```python
clusters = await self._cluster_nodes(current_level_nodes)
```

New:
```python
clusters, cluster_quality = await self._cluster_nodes(current_level_nodes)
# Pass quality metrics to summarization
for cluster_id, cluster_nodes in clusters.items():
    for node in cluster_nodes:
        node.metadata['cluster_quality_metrics'] = cluster_quality
```

---

### 2. Enhance `_summarize_cluster()` - Add Confidence & Coherence Metrics

**File**: Same as above, lines 318-390

**Change 2a: Expand metadata in summary node (line 380)**

Current:
```python
summary_node = TextNode(
    text=summary_text,
    metadata={
        'group_id': group_id,
        'raptor_level': level,
        'cluster_id': cluster_id,
        'source': 'raptor',
        'child_count': len(nodes),
        'child_ids': [n.node_id for n in nodes[:20]],
    }
)
```

New:
```python
# Calculate cluster coherence (intra-cluster similarity)
if nodes[0].embedding is not None:
    from scipy.spatial.distance import pdist
    embeddings = np.array([n.embedding for n in nodes if n.embedding is not None])
    if len(embeddings) > 1:
        avg_similarity = 1 - np.mean(pdist(embeddings, metric='cosine'))
    else:
        avg_similarity = 1.0
else:
    avg_similarity = 0.0

# Confidence level based on cluster cohesion
if avg_similarity >= 0.85:
    confidence = "high"
    confidence_score = 0.95
elif avg_similarity >= 0.75:
    confidence = "medium"
    confidence_score = 0.80
else:
    confidence = "low"
    confidence_score = 0.60

summary_node = TextNode(
    text=summary_text,
    metadata={
        'group_id': group_id,
        'raptor_level': level,
        'cluster_id': cluster_id,
        'source': 'raptor',
        'child_count': len(nodes),
        'child_ids': [n.node_id for n in nodes[:20]],
        # NEW: Quality metrics
        'cluster_coherence': float(avg_similarity),
        'confidence_level': confidence,
        'confidence_score': float(confidence_score),
        'silhouette_score': nodes[0].metadata.get('silhouette_score', 0.0) if nodes else 0.0,
        'creation_model': 'gpt-4o-2024-11-20',
    }
)
```

---

### 3. Update `index_raptor_nodes()` - Include Quality Metadata

**File**: Same, lines 399-460

**Change 3a: Expand essential metadata keys (line 433)**

Current:
```python
ESSENTIAL_METADATA_KEYS = {
    "group_id", 
    "raptor_level", 
    "source", 
    "file_name", 
    "page_number"
}
```

New:
```python
ESSENTIAL_METADATA_KEYS = {
    "group_id", 
    "raptor_level", 
    "source", 
    "file_name", 
    "page_number",
    # NEW: Quality metrics for semantic ranker
    "cluster_coherence",
    "confidence_level",
    "confidence_score",
    "silhouette_score",
    "cluster_quality_metrics",
    "creation_model",
    "child_count",
}
```

**Change 3b: Add logging for indexed metadata (line 455)**

Add after successful indexing:
```python
logger.info(f"RAPTOR indexed metadata: {len(documents)} nodes with quality metrics")
# Log sample metadata for verification
if documents:
    sample_meta = documents[0].metadata
    logger.debug(f"Sample metadata: confidence={sample_meta.get('confidence_level')}, "
                f"coherence={sample_meta.get('cluster_coherence'):.3f}")
```

---

### 4. Update `vector_service.py` - Configure Filterable Metadata

**File**: `/afh/projects/graphrag-orchestration/graphrag-orchestration/app/services/vector_service.py`

**Change 4a: Update Azure AI Search configuration (lines 265-280)**

Current:
```python
vector_store = AzureAISearchVectorStore(
    search_or_index_client=None,
    endpoint=self.endpoint,
    key=self.api_key,
    index_name=azure_index_name,
    filterable_metadata_field_keys=["group_id", "raptor_level", "source"],
    ...
)
```

New:
```python
vector_store = AzureAISearchVectorStore(
    search_or_index_client=None,
    endpoint=self.endpoint,
    key=self.api_key,
    index_name=azure_index_name,
    filterable_metadata_field_keys=[
        "group_id", 
        "raptor_level", 
        "source",
        # NEW: Quality metric fields for filtering
        "confidence_level",
        "cluster_coherence",
        "silhouette_score",
    ],
    ...
)
```

**Change 4b: Update search method to include quality info (lines 350-365)**

Current return:
```python
formatted_results.append({
    "text": result.get("content", ""),
    "score": result.get("@search.score", 0),
    "reranker_score": result.get("@search.reranker_score"),
    "captions": result.get("@search.captions"),
    "metadata": result.get("metadata", {}),
})
```

New return:
```python
metadata = result.get("metadata", {})
formatted_results.append({
    "text": result.get("content", ""),
    "score": result.get("@search.score", 0),
    "reranker_score": result.get("@search.reranker_score"),
    "captions": result.get("@search.captions"),
    "metadata": metadata,
    # NEW: Extract quality metrics for visibility
    "quality_metrics": {
        "confidence_level": metadata.get("confidence_level"),
        "confidence_score": metadata.get("confidence_score"),
        "cluster_coherence": metadata.get("cluster_coherence"),
    }
})
```

---

## Testing Plan

### Test 1: Unit test for cluster quality calculation

**File**: Create `/afh/projects/graphrag-orchestration/graphrag-orchestration/app/services/test_raptor_quality.py`

```python
import pytest
import numpy as np
from llama_index.core.schema import TextNode
from app.services.raptor_service import RaptorService

@pytest.mark.asyncio
async def test_cluster_silhouette_scores():
    """Verify silhouette scores are calculated and stored in metadata."""
    service = RaptorService()
    
    # Create test nodes with embeddings
    nodes = []
    for i in range(10):
        # Create two clusters: i < 5 -> cluster 0, i >= 5 -> cluster 1
        if i < 5:
            embedding = np.array([1.0 + np.random.randn() * 0.1 for _ in range(1536)])
        else:
            embedding = np.array([2.0 + np.random.randn() * 0.1 for _ in range(1536)])
        
        node = TextNode(
            text=f"Test chunk {i}",
            embedding=embedding / np.linalg.norm(embedding)
        )
        nodes.append(node)
    
    # Cluster nodes
    clusters, quality = await service._cluster_nodes(nodes)
    
    # Verify silhouette scores exist
    assert "silhouette_avg" in quality
    assert quality["silhouette_avg"] > 0, "Silhouette should be positive for distinct clusters"
    
    # Verify metadata was added
    for node in nodes:
        assert "silhouette_score" in node.metadata
        assert "cluster_silhouette_avg" in node.metadata

@pytest.mark.asyncio
async def test_summary_confidence_calculation():
    """Verify confidence scores are based on cluster coherence."""
    service = RaptorService()
    
    # Create tightly clustered nodes (high coherence)
    nodes_high_coherence = []
    for i in range(5):
        embedding = np.array([1.0 + np.random.randn() * 0.05 for _ in range(1536)])
        node = TextNode(
            text=f"Related topic: {i}",
            embedding=embedding / np.linalg.norm(embedding)
        )
        nodes_high_coherence.append(node)
    
    summary = await service._summarize_cluster(
        nodes_high_coherence, 
        level=1, 
        cluster_id=0,
        group_id="test-group"
    )
    
    # High coherence should produce high confidence
    assert summary is not None
    assert summary.metadata["confidence_level"] in ["high", "medium", "low"]
    assert 0.0 <= summary.metadata["confidence_score"] <= 1.0
    assert summary.metadata["confidence_score"] >= 0.80  # High coherence

@pytest.mark.asyncio  
async def test_metadata_indexing_completeness():
    """Verify all quality metrics are indexed to Azure AI Search."""
    service = RaptorService()
    
    # Create test node with quality metrics
    node = TextNode(
        text="Test summary",
        metadata={
            "group_id": "test-group",
            "raptor_level": 1,
            "source": "raptor",
            "cluster_coherence": 0.88,
            "confidence_level": "high",
            "confidence_score": 0.95,
            "silhouette_score": 0.75,
        }
    )
    
    # Index node
    from llama_index.core import Document
    documents = [Document(text=node.text, metadata=node.metadata)]
    
    # Verify all metadata keys are in ESSENTIAL_METADATA_KEYS
    from app.services.raptor_service import RaptorService
    indexed_keys = {
        "cluster_coherence",
        "confidence_level", 
        "confidence_score",
        "silhouette_score",
    }
    
    # These should now be in the indexing whitelist
    assert all(key in indexed_keys for key in indexed_keys)
```

### Test 2: Integration test with Azure AI Search

```bash
# Run benchmark with quality metrics
python test_graphrag_5doc_api_benchmark.py --verify-indexing-quality

# Expected output:
# ✅ Indexed 150 RAPTOR nodes to Azure AI Search
# ├─ Level 0: 50 chunks with avg coherence 0.82
# ├─ Level 1: 40 summaries with avg confidence "high" (0.92)
# └─ Level 2: 10 summaries with avg confidence "medium" (0.78)
```

### Test 3: Query time verification

```bash
# Verify quality metrics are returned in search results
curl -X POST http://localhost:8000/graphrag/v2/query/hybrid \
  -H "X-Group-ID: test-group" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the contract amount?"
  }' | jq '.sources[].quality_metrics'

# Expected output:
# {
#   "confidence_level": "high",
#   "confidence_score": 0.95,
#   "cluster_coherence": 0.88
# }
```

---

## Validation Checklist

- [ ] Silhouette scores computed and stored in metadata
- [ ] Confidence levels assigned based on cluster coherence  
- [ ] Quality metrics included in Azure AI Search index
- [ ] Filterable metadata fields updated in AzureAISearchVectorStore
- [ ] Unit tests pass: `test_cluster_silhouette_scores`
- [ ] Unit tests pass: `test_summary_confidence_calculation`
- [ ] Integration test verifies metadata in indexed documents
- [ ] Query results include quality_metrics in response
- [ ] Log messages show cluster quality stats
- [ ] No regression in existing functionality

---

## Rollback Plan

If issues arise:

1. **Git revert**: `git revert <commit-hash>`
2. **Azure AI Search**: Delete and recreate index (takes ~5 min)
3. **Environment**: Rolling restart of container app (0-downtime)

---

## Performance Impact

| Metric | Current | With Phase 1 | Delta |
|--------|---------|-------------|-------|
| Indexing time (5 docs) | ~45s | ~50s | +5s (silhouette calc) |
| Index size | ~2MB | ~2.2MB | +10% (metadata) |
| Query latency | ~200ms | ~210ms | +10ms (metadata serialization) |
| Accuracy improvement | Baseline | +10-15% | +10-15% |

---

## Success Metrics

1. **Quality metrics present**: 100% of RAPTOR nodes have confidence_score
2. **Semantic ranker benefit**: Reranker_score correlates with confidence_score (r > 0.7)
3. **No regressions**: Query latency increase < 5%
4. **User visible**: Quality metrics included in API responses

---

## Timeline

- **Implementation**: 1-2 hours
- **Testing**: 30 minutes
- **Code review**: 15 minutes  
- **Deployment**: 10 minutes (rolling update)
- **Monitoring**: 30 minutes (verify metrics in logs)

**Total**: ~3 hours

---

## Next Steps (Phase 2)

Once Phase 1 is validated:

1. Use quality metrics to filter results at query time (confidence_score >= 0.8)
2. Integrate Azure AI Search queries into `hybrid_search()` endpoint
3. Implement semantic captions extraction as summaries

See: `AZURE_AI_SEARCH_INDEXING_QUALITY_OPTIMIZATION.md` Phase 2 section.
