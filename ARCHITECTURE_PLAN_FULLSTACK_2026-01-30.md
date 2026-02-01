# GraphRAG Full-Stack Architecture Plan

**Date:** January 30, 2026  
**Status:** Approved  
**Author:** Architecture Planning Session

---

## Executive Summary

A modular, enterprise-ready architecture for GraphRAG with a servable API (APIM-ready), integrated frontend (azure-search-openai-demo), and continuous algorithm development (V2+). Route 1 (Vector RAG) is deprecated; the system uses Routes 2-4 only.

---

## Phase 1: Foundation & Cleanup (Week 1-2)

### 1. Deprecate Route 1 Formally
- Remove Route 1 endpoints from `src/api_gateway/routers/hybrid.py`
- Update router logic to reject `route_preference=1`
- Add deprecation notices in API docs
- Update `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` to reflect 3-route reality (Routes 2/3/4 only)

### 2. Restructure Repo for Modularity ✅ COMPLETE (2026-01-31)
Reorganize into clear boundaries:
```
/
├── src/
│   ├── core/           # Shared: Pydantic models, DB connectors, utils
│   ├── api_gateway/    # FastAPI app, auth, compat layer, Redis producer
│   ├── worker/         # Algorithm execution: Routes 2-4, V1/V2 handlers
│   └── frontend/       # Copied from azure-search-openai-demo
├── infra/              # Bicep: API container, Worker container, Redis, Cosmos
└── scripts/            # Test, benchmark, migration scripts
```
**Status:** Deployed to production, all imports migrated. See `RESTRUCTURE_COMPLETE_2026-01-31.md`.

### 3. Extract Shared Models to `src/core/`
- Move Pydantic request/response models from `src/worker/hybrid_v2/orchestrator.py` into shared module
- Ensure API Gateway and Worker use identical contracts

---

## Phase 2: Authentication & Infrastructure (Week 2-3)

### 4. Implement Single Auth System (Entra ID + Easy Auth)
- Configure Azure Container Apps Easy Auth in `infra/main.bicep` with Entra ID provider
- Add JWT validation middleware to FastAPI in `src/api_gateway/main.py`
- Extract `oid`, `groups`, and map to `group_id` for multi-tenancy

### 5. Provision Cosmos DB for Chat History
Add Cosmos DB (Serverless) to `infra/` with:
- Container: `chat_history`
- Partition key: `/user_id`
- Fields: `conversation_id`, `messages[]`, `timestamp`, `group_id`
- TTL: 90 days (configurable)

### 6. Add Chat History API Endpoints
Create `src/api_gateway/routers/chat_history.py` with:
- `GET /chat_history/sessions` — List user's conversations
- `GET /chat_history/sessions/{id}` — Retrieve conversation
- `POST /chat_history` — Save conversation
- `DELETE /chat_history/sessions/{id}` — Delete conversation

---

## Phase 3: Frontend Integration (Week 3-4)

### 7. Copy azure-search-openai-demo Frontend
- Clone `src/frontend/` from the demo repo into `src/frontend/`
- Keep Vite config that builds to `backend/static/` for single-container deployment initially

### 8. Create FastAPI `/chat` Compat Router
Add `src/api_gateway/routers/chat_compat.py` that:
- Exposes `POST /chat` and `POST /chat/stream` matching demo's contract
- Transforms `{messages, context, session_state}` → `{query, group_id, route_preference}`
- Calls existing `HybridPipelineOrchestrator`
- Transforms response → `{message, context.data_points, context.thoughts}`

### 9. Implement Thoughts Panel Mapping
Map GraphRAG internals to demo's `context.thoughts[]`:
```python
thoughts = [
    {"title": "Route Selection", "description": f"Using {route_used} for this query"},
    {"title": "Entities Found", "description": entities_list},
    {"title": "Communities Matched", "description": community_summaries},
    {"title": "Retrieval Strategy", "description": reasoning_explanation}
]
```

### 10. Update CORS Configuration
- Expand CORS in `src/api_gateway/main.py` from `localhost:3000` to include production domains and Azure Static Web Apps URL

### 11. Adapt Frontend Settings Panel
Modify `src/frontend/src/components/Settings/` to expose GraphRAG options:
- Route preference: Auto / Local Search (2) / Global Search (3) / DRIFT (4)
- Algorithm version: V1 / V2 toggle
- Group selector (for multi-tenant users)
- Remove irrelevant demo options (semantic ranker, image search, etc.)

---

## Phase 4: Async/Streaming for Long Queries (Week 4-5)

### 12. Add Redis for Job Queue
- Provision Azure Cache for Redis (Basic tier) in `infra/`
- Configure connection in `src/core/config.py`

### 13. Implement Hybrid Sync/Async Pattern
In `src/api_gateway/routers/chat_compat.py`:
- **Route 2 (Local Search):** Synchronous — typically <5s, return immediately
- **Routes 3/4 (Global/DRIFT):** Async with streaming thoughts:
  1. Return `202 Accepted` with `job_id` for non-streaming requests
  2. For `/chat/stream`, use NDJSON to stream thoughts progressively:
     ```
     {"delta": {"role": "assistant", "content": ""}, "context": {"thoughts": [{"title": "Starting Global Search..."}]}}
     {"delta": {"role": "assistant", "content": ""}, "context": {"thoughts": [{"title": "Found 12 communities"}]}}
     {"delta": {"role": "assistant", "content": "Based on..."}, "context": {...}}
     ```

### 14. Add Job Status Endpoint
- Create `GET /chat/status/{job_id}` for polling pattern (fallback when streaming unavailable)

---

## Phase 5: Container Separation & Scaling (Week 5-6)

### 15. Split into API + Worker Containers
Update `azure.yaml` to define two services:
```yaml
services:
  api:
    project: ./src/api_gateway
    host: containerapp
    # 0.5 CPU, 1GB RAM, scale on HTTP requests
  worker:
    project: ./src/worker
    host: containerapp
    # 2 CPU, 4GB RAM, scale on Redis queue length
```

### 16. Configure Internal Communication
- API container enqueues jobs to Redis
- Worker container polls and processes
- Results stored in Redis with TTL
- API retrieves and returns to client

### 17. Update Bicep for Dual Containers
Modify `infra/main.bicep` to provision:
- API Container App (external ingress, Easy Auth)
- Worker Container App (internal only, no ingress)
- Shared Container Apps Environment
- Redis connection shared via secrets

---

## Phase 6: V2 Algorithm Enablement (Week 6-7)

### 18. Execute V2 Reindex
- Run reindexing script to populate `embedding_v2` on all TextChunk and Entity nodes
- Validate with benchmark suite in `scripts/`

### 19. Create V2-Ready Checklist
Gate production enablement on:
- [ ] All documents have `embedding_v2` populated
- [ ] Voyage API key configured and tested
- [ ] Benchmark shows V2 ≥ V1 accuracy on test set
- [ ] Rollback procedure documented

### 20. Enable V2 with Feature Flag
- Set `VOYAGE_V2_ENABLED=true` in production after checklist passes
- Monitor for 48h before removing V1 fallback

---

## Phase 7: APIM & External API (Week 7-8)

### 21. Provision APIM (When Needed)
Add Azure API Management (Consumption tier) to `infra/` only when external clients require:
- Rate limiting
- API key management
- Developer portal
- Analytics

### 22. Configure APIM Policies
Create policies for:
- External clients: API key validation, rate limits (100 req/min), quota
- Internal (frontend): Passthrough to Container App (no APIM overhead)

### 23. Dual Ingress Pattern
API Container accepts:
- Direct calls from frontend (Easy Auth token in `Authorization` header)
- APIM calls from external clients (`Ocp-Apim-Subscription-Key` header)

---

## Phase 8: API Versioning & Algorithm Switching (Ongoing)

### Version Isolation Strategy (Frozen Snapshots)

**Design Principle:** Each algorithm version is a **frozen snapshot** - fully isolated code that never changes after release. This follows industry best practices (Stripe, AWS, Google APIs) for enterprise stability.

#### Why Isolation Over Sharing

| Approach | Pros | Cons |
|----------|------|------|
| **Shared Code** | DRY, single bug fix | Coupling risk - V3 change can break V2 |
| **Isolated/Copied** | Zero regression, clean rollback | Duplication, patches need N copies |

**Decision:** Isolated versions for algorithm code, shared infrastructure for connections/auth.

#### Directory Structure

```
src/worker/
├── hybrid/             # V1 - DEPRECATED, frozen, delete at sunset (2026-06)
│   ├── orchestrator.py
│   ├── routes/
│   ├── pipeline/
│   └── retrievers/
├── hybrid_v2/          # V2 - STABLE, frozen when V3 ships to production
│   ├── orchestrator.py
│   ├── routes/
│   ├── pipeline/
│   └── retrievers/
├── hybrid_v3/          # V3 - FUTURE, full copy of V2, then evolve
│   ├── orchestrator.py  # Copied from v2, modified
│   ├── routes/
│   ├── pipeline/
│   └── retrievers/
└── services/           # SHARED - infrastructure only (DB connections, auth)

src/core/               # SHARED - across all versions
├── config.py           # DB connections, env vars
├── auth.py             # JWT validation
├── logging.py          # Structured logging
├── models/             # Base Pydantic models (request/response contracts)
└── db/
    ├── neo4j.py        # Connection pool
    └── cosmos.py       # Chat history
```

#### Version Creation Protocol

When creating V(N+1):
1. **Copy entire directory:** `cp -r src/worker/hybrid_vN/ src/worker/hybrid_v{N+1}/`
2. **Update imports:** Change all `hybrid_vN` → `hybrid_v{N+1}` within copied files
3. **Develop independently:** V(N+1) changes cannot affect V(N)
4. **Freeze V(N):** Once V(N+1) is stable, V(N) code is frozen forever

#### Migration Note (V1/V2 Current State)

V1 and V2 currently share some code due to organic development. **Do not refactor** - V1 is deprecated and will be deleted at sunset. The isolation strategy applies from V3 onwards:
- V1 → Leave as-is (deprecated, sunset 2026-06)
- V2 → Freeze when V3 ships
- V3+ → Full isolation from creation

### 24. Implement URL-based API Versioning
Structure API routes with explicit versions:
```
/api/v1/chat          → Algorithm V1 (OpenAI embeddings) - DEPRECATED
/api/v2/chat          → Algorithm V2 (Voyage embeddings) - CURRENT
/api/v3/chat          → Algorithm V3 (future)            - PREVIEW
/chat                 → Alias to current stable version (v2)
```

Create versioned routers in `src/api_gateway/routers/`:
```
routers/
├── v1/              # Deprecated, maintained for backward compat
│   └── chat.py
├── v2/              # Current stable
│   └── chat.py
├── v3/              # Preview/beta
│   └── chat.py
└── chat_compat.py   # Routes to current stable version
```

### 25. Add Version Negotiation Headers
Support client-requested versions:
```
Request:  X-API-Version: 2024-01-30 (date-based)
Request:  X-Algorithm-Version: v2 (explicit)
Response: X-API-Version-Used: v2
Response: X-Algorithm-Version-Used: v2-voyage
```

### 26. Create Algorithm Version Registry
Add `src/core/algorithm_registry.py`:
```python
ALGORITHM_VERSIONS = {
    "v1": {
        "status": "deprecated",
        "embedding_model": "text-embedding-3-large",
        "embedding_dim": 3072,
        "routes": [2, 3, 4],
        "handler": "hybrid.orchestrator.HybridPipelineOrchestrator",
        "sunset_date": "2026-06-01"
    },
    "v2": {
        "status": "stable",
        "embedding_model": "voyage-context-3",
        "embedding_dim": 2048,
        "routes": [2, 3, 4],
        "handler": "hybrid_v2.orchestrator.HybridPipelineOrchestratorV2",
        "release_date": "2026-01-15"
    },
    "v3": {
        "status": "preview",
        "feature_flag": "V3_PREVIEW_ENABLED",
        "handler": "hybrid_v3.orchestrator.HybridPipelineOrchestratorV3"
    }
}
```

### 27. Implement Feature Flags for Version Control
Environment-based version management:
```
# Version availability
ALGORITHM_V1_ENABLED=true       # Deprecated but available
ALGORITHM_V2_ENABLED=true       # Current stable
ALGORITHM_V3_PREVIEW_ENABLED=false  # Not yet available

# Default version (when client doesn't specify)
DEFAULT_ALGORITHM_VERSION=v2

# Canary rollout (% of traffic to new version)
ALGORITHM_V3_CANARY_PERCENT=0   # 0-100
```

### 28. Add Version Switching API for Admins
Create `src/api_gateway/routers/admin.py`:
```
GET  /admin/versions              → List all versions and status
POST /admin/versions/default      → Set default version
POST /admin/versions/{v}/enable   → Enable a version
POST /admin/versions/{v}/disable  → Disable a version
POST /admin/versions/{v}/canary   → Set canary percentage
```

### 29. Implement Blue/Green Deployment for Versions
Container Apps revision management:
- Each algorithm version = separate revision label (`v2-stable`, `v3-preview`)
- Traffic splitting via Container Apps: 95% → v2, 5% → v3 (canary)
- Instant rollback: shift 100% traffic back to previous revision
- Add to `infra/main.bicep`:
  ```bicep
  revisionSuffix: 'v2-${buildNumber}'
  trafficWeight: [
    { revisionName: 'api-v2-stable', weight: 95 }
    { revisionName: 'api-v3-preview', weight: 5 }
  ]
  ```

### 30. Create Version Migration Runbook
Document in `docs/VERSION_MIGRATION.md`:
```
## Promoting V3 to Stable
1. Ensure V3 reindex complete (check /admin/versions)
2. Run benchmark: scripts/benchmark_v3.py
3. Enable canary: POST /admin/versions/v3/canary {"percent": 10}
4. Monitor for 48h (check error rates, latency)
5. Increase canary: 10% → 25% → 50% → 100%
6. Update DEFAULT_ALGORITHM_VERSION=v3
7. Mark V2 as deprecated (6-month sunset)
8. Update frontend default in Settings panel
```

---

## Phase 9: Upstream Sync Strategy (Ongoing)

### 31. Use Git Subtree for Frontend
Instead of copying, use subtree to maintain upstream link:
```bash
# Initial add
git subtree add --prefix=src/frontend \
  https://github.com/Azure-Samples/azure-search-openai-demo.git \
  main --squash

# Future updates
git subtree pull --prefix=src/frontend \
  https://github.com/Azure-Samples/azure-search-openai-demo.git \
  main --squash
```

### 32. Isolate Customizations in Overlay Structure
Separate upstream code from customizations:
```
src/frontend/
├── upstream/           # Pure copy from azure-search-openai-demo (don't edit)
│   └── app/frontend/   # Git subtree target
├── overrides/          # Our customizations (patch files or replacement components)
│   ├── components/
│   │   └── Settings/   # Custom GraphRAG settings
│   ├── api/
│   │   └── models.ts   # Extended models for GraphRAG
│   └── pages/
│       └── chat/       # Modified Chat.tsx
└── build.sh            # Merges upstream + overrides → dist/
```

### 33. Track Upstream Version
Add `src/frontend/UPSTREAM_VERSION.md`:
```markdown
# Upstream Tracking

**Repository:** Azure-Samples/azure-search-openai-demo
**Current Base:** commit abc123 (2026-01-15)
**Last Sync:** 2026-01-20

## Applied Patches
- Settings panel: Added route selector, V1/V2 toggle
- API models: Extended ChatAppResponse with route_used, entities
- Chat.tsx: Modified makeApiRequest for GraphRAG contract

## Known Divergences
- Removed: Semantic ranker options (not applicable)
- Removed: Image search (not supported)
- Added: Group selector for multi-tenancy
```

### 34. Create Sync Script
Add `scripts/sync_upstream.sh`:
```bash
#!/bin/bash
# Sync upstream and report conflicts

UPSTREAM_REPO="https://github.com/Azure-Samples/azure-search-openai-demo.git"
UPSTREAM_BRANCH="main"

echo "Fetching upstream..."
git subtree pull --prefix=src/frontend/upstream \
  $UPSTREAM_REPO $UPSTREAM_BRANCH --squash

echo "Checking for conflicts with overrides..."
# Compare upstream changes against our override files
for file in src/frontend/overrides/**/*; do
  upstream_file="src/frontend/upstream/${file#src/frontend/overrides/}"
  if [ -f "$upstream_file" ]; then
    if ! diff -q "$file" "$upstream_file" > /dev/null 2>&1; then
      echo "⚠️  CONFLICT: $file differs from upstream"
    fi
  fi
done

echo "Sync complete. Review conflicts above."
```

### 35. Set Up Upstream Monitoring
GitHub Action to check for upstream updates weekly:
```yaml
# .github/workflows/upstream-check.yml
name: Check Upstream Updates
on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday 9am
  workflow_dispatch:

jobs:
  check-upstream:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check for upstream updates
        run: |
          CURRENT=$(cat src/frontend/UPSTREAM_VERSION.md | grep "Current Base:" | cut -d' ' -f3)
          LATEST=$(git ls-remote https://github.com/Azure-Samples/azure-search-openai-demo.git HEAD | cut -f1)
          if [ "$CURRENT" != "$LATEST" ]; then
            echo "::warning::Upstream has new commits. Current: $CURRENT, Latest: $LATEST"
            # Create issue or PR
          fi
```

### 36. Document Breaking Changes Protocol
When upstream has breaking changes:
1. Review upstream changelog/commits
2. Test sync in feature branch
3. Update override files if APIs changed
4. Run integration tests
5. Update `UPSTREAM_VERSION.md`
6. PR with "upstream-sync" label for review

---

## Phase 10: CI/CD Pipeline (Week 8-9)

### 37. Create GitHub Actions Workflow
Add `.github/workflows/deploy.yml`:
```yaml
name: Build & Deploy
on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'infra/**'
  workflow_dispatch:
    inputs:
      algorithm_version:
        description: 'Algorithm version to deploy'
        required: true
        default: 'v2'
        type: choice
        options: [v1, v2, v3]
      environment:
        description: 'Target environment'
        required: true
        default: 'staging'
        type: choice
        options: [staging, production]

jobs:
  build-api:
    # Build API container with version tag
  build-worker:
    # Build Worker container with algorithm version
  build-frontend:
    # Merge upstream + overrides, build static
  deploy-staging:
    # Deploy to staging, run smoke tests
  deploy-production:
    needs: [deploy-staging]
    if: github.event.inputs.environment == 'production'
    # Blue/green deploy with canary
```

### 38. Implement Version-Tagged Container Images
Tagging strategy:
```
graphrag-api:v2.1.0-20260130        # API version + build date
graphrag-worker:v2-algo-20260130    # Worker with algorithm version
graphrag-worker:v3-algo-20260130    # Worker with V3 algorithm
```
Multiple worker images allow running V2 and V3 simultaneously.

### 39. Add Rollback Automation
Script `scripts/rollback.sh`:
```bash
#!/bin/bash
# Instant rollback to previous stable version

PREVIOUS_REVISION=${1:-"api-v2-stable"}

az containerapp revision activate \
  --name graphrag-api \
  --resource-group $RG \
  --revision $PREVIOUS_REVISION

az containerapp ingress traffic set \
  --name graphrag-api \
  --resource-group $RG \
  --revision-weight $PREVIOUS_REVISION=100

echo "Rolled back to $PREVIOUS_REVISION"
```

---

## Architecture Diagram (Final State)

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Users                                    │
└─────────────────────────────────────────────────────────────────────┘
          │                                          │
          ▼                                          ▼
┌───────────────────────┐                 ┌───────────────────────┐
│   Your Frontend       │                 │   External Clients    │
│   (React + MSAL)      │                 │   (Partners/APIs)     │
│   Served from API     │                 │                       │
└──────────┬────────────┘                 └──────────┬────────────┘
           │                                         │
           │ /chat, /chat/stream                     │ API Key
           │ (Bearer token)                          ▼
           │                              ┌───────────────────────┐
           │                              │       APIM            │
           │                              │   (Rate limits,       │
           │                              │    Analytics)         │
           │                              └──────────┬────────────┘
           │                                         │
           ▼                                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     API Container App                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │ /chat (compat)  │  │ /chat_history   │  │ /hybrid/* (legacy)  │ │
│  │ /chat/stream    │  │ /config         │  │ /lifecycle/*        │ │
│  └────────┬────────┘  └─────────────────┘  └─────────────────────┘ │
│           │ Easy Auth (JWT validation)                              │
└───────────┼─────────────────────────────────────────────────────────┘
            │
            │ Redis Queue (async jobs)
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Worker Container App                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │ Route 2: Local  │  │ Route 3: Global │  │ Route 4: DRIFT      │ │
│  │ (LazyGraphRAG)  │  │ (Communities)   │  │ (Multi-hop)         │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘ │
│           │                    │                     │              │
│           ▼                    ▼                     ▼              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              V1 (OpenAI) / V2 (Voyage) Embeddings           │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Data Layer                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │   Neo4j      │  │  Cosmos DB   │  │   Azure AI Search        │  │
│  │  (Graph)     │  │  (History)   │  │   (RAPTOR index)         │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Versioning Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     API Container App                               │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    Version Router Middleware                     ││
│  │    Reads: X-Algorithm-Version header OR default from config      ││
│  └──────────────────────────┬──────────────────────────────────────┘│
│                             │                                        │
│     ┌───────────────────────┼───────────────────────┐               │
│     ▼                       ▼                       ▼               │
│  ┌──────────┐         ┌──────────┐           ┌──────────┐          │
│  │ /api/v1  │         │ /api/v2  │           │ /api/v3  │          │
│  │(deprecated)│       │ (stable) │           │ (preview)│          │
│  └──────────┘         └──────────┘           └──────────┘          │
└─────────────────────────────────────────────────────────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Worker V1       │  │ Worker V2       │  │ Worker V3       │
│ (OpenAI embed)  │  │ (Voyage embed)  │  │ (Future algo)   │
│ Traffic: 0%     │  │ Traffic: 95%    │  │ Traffic: 5%     │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Version Lifecycle Summary

| Stage | Availability | Traffic | Feature Flag | Actions |
|-------|--------------|---------|--------------|---------|
| **Development** | Internal only | 0% | `V3_DEV_ENABLED=true` | Local testing, unit tests |
| **Preview** | Opt-in via header | 0% default | `V3_PREVIEW_ENABLED=true` | Beta testers, explicit header |
| **Canary** | Percentage of traffic | 5-25% | `V3_CANARY_PERCENT=10` | A/B testing, monitoring |
| **Stable** | Default for all | 100% | `DEFAULT_VERSION=v3` | Full production |
| **Deprecated** | Opt-in only | 0% default | `V2_DEPRECATED=true` | Sunset warnings |
| **Sunset** | Disabled | 0% | `V2_ENABLED=false` | Returns 410 Gone |

---

## Risk Mitigations

| Risk | Mitigation |
|------|------------|
| Auth token mismatch between frontend/API | Use same Entra ID app registration; test OBO flow early |
| Long query timeouts (30s+) | Streaming thoughts + async polling; set Container Apps timeout to 120s |
| V2 reindex causes downtime | Run reindex in background; V1 remains active until V2 validated |
| Frontend/API contract drift | Shared Pydantic models in `src/core/`; integration tests |
| Redis single point of failure | Use Azure Cache for Redis with zone redundancy (Standard tier for prod) |
| Upstream breaking changes | Weekly sync checks, isolated overrides, conflict detection |

---

## Success Criteria

- [ ] Frontend loads and authenticates via MSAL
- [ ] `/chat` endpoint returns responses with working citations
- [ ] Thoughts panel shows route selection and retrieval steps
- [ ] Chat history persists across sessions
- [ ] Routes 3/4 stream progress without browser timeout
- [ ] V2 embeddings enabled with ≥ parity to V1 benchmarks
- [ ] External API clients can authenticate via APIM
- [ ] Clients can request specific algorithm version via header
- [ ] Admin can enable/disable versions without redeployment
- [ ] Canary deployment routes X% traffic to new version
- [ ] Rollback completes in <60 seconds
- [ ] Upstream sync runs weekly with conflict detection
- [ ] Customizations isolated from upstream code

---

## Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Web Framework** | FastAPI (not Quart) | Unified stack, better docs, already in use |
| **Frontend Source** | azure-search-openai-demo | Battle-tested, feature-rich, saves months |
| **Auth System** | MSAL/Entra ID (single system) | Enterprise-ready, enables RBAC |
| **Chat History** | Cosmos DB (Serverless) | Multi-device sync, low cost |
| **Container Strategy** | Same repo, separate containers | Independent scaling, no contract drift |
| **API Pattern** | Hybrid sync/async | Fast queries sync, slow queries stream |
| **Versioning** | URL + header-based | Explicit versions, graceful migration |
| **Version Isolation** | Frozen snapshots (copy, not share) | Zero regression risk, clean rollback, enterprise stability |
| **Upstream Sync** | Git subtree + overlays | Maintain upstream link, isolate changes |
| **Route 1** | Deprecated | Removed from production, 3-route system |

---

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Foundation | Week 1-2 | Route 1 deprecated, repo restructured |
| Phase 2: Auth & Infra | Week 2-3 | Easy Auth, Cosmos DB, history API |
| Phase 3: Frontend | Week 3-4 | Demo integrated, compat router, thoughts panel |
| Phase 4: Async/Streaming | Week 4-5 | Redis, streaming thoughts, job polling |
| Phase 5: Container Split | Week 5-6 | API + Worker containers, internal comms |
| Phase 6: V2 Enablement | Week 6-7 | Reindex complete, V2 in production |
| Phase 7: APIM | Week 7-8 | External API ready, rate limiting |
| Phase 8-10: Ongoing | Continuous | Versioning, upstream sync, CI/CD |

---

## Implementation Status (Updated 2026-02-01)

### ✅ Completed Phases

| Phase | Status | Commit | Key Files |
|-------|--------|--------|-----------|
| **Phase 1: Redis Backbone** | ✅ Complete | - | `src/core/services/redis_service.py` |
| **Phase 2: JWT Security** | ✅ Complete | - | `src/api_gateway/middleware/auth.py` |
| **Phase 3: Observability** | ✅ Complete | - | X-Correlation-ID headers |
| **Phase 4: Async/Streaming** | ✅ Complete | `1087b0a` | `src/api_gateway/routers/chat.py` |
| **Phase 5: Container Separation** | ✅ Complete | - | `graphrag-api` + `graphrag-worker` |
| **Phase 6/8: Algorithm Versioning** | ✅ Complete | `b46dc7d` | `src/core/algorithm_registry.py` |
| **Phase 9: Upstream Sync** | ✅ Complete | `8393f0e` | `frontend/UPSTREAM_VERSION.md` |
| **Phase 10: CI/CD Pipeline** | ✅ Complete | `e890624` | `.github/workflows/deploy.yml` |

### ⬜ Pending Phases

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 7: APIM** | ⬜ When Needed | For external API clients requiring rate limiting |

---

## Production Architecture (Current State)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Production                                   │
│                                                                      │
│  ┌───────────────────┐        ┌─────────────────────────────────┐   │
│  │   graphrag-api    │───────▶│      graphrag-worker            │   │
│  │  (external ingress)│        │     (internal only)             │   │
│  │                    │        │                                 │   │
│  │  - /chat           │  Redis │  - HybridPipeline               │   │
│  │  - /chat/stream    │◀──────▶│  - Routes 2/3/4                 │   │
│  │  - /chat/status    │  Queue │  - DEFAULT_ALGORITHM_VERSION=v2 │   │
│  │  - /health         │        │                                 │   │
│  └───────────────────┘        └─────────────────────────────────┘   │
│           │                                                          │
│           │ (Optional: for v3 testing)                              │
│           │                                                          │
│           │                    ┌─────────────────────────────────┐   │
│           └──────────────────▶│  graphrag-worker-preview        │   │
│             X-Algorithm-       │  (internal only)                │   │
│             Version: v3        │  DEFAULT_ALGORITHM_VERSION=v3   │   │
│                                └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Container Details

| Container | URL | Algorithm | Replicas |
|-----------|-----|-----------|----------|
| graphrag-api | `https://graphrag-api.salmonhill-*.swedencentral.azurecontainerapps.io` | - | 1 |
| graphrag-worker | Internal only | v2 (default) | 1 |
| graphrag-worker-preview | Internal only | v3 (optional) | 0-1 |

---

## Operations Guide

### Daily Operations

#### Check System Health
```bash
# API health
curl https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/health

# Check version headers
curl -I https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/health | grep -i x-
```

#### View Container Logs
```bash
# API logs
az containerapp logs show \
  --name graphrag-api \
  --resource-group rg-graphrag-feature \
  --follow

# Worker logs
az containerapp logs show \
  --name graphrag-worker \
  --resource-group rg-graphrag-feature \
  --follow
```

#### Check Worker Status
```bash
./scripts/preview-worker.sh status
```

### Deployment Operations

#### Deploy via GitHub Actions
1. Push to `main` branch (auto-deploys)
2. Or manually trigger: **Actions → Build & Deploy → Run workflow**
   - Choose algorithm version (v1/v2/v3)
   - Optionally enable `deploy_preview` for v3 testing

#### Manual Deployment
```bash
# Build and push images
az acr login --name graphragacr12153
docker build -t graphragacr12153.azurecr.io/graphrag-api:latest -f Dockerfile.api .
docker build -t graphragacr12153.azurecr.io/graphrag-worker:latest -f Dockerfile.worker .
docker push graphragacr12153.azurecr.io/graphrag-api:latest
docker push graphragacr12153.azurecr.io/graphrag-worker:latest

# Update containers
az containerapp update --name graphrag-api --resource-group rg-graphrag-feature \
  --image graphragacr12153.azurecr.io/graphrag-api:latest

az containerapp update --name graphrag-worker --resource-group rg-graphrag-feature \
  --image graphragacr12153.azurecr.io/graphrag-worker:latest
```

#### Rollback
```bash
# List available revisions
./scripts/rollback.sh --list

# Rollback to previous
./scripts/rollback.sh

# Rollback to specific revision
./scripts/rollback.sh graphrag-api--abc123
```

### Algorithm Version Testing

#### Testing v3 Before Production

**Step 1: Create Preview Worker**
```bash
./scripts/preview-worker.sh create v3
```

**Step 2: Enable API Routing to Preview**
```bash
# Set on API container
az containerapp update --name graphrag-api --resource-group rg-graphrag-feature \
  --set-env-vars "WORKER_PREVIEW_URL=http://graphrag-worker-preview" \
                 "ALGORITHM_V3_PREVIEW_ENABLED=true"
```

**Step 3: Test v3**
```bash
# Explicit v3 request
curl -X POST https://graphrag-api.../chat \
  -H "X-Algorithm-Version: v3" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "test query"}]}'
```

**Step 4: After Testing**
```bash
# Option A: Promote v3 to production
./scripts/preview-worker.sh promote

# Option B: Delete preview (v3 not ready)
./scripts/preview-worker.sh delete
```

### Version Header Reference

| Header | Direction | Values | Description |
|--------|-----------|--------|-------------|
| `X-Algorithm-Version` | Request | `v1`, `v2`, `v3` | Request specific version |
| `X-API-Version` | Request | `2024-01-30` | Request API version (date-based) |
| `X-Algorithm-Version-Used` | Response | `v1`, `v2`, `v3` | Actual version used |
| `X-API-Version-Used` | Response | `v2` | Actual API version |

### Environment Variables

#### API Container
| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_ALGORITHM_VERSION` | `v2` | Default when client doesn't specify |
| `ALGORITHM_V1_ENABLED` | `true` | Allow v1 requests |
| `ALGORITHM_V2_ENABLED` | `true` | Allow v2 requests |
| `ALGORITHM_V3_PREVIEW_ENABLED` | `false` | Allow v3 requests |
| `WORKER_PREVIEW_URL` | `null` | URL for preview worker (v3 testing) |

#### Worker Container
| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_ALGORITHM_VERSION` | `v2` | Algorithm version this worker runs |
| `VOYAGE_V2_ENABLED` | `true` | Use Voyage embeddings |
| `VOYAGE_API_KEY` | - | Voyage AI API key |

---

## Key Files Reference

### Core Implementation

| File | Purpose |
|------|---------|
| [src/api_gateway/routers/chat.py](src/api_gateway/routers/chat.py) | OpenAI-compatible chat endpoint, NDJSON streaming |
| [src/api_gateway/middleware/version.py](src/api_gateway/middleware/version.py) | X-API-Version and X-Algorithm-Version headers |
| [src/core/algorithm_registry.py](src/core/algorithm_registry.py) | Version definitions, feature flags, handler mapping |
| [src/core/config.py](src/core/config.py) | All configuration settings |
| [src/worker/hybrid_v2/orchestrator.py](src/worker/hybrid_v2/orchestrator.py) | HybridPipeline (v2 algorithm) |

### CI/CD & Operations

| File | Purpose |
|------|---------|
| [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Build & deploy pipeline |
| [.github/workflows/upstream-check.yml](.github/workflows/upstream-check.yml) | Weekly upstream monitoring |
| [scripts/preview-worker.sh](scripts/preview-worker.sh) | Manage preview workers |
| [scripts/rollback.sh](scripts/rollback.sh) | Instant rollback |
| [scripts/sync_upstream.sh](scripts/sync_upstream.sh) | Sync frontend from upstream |

### Documentation

| File | Purpose |
|------|---------|
| [frontend/UPSTREAM_VERSION.md](frontend/UPSTREAM_VERSION.md) | Track upstream azure-search-openai-demo |

---

*Document generated: January 30, 2026*

---

## Appendix A: V2 Configuration Reference (Updated 2026-01-30)

### Active Test Groups

| Group ID | Version | Embedding Model | Dimensions | Status |
|----------|---------|-----------------|------------|--------|
| `test-5pdfs-1769071711867955961` | V1 | OpenAI text-embedding-3-large | 3072 | Active |
| `test-5pdfs-v2-enhanced-ex` | V2 | Voyage voyage-context-3 | 2048 | Active |

### Vector Index Configuration

| Index Name | Label | Property | Dimensions | Status |
|------------|-------|----------|------------|--------|
| `entity_embedding` | `__Entity__` | `embedding` | 3072 (OpenAI) | ONLINE |
| `entity_embedding_v2` | `Entity` | `embedding_v2` | 2048 (Voyage) | ONLINE |
| `chunk_embedding` | `TextChunk` | `embedding` | 3072 | ONLINE |
| `chunk_embeddings_v2` | `TextChunk` | `embedding_v2` | 2048 | ONLINE |

### V2 Embedding Configuration

```python
# src/core/config.py
VOYAGE_MODEL_NAME: str = "voyage-context-3"  # NOT voyage-3 or voyage-3-large
VOYAGE_EMBEDDING_DIM: int = 2048
VOYAGE_V2_ENABLED: bool = True  # Set in .env
```

### KNN Status

**Current:** KNN disabled in V2 semantic beam search  
**TODO:** Enable KNN for better recall on entity expansion

---

## Appendix B: Changes Log (2026-01-30)

### Bug Fixes

1. **Missing Vector Index** (`entity_embedding_v2`)
   - **Symptom:** V2 semantic beam search returned 0 results
   - **Root Cause:** `src/api_gateway/main.py` only called V1 `initialize_schema()`, not V2
   - **Fix:** Added V2 schema initialization at app startup
   - **Commit:** `b2c6bd8`

2. **Logging Reserved Keyword Errors**
   - **Symptom:** `Logger._log() got unexpected keyword argument 'error'`
   - **Root Cause:** structlog reserves `error=` parameter
   - **Fix:** Changed to `logger.exception()` or `error_msg=`
   - **Files:** `tracing.py`, `intent.py`, `async_neo4j_service.py`

3. **Wrong Voyage Model in Test Scripts**
   - **Symptom:** `403 Model voyage-3 is not available for caller`
   - **Root Cause:** Test used `voyage-3` instead of `voyage-context-3`
   - **Fix:** Updated `scripts/test_v1_v2_comprehensive.py`

4. **API Embedding Version Mismatch**
   - **Symptom:** API used global `VOYAGE_V2_ENABLED` for all groups
   - **Root Cause:** V1 groups queried with V2 embeddings = dimension mismatch
   - **Fix:** Added `detect_embedding_version(group_id)` to auto-detect per group
   - **Commit:** `10878d0`

### Test Results (2026-01-30)

```
V1 vs V2 Comprehensive Test (voyage-context-3)
──────────────────────────────────────────────
Average Score:   V1: 93.3%  |  V2: 93.3%  |  TIE
Total Citations: V1: 138    |  V2: 144    |  V2 wins
Total Time:      V1: 252.3s |  V2: 241.0s |  V2 wins

Question Breakdown:
  CONSISTENCY_DEEP: V1=100%, V2=100% (TIE)
  Q-DR1:            V1=100%, V2=100% (TIE)
  Q-DR3:            V1=67%,  V2=67%  (TIE)
  Q-DR5:            V1=100%, V2=100% (TIE)
  Q-DR7:            V1=100%, V2=100% (TIE)
```

