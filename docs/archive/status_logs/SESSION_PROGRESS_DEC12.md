# GraphRAG V3 Invoice Verification Test - Session Progress

**Date:** December 12, 2025  
**Session Goal:** Test GraphRAG V3 with 5 real PDF documents for invoice/contract verification using DRIFT query

---

## ✅ Completed Today

### 1. Neo4j Vector Index Fix
- **Issue:** Vector index referenced wrong label (`__Entity__`) and wrong dimensions (1536 for ada-002 instead of 3072 for text-embedding-3-large)
- **Fix Applied:**
  - Updated `create_neo4j_indexes.py` to use `Entity` label (correct for V3 data model)
  - Changed dimensions from 1536 → 3072
  - Index created and verified ONLINE with 100% population
  - File: `services/graphrag-orchestration/create_neo4j_indexes.py` and `graphrag-orchestration/create_neo4j_indexes.py`

### 2. Embedder Wrapper Methods
- **Issue:** `GraphRAGEmbeddingWrapper` missing `get_text_embedding()` method causing AttributeError
- **Fix Applied:**
  - Added `get_text_embedding()` method to pass through to LlamaIndex embedder
  - Added `embed_query()` method for MS GraphRAG compatibility
  - File: `graphrag-orchestration/app/v3/services/drift_adapter.py` lines 26-45

### 3. None Embedder Safety Checks
- **Issue:** Embedder could be None when Azure OpenAI not configured, causing NoneType errors
- **Fix Applied:**
  - Added conditional wrapper: `self.embedder = GraphRAGEmbeddingWrapper(embedder) if embedder else None`
  - Added explicit error message in fallback search when embedder is None
  - File: `graphrag-orchestration/app/v3/services/drift_adapter.py` lines 77, 447

### 4. DRIFT API Key Fallback
- **Issue:** MS GraphRAG DRIFT requires API key authentication, fails with Azure managed identity
- **Fix Applied:**
  - Added check for `settings.AZURE_OPENAI_API_KEY` before initializing DRIFT
  - Falls back to basic vector search when API key unavailable
  - File: `graphrag-orchestration/app/v3/services/drift_adapter.py` lines 372-385

### 5. Docker Build Optimization
- **Issue:** `.venv` directory being copied to container causing "no space left on device" errors
- **Fix Applied:**
  - Created `.dockerignore` file excluding `.venv/`, `__pycache__/`, `.env`, etc.
  - File: `graphrag-orchestration/.dockerignore`

### 6. Deployment Success
- **Full rebuild completed:** 4 minutes 15 seconds (after clearing build cache)
- **Endpoint:** `https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/`
- **Status:** Deployed and healthy (health check returns 200)

---

## ❌ Remaining Issues

### 1. **CRITICAL: Entities Missing Embeddings**
**Problem:**
- Neo4j contains 10,867 entities for group `invoice-verification-test-v3`
- **ZERO entities have embeddings** (verified: `MATCH (e:Entity {group_id: "..."}) WHERE e.embedding IS NOT NULL RETURN count(e)` returns 0)
- Vector index exists and is ONLINE but has nothing to search

**Root Cause:**
- V3 indexing pipeline code has embedding logic: `entity.embedding = await self._embed_text(desc_text)` (line 840 of `indexing_pipeline.py`)
- Background indexing job either:
  - Failed silently during embedding computation
  - Skipped embedding step due to missing configuration
  - Computed embeddings but didn't save them to Neo4j

**Impact:**
- Vector search returns 0 results
- DRIFT search fails: `"There is no such vector schema index: entity_embedding"` (because index has no vectors)
- Query endpoint returns 500 errors

**Next Steps:**
1. Check indexing logs to see if embeddings were attempted
2. Verify embedder is initialized during indexing (not just querying)
3. Re-run indexing with proper logging to track embedding computation
4. Confirm embeddings are saved to Neo4j: `CREATE (e:Entity) SET e.embedding = $embedding`

### 2. **Deployed API Missing Azure OpenAI Configuration**
**Problem:**
- Container App environment variables not set
- `llm_service.py` initialization returns early when `settings.AZURE_OPENAI_ENDPOINT` is None
- Results in `self._embed_model = None`

**Required Environment Variables:**
```bash
AZURE_OPENAI_ENDPOINT=https://your-openai-instance.openai.azure.com/
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-10-21
# Either:
AZURE_OPENAI_API_KEY=sk-...
# Or managed identity (requires additional setup)
```

**Impact:**
- All queries fail with: `'NoneType' object has no attribute 'embed_query'`
- Cannot test deployed API until configured

**Next Steps:**
1. Add environment variables to Container App via Azure Portal or CLI
2. Restart container app after adding variables
3. Verify initialization: Check logs for "Embedding model initialized successfully"

### 3. **Two Separate Neo4j Instances**
**Problem:**
- Local development uses: `a86dcf63.databases.neo4j.io` (from `.env` file)
- Deployed API uses: `neo4j-graphrag-23987.swedencentral.azurecontainer.io` (from Container App config)
- Fixes applied to local Neo4j, but deployed API can't access it

**Impact:**
- Cannot test deployed API against local data
- Stats show different data: Local has ~8400 entities, deployed has 10,867

**Decision Needed:**
- Either test locally (requires local API server) OR configure deployed API properly
- Current approach: Fix code for both, deploy, configure environment for deployed

---

## 📋 TODO List for Tomorrow

### High Priority
- [ ] **Debug why entities don't have embeddings**
  - [ ] Check `indexing_pipeline.py` line 840 - is `_embed_text()` being called?
  - [ ] Add logging to track embedding computation: `logger.info(f"Generated {len(embedding)} dim embedding for {entity.name}")`
  - [ ] Verify Neo4j write: Check if `store.save_entity()` includes embedding field
  - [ ] Test with single entity: Manually create entity with embedding and verify vector search works

- [ ] **Configure Azure Container App environment variables**
  - [ ] Get Azure OpenAI credentials from Azure Portal
  - [ ] Run: `az containerapp update --name graphrag-orchestration --resource-group rg-graphrag-feature --set-env-vars ...`
  - [ ] Restart container and verify health check shows embedder initialized
  - [ ] Test query endpoint

- [ ] **Re-run indexing with embedding verification**
  - [ ] Clear old group data: `MATCH (n {group_id: "invoice-verification-test-v3"}) DETACH DELETE n`
  - [ ] Run test with verbose logging
  - [ ] Verify embeddings are saved: Check entity count with embeddings after indexing
  - [ ] Test vector search: `CALL db.index.vector.queryNodes('entity_embedding', 5, $test_embedding)`

### Medium Priority
- [ ] **Test complete invoice verification flow**
  - [ ] Verify extraction: Check that all 5 PDFs were processed
  - [ ] Verify entities: Should have company names, dates, amounts from documents
  - [ ] Run DRIFT query: "What companies are mentioned in the documents?"
  - [ ] Run DRIFT query: "Find any discrepancies between invoices and contracts"
  - [ ] Validate results against actual PDF content

- [ ] **Fix dimension mismatch if needed**
  - [ ] Verify embedder is using 3072 dimensions: Check `settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS`
  - [ ] Verify entities have 3072-dim embeddings: `RETURN size(e.embedding)`
  - [ ] If mismatch, drop and recreate index with correct dimensions

### Low Priority
- [ ] **Improve error messages**
  - [ ] Add clear error when embedder is None: "Please configure AZURE_OPENAI_ENDPOINT"
  - [ ] Add clear error when entities lack embeddings: "Please re-run indexing"
  - [ ] Add validation in indexing endpoint to check embedder is initialized

- [ ] **Documentation**
  - [ ] Document the two-step flow: indexing (compute embeddings) → querying (search embeddings)
  - [ ] Add troubleshooting guide for common errors
  - [ ] Create example query payloads for testing

- [ ] **Optimization**
  - [ ] Consider batch embedding during indexing (current: one-by-one)
  - [ ] Add embedding progress tracking in stats endpoint
  - [ ] Cache embeddings to avoid recomputation

---

## 🔍 Investigation Notes

### Test Environment
- **Group ID:** `invoice-verification-test-v3`
- **Documents:** 5 PDFs (BUILDERS WARRANTY, purchase contract, tank servicing, property management, invoice)
- **Schema:** `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json`
- **Local Neo4j:** `a86dcf63.databases.neo4j.io`
- **Deployed Neo4j:** `neo4j-graphrag-23987.swedencentral.azurecontainer.io`

### Code Locations
- Vector index creation: `create_neo4j_indexes.py`
- Embedder wrapper: `app/v3/services/drift_adapter.py` class `GraphRAGEmbeddingWrapper`
- Embedding computation: `app/v3/services/indexing_pipeline.py` line 840
- Entity storage: `app/v3/services/neo4j_store.py` `save_entity()` method
- Query logic: `app/v3/routers/graphrag_v3.py` `/query/local` endpoint

### Useful Commands
```bash
# Check entity embeddings
python3 -c "from dotenv import load_dotenv; from neo4j import GraphDatabase; import os; load_dotenv(); driver = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD'))); session = driver.session(); result = session.run('MATCH (e:Entity {group_id: \"invoice-verification-test-v3\"}) WHERE e.embedding IS NOT NULL RETURN count(e)'); print(f'Entities with embeddings: {result.single()[0]}'); driver.close()"

# Test vector index
python3 -c "from dotenv import load_dotenv; from neo4j import GraphDatabase; import os; load_dotenv(); driver = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD'))); session = driver.session(); result = session.run('CALL db.index.vector.queryNodes(\"entity_embedding\", 5, [0.01] * 3072) YIELD node, score RETURN node.name, score LIMIT 5'); [print(f\"{r['node.name']}: {r['score']}\") for r in result]; driver.close()"

# Check deployed API stats
curl -H "X-Group-ID: invoice-verification-test-v3" https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/graphrag/v3/stats/invoice-verification-test-v3

# Re-run indexing
cd /afh/projects/graphrag-orchestration/graphrag-orchestration && python3 test_invoice_verification.py
```

---

## 📊 Current State

### Code Quality: ✅ READY
- All fixes implemented and tested locally
- Deployed successfully (4m15s full rebuild)
- No syntax errors or import errors
- Safety checks in place for None values

### Data Quality: ❌ BLOCKED
- Entities exist (10,867) but missing embeddings
- Vector index exists but empty
- Cannot test queries until embeddings are computed

### Deployment: ⚠️ PARTIAL
- API deployed and healthy
- Missing Azure OpenAI environment variables
- Cannot process requests until configured

### Next Session Focus
**Primary Goal:** Get entities to have embeddings so vector search works
**Secondary Goal:** Configure deployed API with Azure OpenAI credentials
**Success Criteria:** Query returns relevant companies from the 5 PDFs

---

## 📝 Session Summary

**Time Spent:** ~2 hours of troubleshooting and fixes  
**Deployments:** 6 attempts (5 with cache, 1 full rebuild)  
**Lines Changed:** ~50 lines across 4 files  
**Tests Run:** 15+ manual tests of vector index, embeddings, queries

**Key Learning:** Neo4j vector index configuration is separate from entity data - index can be ONLINE with 0 vectors if entities lack embeddings. The two-step process (index creation + data population) must both succeed for vector search to work.

**Status:** Code is fixed and ready. Data needs to be reindexed with proper embedding computation.
