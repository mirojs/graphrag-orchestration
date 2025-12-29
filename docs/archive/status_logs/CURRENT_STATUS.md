# Current Status - GraphRAG 3072-Dimension Upgrade

**Date**: December 18, 2025  
**Status**: Deployment successful, admin endpoint needs one more deployment cycle

## Overview
Upgraded entire GraphRAG system from 1536-dimension embeddings (text-embedding-3-small) to 3072-dimension embeddings (text-embedding-3-large) to improve search quality, especially for RAPTOR.

## Completed Work ✅

1. **System Upgrade**
   - Switched from text-embedding-3-small (1536 dims) → text-embedding-3-large (3072 dims)
   - Updated all vector indexes to 3072 dimensions:
     - `entity_embedding`
     - `raptor_embedding` 
     - `chunk_embedding`
   - Resource group corrected: `rg-graphrag-feature`
   - Container registry: `graphragacr12153`

2. **Code Fixes**
   - Fixed DRIFT sources format: `List[str]` → `List[Dict[str, Any]]`
   - Created admin cleanup endpoint: `POST /admin/cleanup-raptor`
   - Updated middleware to allow `/admin` paths
   - Commented out auto-drop index logic to prevent timeouts

3. **Deployment**
   - Current revision: **graphrag-orchestration--0000039**
   - Service is healthy and running
   - URL: https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io
   - Deployment method: `deploy-graphrag.sh` (reliable Docker build/push)

## Current Issue ⚠️

**Admin endpoint needs Neo4j credentials fix:**
- File: `graphrag-orchestration/app/v3/routers/admin.py`
- Issue: Neo4jStoreV3 initialization was missing environment variable configuration
- Fix applied locally (lines 28-52): Added proper env var reading for Neo4j credentials
- **Next step**: Run one more deployment to apply this fix

## What Remains

### 1. Deploy Admin Endpoint Fix
```bash
cd /afh/projects/graphrag-orchestration
export CONTAINER_REGISTRY_NAME=graphragacr12153
./deploy-graphrag.sh
```

### 2. Clean Up Old RAPTOR Data
After deployment completes:
```bash
./cleanup_raptor.sh
```
Expected result:
```json
{
  "group_id": "test-3072-fresh",
  "nodes_deleted": 14,
  "index_dropped": true,
  "index_created": true
}
```

### 3. Re-index with 3072-dim Embeddings
```bash
python test_managed_identity_pdfs.py
```
This will:
- Process 5 PDFs from Azure Blob Storage
- Create ~348 entities with 3072-dim embeddings
- Generate ~14 RAPTOR nodes with 3072-dim embeddings
- Store everything in Neo4j with group_id="test-3072-fresh"

### 4. Run Comprehensive Test
```bash
python tests/test_search_methods_comparison.py
```
Expected results (all 4 methods should work):
- **LOCAL**: Entity-focused search ✅
- **GLOBAL**: Community summaries (already working at 0.85 confidence) ✅
- **DRIFT**: Multi-step reasoning with fixed sources format ✅
- **RAPTOR**: Hierarchical abstractions with matching 3072-dim embeddings ⚠️ (needs cleanup first)

## Files Modified

### Key Changes
1. **app/v3/routers/admin.py** (lines 1-52)
   - Added `import os`
   - Fixed Neo4jStoreV3 initialization with env vars:
     ```python
     neo4j_uri = os.getenv("NEO4J_URI")
     neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
     neo4j_password = os.getenv("NEO4J_PASSWORD")
     neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
     
     store = Neo4jStoreV3(
         uri=neo4j_uri,
         username=neo4j_username,
         password=neo4j_password,
         database=neo4j_database
     )
     ```

2. **app/v3/services/drift_adapter.py** (lines 540-620)
   - Fixed sources response format for validation

3. **app/v3/services/neo4j_store.py** (lines 165-220)
   - Vector indexes configured for 3072 dims
   - Auto-drop logic commented out

4. **app/middleware/group_isolation.py** (line 15)
   - Added `/admin` to skip_paths

5. **cleanup_raptor.sh**
   - Added `X-Group-ID` header for multi-tenancy

## Technical Context

### Neo4j Support
- Neo4j 5.x supports up to **4096 dimensions** (verified via GitHub issue)
- Current setup: 3072 dimensions
- Vector similarity: cosine

### Search Methods Status
| Method | Status | Notes |
|--------|--------|-------|
| LOCAL | ✅ Ready | Entity-focused with 3072-dim embeddings |
| GLOBAL | ✅ Working | 0.85 confidence confirmed |
| DRIFT | ✅ Ready | Sources format fixed |
| RAPTOR | ⚠️ Blocked | Old 1536-dim nodes need cleanup |

### Azure Resources
- **Resource Group**: rg-graphrag-feature
- **Container App**: graphrag-orchestration
- **Container Registry**: graphragacr12153
- **Location**: swedencentral
- **Current Revision**: 0000039
- **Neo4j**: neo4j-graphrag-23987.swedencentral.azurecontainer.io

## Next Session Commands

```bash
# 1. Deploy admin endpoint fix
cd /afh/projects/graphrag-orchestration
export CONTAINER_REGISTRY_NAME=graphragacr12153
./deploy-graphrag.sh

# 2. Wait for deployment (2-3 minutes), then cleanup
./cleanup_raptor.sh

# 3. Re-index with fresh data
python test_managed_identity_pdfs.py

# 4. Run comparison test
python tests/test_search_methods_comparison.py
```

## Notes

- Original goal: Fix all 4 search methods (LOCAL, GLOBAL, DRIFT, RAPTOR)
- Evolved into: Full system upgrade to 3072-dimension embeddings
- Key insight: Neo4j 5.x supports much higher dimensions than initially assumed
- Deployment strategy: Docker build/push via deploy-graphrag.sh is more reliable than `az containerapp up`
- Data contamination: Mixed 1536 and 3072 dim data requires cleanup + re-indexing
