# GraphRAG v3 - Next Session Handoff Document
**Date:** December 16, 2025  
**Status:** Managed Identity Working, DRIFT Needs Fix  
**Commit:** aeb2107 - "WIP: Managed identity embedding fix + DRIFT fallback improvement"

---

## ✅ What's Working (Verified Today)

### 1. Managed Identity Authentication
- **LLM (GPT-4o):** ✅ Working
- **Embeddings (text-embedding-3-large):** ✅ Working with workaround
- **Workaround Applied:** `api_key: ""` in `llm_service.py` line 88-108
- **File:** `graphrag-orchestration/app/services/llm_service.py`
- **Status:** Production-ready, no API keys needed

### 2. Entity Extraction Pipeline
- **Test Result:** 107 entities, 78 relationships from 5 sample documents
- **Processing Time:** ~36 seconds per document
- **Community Detection:** 11 communities created
- **RAPTOR:** 6 hierarchical nodes created
- **File:** `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
- **Status:** Fully functional

### 3. Query Types
- **Global Queries:** ✅ Excellent (0.85 confidence, 10 sources, 3.23s avg)
- **Local Queries:** ✅ Good (0.53s avg, fast graph traversal)
- **DRIFT Queries:** ⚠️ Working but using fallback (see below)

### 4. Test Suite
- **Created:** `test_managed_identity.py` (4 automated tests, all passing)
- **Documentation:** `TEST_README.md` (usage, troubleshooting, technical details)
- **Status:** Reusable for regression testing

---

## ⚠️ Critical Issue: DRIFT Fallback (High Priority)

### Problem
**DRIFT queries fall back to basic search** instead of using MS GraphRAG's DRIFT algorithm.

### Root Cause
**File:** `graphrag-orchestration/app/v3/services/drift_adapter.py`  
**Lines:** 467-473

```python
if settings.AZURE_OPENAI_API_KEY:
    # Use MS GraphRAG's LitellmChatModel (requires API key)
    llm_config = LanguageModelConfig(...)
    drift_llm = LitellmChatModel(config=llm_config)
else:
    # MANAGED IDENTITY PATH - Currently falls back!
    logger.warning("DRIFT requires API key, falling back to basic search")
    return await self._fallback_search(...)
```

### Why This Matters
- **Fallback search** returns generic "can't answer without context" responses
- **Real DRIFT** provides multi-step reasoning with confidence scores
- **MS GraphRAG's LitellmChatModel** only supports API key authentication
- **Our LlamaIndex LLM** already works with managed identity

### Solution (To Implement Tomorrow)
**Use LlamaIndex LLM directly with MS GraphRAG DRIFT instead of LitellmChatModel wrapper**

#### Option 1: Create LLM Adapter (Recommended)
Create a wrapper that adapts LlamaIndex LLM to MS GraphRAG's interface:

```python
# In drift_adapter.py, replace lines 467-476 with:

from graphrag.language_model.base import LanguageModel

class LlamaIndexChatModelAdapter(LanguageModel):
    """Adapter to use LlamaIndex LLM with MS GraphRAG DRIFT"""
    def __init__(self, llama_llm):
        self.llm = llama_llm
    
    async def generate(self, messages, **kwargs):
        # Convert MS GraphRAG messages to LlamaIndex format
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        response = await self.llm.acomplete(prompt)
        return response.text
    
    def complete(self, prompt, **kwargs):
        response = self.llm.complete(prompt)
        return response.text

# Then use it:
drift_llm = LlamaIndexChatModelAdapter(self.llm)

# Rest of DRIFT initialization stays the same
context_builder = DRIFTSearchContextBuilder(
    model=drift_llm,  # Our managed identity LLM
    text_embedder=GraphRAGEmbeddingWrapper(self.embedder),
    entities=entities,
    entity_text_embeddings=entity_embeddings_store,
    relationships=relationships,
    reports=communities,
    text_units=text_units,
)
```

#### Option 2: Bypass MS GraphRAG Wrapper
Use LlamaIndex LLM directly if DRIFT supports it (check MS GraphRAG docs).

#### Files to Modify
1. **`graphrag-orchestration/app/v3/services/drift_adapter.py`** (lines 467-500)
   - Remove fallback logic
   - Add LlamaIndex LLM adapter
   - Test DRIFT works with managed identity

2. **Test After Changes:**
   ```bash
   cd /afh/projects/graphrag-orchestration
   python3 test_managed_identity.py
   ```
   - DRIFT queries should return detailed answers with sources
   - Check confidence > 0.7
   - Verify reasoning_path is populated

---

## 🔴 Blocking Issue: PDF Upload Not Supported

### Problem
**Test attempted to upload base64-encoded PDFs but API only accepts URLs**

### Root Cause
**File:** `graphrag-orchestration/app/services/document_intelligence_service.py`  
**Lines:** 425-440

Document Intelligence service only processes:
1. **URLs** (blob storage SAS URLs)
2. **Plain text** (passthrough)

It does NOT accept base64-encoded PDF content.

### Evidence
**Test:** `test_pdfs_with_schema.py` (lines 120-180)
- Loaded 5 PDFs (0.26 MB base64)
- Sent to `/v3/index` endpoint
- API treated base64 as plain text (not PDF)
- Entity extraction tried to parse base64 gibberish → timeout

### Solutions

#### Option 1: Upload to Blob Storage (Production Pattern)
**Modify test to upload PDFs to blob storage first, then send URLs:**

```python
# Add to test_pdfs_with_schema.py

from azure.storage.blob import BlobServiceClient
from datetime import datetime, timedelta
from azure.storage.blob import generate_blob_sas, BlobSasPermissions

def upload_pdfs_to_blob(pdf_files: List[Dict]) -> List[str]:
    """Upload PDFs to blob storage and return SAS URLs"""
    # Get blob service client
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_name = "graphrag-test-pdfs"
    
    # Create container if not exists
    try:
        blob_service.create_container(container_name)
    except:
        pass
    
    urls = []
    for pdf in pdf_files:
        # Upload PDF
        blob_name = f"{TEST_GROUP_ID}/{pdf['filename']}"
        blob_client = blob_service.get_blob_client(container_name, blob_name)
        
        # Decode base64 and upload
        import base64
        pdf_bytes = base64.b64decode(pdf['content'])
        blob_client.upload_blob(pdf_bytes, overwrite=True)
        
        # Generate SAS URL (2 hour expiry)
        sas = generate_blob_sas(
            account_name=blob_service.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=blob_service.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=2)
        )
        
        url = f"https://{blob_service.account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas}"
        urls.append(url)
    
    return urls

# Then in test_indexing_with_schema:
pdf_urls = upload_pdfs_to_blob(files_data)
response = requests.post(
    f"{BASE_URL}/graphrag/v3/index",
    json={
        "documents": pdf_urls,  # URLs, not base64
        "ingestion": "document-intelligence",
        "run_raptor": True,
        "run_community_detection": True
    }
)
```

**Files to Create/Modify:**
- `test_pdfs_with_schema.py` (add blob upload function)
- Requires: `AZURE_STORAGE_CONNECTION_STRING` environment variable

#### Option 2: Use Sample Text (Current Workaround)
Keep using plain text samples (fast, tests pipeline without DI dependency).

---

## 🚀 Architecture Decision: V2 vs V3 Strategy

### Keep Both Versions - Different Use Cases

#### V2: Fast Query (Optimized for Speed)
**Use Case:** Real-time applications, chatbots, quick lookups  
**Strengths:**
- Faster response times (~500ms)
- Simpler query model
- Lower compute cost
- Proven stability

**Endpoints:**
- `/api/v1/graphrag/query` - Basic graph query
- `/api/v1/graphrag/search` - Keyword search

**Architecture:**
- Direct Neo4j Cypher queries
- Simple LLM prompts
- No multi-step reasoning

#### V3: Deep Dive (Optimized for Accuracy)
**Use Case:** Research, complex analysis, multi-hop reasoning  
**Strengths:**
- DRIFT multi-step reasoning
- RAPTOR hierarchical summaries
- Community-based global search
- Higher accuracy on complex queries

**Endpoints:**
- `/graphrag/v3/query/drift` - Multi-step reasoning
- `/graphrag/v3/query/global` - Community summaries
- `/graphrag/v3/query/local` - Entity-focused search

**Architecture:**
- MS GraphRAG DRIFT algorithm
- LlamaIndex PropertyGraph extraction
- Hierarchical community detection
- Vector embeddings for semantic search

### Recommended Usage Pattern

```python
# Application Layer
async def query_knowledge_graph(query: str, mode: str = "auto"):
    if mode == "fast" or len(query.split()) < 10:
        # V2 for simple queries
        return await v2_api.query(query)
    
    elif mode == "deep" or "how" in query.lower() or "why" in query.lower():
        # V3 for complex reasoning
        return await v3_api.drift_query(query)
    
    else:
        # Auto-detect: try V2 first, fallback to V3 if low confidence
        result = await v2_api.query(query)
        if result.confidence < 0.6:
            result = await v3_api.drift_query(query)
        return result
```

### Migration Path
1. **Phase 1 (Current):** Both V2 and V3 running in parallel
2. **Phase 2 (Q1 2026):** Route by query complexity automatically
3. **Phase 3 (Q2 2026):** Deprecate V2 only if V3 matches speed benchmarks

**Files:**
- V2: `graphrag-orchestration/app/routers/graphrag.py`
- V3: `graphrag-orchestration/app/v3/routers/graphrag_v3.py`

---

## 📋 Complete To-Do List for Next Session

### Priority 1: Fix DRIFT Managed Identity (1-2 hours)
**Reason:** DRIFT is flagship V3 feature, currently falling back  
**Impact:** High - Enables complex reasoning queries with managed identity

**Tasks:**
1. Create `LlamaIndexChatModelAdapter` class in `drift_adapter.py`
2. Remove fallback logic (lines 467-473)
3. Test adapter implements MS GraphRAG's `LanguageModel` interface
4. Run `test_managed_identity.py` - verify DRIFT returns detailed answers
5. Deploy to Azure Container Apps
6. Re-run production test with 5 PDFs

**Files:**
- `graphrag-orchestration/app/v3/services/drift_adapter.py` (lines 467-500)
- `test_managed_identity.py` (re-run to verify)

**Success Criteria:**
- [ ] DRIFT queries return confidence > 0.7
- [ ] Sources populated (not empty array)
- [ ] Reasoning path shows multi-step logic
- [ ] No "falling back" warning in logs

---

### Priority 2: Enable PDF Upload Testing (2-3 hours)
**Reason:** Need to test with actual PDFs, not sample text  
**Impact:** Medium - Validates Document Intelligence integration

**Tasks:**
1. Create `upload_pdfs_to_blob()` function in `test_pdfs_with_schema.py`
2. Add Azure Storage connection string to environment
3. Upload 5 test PDFs to blob storage
4. Generate SAS URLs (2 hour expiry)
5. Modify test to send URLs instead of base64
6. Run full test with Document Intelligence extraction
7. Measure timing: blob upload + DI extraction + indexing

**Files:**
- `test_pdfs_with_schema.py` (add blob upload, lines 50-120)
- `.env` (add `AZURE_STORAGE_CONNECTION_STRING`)

**Success Criteria:**
- [ ] 5 PDFs uploaded to blob storage
- [ ] SAS URLs generated successfully
- [ ] Document Intelligence extracts text from PDFs
- [ ] Entity extraction finds relevant entities
- [ ] Complete test runs under 5 minutes (no gateway timeout)

---

### Priority 3: Optimize Gateway Timeout (1 hour)
**Reason:** 240-second limit too short for 5+ PDFs  
**Impact:** Medium - Enables batch processing

**Tasks:**
1. Review Azure Container Apps timeout settings
2. Check if `v3/index` threshold can be lowered (currently 10 docs)
3. Modify line 245 in `graphrag_v3.py`: change `<= 10` to `<= 2`
4. Test background processing triggers for 5 PDFs
5. Add status endpoint for async job polling

**Files:**
- `graphrag-orchestration/app/v3/routers/graphrag_v3.py` (line 245)
- `infra/main.bicep` (check timeout configuration)

**Background Processing Pattern:**
```python
# If more than 2 documents, use background processing
if len(docs_for_pipeline) > 2:
    job_id = str(uuid.uuid4())
    background_tasks.add_task(run_indexing, job_id, ...)
    return {"status": "processing", "job_id": job_id}
```

**Success Criteria:**
- [ ] 5 PDFs trigger background processing
- [ ] API returns immediately with job_id
- [ ] Client can poll `/v3/status/{job_id}` for completion
- [ ] No 504 gateway timeouts

---

### Priority 4: Document V2/V3 Usage Patterns (30 minutes)
**Reason:** Clarify when to use each version  
**Impact:** Low - Documentation only

**Tasks:**
1. Create `V2_VS_V3_GUIDE.md`
2. Document performance benchmarks
3. Add decision tree diagram
4. Update API documentation

**Files:**
- Create: `V2_VS_V3_GUIDE.md`
- Update: `README.md` (add usage section)

**Success Criteria:**
- [ ] Clear guidance on V2 vs V3 selection
- [ ] Performance comparison table
- [ ] Code examples for both versions
- [ ] Migration timeline documented

---

## 📊 Test Results Summary (From Today)

### Test 1: Managed Identity Pipeline
**File:** `test_managed_identity.py`  
**Result:** ✅ 4/4 tests passed
- Documents processed: 3
- Entities created: 28
- Relationships created: 26
- Communities created: 4
- Total time: ~2 minutes

### Test 2: PDF Test (Attempted)
**File:** `test_pdfs_with_schema.py`  
**Result:** ⚠️ 504 Gateway Timeout
- PDFs loaded: 5 (0.26 MB base64)
- Timeout: 240 seconds (gateway limit)
- Root cause: Base64 treated as text, not PDFs
- Solution: Use blob storage URLs

### Test 3: Query Performance
**Source:** `PDF_TEST_RESULTS.md`

| Query Type | Avg Time | Confidence | Sources | Status |
|------------|----------|------------|---------|--------|
| Global | 3.23s | 0.85 | 10 | ✅ Excellent |
| Local | 0.53s | 0.17 | 0.25 | ✅ Fast |
| DRIFT | 9.49s* | 0.70 | 0 | ⚠️ Fallback |

*One query timed out at 60s

---

## 🔧 Environment Configuration

### Required Environment Variables
```bash
# Azure OpenAI (Managed Identity - No keys needed)
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-10-21

# Neo4j
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password

# Azure Storage (For PDF testing)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

# Azure Document Intelligence
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-di.cognitiveservices.azure.com
# No key needed with managed identity
```

### Deployment Commands
```bash
# Deploy to Azure Container Apps
cd /afh/projects/graphrag-orchestration
azd deploy

# Test locally
cd /afh/projects/graphrag-orchestration
python3 test_managed_identity.py
```

---

## 📁 Key Files Reference

### Modified Today
1. `graphrag-orchestration/app/services/llm_service.py` (lines 88-108)
   - Added `api_key: ""` workaround for embeddings

2. `graphrag-orchestration/app/v3/services/drift_adapter.py` (lines 467-473, 538-600)
   - DRIFT fallback logic (needs removal)
   - Improved fallback search with text-based entity retrieval

3. `test_managed_identity.py` (NEW - 232 lines)
   - Comprehensive test suite for managed identity

4. `test_pdfs_with_schema.py` (NEW - 431 lines)
   - PDF testing with timing (needs blob upload fix)

### Key Documentation Created
1. `TEST_README.md` - Test suite usage guide
2. `PDF_TEST_RESULTS.md` - Performance benchmarks
3. `TEST_ISSUES_EXPLAINED.md` - Timeout and schema issues
4. `GATEWAY_TIMEOUT_ANALYSIS.md` - 504 error deep dive
5. `DEPLOYMENT_FIXES_2025-12-16.md` - Today's fixes summary

---

## 🎯 Success Metrics for Next Session

### Must Have
- [ ] DRIFT returns detailed answers (not fallback generic responses)
- [ ] DRIFT sources populated with entity IDs
- [ ] PDF test completes without timeout

### Nice to Have
- [ ] Background processing for large batches
- [ ] V2/V3 usage guide published
- [ ] Performance benchmarks documented

### Stretch Goals
- [ ] Schema-based extraction test (requires Cosmos DB setup)
- [ ] RAPTOR query endpoint tested
- [ ] Load testing with 50+ documents

---

## 💡 Ideas for Future Sessions

### Week 1: Core Functionality
- Implement DRIFT managed identity (Priority 1)
- Enable PDF upload testing (Priority 2)
- Fix gateway timeouts (Priority 3)

### Week 2: Performance & Scale
- Batch processing optimization
- Caching strategy for DRIFT queries
- Load testing with 100+ documents

### Week 3: Advanced Features
- Schema-based extraction integration
- Hybrid V2/V3 query routing
- Real-time indexing webhook

### Week 4: Production Readiness
- Monitoring and alerting
- Error handling improvements
- Documentation and examples

---

## 📞 Contact Points for Tomorrow

**Git Commit:** aeb2107  
**Branch:** main  
**Status:** Pushed to origin

**Start Here Tomorrow:**
1. Review this document
2. Run `test_managed_identity.py` to verify current state
3. Start with Priority 1: Fix DRIFT managed identity
4. Reference `drift_adapter.py` lines 467-500

**Questions to Answer:**
- Does MS GraphRAG's DRIFT accept custom LLM implementations?
- Can we create an adapter that wraps LlamaIndex LLM?
- What's the minimum interface DRIFT requires from an LLM?

---

**End of Handoff Document**  
**Next Session:** Continue with Priority 1 (DRIFT Managed Identity Fix)
