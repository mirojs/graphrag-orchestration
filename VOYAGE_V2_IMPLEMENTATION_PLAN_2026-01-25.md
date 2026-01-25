# V2 Contextual Chunking Implementation Plan

**Date:** January 25, 2026  
**Status:** Ready for Implementation  
**Estimated Effort:** 5-6 weeks  
**Related:** `VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md`

---

## Phase 1: Setup & Dependencies (Week 1)

### Step 1.1: Add Voyage Dependency
**File:** `graphrag-orchestration/requirements.txt`

```diff
+ voyageai>=0.2.0
```

**Verification:**
```bash
pip install voyageai
python -c "import voyageai; print(voyageai.__version__)"
```

---

### Step 1.2: Add Configuration
**File:** `graphrag-orchestration/app/core/config.py`

Add new settings:
```python
# Voyage AI V2
VOYAGE_API_KEY: str = ""
VOYAGE_V2_ENABLED: bool = False
VOYAGE_MODEL_NAME: str = "voyage-context-3"
VOYAGE_EMBEDDING_DIM: int = 2048
```

**File:** `.env`
```bash
VOYAGE_API_KEY=your-voyage-api-key-here
VOYAGE_V2_ENABLED=0  # Set to 1 to enable V2
```

---

### Step 1.3: Copy V1 Code to V2 Directory (CRITICAL: Start from Working Code)

**⚠️ IMPORTANT:** Do NOT create V2 from scratch. Copy all V1 code first, then modify incrementally. This ensures V2 starts from a known-working state.

**Commands:**
```bash
# Step 1.3.1: Copy entire V1 hybrid module to V2
cp -r app/hybrid app/hybrid_v2

# Step 1.3.2: Copy ingestion service
cp app/services/cu_standard_ingestion_service.py app/services/cu_standard_ingestion_service_v2.py

# Step 1.3.3: Update imports in V2 files to use hybrid_v2 paths
# (Run after copying - update all internal imports)
find app/hybrid_v2 -name "*.py" -exec sed -i 's/from app\.hybrid\./from app.hybrid_v2./g' {} \;
find app/hybrid_v2 -name "*.py" -exec sed -i 's/import app\.hybrid\./import app.hybrid_v2./g' {} \;

# Step 1.3.4: Create embeddings directory for Voyage service
mkdir -p app/hybrid_v2/embeddings
touch app/hybrid_v2/embeddings/__init__.py
```

**Verification (V2 should work identically to V1 after copy):**
```bash
# Run V2 tests to ensure copy is functional
python -c "from app.hybrid_v2.routes.route_2_local import LocalSearchRoute; print('V2 imports OK')"
```

**Result:**
```
app/
├── hybrid/                    # V1 (UNCHANGED - still in production)
│   ├── __init__.py
│   ├── routes/
│   │   ├── route_2_local.py   # V1 Local Search
│   │   ├── route_3_global.py  # V1 Global Search
│   │   └── route_4_drift.py   # V1 DRIFT
│   ├── pipeline/
│   │   ├── enhanced_graph_retriever.py
│   │   ├── hub_extractor.py
│   │   └── synthesis.py
│   └── indexing/
│
├── hybrid_v2/                 # V2 (COPY of V1, then modify)
│   ├── __init__.py
│   ├── routes/                # Copied from V1
│   │   ├── route_2_local.py   # Will modify for Voyage
│   │   ├── route_3_global.py  # Will simplify
│   │   └── route_4_drift.py   # Will simplify
│   ├── pipeline/              # Copied from V1
│   │   ├── enhanced_graph_retriever.py  # Will remove section diversification
│   │   ├── hub_extractor.py   # Will deprecate
│   │   └── synthesis.py
│   ├── indexing/              # Copied from V1
│   └── embeddings/            # NEW for Voyage
│       ├── __init__.py
│       └── voyage_embed.py    # Step 1.4
│
└── services/
    ├── cu_standard_ingestion_service.py      # V1 (unchanged)
    └── cu_standard_ingestion_service_v2.py   # V2 (copy, then modify)
```

**Key Principle:** Every V2 file starts as an exact copy of V1. Modifications are incremental and testable.

---

### Step 1.4: Add Voyage Embedding Service (New File)
**File:** `app/hybrid_v2/embeddings/voyage_embed.py`

```python
"""
Voyage AI Embedding Service for V2 Contextual Chunking.

Uses voyage-context-3 (2048 dimensions) via LlamaIndex.
"""

import logging
from typing import List, Optional

from llama_index.embeddings.voyageai import VoyageEmbedding

from app.core.config import settings

logger = logging.getLogger(__name__)


class VoyageEmbedService:
    """Voyage AI embedding service with contextual embedding support."""
    
    def __init__(
        self,
        model_name: str = None,
        api_key: str = None,
    ):
        self.model_name = model_name or settings.VOYAGE_MODEL_NAME
        self.api_key = api_key or settings.VOYAGE_API_KEY
        
        if not self.api_key:
            raise ValueError("VOYAGE_API_KEY is required for V2 embeddings")
        
        self._embed_model = VoyageEmbedding(
            model_name=self.model_name,
            voyage_api_key=self.api_key,
        )
        
        logger.info(f"VoyageEmbedService initialized with model: {self.model_name}")
    
    @property
    def embed_dim(self) -> int:
        """Return embedding dimensions (2048 for voyage-context-3)."""
        return settings.VOYAGE_EMBEDDING_DIM
    
    def embed_documents(
        self,
        texts: List[str],
        contexts: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed documents with optional context.
        
        Args:
            texts: List of text chunks to embed
            contexts: Optional list of context strings (e.g., section titles)
            
        Returns:
            List of embedding vectors (2048 dimensions each)
        """
        if contexts:
            # Prepend context to each text for contextual embedding
            texts_with_context = [
                f"{ctx}:\n{text}" if ctx else text
                for ctx, text in zip(contexts, texts)
            ]
        else:
            texts_with_context = texts
        
        embeddings = self._embed_model.get_text_embedding_batch(texts_with_context)
        
        logger.debug(f"Embedded {len(texts)} documents with Voyage")
        return embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """Embed a query string."""
        return self._embed_model.get_query_embedding(query)


# Singleton instance
_voyage_service: Optional[VoyageEmbedService] = None


def get_voyage_embed_service() -> VoyageEmbedService:
    """Get or create singleton VoyageEmbedService."""
    global _voyage_service
    if _voyage_service is None:
        _voyage_service = VoyageEmbedService()
    return _voyage_service
```

**Verification:**
```python
from app.hybrid_v2.embeddings.voyage_embed import get_voyage_embed_service

service = get_voyage_embed_service()
embedding = service.embed_query("test query")
print(f"Embedding dim: {len(embedding)}")  # Should be 2048
```

---

## Phase 2: Section-Aware Chunking (Week 2)

### Step 2.1: Implement Section-Aware Ingestion Service
**File:** `app/services/cu_standard_ingestion_service_v2.py`

Key changes from V1:
1. Buffer text by Azure DI sections (not pages)
2. Apply min/max token rules
3. Store `parent_doc_title` separately from `section_title`
4. Detect summary sections

```python
# Key method additions:

def _buffer_by_sections(self, pages: List[Dict]) -> List[Dict]:
    """
    Buffer text by Azure DI section boundaries.
    
    Returns list of section dicts with:
    - text: Complete section text
    - section_title: Section heading
    - section_level: Heading level (1, 2, 3)
    - section_path: Full path ["Doc", "Section", "Subsection"]
    - is_summary_section: True if title matches summary patterns
    """
    sections = []
    current_section = None
    
    for page in pages:
        for para in page.get("paragraphs", []):
            role = para.get("role", "")
            content = para.get("content", "").strip()
            
            if role in ("title", "sectionHeading"):
                # Save previous section
                if current_section and current_section["text"]:
                    sections.append(current_section)
                
                # Start new section
                level = 1 if role == "title" else 2
                current_section = {
                    "text": "",
                    "section_title": content,
                    "section_level": level,
                    "section_path": self._build_section_path(content, level),
                    "is_summary_section": self._is_summary_section(content),
                }
            elif current_section:
                current_section["text"] += content + "\n\n"
    
    # Don't forget last section
    if current_section and current_section["text"]:
        sections.append(current_section)
    
    return sections

def _is_summary_section(self, title: str) -> bool:
    """Detect summary sections by title pattern."""
    patterns = [
        "purpose", "summary", "executive summary",
        "introduction", "overview", "scope",
        "background", "abstract", "objectives",
        "recitals", "whereas",
    ]
    title_lower = title.lower()
    return any(p in title_lower for p in patterns)

def _apply_chunking_rules(
    self,
    sections: List[Dict],
    min_tokens: int = 100,
    max_tokens: int = 1500,
    overlap_tokens: int = 50,
) -> List[Dict]:
    """
    Apply split/merge rules to sections.
    
    - Merge sections < min_tokens with sibling
    - Split sections > max_tokens at paragraph boundaries
    """
    # Implementation details...
```

---

### Step 2.2: Create V2 Neo4j Index
**Cypher:**
```cypher
// Create V2 vector index with 2048 dimensions
CREATE VECTOR INDEX chunk_embeddings_v2 IF NOT EXISTS
FOR (c:TextChunk)
ON c.embedding_v2
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 2048,
    `vector.similarity_function`: 'cosine'
  }
}
```

**Python migration script:**
```python
# scripts/create_v2_index.py

async def create_v2_index():
    query = """
    CREATE VECTOR INDEX chunk_embeddings_v2 IF NOT EXISTS
    FOR (c:TextChunk)
    ON c.embedding_v2
    OPTIONS {
      indexConfig: {
        `vector.dimensions`: 2048,
        `vector.similarity_function`: 'cosine'
      }
    }
    """
    await neo4j_service.execute(query)
    logger.info("Created chunk_embeddings_v2 index")
```

---

## Phase 3: Pipeline Simplification (Week 3)

### Step 3.1: Remove Section Diversification
**File:** `app/hybrid_v2/pipeline/enhanced_graph_retriever.py`

Delete or bypass:
- `get_summary_chunks_by_section()`
- Section diversification logic in retrieval

Replace with:
```python
async def get_chunks_by_summary_section(
    self,
    group_id: str,
    limit: int = 5,
) -> List[TextChunk]:
    """
    V2: Retrieve chunks marked as summary sections.
    
    No diversification needed - chunks ARE sections.
    """
    query = """
    MATCH (c:TextChunk)
    WHERE c.group_id = $group_id
      AND c.is_summary_section = true
    RETURN c
    LIMIT $limit
    """
    return await self._execute_chunk_query(query, group_id=group_id, limit=limit)
```

---

### Step 3.2: Remove Hub Entity Extraction
**File:** `app/hybrid_v2/pipeline/hub_extractor.py`

Mark as deprecated or delete entirely. Contextual embeddings capture document context natively.

---

### Step 3.3: Upgrade Route 2 Embeddings
**File:** `app/hybrid_v2/routes/route_2_local.py`

**Note:** Route 1 (Vector RAG) was already removed on January 24, 2026. We upgrade Route 2 only.

Update Route 2 to use Voyage embeddings:
```python
# app/hybrid_v2/routes/route_2_local.py

from app.hybrid_v2.embeddings.voyage_embed import get_voyage_embed_service

class LocalSearchRouteV2:
    """
    V2: Local Search with Voyage embeddings.
    
    Changes from V1:
    - Voyage embeddings (2048 dim) instead of OpenAI (3072 dim)
    - Section-aware chunks for better semantic coherence
    - BM25+Vector hybrid approach retained
    """
    
    def __init__(self):
        self._embed_service = get_voyage_embed_service()
    
    async def search(
        self,
        query: str,
        group_id: str,
        top_k: int = 10,
    ) -> SearchResult:
        # 1. Vector search (Voyage embeddings)
        query_embedding = self._embed_service.embed_query(query)
        vector_results = await self._vector_search(query_embedding, group_id, top_k)
        
        # 2. BM25 keyword search (unchanged)
        bm25_results = await self._bm25_search(query, group_id, top_k)
        
        # 3. RRF fusion (unchanged)
        fused = self._rrf_fusion(vector_results, bm25_results)
        
        return SearchResult(chunks=fused[:top_k])
```

---

## Phase 4: Testing & Validation (Week 4)

### Step 4.1: Re-Index Test Corpus
```bash
# Index with V2 pipeline
VOYAGE_V2_ENABLED=1 python scripts/reindex_test_group.py \
    --group-id test-5pdfs-v2 \
    --use-v2
```

**Expected output:**
- ~17 chunks (vs V1's ~74)
- All chunks have `section_title` populated
- All chunks have `parent_doc_title` (base document name only)
- Summary sections marked with `is_summary_section=true`

---

### Step 4.2: Run Benchmark
```bash
# Run full Q-D/Q-N benchmark on V2
VOYAGE_V2_ENABLED=1 python scripts/benchmark_route4_drift_multi_hop.py \
    --group-id test-5pdfs-v2 \
    --use-v2
```

**Target:** 100% (57/57)

**Specific validation:**
- Q-D8: "Fabrikam Inc." = 4 docs, "Contoso Ltd." = 3 docs (NOT 5 vs 5)

---

### Step 4.3: Compare V1 vs V2

| Metric | V1 | V2 | Pass? |
|--------|----|----|-------|
| Q-D Accuracy | 96.5% | Target: 100% | |
| Q-N Accuracy | 100% | Target: 100% | |
| Latency (p50) | ~20s | Target: <16s | |
| Storage | 11.4 GB/1M | Target: <8 GB/1M | |

---

## Phase 5: Production Rollout (Week 5-6)

### Step 5.1: Feature Flag Deployment
```bash
# Enable V2 in production via env var
VOYAGE_V2_ENABLED=1
```

### Step 5.2: Monitoring
- Track error rates
- Track latency percentiles
- Track embedding API costs

### Step 5.3: Soak Period
- 2 weeks with V2 enabled
- Monitor for regressions
- Rollback plan: Set `VOYAGE_V2_ENABLED=0`

### Step 5.4: V1 Deprecation
After successful soak:
1. Remove V1 code (`app/hybrid/`)
2. Rename `app/hybrid_v2/` → `app/hybrid/`
3. Drop `chunk_embeddings` index (V1)
4. Update documentation

---

## Checklist

### Week 1
- [ ] Add `voyageai` to requirements.txt
- [ ] Add config for `VOYAGE_API_KEY`, `VOYAGE_V2_ENABLED`
- [ ] Create `app/hybrid_v2/` directory structure
- [ ] Implement `voyage_embed.py`
- [ ] Verify Voyage API connectivity

### Week 2
- [ ] Implement `cu_standard_ingestion_service_v2.py`
- [ ] Create `chunk_embeddings_v2` Neo4j index
- [ ] Test section buffering logic
- [ ] Test split/merge rules

### Week 3
- [ ] Remove Section Diversification from V2
- [ ] Remove Hub Entity Extraction from V2
- [ ] Upgrade Route 2 with Voyage embeddings
- [ ] Update router for V2

### Week 4
- [ ] Re-index test corpus with V2
- [ ] Run Q-D/Q-N benchmark
- [ ] Validate Q-D8 fix
- [ ] Compare V1 vs V2 metrics

### Week 5-6
- [ ] Deploy with feature flag
- [ ] Monitor production
- [ ] Complete soak period
- [ ] Deprecate V1

---

## Rollback Plan

If V2 causes issues in production:

1. **Immediate:** Set `VOYAGE_V2_ENABLED=0` (routes to V1)
2. **Data:** V1 index (`chunk_embeddings`) remains intact
3. **Investigation:** Debug V2 issues with V1 serving traffic
4. **Re-deploy:** Fix and re-enable V2

---

## Contacts

- **Owner:** [TBD]
- **Reviewer:** [TBD]
- **Stakeholders:** [TBD]
