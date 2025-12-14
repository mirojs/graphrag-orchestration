# Session Summary - November 30, 2025
## GraphRAG + LlamaIndex Integration Implementation

---

## What We Accomplished Today

### 1. Technology Evaluation & Architecture Planning
**Analyzed GraphRAG vs LlamaIndex:**
- **GraphRAG v2.7.0**: Specialized knowledge graph library for deep reasoning
  - Entity/relationship extraction with community detection (Leiden algorithm)
  - Three query engines: global_search (community-based), local_search (entity-focused), drift_search (multi-step iterative reasoning)
  - Parquet-based data model (entities, relationships, text_units, communities, community_reports)
  - Rapid iteration cycle (weekly releases), research-focused
  
- **LlamaIndex v0.11.0**: Mature general-purpose RAG framework
  - 300+ integration packages, production-ready since 2022
  - Workflows for multi-step orchestration, query routers, agent tool calling
  - Strong Azure integrations (OpenAI, AI Search, Cosmos DB)
  - Monorepo with active daily/weekly releases

**Key Insight:** Combining both gives us the best of both worlds - GraphRAG for specialized graph reasoning + LlamaIndex for flexible orchestration. This approach can replicate and exceed Azure Content Understanding Pro Mode capabilities while avoiding managed-service lock-in.

### 2. Vector Store Selection
**Evaluated three options:**

1. **LanceDB** (Chosen for local development)
   - File-backed embedded vector DB using Lance columnar format
   - No managed service dependency - perfect for local iteration
   - Requires manual tenant isolation via path strategy
   - Fast development velocity

2. **Azure AI Search** (Recommended for near-term production)
   - Managed service with hybrid BM25+vector+semantic ranking
   - Strong LlamaIndex integration, enterprise SLA
   - Best retrieval quality with facets/filters
   - Requires filtering strategy for multi-tenancy

3. **Cosmos DB Vector Search** (Optional future consolidation)
   - Co-locates embeddings with app data
   - Natural `partition_key=group_id` isolation
   - Fewer search features than AI Search but simpler multi-tenancy
   - Reduces service sprawl

**Decision:** Start with LanceDB for dev, build abstraction layer (`VectorStoreProvider`) to enable seamless production swap to Azure AI Search or Cosmos Vector.

### 3. Reference Repository Analysis
**Evaluated four Microsoft accelerators:**

- **azure-search-openai-demo**: Battle-tested MSAL auth, Azure deployment patterns ✅ PRIMARY
- **graphrag-accelerator**: Production scaffold for GraphRAG pipelines, job orchestration ✅ PRIMARY  
- **Conversation-Knowledge-Mining-Solution-Accelerator**: Streaming chat UI, Chart.js integration ⚠️ UI PATTERNS ONLY
- **Document-Knowledge-Mining-Solution-Accelerator**: Document viewer components, Kernel Memory ⚠️ UI PATTERNS ONLY

**Strategy:** Use Azure demo + GraphRAG accelerator as foundation; borrow UI/UX patterns from Conversation/Document accelerators without their backend dependencies.

### 4. Comprehensive Architecture Documentation
**Created `ARCHITECTURE_DECISIONS.md`** with:
- **Problem Description**: Multi-tenant constraints, dual storage requirements, fragmentation pain points
- **Decision Log**: Rationale for each technology choice with trade-offs
- **8-Phase Implementation Plan**: Prereqs → Foundation → GraphRAG → Orchestration → Frontend → Security → Testing → Deployment → Cost/Perf
- **Upgrade Strategy**: Version pinning, abstraction layers, migration playbooks, testing gates, observability
- **Repository Recommendation**: Build on current repo (preserves multi-tenancy context) via feature branch; optional clone later

### 5. Repository Strategy Decision
**Question:** New repo vs current repo?

**Decision:** Feature branch in current repository
- **Why**: Already has multi-tenancy (`X-Group-ID`), dual storage (Cosmos+Blob), extensive docs
- **How**: Add new service folders (`services/graphrag-orchestration/`), shared helpers in `libs/`
- **Future**: Optional mirror-push to new repo later if needed (preserves full history)

### 6. Docker Development Environment Setup
**Created `docker-compose.dev.yml`** with 3-container consolidated architecture:

```yaml
services:
  api:        # Existing ContentProcessorAPI (port 8000)
  web:        # Existing React frontend (port 3000)
  graphrag:   # NEW - Consolidated GraphRAG + LlamaIndex service (port 8001)
```

**Key Design Decisions:**
- **Consolidated vs Split**: Combined GraphRAG indexing + query + LlamaIndex orchestration into ONE container (saves resources, simpler dev)
- **Container Count**: 3 total (not 4) - minimizes development environment impact
- **Resource Impact**: ~3-4 GB RAM for new GraphRAG service
- **Storage**: Persistent `graphrag-data` volume for graph artifacts and LanceDB index
- **Multi-Tenancy**: `ENABLE_GROUP_ISOLATION=true` enforces `X-Group-ID` header

### 7. GraphRAG Service Scaffolding
**Created `services/graphrag-orchestration/` structure:**

**README.md** - Service documentation:
- 8 main endpoints documented:
  - `POST /graphrag/index` - Trigger indexing for a group
  - `GET /graphrag/index/{job_id}` - Check indexing status
  - `POST /graphrag/query/global` - Global community-based search
  - `POST /graphrag/query/local` - Local entity-focused search  
  - `POST /graphrag/query/drift` - Multi-step DRIFT reasoning
  - `POST /orchestrate/analyze` - Route query to appropriate engine(s)
  - `POST /orchestrate/extract` - Schema-based extraction via LlamaIndex
  - `GET /health`, `GET /metrics` - Admin endpoints
- Multi-tenancy enforcement via `X-Group-ID` header (mandatory)
- Local development commands

**Dockerfile** - Container image:
- Python 3.11-slim base
- Data directories: `/data/graphrag`, `/data/lancedb`, `/data/cache`
- Port 8001 exposure
- Uvicorn with FastAPI

**requirements.txt** - Pinned dependencies:
```
fastapi==0.109.0
uvicorn==0.27.0
graphrag==2.7.0           # Locked to stable release
llama-index-core==0.11.0
llama-index-llms-azure-openai==0.2.0
llama-index-embeddings-azure-openai==0.2.0
llama-index-vector-stores-lancedb==0.2.0
llama-index-vector-stores-azureaisearch==0.3.0
lancedb==0.13.0
azure-search-documents==11.4.0
azure-cosmos==4.5.1
azure-storage-blob==12.19.0
azure-identity==1.15.0
structlog==24.1.0
tenacity==8.2.3
```

---

## What's NOT Done Yet (Implementation Needed)

### Critical Missing Pieces

#### 1. **Python Application Code** (HIGHEST PRIORITY)
The service structure is documented but not implemented:

**Needed Files:**
```
services/graphrag-orchestration/
├── app/
│   ├── main.py              ❌ NOT CREATED - FastAPI app initialization
│   ├── routers/
│   │   ├── graphrag.py      ❌ NOT CREATED - GraphRAG endpoints
│   │   ├── orchestration.py ❌ NOT CREATED - Orchestration endpoints
│   │   └── health.py        ❌ NOT CREATED - Health/metrics endpoints
│   ├── services/
│   │   ├── vector_store.py  ❌ NOT CREATED - VectorStoreProvider abstraction
│   │   ├── graphrag_service.py ❌ NOT CREATED - GraphRAG facade wrapper
│   │   └── orchestrator.py  ❌ NOT CREATED - LlamaIndex workflow coordinator
│   ├── middleware/
│   │   └── group_isolation.py ❌ NOT CREATED - X-Group-ID enforcement
│   └── core/
│       └── config.py        ❌ NOT CREATED - Settings management
```

**What Each File Should Do:**

- **`main.py`**: FastAPI app setup, CORS config, middleware registration, router inclusion
- **`routers/graphrag.py`**: POST /graphrag/index, /query/global, /query/local, /query/drift with async handlers
- **`routers/orchestration.py`**: POST /orchestrate/analyze (query router), POST /orchestrate/extract (schema extraction)
- **`routers/health.py`**: GET /health (liveness), GET /metrics (Prometheus-compatible)
- **`services/vector_store.py`**: ABC with `LanceDBStore`, `AzureAISearchStore`, `CosmosVectorStore` adapters
- **`services/graphrag_service.py`**: Wraps GraphRAG indexing pipeline and query engines with config
- **`services/orchestrator.py`**: LlamaIndex RouterQueryEngine composition, tool selection, response synthesis
- **`middleware/group_isolation.py`**: Enforce X-Group-ID header, extract group_id, inject into request state
- **`core/config.py`**: Pydantic settings for environment variables with validation

#### 2. **Multi-Tenant Isolation Implementation**
**Critical Security Requirement:**

- Middleware must extract `X-Group-ID` header and inject into request state
- All Cosmos DB queries must use `partition_key=group_id`
- All Blob Storage paths must resolve to `/{group_id}/...`
- Vector store queries must filter by group metadata
- Requests without `X-Group-ID` must be rejected (401/403)

**Testing Required:**
```bash
python test_database_isolation.py  # Create this test file
```

#### 3. **Configuration Management**
**Needed Environment Variables:**
```env
# Azure Services
COSMOS_ENDPOINT=
COSMOS_KEY=
STORAGE_ACCOUNT_NAME=
STORAGE_ACCOUNT_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
AZURE_OPENAI_DEPLOYMENT_NAME=
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=

# Vector Store
VECTOR_STORE_TYPE=lancedb  # or azure_search or cosmos
LANCEDB_PATH=/data/lancedb
AZURE_SEARCH_ENDPOINT=     # if using azure_search
AZURE_SEARCH_KEY=          # if using azure_search

# GraphRAG
GRAPHRAG_DATA_DIR=/data/graphrag
GRAPHRAG_CACHE_DIR=/data/cache

# Multi-Tenancy
ENABLE_GROUP_ISOLATION=true
```

#### 4. **Testing Infrastructure**
**Test Files Needed:**
- `tests/test_group_isolation.py` - Positive/negative isolation tests
- `tests/test_graphrag_service.py` - Mocked LLM responses for CI
- `tests/test_vector_store.py` - Adapter pattern testing
- `tests/test_orchestration.py` - Workflow composition tests

#### 5. **Frontend Integration** (Lower Priority)
**Changes to `ContentProcessorWeb`:**
- Add `REACT_APP_GRAPHRAG_API_URL=http://localhost:8001` to `.env`
- Create GraphRAG query components (chat interface, query type selector)
- Update API client to propagate `X-Group-ID` header from Redux state
- Add streaming response handling for chat UX

#### 6. **Deployment Documentation**
**Needed Files:**
- `services/graphrag-orchestration/DEPLOYMENT.md` - Azure Container Apps deployment steps
- Update main `README.md` with architecture diagram and local dev quickstart

---

## How to Pick Up Tomorrow

### Immediate Next Steps (Priority Order)

#### Step 1: Implement Core FastAPI Application (1-2 hours)
```bash
# Create app/main.py with:
# - FastAPI initialization
# - CORS middleware
# - X-Group-ID enforcement middleware
# - Router registration (graphrag, orchestration, health)
# - Startup/shutdown event handlers
```

**Minimal Viable `main.py`:**
```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import structlog

app = FastAPI(title="GraphRAG Orchestration Service")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# X-Group-ID enforcement
@app.middleware("http")
async def enforce_group_id(request: Request, call_next):
    if request.url.path not in ["/health", "/metrics"]:
        group_id = request.headers.get("X-Group-ID")
        if not group_id:
            raise HTTPException(status_code=401, detail="Missing X-Group-ID header")
        request.state.group_id = group_id
    return await call_next(request)

# Health endpoint
@app.get("/health")
async def health():
    return {"status": "healthy"}

# Include routers (stub for now)
# from app.routers import graphrag, orchestration, health
# app.include_router(graphrag.router, prefix="/graphrag", tags=["graphrag"])
# app.include_router(orchestration.router, prefix="/orchestrate", tags=["orchestration"])
```

#### Step 2: Create Stub Routers (30 minutes)
```bash
# Create routers with 501 Not Implemented responses
# This enables container startup and health check validation
# before implementing full business logic
```

**Example stub router:**
```python
# app/routers/graphrag.py
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.post("/index")
async def trigger_indexing(request: Request):
    group_id = request.state.group_id
    return {"error": "Not implemented", "group_id": group_id}, 501

@router.post("/query/global")
async def query_global(request: Request):
    return {"error": "Not implemented"}, 501
```

#### Step 3: Test Container Startup (15 minutes)
```bash
# Verify Docker setup works
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939
docker-compose -f docker-compose.dev.yml build graphrag
docker-compose -f docker-compose.dev.yml up graphrag

# Test health endpoint
curl http://localhost:8001/health
# Expected: {"status": "healthy"}

# Test X-Group-ID enforcement
curl http://localhost:8001/graphrag/index
# Expected: 401 Missing X-Group-ID header

curl -H "X-Group-ID: test-group" http://localhost:8001/graphrag/index
# Expected: 501 Not implemented
```

#### Step 4: Implement VectorStoreProvider Abstraction (1-2 hours)
```python
# app/services/vector_store.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class VectorStoreProvider(ABC):
    @abstractmethod
    async def insert(self, group_id: str, documents: List[Dict[str, Any]]):
        pass
    
    @abstractmethod
    async def query(self, group_id: str, query_vector: List[float], top_k: int = 10):
        pass

class LanceDBStore(VectorStoreProvider):
    def __init__(self, db_path: str):
        import lancedb
        self.db = lancedb.connect(db_path)
    
    async def insert(self, group_id: str, documents: List[Dict[str, Any]]):
        # Implementation with group_id in metadata
        pass
    
    async def query(self, group_id: str, query_vector: List[float], top_k: int = 10):
        # Implementation with group_id filtering
        pass

# Factory pattern
def create_vector_store(store_type: str, **kwargs) -> VectorStoreProvider:
    if store_type == "lancedb":
        return LanceDBStore(kwargs["db_path"])
    elif store_type == "azure_search":
        return AzureAISearchStore(kwargs["endpoint"], kwargs["key"])
    elif store_type == "cosmos":
        return CosmosVectorStore(kwargs["endpoint"], kwargs["key"])
    raise ValueError(f"Unknown store type: {store_type}")
```

#### Step 5: Implement GraphRAG Service Facade (2-3 hours)
```python
# app/services/graphrag_service.py
from graphrag.query.indexer_adapters import read_indexer_entities, read_indexer_reports
from graphrag.query.llm.oai.chat_openai import ChatOpenAI
from graphrag.query.structured_search.global_search.search import GlobalSearch
from graphrag.query.structured_search.local_search.search import LocalSearch

class GraphRAGService:
    def __init__(self, data_dir: str, llm_config: Dict[str, Any]):
        self.data_dir = data_dir
        self.llm = ChatOpenAI(**llm_config)
    
    async def index_documents(self, group_id: str, document_paths: List[str]):
        # Trigger GraphRAG indexing pipeline
        # Output to {data_dir}/{group_id}/output/
        pass
    
    async def query_global(self, group_id: str, query: str):
        # Load community reports for group
        # Run GlobalSearch
        pass
    
    async def query_local(self, group_id: str, query: str):
        # Load entities/relationships for group
        # Run LocalSearch
        pass
    
    async def query_drift(self, group_id: str, query: str):
        # Run DRIFT search with iterative reasoning
        pass
```

#### Step 6: Wire Everything Together (1 hour)
- Update `main.py` to initialize services with config
- Implement actual router handlers calling service methods
- Add error handling and logging (structlog)
- Test end-to-end with sample queries

---

## Key Architectural Patterns to Remember

### 1. Group-Based Multi-Tenancy (CRITICAL)
**Every API call must include `X-Group-ID` header:**
```python
# Backend: All Cosmos DB queries use partition_key
cosmos_helper.find_documents(
    collection_name="cases",
    query={"case_id": case_id},
    partition_key=group_id  # REQUIRED
)

# All Blob paths use group prefix
blob_path = f"{group_id}/files/{file_id}.pdf"

# Vector queries filter by group
vector_results = await vector_store.query(
    group_id=group_id,
    query_vector=embedding
)
```

### 2. Dual Schema Storage Pattern
**Schemas exist in TWO places:**
1. **Cosmos DB (`schemas` collection)** - Metadata (name, description, created_at, group_id)
2. **Blob Storage (`schemas/` container)** - Raw JSON for AI processing

**Critical:** When saving/deleting schemas, update BOTH locations.

### 3. Abstraction Layers for Stability
**Why:** GraphRAG and LlamaIndex update frequently (weekly releases)

**Strategy:**
- `VectorStoreProvider` ABC - swap implementations without code changes
- `GraphRAGService` facade - isolate GraphRAG API changes
- Version pinning in `requirements.txt` - controlled upgrades only

### 4. Async Patterns Throughout
**All Azure SDK calls are async:**
```python
# Correct
result = await analyze_with_analyzer(...)

# Wrong - blocks event loop
result = analyze_with_analyzer(...)  # Missing await
```

---

## Documentation Reference

### Files Created Today
1. ✅ `ARCHITECTURE_DECISIONS.md` - Comprehensive decision log with rationale
2. ✅ `docker-compose.dev.yml` - 3-container development setup
3. ✅ `services/graphrag-orchestration/README.md` - Service documentation
4. ✅ `services/graphrag-orchestration/Dockerfile` - Container image definition
5. ✅ `services/graphrag-orchestration/requirements.txt` - Pinned dependencies

### Key Existing Documentation (Reference for Context)
- `GROUP_ISOLATION_QUICK_REFERENCE.md` - Multi-tenancy implementation patterns
- `DEPLOYMENT_GUIDE.md` - Azure deployment steps
- `TESTING_GUIDE.md` - Test suite instructions
- `AZURE_CONTENT_UNDERSTANDING_SCHEMA_EXTRACTION_IMPLEMENTATION.md` - Two-step analyzer workflow
- `.github/copilot-instructions.md` - Project conventions and patterns

---

## Open Questions / Decisions Needed

### 1. LlamaIndex Workflow Composition
**Question:** Should we use LlamaIndex Workflows (declarative) or RouterQueryEngine (simpler)?

**Consideration:**
- Workflows: More powerful for complex multi-step reasoning, harder to debug
- RouterQueryEngine: Simpler routing logic, easier to understand

**Recommendation:** Start with RouterQueryEngine for MVP, migrate to Workflows if complexity requires.

### 2. GraphRAG Indexing Trigger
**Question:** How should indexing be triggered?
- Option A: Manual API call (`POST /graphrag/index`)
- Option B: Automatic when new documents uploaded
- Option C: Scheduled job (daily/weekly)

**Recommendation:** Start with manual API (Option A) for control, add automatic triggers later.

### 3. Vector Store Production Choice
**Question:** Azure AI Search or Cosmos DB Vector Search for production?

**Trade-offs:**
- **Azure AI Search**: Better retrieval quality, more features, separate service to manage
- **Cosmos Vector**: Simpler multi-tenancy (native partition keys), fewer search features

**Recommendation:** Start with Azure AI Search for retrieval quality, evaluate Cosmos consolidation after measuring actual usage patterns.

### 4. Frontend Integration Timing
**Question:** When to integrate with existing React frontend?

**Options:**
- Option A: After backend MVP is stable (recommended)
- Option B: Build frontend in parallel
- Option C: Use API testing tools (Postman/curl) initially

**Recommendation:** Option A - stabilize backend first with API tests, then add frontend.

---

## Quick Reference Commands

### Local Development
```bash
# Start all services
docker-compose -f docker-compose.dev.yml up

# Start only GraphRAG service
docker-compose -f docker-compose.dev.yml up graphrag

# Rebuild after code changes
docker-compose -f docker-compose.dev.yml build graphrag
docker-compose -f docker-compose.dev.yml up graphrag

# View logs
docker-compose -f docker-compose.dev.yml logs -f graphrag

# Stop all services
docker-compose -f docker-compose.dev.yml down

# Clean volumes (reset data)
docker-compose -f docker-compose.dev.yml down -v
```

### Testing
```bash
# Health check
curl http://localhost:8001/health

# Test with X-Group-ID
curl -H "X-Group-ID: test-group" \
     -H "Content-Type: application/json" \
     -X POST http://localhost:8001/graphrag/query/global \
     -d '{"query": "What are the main topics?"}'

# Run unit tests (once implemented)
cd services/graphrag-orchestration
pytest tests/ -v

# Run isolation tests
python test_database_isolation.py
```

### Dependency Management
```bash
# Upgrade GraphRAG (careful - check breaking changes)
pip install graphrag==<new_version>
pip freeze | grep graphrag

# Upgrade LlamaIndex (careful - check monorepo changes)
pip install llama-index-core==<new_version>
pip freeze | grep llama-index

# Lock all dependencies
pip freeze > requirements.txt
```

---

## Success Criteria for Tomorrow

### Minimum Viable Implementation (MVP)
- ✅ Container starts successfully
- ✅ Health endpoint returns 200
- ✅ X-Group-ID enforcement working (401 without header)
- ✅ Stub endpoints return 501 Not Implemented
- ✅ VectorStoreProvider abstraction implemented with LanceDB adapter
- ✅ GraphRAG service can run global search on sample data
- ✅ Basic logging with structlog

### Stretch Goals
- ✅ All three query types working (global, local, DRIFT)
- ✅ LlamaIndex RouterQueryEngine composing GraphRAG + vector retrieval
- ✅ Schema-based extraction endpoint functional
- ✅ Integration tests with mocked LLMs
- ✅ Frontend component for chat interface

---

## Notes & Reminders

### Multi-Tenancy is Security-Critical
**Never skip `X-Group-ID` enforcement** - this is the primary mechanism preventing cross-tenant data leaks. Review `GROUP_ISOLATION_IMPLEMENTATION_COMPLETE.md` before editing auth/data access code.

### Version Pinning is Essential
GraphRAG and LlamaIndex update frequently. Always pin exact versions in `requirements.txt` and test upgrades in feature branches before merging.

### Dual Schema Storage is Mandatory
When creating/updating/deleting schemas, BOTH Cosmos and Blob must be updated. Missing either location breaks the system.

### LanceDB is Dev-Only
Production deployments should use Azure AI Search or Cosmos Vector Search for managed SLA and better multi-tenancy. LanceDB abstraction enables easy swap.

### Docker Volumes Persist Data
The `graphrag-data` volume persists across container restarts. To reset state during development: `docker-compose -f docker-compose.dev.yml down -v`

---

## Contact Context

**Today's Session Date:** November 30, 2025

**Implementation Status:**
- ✅ Architecture decisions documented
- ✅ Docker infrastructure scaffolded  
- ✅ Service structure defined
- ❌ Python application code not yet implemented
- ❌ Multi-tenant isolation not yet wired
- ❌ Tests not yet created

**Repository State:**
- Branch: `main` (feature branch for GraphRAG work not yet created)
- New files: `ARCHITECTURE_DECISIONS.md`, `docker-compose.dev.yml`, `services/graphrag-orchestration/*`
- Existing codebase: `src/ContentProcessorAPI/`, `src/ContentProcessorWeb/` (unchanged)

**Next Session Starting Point:**
Begin with Step 1 in "How to Pick Up Tomorrow" section above - implement core FastAPI application (`app/main.py`) with middleware and health endpoints.
