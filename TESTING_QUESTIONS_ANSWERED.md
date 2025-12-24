# Testing Questions - Answered
**Date:** 2025-12-24  
**Status:** Clarifications Provided

---

## Question 1: Test Questions Based on Actual PDF Content

**Question:** "We will always use the existing 5 PDF files to test, so the questions needs to come from the files."

**Answer:** ✅ **You're absolutely right!** The test plan needs content-specific questions.

### The 5 Test PDFs
Based on the test output, the files are:
1. **BUILDERS LIMITED WARRANTY.pdf**
2. **HOLDING TANK SERVICING CONTRACT.pdf**
3. **PROPERTY MANAGEMENT AGREEMENT.pdf**
4. **contoso_lifts_invoice.pdf**
5. **purchase_contract.pdf**

### Problem with Current Test Plan
The questions in `COMPREHENSIVE_TEST_PLAN_2025-12-24.md` are **generic placeholders** - they assume content without knowing actual document details.

### Solution Needed
**Option A: Content-First Approach (Recommended)**
1. **Extract actual content** from the 5 PDFs first
2. **Identify key facts** (amounts, dates, parties, terms)
3. **Write questions** based on actual content
4. **Verify answerability** - ensure each question can be answered from the documents

**Option B: Discovery-Based Testing**
1. Start with **exploratory queries** to understand what's in the documents
2. Index the 5 PDFs → examine entities created
3. Review the actual content in Neo4j
4. Generate questions based on discovered facts

**Action Item:** 🔴 **CRITICAL** - Need to either:
- Read the 5 PDF files and extract key facts
- OR run exploratory queries first to understand content
- THEN update test plan with content-specific questions

---

## Question 2: RAPTOR Routing Architecture

**Question:** "Are we including RAPTOR as one route in GraphRAG besides local/global/drift search, or as another route besides Vector RAG and GraphRAG?"

**Answer:** Based on the code analysis:

### Current Architecture (What's Implemented)

```
Top Level Router
├── Vector RAG (Direct chunk retrieval)
└── GraphRAG
    ├── LOCAL Search (Entity-focused)
    ├── GLOBAL Search (Community-based)
    ├── DRIFT Search (Multi-hop reasoning)
    └── RAPTOR Search (Hierarchical summaries)
```

**RAPTOR is the 4th route WITHIN GraphRAG**, not a separate top-level route.

### Evidence from Code

**File:** `app/v3/services/triple_engine_retriever.py`

```python
QueryRoute = Literal["vector", "graph", "raptor", "drift"]

def route_query(self, query: str) -> Tuple[QueryRoute, str]:
    """
    Use LLM to classify query intent.
    
    Routes:
    1. **vector**: For specific fact lookups
    2. **graph**: For relational reasoning  
    3. **raptor**: For thematic summaries
    4. **drift**: For complex multi-hop reasoning
    """
```

### Routing Logic

**4-Way Routing (Current):**
- `vector` → Entity search (Hybrid+Boost)
- `graph` → Community/relationship traversal
- `raptor` → Hierarchical summaries
- `drift` → Multi-hop reasoning

**NOT:** Vector RAG vs GraphRAG (2-way)  
**IS:** 4 distinct routes within a unified system

### Clarification Needed

The architecture is **ambiguous** in the codebase. We have:

1. **Triple-Engine Retriever** (named for 3 engines, but has 4 routes)
2. **Query Router** that routes to: `vector`, `graph`, `raptor`, `drift`

**Recommendation:** Rename to **"Quad-Engine Retriever"** or **"4-Way Router"** for clarity.

### RAPTOR Enhancement vs RAPTOR Route

**Two different concepts:**

1. **RAPTOR Route** - Direct query to hierarchical summaries
   - Example: "What are the main themes?"
   - Goes directly to RAPTOR nodes (Level 1, 2)

2. **RAPTOR Enhancement** - Adds context to other routes
   - Example: "What is the invoice amount?" (LOCAL route)
   - Returns: Amount + parent RAPTOR summary for context

**The test plan mixes these concepts!**

### Corrected Architecture

```
Query Router (o4-mini)
│
├── Vector RAG Route
│   ├── Pure Vector (chunks only)
│   └── Vector + RAPTOR Enhancement (chunks + parent summaries)
│
└── GraphRAG Routes
    ├── LOCAL Search
    │   ├── Pure LOCAL (entities only)
    │   └── LOCAL + RAPTOR Enhancement (entities + parent summaries)
    │
    ├── GLOBAL Search
    │   ├── Pure GLOBAL (communities)
    │   └── GLOBAL + RAPTOR Pruning (RAPTOR-filtered communities)
    │
    ├── RAPTOR Search (NEW - Direct to hierarchical summaries)
    │   └── Query RAPTOR tree directly for themes
    │
    └── DRIFT Search
        ├── Pure DRIFT (graph traversal)
        └── DRIFT + RAPTOR Highways (RAPTOR-guided multi-hop)
```

### Action Item
🔴 **CRITICAL** - The test plan needs to distinguish:
- **Pure routes** (baseline functionality)
- **RAPTOR-enhanced routes** (with contextual enrichment)
- **RAPTOR-direct route** (hierarchical summary queries)

---

## Question 3: Model Configuration Issue

**Question:** "I noticed for the test_phase1_5docs.py test log that we are still using gpt-4o model. Is that true or it's just a logging issue?"

**Answer:** 🔴 **CRITICAL BUG FOUND** - The deployed container is **NOT** using the updated configuration!

### Evidence

**Container Startup Log:**
```json
{
  "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4o",  // ❌ WRONG - Should be gpt-5-2
  "AZURE_OPENAI_DRIFT_DEPLOYMENT_NAME": "gpt-5-2",  // ✅ Correct
  "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-large",  // ❌ WRONG - Should be text-embedding-3-small
  "AZURE_OPENAI_EMBEDDING_DIMENSIONS": 1536,  // ✅ Correct
  "event": "service_startup"
}
```

**LLM Service Initialization:**
```json
{
  "model": "gpt-4o",  // ❌ WRONG
  "event": "llm_service_initialized"
}
```

### Root Cause

**The deployment script does NOT propagate the `.env` file to the container!**

**Deployment Process:**
1. ✅ Code changes committed (config.py updated)
2. ✅ Docker image built
3. ❌ **Container uses OLD environment variables** from Azure Container Apps settings
4. ❌ New defaults in `config.py` are **overridden** by Azure env vars

### Current Configuration

**Local `.env` (Correct):**
```bash
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-2  ✅
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
```

**Azure Container Apps (WRONG):**
```bash
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o  ❌
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large  ❌
```

### Impact

**Current System State:**
- ✅ **Code:** Updated to use gpt-5-2 and 1536 dims
- ✅ **Neo4j Indexes:** Updated to 1536 dimensions
- ❌ **Deployed Container:** Still using gpt-4o (old model)
- ❌ **Embeddings:** Potentially using text-embedding-3-large (3072 dims) **MISMATCH!**

**This is a CRITICAL configuration drift!**

### Symptoms
1. **Indexing still works** because embeddings happen to be 1536 (lucky?)
2. **Query synthesis** uses old model (gpt-4o, not gpt-5-2)
3. **Performance targets** won't be met because we're not using the fast model

### Solution Required

**Option A: Update Azure Container Apps Environment Variables**
```bash
az containerapp update \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --set-env-vars \
    AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-2 \
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
```

**Option B: Update Deployment Script**
Modify `deploy-simple.sh` to pass environment variables during `az containerapp create`:
```bash
az containerapp create \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --image graphragacr12153.azurecr.io/graphrag-orchestration:latest \
  --environment-variables \
    AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-2 \
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536 \
  ...
```

**Option C: Rebuild Container with Correct Defaults**
The container already has correct defaults in `config.py`, but Azure overrides them. Need to either:
- Remove Azure env var overrides
- OR ensure deployment script sets them correctly

### Action Items

🔴 **IMMEDIATE:**
1. **Update Azure Container Apps env vars** to match new configuration
2. **Restart container** to pick up changes
3. **Verify startup logs** show correct models
4. **Re-run test_phase1_5docs.py** to confirm gpt-5-2 is used

🟡 **SHORT-TERM:**
1. Update `deploy-simple.sh` to set environment variables explicitly
2. Add deployment verification step to check configured models
3. Document configuration precedence (Azure > .env > config.py defaults)

🟢 **LONG-TERM:**
1. Implement configuration validation in startup
2. Add health check endpoint that returns current model configuration
3. Create deployment checklist with configuration verification

---

## Summary of Action Items

### 🔴 CRITICAL (Block Testing)

1. **Fix Model Configuration:**
   - Update Azure Container Apps environment variables
   - Verify gpt-5-2 and text-embedding-3-small are used
   - Re-index if embeddings were wrong

2. **Extract Actual PDF Content:**
   - Read the 5 test PDF files
   - Document key facts (amounts, dates, parties, clauses)
   - Create content-specific test questions

3. **Clarify RAPTOR Architecture:**
   - Decide: Is RAPTOR a 4th route or an enhancement layer?
   - Update code/docs to reflect correct architecture
   - Rename "Triple-Engine" if we have 4 routes

### 🟡 IMPORTANT (Improve Testing)

4. **Update Test Plan:**
   - Replace generic questions with content-specific ones
   - Separate "pure route" tests from "RAPTOR-enhanced" tests
   - Add "RAPTOR-direct" tests if it's a standalone route

5. **Fix Deployment Script:**
   - Add environment variable propagation
   - Add post-deployment verification
   - Document configuration precedence

6. **Add Configuration Health Check:**
   - Create `/config` endpoint showing active models
   - Include in pre-test verification
   - Log configuration on startup for debugging

---

## Revised Test Plan Structure

Based on clarifications, the test plan should be:

### Phase 0: Content Discovery (NEW)
- Index 5 PDFs
- Query Neo4j for entity list
- Document actual content available
- Generate content-specific questions

### Phase 1: Pure Routes (Baseline)
- **1.1:** Vector RAG (no graph, no RAPTOR)
- **1.2:** LOCAL Search (entities only, no RAPTOR)
- **1.3:** GLOBAL Search (communities only, no RAPTOR)
- **1.4:** DRIFT Search (traversal only, no RAPTOR)
- **1.5:** RAPTOR-Direct Search (hierarchical summaries)

### Phase 2: RAPTOR-Enhanced Routes
- **2.1:** Vector RAG + RAPTOR Context
- **2.2:** LOCAL + RAPTOR Context
- **2.3:** GLOBAL + RAPTOR Pruning
- **2.4:** DRIFT + RAPTOR Highways

### Phase 3: Routing Validation
- **3.1:** Query Router (4-way or 5-way?)
- **3.2:** Route Correctness (verify routing decisions)

### Phase 4: Comparison & Metrics
- **4.1:** Baseline vs Enhanced (measure RAPTOR improvement)
- **4.2:** Performance Benchmarking (< 2 min SLA)
- **4.3:** Accuracy Assessment (entity/relationship correctness)

---

## Next Steps

1. **STOP** - Don't run tests with wrong configuration
2. **FIX** - Update Azure Container Apps environment variables
3. **VERIFY** - Check startup logs show gpt-5-2
4. **DISCOVER** - Extract content from 5 PDFs
5. **UPDATE** - Revise test plan with content-specific questions
6. **TEST** - Execute revised test plan

**Estimated Time to Fix:** 1-2 hours  
**Estimated Time to Revise Test Plan:** 2-3 hours  
**Total Before Testing:** 3-5 hours
