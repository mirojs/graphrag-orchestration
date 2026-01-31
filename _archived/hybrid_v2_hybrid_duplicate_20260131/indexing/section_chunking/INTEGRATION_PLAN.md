# Section-Aware Chunking: Test & Integration Plan

## Overview

This document provides a step-by-step plan to test section-aware chunking and integrate it with the existing indexing and retrieval pipelines.

## Phase 1: Unit Testing (No Pipeline Changes)

### Step 1.1: Run Standalone Tests

```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration

# Run the built-in test
python -m app.hybrid.indexing.section_chunking.test_chunker
```

**Expected output:**
- Section extraction from mock DI units
- Tiny section merging
- Large section splitting
- Summary section detection
- TextChunk conversion

### Step 1.2: Test with Real Azure DI Output

Create a test script that uses actual DI extraction:

```bash
# Create test script
python scripts/test_section_chunking_real.py
```

**Test file to create:** `scripts/test_section_chunking_real.py`

---

## Phase 2: Indexing Pipeline Integration

### Step 2.1: Code Change - Add Feature Flag to lazygraphrag_pipeline.py

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py`

**Location:** Near the top, after imports (~line 50)

```python
# Add import
import os

# Add feature flag
USE_SECTION_CHUNKING = os.getenv("USE_SECTION_CHUNKING", "0").strip().lower() in {"1", "true", "yes"}
```

### Step 2.2: Code Change - Modify _chunk_di_units Method

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py`

**Location:** `_chunk_di_units` method (~line 315)

**Current code:**
```python
async def _chunk_di_units(self, *, di_units: Sequence[LlamaDocument], doc_id: str) -> List[TextChunk]:
    chunks: List[TextChunk] = []
    chunk_index = 0
    for unit_i, unit in enumerate(di_units):
        # ... existing fixed chunking logic
```

**Change to:**
```python
async def _chunk_di_units(self, *, di_units: Sequence[LlamaDocument], doc_id: str) -> List[TextChunk]:
    # Check if section-aware chunking is enabled
    if USE_SECTION_CHUNKING:
        return await self._chunk_di_units_section_aware(di_units=di_units, doc_id=doc_id)
    
    # Original fixed chunking logic follows...
    chunks: List[TextChunk] = []
    chunk_index = 0
    # ... rest of existing code
```

### Step 2.3: Code Change - Add New Section-Aware Method

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py`

**Location:** After `_chunk_di_units` method

**Add new method:**
```python
async def _chunk_di_units_section_aware(
    self, 
    *, 
    di_units: Sequence[LlamaDocument], 
    doc_id: str
) -> List[TextChunk]:
    """Section-aware chunking using Azure DI section boundaries."""
    from app.hybrid.indexing.section_chunking.integration import (
        chunk_di_units_section_aware
    )
    
    # Extract doc metadata for the chunker
    doc_source = ""
    doc_title = ""
    if di_units:
        first_meta = getattr(di_units[0], "metadata", None) or {}
        doc_source = first_meta.get("url", "") or first_meta.get("source", "")
        doc_title = first_meta.get("title", "")
    
    return await chunk_di_units_section_aware(
        di_units=di_units,
        doc_id=doc_id,
        doc_source=doc_source,
        doc_title=doc_title,
    )
```

### Step 2.4: Test Indexing with Section Chunking

```bash
# Set environment variable
export USE_SECTION_CHUNKING=1

# Run indexing on test corpus (use existing test script or API)
# Option A: Direct API call
curl -X POST "http://localhost:8000/api/v1/index" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "test-section-chunking-001",
    "documents": [...],
    "ingestion": "document-intelligence"
  }'

# Option B: Use smoke test script (if available)
python scripts/smoke_test_lazy.py --group-id test-section-chunking-001
```

### Step 2.5: Verify Chunks in Neo4j

```cypher
-- Check chunk metadata has section info
MATCH (c:TextChunk {group_id: "test-section-chunking-001"})
RETURN 
    c.id,
    c.metadata.section_title,
    c.metadata.section_level,
    c.metadata.section_path_key,
    c.metadata.is_summary_section,
    c.metadata.chunk_strategy
LIMIT 20;

-- Count summary sections per document
MATCH (c:TextChunk {group_id: "test-section-chunking-001"})
WHERE c.metadata.is_summary_section = true
RETURN c.document_id, count(c) as summary_chunks;
```

---

## Phase 3: Retrieval Pipeline Integration

### Step 3.1: Code Change - Add Summary Chunk Retrieval Method

**File:** `app/hybrid/pipeline/enhanced_graph_retriever.py`

**Location:** After `get_coverage_chunks` method

**Add new method:**
```python
async def get_summary_chunks_by_section(
    self,
    max_per_document: int = 1,
) -> List[SourceChunk]:
    """Get summary section chunks for coverage-guaranteed queries.
    
    This method leverages section-aware chunking metadata to retrieve
    semantically appropriate chunks (Purpose, Introduction sections)
    instead of arbitrary first chunks.
    
    Requires: Documents indexed with USE_SECTION_CHUNKING=1
    """
    if not self.driver:
        return []
    
    query = """
    MATCH (d:Document)<-[:PART_OF]-(t:TextChunk)
    WHERE d.group_id = $group_id
      AND t.group_id = $group_id
      AND (
          t.metadata.is_summary_section = true
          OR t.chunk_index = 0
      )
    WITH d, t
    ORDER BY 
        CASE WHEN t.metadata.is_summary_section = true THEN 0 ELSE 1 END,
        t.chunk_index ASC
    WITH d, collect(t)[0..$max_per_document] AS chunks
    UNWIND chunks AS chunk
    RETURN
        chunk.id AS chunk_id,
        chunk.text AS text,
        chunk.metadata AS metadata,
        d.id AS doc_id,
        d.title AS doc_title,
        d.source AS doc_source
    """
    
    try:
        loop = asyncio.get_event_loop()
        
        def _run_query():
            with self.driver.session() as session:
                result = session.run(
                    query,
                    group_id=self.group_id,
                    max_per_document=max_per_document,
                )
                return list(result)
        
        records = await loop.run_in_executor(None, _run_query)
        
        chunks: List[SourceChunk] = []
        for record in records:
            metadata = {}
            raw_meta = record.get("metadata")
            if raw_meta:
                try:
                    metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                except Exception:
                    metadata = {}
            
            section_path = metadata.get("section_path", []) or []
            
            chunks.append(
                SourceChunk(
                    chunk_id=record.get("chunk_id") or "",
                    text=record.get("text") or "",
                    entity_name="summary_section_retrieval",
                    section_path=section_path,
                    section_id=metadata.get("section_id", ""),
                    document_id=record.get("doc_id") or "",
                    document_title=record.get("doc_title") or "",
                    document_source=record.get("doc_source") or "",
                    relevance_score=1.0,
                )
            )
        
        logger.info(
            "summary_section_chunks_retrieved",
            num_chunks=len(chunks),
            group_id=self.group_id,
        )
        return chunks
        
    except Exception as e:
        logger.error("summary_section_retrieval_failed", error=str(e))
        return []
```

### Step 3.2: Code Change - Update Coverage Retrieval in Orchestrator

**File:** `app/hybrid/orchestrator.py`

**Location:** Stage 3.4.1 coverage gap fill block (~line 3020)

**Modify the coverage retrieval to prefer summary sections:**

```python
# In the coverage_mode block, add fallback logic:

if coverage_mode:
    logger.info("stage_3.4.1_coverage_gap_fill_start")
    t0_cov = time.perf_counter()
    try:
        from .pipeline.enhanced_graph_retriever import SourceChunk
        
        # Try summary section retrieval first (requires section-aware indexing)
        coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(
            max_per_document=1,
        )
        
        # Fallback to position-based if no summary sections found
        if not coverage_chunks:
            logger.info("stage_3.4.1_fallback_to_position_based")
            coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(
                max_per_document=1,
                max_total=20,
            )
        
        # ... rest of gap fill logic
```

### Step 3.3: Add Feature Flag for Section-Based Retrieval

**File:** `app/hybrid/orchestrator.py`

**Location:** Near coverage_mode detection

```python
# Add at route start
use_section_retrieval = os.getenv("USE_SECTION_RETRIEVAL", "1").strip().lower() in {"1", "true", "yes"}

# In coverage block
if coverage_mode:
    if use_section_retrieval:
        coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(...)
    else:
        coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(...)
```

---

## Phase 4: End-to-End Testing

### Step 4.1: Re-Index Test Corpus

```bash
# Delete old test data
curl -X DELETE "http://localhost:8000/api/v1/groups/test-5pdfs-section-v2"

# Re-index with section chunking enabled
export USE_SECTION_CHUNKING=1
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=<password>

# Run indexing (adjust to your ingestion method)
python scripts/ingest_test_corpus.py \
  --group-id test-5pdfs-section-v2 \
  --documents /path/to/5-pdf-corpus/*.pdf \
  --ingestion document-intelligence
```

### Step 4.2: Run Route 3 Benchmark

```bash
# Run thematic benchmark against new corpus
python benchmark_route3_thematic.py \
  --group-id test-5pdfs-section-v2 \
  --output bench_section_chunking_thematic.json

# Run global search benchmark
python benchmark_route3_global_search.py \
  --group-id test-5pdfs-section-v2 \
  --output bench_section_chunking_global.json
```

### Step 4.3: Compare Results

Key metrics to compare:

| Metric | Fixed Chunking Baseline | Section Chunking |
|--------|------------------------|------------------|
| X-2 "each document" citations | 2/5 docs | ? |
| Average thematic score | 85% | ? |
| Coverage retrieval accuracy | ~60% | ? |
| Questions at 100% coverage | 6/10 | ? |

### Step 4.4: Verify Summary Section Quality

```bash
# Run verification script
python scripts/verify_summary_sections.py --group-id test-5pdfs-section-v2
```

**Verification script to create:**
```python
# scripts/verify_summary_sections.py
"""Verify that summary sections are correctly identified and useful."""

import asyncio
from neo4j import GraphDatabase

async def verify_summary_sections(group_id: str):
    driver = GraphDatabase.driver(...)
    
    with driver.session() as session:
        # Get summary sections
        result = session.run("""
            MATCH (c:TextChunk {group_id: $gid})
            WHERE c.metadata.is_summary_section = true
            RETURN 
                c.document_id,
                c.metadata.section_title,
                substring(c.text, 0, 200) as preview
            ORDER BY c.document_id
        """, gid=group_id)
        
        print("Summary Sections Found:")
        print("=" * 60)
        for record in result:
            print(f"Doc: {record['document_id']}")
            print(f"Section: {record['section_title']}")
            print(f"Preview: {record['preview']}...")
            print("-" * 60)

if __name__ == "__main__":
    import sys
    group_id = sys.argv[2] if len(sys.argv) > 2 else "test-5pdfs-section-v2"
    asyncio.run(verify_summary_sections(group_id))
```

---

## Phase 5: Production Rollout

### Step 5.1: Feature Flag Gradual Rollout

```bash
# Stage 1: Test environment only
# In test deployment:
export USE_SECTION_CHUNKING=1
export USE_SECTION_RETRIEVAL=1

# Stage 2: Canary deployment (10% traffic)
# Configure in Azure Container Apps or load balancer

# Stage 3: Full rollout
# Make section chunking the default
```

### Step 5.2: Monitoring & Metrics

Add logging to track:
- `chunk_strategy` distribution (section_aware_v2 vs fixed)
- `is_summary_section` hit rate in coverage retrieval
- Route 3 response quality (manual sampling)

### Step 5.3: Deprecation of Fixed Chunking

Once validated:
1. Make `USE_SECTION_CHUNKING=1` the default
2. Add deprecation warning for `USE_SECTION_CHUNKING=0`
3. Remove fixed chunking code path in next major version

---

## Code Changes Summary

| File | Change | Priority |
|------|--------|----------|
| `lazygraphrag_pipeline.py` | Add `USE_SECTION_CHUNKING` flag | P0 |
| `lazygraphrag_pipeline.py` | Add conditional in `_chunk_di_units` | P0 |
| `lazygraphrag_pipeline.py` | Add `_chunk_di_units_section_aware` method | P0 |
| `enhanced_graph_retriever.py` | Add `get_summary_chunks_by_section` method | P1 |
| `orchestrator.py` | Update Stage 3.4.1 to prefer summary sections | P1 |
| `orchestrator.py` | Add `USE_SECTION_RETRIEVAL` flag | P2 |

---

## Rollback Plan

If issues are discovered:

```bash
# Immediate rollback
export USE_SECTION_CHUNKING=0
export USE_SECTION_RETRIEVAL=0

# Restart services
az containerapp update --name graphrag-orchestration ...
```

No data migration needed - old chunks remain valid, new chunks just have richer metadata.

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Unit Testing | 1 hour | None |
| Phase 2: Indexing Integration | 2-3 hours | Phase 1 |
| Phase 3: Retrieval Integration | 2-3 hours | Phase 2 |
| Phase 4: E2E Testing | 2-4 hours | Phase 3 + test corpus |
| Phase 5: Production Rollout | 1-2 days | Phase 4 approval |

**Total estimated time:** 1-2 days for validation, 1 week for production rollout.
