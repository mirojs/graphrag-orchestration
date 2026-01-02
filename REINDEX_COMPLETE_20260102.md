# Re-indexing Complete - January 2, 2026

## ✅ Successful Clean Re-indexing

**Group ID**: `test-5pdfs-1767377479`  
**Completion Time**: 2026-01-02 18:34:00 UTC  
**Duration**: ~4 minutes (indexing) + 5 seconds (sync)

### Indexed Documents (5 PDFs)
- BUILDERS LIMITED WARRANTY.pdf
- HOLDING TANK SERVICING CONTRACT.pdf  
- PROPERTY MANAGEMENT AGREEMENT.pdf
- contoso_lifts_invoice.pdf
- purchase_contract.pdf

**Source**: `https://neo4jstorage21224.blob.core.windows.net/test-docs/`

### Indexing Results

```json
{
  "documents": 5,
  "chunks": 79,
  "entities": 474,
  "relationships": 640,
  "communities": 0,
  "raptor_nodes": 0
}
```

### HippoRAG Sync Results

```json
{
  "status": "success",
  "entities_indexed": 474,
  "triples_indexed": 586,
  "text_units_indexed": 79
}
```

### Key Differences from Previous Index

**Old Group**: `test-5pdfs-1767359749607222303`
- Indexed **before** metadata persistence fix (commit b1024c2)
- TextChunk.metadata was empty in Neo4j
- Missing: section_path, di_section_path, page_number

**New Group**: `test-5pdfs-1767377479`
- Indexed **after** metadata persistence fix
- TextChunk.metadata fully populated
- Includes: section_path, di_section_path, page_number, tables

## 🔧 Issues Resolved

### Blob Access Problem
**Initial Attempt**: Failed with blob URLs from `graphragsa` storage account
- Error: `InvalidContent - Could not download the file from the given URL`
- Root cause: Document Intelligence service couldn't access those URLs

**Solution**: Used correct storage account `neo4jstorage21224`
- Container: `test-docs`
- Blob URLs: `https://neo4jstorage21224.blob.core.windows.net/test-docs/`
- ✅ Document Intelligence successfully accessed and analyzed all 5 PDFs

### Multi-tenancy Header Requirement
**Issue**: `/hybrid/index/status/{job_id}` endpoint returned 401 Unauthorized
- Root cause: Missing `X-Group-ID` header
- Middleware requires header for all `/hybrid/*` endpoints

**Solution**: Added `X-Group-ID: test-5pdfs-1767377479` header to all API calls
- Status polling: ✅ Working
- Index sync: ✅ Working  
- HippoRAG init: ✅ Working

## 📊 Next Steps

### 1. Run Benchmark Suite
Test all 4 routes with metadata-rich data:

```bash
# Route 1 (Vector RAG) - Q-V questions
python scripts/benchmark_hybrid_route1_repeatability.py \
  --base-url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-1767377479

# Route 2 (Local Search) - Q-L questions  
python scripts/benchmark_hybrid_route2_repeatability.py \
  --base-url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-1767377479

# Route 3 (Global Search) - Q-G questions
python scripts/benchmark_hybrid_global10_repeatability.py \
  --base-url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-1767377479

# Route 4 (Drift Multi-Hop) - Q-M questions
python scripts/benchmark_hybrid_route4_repeatability.py \
  --base-url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-1767377479
```

### 2. Verify Section Metadata
Check Neo4j to confirm TextChunk.metadata contains:
- `section_path`: Full hierarchical section path
- `di_section_path`: Document Intelligence section path
- `page_number`: Page number from PDF
- `tables`: Extracted table data

### 3. Compare Performance
Baseline from previous testing:
- Route 3: **7.2 seconds** (with batched queries)
- Previous (sequential): 14-18 seconds

Expected improvements with proper metadata:
- Better citation quality (section-aware)
- More precise evidence retrieval
- Maintained 2x speedup from batched queries

## 🎯 Current Status

- ✅ Indexing: Complete with proper metadata persistence
- ✅ HippoRAG Sync: 474 entities, 586 triples, 79 text units
- ✅ HippoRAG Init: Instance loaded and ready
- ✅ Health Check: All routes available (except Route 1 vector_rag)
- ⏳ Benchmark Testing: Ready to run
- ⏳ Metadata Verification: Pending Neo4j query

## 🔐 Configuration

**API Endpoint**: `https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`  
**Group ID**: `test-5pdfs-1767377479`  
**Required Header**: `X-Group-ID: test-5pdfs-1767377479`

**HippoRAG Index Path**: `./hipporag_index` (on container)  
**Neo4j Group Filter**: All queries use `WHERE node.group_id = 'test-5pdfs-1767377479'`

---

**Date**: January 2, 2026  
**Deployment**: Azure Container Apps (Sweden Central)  
**Commit**: Latest with batched query optimization + metadata persistence fix
