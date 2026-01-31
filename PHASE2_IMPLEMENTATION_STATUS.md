# Phase 2 Implementation Status

**Updated:** January 31, 2026  
**Started:** January 31, 2026

---

## Overview

This document tracks the implementation of Phase 2: Fullstack Restructure with Resource Consolidation, as defined in [RESTRUCTURE_COMPLETE_2026-01-31.md](RESTRUCTURE_COMPLETE_2026-01-31.md).

---

## Progress Summary

| Phase | Tasks | Completed | In Progress | Not Started |
|-------|-------|-----------|-------------|-------------|
| **Phase 1** | 5 tasks | 2 | 0 | 3 |
| **Phase 2** | 5 tasks | 0 | 0 | 5 |
| **Phase 3** | 3 tasks | 0 | 0 | 3 |
| **Total** | 13 tasks | 2 | 0 | 11 |

**Overall Progress:** 15% (2/13 tasks)

---

## Completed Tasks ✅

### Task 1a: Remove Route 1 from Code
**Status:** ✅ Complete  
**Commit:** `44a40b6`  
**Date:** January 31, 2026

**Changes:**
- Removed Route 1 (Vector RAG) implementation from orchestrator (2200+ lines)
- Deleted `src/worker/hybrid_v2/hybrid/routes/route_1_vector.py`
- Updated `routes/__init__.py` to remove VectorRAGHandler import/export
- Updated router to 3-route system (Routes 2/3/4 only)
- VECTOR_RAG enum now maps to LOCAL_SEARCH for backward compatibility
- Updated orchestrator header documentation
- Updated health_check endpoint to remove route_1 status

**Files Modified:**
- `src/worker/hybrid_v2/orchestrator.py` (2857 deletions, 30 insertions)
- `src/worker/hybrid_v2/hybrid/routes/__init__.py`
- `src/worker/hybrid_v2/router/main.py`
- `src/worker/hybrid_v2/hybrid/routes/route_1_vector.py` (deleted)

**Testing:**
- ✅ Syntax validation passed
- ⏳ Runtime testing pending

---

### Task 1b: Remove Azure AI Search Dependency
**Status:** ✅ Complete  
**Commit:** `44a40b6`  
**Date:** January 31, 2026

**Changes:**
- Removed `azure-search-documents==11.6.0` from requirements.txt

**Files Modified:**
- `graphrag-orchestration/requirements.txt`

**Remaining Work:**
- Remove Azure Search from infra/main.bicep
- Remove Azure Search from infra/core/security/role-assignments.bicep

---

## In Progress Tasks 🔄

None currently.

---

## Not Started Tasks ⏳

### Task 1c: Remove Azure Search from Infra
**Status:** ⏳ Not Started  
**Effort:** 0.5 day

**Required Changes:**
- Remove `azureSearchEndpoint` parameter from `infra/main.bicep`
- Remove `AZURE_SEARCH_ENDPOINT` environment variable
- Remove `AZURE_SEARCH_INDEX_NAME` environment variable
- Remove `VECTOR_STORE_TYPE=azure_search` environment variable
- Remove `azureSearchName` parameter from `infra/core/security/role-assignments.bicep`
- Remove Azure Search role assignment
- Remove Azure Search service reference

**Files to Modify:**
- `infra/main.bicep` (lines 28, 130-139)
- `infra/core/security/role-assignments.bicep` (lines 6, 28-30, 77-80)

---

### Task 1d: Add Cosmos DB to Infra
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Create `infra/core/database/cosmos-db.bicep` module
- Add Cosmos DB account (serverless)
- Add `chat_history` container (partition key: `/user_id`, TTL: 90 days)
- Add `usage` container (partition key: `/partition_id`, TTL: 90 days)
- Add Cosmos DB connection string to Container App environment
- Add role assignment for Container App managed identity

**Environment Variables:**
```
COSMOS_DB_ENDPOINT=https://<account>.documents.azure.com
COSMOS_DB_DATABASE_NAME=graphrag
```

---

### Task 1e: Add Redis to Infra
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Create `infra/core/cache/redis.bicep` module
- Provision Azure Cache for Redis (Basic C0 tier)
- Add Redis connection string to Container App environment
- Configure Redis for async job queue

**Environment Variables:**
```
REDIS_CONNECTION_STRING=<redis-connection>
REDIS_QUEUE_NAME=graphrag_jobs
```

---

### Task 1f: Expand src/core/ Module
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Structure:**
```
src/core/
├── __init__.py
├── config.py              # ✅ Exists
├── models/
│   ├── __init__.py
│   ├── usage.py          # UsageRecord, UsageType
│   ├── chat.py           # ChatSession, ChatMessage
│   └── folder.py         # Folder
├── services/
│   ├── __init__.py
│   ├── usage_tracker.py  # UsageTracker
│   └── cosmos_client.py  # CosmosDBClient
└── logging/
    ├── __init__.py
    └── structured.py     # Structured logging setup
```

---

### Task 1g: Create UsageTracker Service
**Status:** ⏳ Not Started  
**Effort:** 2 days

**Implementation:**
- Fire-and-forget pattern using FastAPI `BackgroundTasks`
- Batch writes to Cosmos DB (configurable interval)
- Fallback to structlog if Cosmos unavailable
- Support for LLM, embedding, and Document Intelligence usage types

**Files to Create:**
- `src/core/services/usage_tracker.py`
- `src/core/models/usage.py`

---

### Task 1h: Instrument LLM Calls
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Wrap `llm.acomplete()` in `src/worker/services/llm_service.py`
- Extract `prompt_tokens`, `completion_tokens` from response
- Call `usage_tracker.log_usage()` with fire-and-forget pattern

---

### Task 1i: Instrument Embedding Calls
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Add tiktoken counting for OpenAI embeddings
- Extract `total_tokens` from Voyage API response
- Call `usage_tracker.log_usage()` for all embedding operations

**Files to Modify:**
- `src/worker/services/embedding_service.py`
- `src/worker/hybrid_v2/embeddings/voyage_embed.py`

---

### Task 2a: Add Runtime Config Endpoint
**Status:** ⏳ Not Started  
**Effort:** 0.5 day

**Implementation:**
```python
@router.get("/config")
async def get_config():
    return {
        "authType": os.getenv("AUTH_TYPE", "B2B"),
        "clientId": os.getenv("CLIENT_ID"),
        "authority": os.getenv("AUTHORITY"),
        "features": {
            "showAdminPanel": os.getenv("AUTH_TYPE") == "B2B",
            "showFolders": True
        }
    }
```

**Files to Create:**
- `src/api_gateway/routers/config.py`

---

### Task 2b: Create Folder Schema
**Status:** ⏳ Not Started  
**Effort:** 2 days

**Neo4j Schema:**
```cypher
CREATE CONSTRAINT folder_id IF NOT EXISTS FOR (f:Folder) REQUIRE f.id IS UNIQUE;
CREATE INDEX folder_partition IF NOT EXISTS FOR (f:Folder) ON (f.group_id);
(:Folder)-[:SUBFOLDER_OF]->(:Folder)
(:Document)-[:IN_FOLDER]->(:Folder)
```

**API Endpoints:**
- `POST /folders` - Create folder
- `GET /folders` - List folders
- `GET /folders/{id}` - Get folder details
- `PUT /folders/{id}` - Update folder
- `DELETE /folders/{id}` - Delete folder (cascade)

**Files to Create:**
- `src/api_gateway/routers/folders.py`
- `src/core/models/folder.py`

---

### Task 2c: Add JWT Validation Middleware
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Implementation:**
- Validate JWT tokens from Easy Auth headers
- Extract `group_id` from `groups[0]` (B2B) or `user_id` from `oid` (B2C)
- Replace current `X-Group-ID` header trust with token-based claims
- Add to `src/api_gateway/middleware/auth.py`

---

### Task 2d: Create Chat Compatibility Router
**Status:** ⏳ Not Started  
**Effort:** 2 days

**Implementation:**
- `POST /chat` - Transform to internal GraphRAG query
- `POST /chat/stream` - SSE streaming response
- `GET /chat/status/{job_id}` - Poll async job status
- Adapter layer to map azure-search-openai-demo contract to internal format

**Files to Create:**
- `src/api_gateway/routers/chat_compat.py`

---

### Task 2e: Git Subtree Frontend
**Status:** ⏳ Not Started  
**Effort:** 0.5 day

**Commands:**
```bash
git subtree add --prefix src/frontend \
  https://github.com/Azure-Samples/azure-search-openai-demo.git \
  main --squash
```

---

### Task 3a: Split API/Worker Containers
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Create separate Dockerfiles for API and Worker
- Update `infra/main.bicep` to provision two Container Apps
- Configure shared Redis queue for communication
- Update `azure.yaml` for multi-service deployment

---

### Task 3b: Easy Auth Configuration
**Status:** ⏳ Not Started  
**Effort:** 1 day

**Required Changes:**
- Configure Entra ID authentication for B2B Container App
- Configure Entra External ID authentication for B2C Container App
- Update `infra/main.bicep` with auth settings

---

### Task 3c: Dashboard UI
**Status:** ⏳ Not Started  
**Effort:** 3-5 days

**Implementation:**
- Admin dashboard (usage by group, top users, cost projections)
- User dashboard (personal usage, query history)
- Integrate with React frontend

---

## Dependencies & Blockers

| Task | Depends On | Blocker |
|------|------------|---------|
| 1g (UsageTracker) | 1d (Cosmos DB) | ⚠️ Need Cosmos provisioned |
| 1h (LLM instrumentation) | 1g (UsageTracker) | ⚠️ Need tracker service |
| 1i (Embedding instrumentation) | 1g (UsageTracker) | ⚠️ Need tracker service |
| 2d (Chat router) | 2e (Frontend) | ⚠️ Need contract definition |
| 3a (Container split) | 1e (Redis) | ⚠️ Need job queue |
| 3c (Dashboard) | 1g (UsageTracker) | ⚠️ Need usage data |

---

## Next Steps

### Immediate (Can Start Now)
1. ✅ Task 1c: Remove Azure Search from infra
2. Task 1d: Add Cosmos DB to infra
3. Task 1e: Add Redis to infra
4. Task 1f: Expand src/core/ structure

### After Infrastructure
5. Task 1g: Create UsageTracker service
6. Task 1h-1i: Instrument LLM/embedding calls
7. Task 2a: Add runtime config endpoint
8. Task 2b: Create folder schema

### After Core Features
9. Task 2c: Add JWT validation
10. Task 2e: Git subtree frontend
11. Task 2d: Chat compatibility router
12. Task 3a: Split containers
13. Task 3b: Easy Auth
14. Task 3c: Dashboard UI

---

## Testing Plan

### Unit Tests
- [ ] Route 2/3/4 handlers work without Route 1
- [ ] UsageTracker fire-and-forget pattern
- [ ] Folder CRUD operations
- [ ] JWT validation middleware

### Integration Tests
- [ ] Full query flow through 3 routes
- [ ] Cosmos DB write/read for usage records
- [ ] Redis job queue for async operations
- [ ] Frontend config endpoint

### Deployment Tests
- [ ] Build succeeds without azure-search-documents
- [ ] Container Apps deploy successfully
- [ ] Auth flow works for B2B and B2C
- [ ] Usage tracking captures all metrics

---

*Implementation started: January 31, 2026*
*Last updated: January 31, 2026*
