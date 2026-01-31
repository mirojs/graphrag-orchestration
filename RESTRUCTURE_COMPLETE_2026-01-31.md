# Directory Restructuring Complete - January 31, 2026

**Status:** ✅ COMPLETED  
**Scope:** Phase 1, Step 2 from ARCHITECTURE_PLAN_FULLSTACK_2026-01-30.md

---

## What Was Done

### 1. New Directory Structure Created ✅

```
/afh/projects/graphrag-orchestration/
├── src/                           # NEW - Modular architecture
│   ├── core/                      # Shared config and models
│   │   ├── __init__.py
│   │   └── config.py
│   ├── api_gateway/               # FastAPI app (external facing)
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── middleware/
│   │   └── routers/
│   │       ├── health.py
│   │       ├── hybrid.py
│   │       ├── graphrag.py
│   │       ├── orchestration.py
│   │       ├── document_analysis.py
│   │       └── knowledge_map.py
│   └── worker/                    # Algorithm execution
│       ├── __init__.py
│       ├── services/              # All services (graph, llm, etc.)
│       ├── hybrid/                # V1 pipeline
│       └── hybrid_v2/             # V2 pipeline (Voyage embeddings)
├── graphrag-orchestration/        # OLD - Still exists for backward compat
│   └── app/                       # Scripts still reference this
├── infra/                         # Unchanged
├── scripts/                       # Unchanged (uses old imports for now)
└── Dockerfile                     # UPDATED - Uses new src/ structure
```

### 2. All Imports Updated (97 files) ✅

Systematic replacement across all Python files in `src/`:

| Old Import | New Import |
|------------|-----------|
| `from app.core.` | `from src.core.` |
| `from app.services.` | `from src.worker.services.` |
| `from app.hybrid.` | `from src.worker.hybrid.` |
| `from app.hybrid_v2.` | `from src.worker.hybrid_v2.` |
| `from app.routers.` | `from src.api_gateway.routers.` |
| `from app.middleware.` | `from src.api_gateway.middleware.` |

**Verification:** `grep -r "from app\." src/ --include="*.py"` returns 0 results ✅

### 3. Dockerfile Updated ✅

**Old:**
```dockerfile
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**New:**
```dockerfile
COPY src/ /app/src/
CMD ["uvicorn", "src.api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4. azure.yaml Updated ✅

**Old:**
```yaml
services:
  graphrag:
    project: ./graphrag-orchestration
```

**New:**
```yaml
services:
  graphrag:
    project: .
```

Now builds from root with new Dockerfile.

### 5. Syntax Validation ✅

All key files compile without errors:
- ✅ `src/api_gateway/main.py`
- ✅ `src/api_gateway/routers/hybrid.py`
- ✅ `src/worker/hybrid_v2/orchestrator.py`
- ✅ Import test: `from src.core.config import settings` works

---

## Migration Strategy: Dual-Path Coexistence

### Current State
- **New path:** `src/` - Used by Docker container (production)
- **Old path:** `graphrag-orchestration/app/` - Used by scripts (dev/test)
- **Both exist** to avoid breaking scripts during parallel work

### Why Keep Both?
- 40+ script files in `scripts/` directory still use `from app.` imports
- Handover tasks (KNN, API tests) can proceed without script migration
- Architecture tasks (auth, frontend) use new `src/` structure
- **No conflicts** - different import paths

### Migration Path for Scripts (Future)
When ready to fully migrate scripts:
```bash
# Option 1: Update scripts to use src. imports
find scripts/ -name "*.py" -exec sed -i 's/from app\./from src.worker./g' {} \;

# Option 2: Add symbolic link (quick fix)
ln -s ../src/worker graphrag-orchestration/app

# Option 3: Update PYTHONPATH in script runners
export PYTHONPATH=/afh/projects/graphrag-orchestration:$PYTHONPATH
```

---

## What This Enables

### ✅ Immediate Benefits
1. **Clean separation** - API gateway vs worker logic
2. **Docker uses new structure** - Production deployments work
3. **Parallel work enabled** - Handover + Architecture can proceed independently
4. **Foundation for Phase 2** - Auth, frontend, Redis ready for implementation

### 🚀 Next Steps (No Blockers)

**Handover Track (Yesterday's Tasks):**
- Enable KNN in V2 → Edit `src/worker/hybrid_v2/pipeline/tracing.py`
- Run API tests → Use new `src.api_gateway.routers.hybrid`
- Validate 11 ground-truth → Deploy container with new structure

**Architecture Track (From Plan):**
- Phase 1, Step 1: Deprecate Route 1 → Edit `src/api_gateway/routers/hybrid.py`
- Phase 2: Add auth → Work in `src/api_gateway/main.py`, `middleware/`
- Phase 3: Add frontend → Create `src/frontend/` (new directory)

---

## Testing & Validation

### Quick Test (Local)
```bash
cd /afh/projects/graphrag-orchestration
python3 -c "from src.core.config import settings; print('✅ Imports work')"
python3 -m py_compile src/api_gateway/main.py
```

### Build Test (Docker)
```bash
docker build -t graphrag-test -f Dockerfile .
# Should build successfully with new paths
```

### Deploy Test (Azure)
```bash
azd deploy
# azure.yaml now points to root, uses new Dockerfile
```

---

## Files Changed Summary

| Category | Files | Status |
|----------|-------|--------|
| **Python files updated** | 97 | ✅ All imports fixed |
| **New directories** | 3 (core, api_gateway, worker) | ✅ Created |
| **Config files** | 2 (Dockerfile, azure.yaml) | ✅ Updated |
| **Syntax validated** | 3 key files | ✅ Compiles |
| **Old structure** | graphrag-orchestration/app/ | ⚠️ Kept for scripts |

---

## Risk Assessment

| Risk | Mitigation | Status |
|------|-----------|--------|
| Import conflicts | All `from app.` updated in src/ | ✅ Resolved |
| Docker build fails | Dockerfile tested with new paths | ✅ Validated |
| Scripts break | Old structure kept for backward compat | ✅ Safe |
| Deployment issues | azure.yaml points to root | ✅ Updated |

---

## Commands Reference

### Check Import Status
```bash
# Should return 0
grep -r "from app\." src/ --include="*.py" | wc -l
```

### Validate Syntax
```bash
python3 -m py_compile src/api_gateway/main.py
python3 -m py_compile src/worker/hybrid_v2/orchestrator.py
```

### Test Imports
```bash
cd /afh/projects/graphrag-orchestration
python3 -c "from src.core.config import settings; print('Success')"
```

### Build Container
```bash
docker build -t graphrag-restructured .
```

---

## Next Session Checklist

✅ **Ready for parallel work:**
1. [ ] Deploy to test environment with new structure
2. [ ] Verify API endpoints work (`/hybrid/query`)
3. [ ] Start handover tasks (KNN, API tests)
4. [ ] Start architecture tasks (deprecate Route 1)
5. [ ] Gradually migrate scripts when convenient (no urgency)

---

## ✅ FINAL STATUS: Complete Migration

### Production Testing
- ✅ **Deployed successfully** to Azure (32 seconds)
- ✅ **Health check passed**: `{"status":"healthy"}`
- ✅ **API responding**: `/hybrid/query` endpoint working
- ✅ **New structure active**: `src.api_gateway.main:app` running in container

### Scripts Migration
- ✅ **76 scripts updated** to use `src.*` imports
- ✅ **0 old imports remaining** in scripts/ directory
- ✅ **Syntax validated**: All scripts compile successfully
- ✅ **Committed and pushed**: Commit `b920170`

### Clean State
- ✅ **Production uses**: `src/` only
- ✅ **Scripts use**: `src/` only
- ⚠️ **Old structure**: `graphrag-orchestration/app/` still exists but unused
  - Can be deleted when convenient (not referenced by code)
  - 212 references in docs/logs (historical, non-functional)

---

**Bottom Line:** Directory restructuring is **COMPLETE**, **TESTED**, and **DEPLOYED**. All code (production + scripts) now uses unified `src/` structure. Ready for parallel work on handover tasks and architecture implementation.

*Restructuring completed: January 31, 2026 04:55 UTC*  
*Scripts migrated: January 31, 2026 05:15 UTC*  
*Production validated: January 31, 2026 05:15 UTC*

---

# Phase 2: Fullstack Implementation Plan (v2)

**Updated:** January 31, 2026  
**Status:** 🔲 Planning Complete — Ready for Implementation

**TL;DR:** Merge the azure-search-openai-demo frontend, remove Route 1 and Azure AI Search, consolidate on existing resources, add Cosmos DB for chat history + usage tracking, support dual auth (B2B/B2C) with hierarchical folder isolation, and instrument token consumption from day one.

---

## Resources Summary

| Resource | Action | Notes |
|----------|--------|-------|
| `neo4jstorage21224` | ✅ Keep | Blob storage (shared) |
| `graphrag-openai-8476` | ✅ Keep | LLM + embeddings |
| Neo4j Aura | ✅ Keep | Graph + vector (Routes 2/3/4) |
| `graphragacr12153` | ✅ Keep | Container images |
| `graphrag-search` | ❌ **Remove** | Unused — RAPTOR deprecated |
| `azure-search-documents` | ❌ **Remove** | Remove from requirements.txt |
| Cosmos DB Serverless | ➕ Add | Chat history + usage tracking |
| Redis Basic | ➕ Add | Async job queue |

---

## Route Deprecation

| Route | Status | Action |
|-------|--------|--------|
| Route 1 (Vector RAG) | ❌ **Deprecated** | Remove from code: endpoints, router, orchestrator references |
| Route 2 (Local Search) | ✅ Active | Keep — LazyGraphRAG iterative deepening |
| Route 3 (Global Search) | ✅ Active | Keep — Community + HippoRAG PPR |
| Route 4 (DRIFT) | ✅ Active | Keep — Multi-hop iterative reasoning |

**Code changes required:**
- Remove Route 1 from `src/api_gateway/routers/`
- Update route orchestrator to 3-way routing (2/3/4)
- Remove RAPTOR service references
- Update route selection logic and documentation

---

## Architecture

```
┌─────────────────────────┐     ┌─────────────────────────┐
│   B2B Frontend          │     │   B2C Frontend          │
│   (Organization)        │     │   (Personal)            │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │  Same React build             │
            │  (runtime config)             │
            ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│ Container App (B2B)     │     │ Container App (B2C)     │
│ AUTH_TYPE=B2B           │     │ AUTH_TYPE=B2C           │
│ partition=group_id      │     │ partition=user_id       │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
              ┌───────────────────────────┐
              │      Shared Backend       │
              │  ┌─────────┐ ┌─────────┐  │
              │  │   API   │ │ Worker  │  │
              │  │Container│ │Container│  │
              │  └────┬────┘ └────┬────┘  │
              └───────┼───────────┼───────┘
                      ▼           ▼
        ┌─────────────────────────────────────┐
        │         Shared Resources            │
        │  • Neo4j Aura (graph + vectors)     │
        │  • Azure OpenAI (LLM)               │
        │  • Cosmos DB (history + usage)      │
        │  • Redis (job queue)                │
        │  • Blob Storage (files)             │
        └─────────────────────────────────────┘
```

---

## Security: Current Gap & Required Fix

| Current State | Risk | Required Fix |
|---------------|------|--------------|
| `X-Group-ID` header is caller-controlled | ⚠️ **High** — Any caller can impersonate any group | Add JWT validation middleware |
| No token verification | ⚠️ **High** — No proof of identity | Extract `group_id` from `token.groups[0]` (B2B) or `user_id` from `token.oid` (B2C) |
| Easy Auth not configured | ⚠️ **Medium** — No IdP integration | Configure Entra ID / External ID on Container Apps |

**Note:** Current system is suitable for internal/dev use only. JWT validation is a **blocker for production deployment**.

---

## Runtime Config for Dual Frontend

**Endpoint:** `GET /config`

```json
{
  "authType": "B2B",
  "clientId": "xxx-xxx-xxx",
  "authority": "https://login.microsoftonline.com/{tenant}",
  "features": {
    "showAdminPanel": true,
    "showFolders": true
  }
}
```

- Frontend fetches `/config` on app init before MSAL setup
- Single Docker image works for both B2B and B2C deployments
- Container App env vars drive the response

---

## Folder Hierarchy

**Schema:**
```cypher
CREATE CONSTRAINT folder_id IF NOT EXISTS FOR (f:Folder) REQUIRE f.id IS UNIQUE
CREATE INDEX folder_partition IF NOT EXISTS FOR (f:Folder) ON (f.group_id)

(:Folder)-[:SUBFOLDER_OF]->(:Folder)
(:Document)-[:IN_FOLDER]->(:Folder)
```

**Backward compatibility:**
- `folder_id = null` → "Root" / "Unfiled" in UI
- No migration needed
- Max depth = 2 (enforced in API)

---

## Usage Tracking (Fire-and-Forget)

**Pattern:**
```python
@router.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    response = await process_query(request)
    
    # Fire-and-forget: doesn't block response
    background_tasks.add_task(log_usage, UsageRecord(...))
    
    return response
```

**Cosmos containers:**

| Container | Partition Key | TTL | Purpose |
|-----------|---------------|-----|---------|
| `chat_history` | `/user_id` | 90 days | Sessions, messages |
| `usage` | `/partition_id` | 90 days | Tokens, pages, costs |

**Usage record schema:**
```json
{
  "id": "uuid",
  "partition_id": "group-123",
  "user_id": "user-456",
  "timestamp": "2026-01-31T10:30:00Z",
  "usage_type": "llm_completion",
  "model": "gpt-4o",
  "prompt_tokens": 1500,
  "completion_tokens": 350,
  "total_tokens": 1850,
  "route": "route_2",
  "cost_estimate_usd": 0.0285,
  "ttl": 7776000
}
```

---

## Implementation Phases

| Phase | Task | Status | Effort |
|-------|------|--------|--------|
| **1a** | Remove Route 1 from code | 🔲 Pending | 1 day |
| **1b** | Remove Azure AI Search from infra + deps | 🔲 Pending | 0.5 day |
| **1c** | Add Cosmos DB + Redis to infra | 🔲 Pending | 1 day |
| **1d** | Instrumentation hooks (fire-and-forget) | 🔲 Pending | 2 days |
| **1e** | Create `src/core/` module structure | 🔲 Pending | 1 day |
| **2a** | Git subtree frontend from azure-search-openai-demo | 🔲 Pending | 0.5 day |
| **2b** | Runtime config endpoint (`/config`) | 🔲 Pending | 0.5 day |
| **2c** | Chat compat router (`/chat`, `/chat/stream`) | 🔲 Pending | 2 days |
| **2d** | JWT validation middleware | 🔲 Pending | 1 day |
| **2e** | Folder schema + CRUD endpoints | 🔲 Pending | 2 days |
| **3a** | Split API/Worker containers in Bicep | 🔲 Pending | 1 day |
| **3b** | Easy Auth configuration (B2B + B2C) | 🔲 Pending | 1 day |
| **3c** | Dashboard UI (admin + user) | 🔲 Pending | 3-5 days |

---

## Cleanup Checklist

| Item | File(s) | Action |
|------|---------|--------|
| Route 1 endpoints | `src/api_gateway/routers/` | Delete route_1 router |
| Route 1 orchestrator | `src/api_gateway/orchestrator.py` | Remove Route 1 case |
| RAPTOR service | `src/worker/services/raptor_service.py` | Delete or archive |
| RAPTOR types | `src/worker/models/` | Remove RAPTOR-related models |
| Azure AI Search config | `infra/main.bicep` | Remove `graphrag-search` resource |
| Azure AI Search deps | `requirements.txt` | Remove `azure-search-documents` |
| Route selection docs | `ARCHITECTURE_*.md` | Update to 3-route system |
| Routing logic | Query classifier | Update to route 2/3/4 only |

---

## Final Checklist

| Item | Status |
|------|--------|
| Route 1 deprecated in code | ✅ Planned |
| Azure AI Search removed from infra | ✅ Planned |
| RAPTOR fully deprecated | ✅ Planned |
| Reuse existing storage account | ✅ |
| Neo4j as sole retrieval DB | ✅ |
| Cosmos DB for chat history | ✅ |
| Cosmos DB for usage tracking | ✅ |
| Fire-and-forget usage logging | ✅ |
| Dual frontend (B2B/B2C) | ✅ |
| Runtime config endpoint | ✅ |
| Folder hierarchy | ✅ |
| Max folder depth constraint | ✅ |
| JWT validation (security gap noted) | ✅ |
| `src/core/` module gap noted | ✅ |
| Dashboard UI deferred to Phase 3 | ✅ |

---

*Phase 2 plan finalized: January 31, 2026*
