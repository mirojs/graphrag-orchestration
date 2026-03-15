# Handover — 2026-03-11: Auto-Resume, Pipeline Resilience & Monitoring

## Summary

Extended the pipeline resilience system with **auto-resume on container restart** so that zombie "analyzing" folders are automatically detected and re-triggered without manual intervention. Also monitored a live indexing run that confirmed the pipeline is still crashing silently mid-run — the auto-resume feature is the fix for this pattern.

## What Was Done

### 1. Auto-Resume on Container Startup (commit `bc1ca772`)
- **File**: `src/api_gateway/main.py`
- Added `_auto_resume_zombie_analyses(app)` function launched via `asyncio.create_task()` right before the lifespan `yield`
- Logic: waits 10s after startup, queries Neo4j for folders with `analysis_status = "analyzing"`, resolves blobs from storage, and kicks off `_run_folder_analysis` for each zombie folder
- Combined with existing file-level resume + step checkpoint, this means fully automatic recovery

### 2. Pipeline Run Monitoring
- User triggered analysis at ~01:24 UTC on the old deploy (`a085b962`)
- Monitored for 13+ minutes: folder stayed at 0/6 files processed, no checkpoint written, entity/sentence counts unchanged (981/304)
- Container was healthy (200 on /health), but no analysis logs in the 300-line log window — all consumed by `/folders` polling (~6s interval)
- Conclusion: pipeline crashed silently with no error captured in Neo4j

### 3. Build & Deploy
- Built and deployed `bc1ca772` to all 3 container apps (graphrag-api, graphrag-api-b2c, graphrag-worker)
- Auto-resume triggered on startup but **hit an import error** (see Known Bug below)

## Known Bug — MUST FIX Before Next Session

### Import Error in Auto-Resume
```
auto_resume: top-level error: cannot import name 'get_graph_driver' from 'src.worker.services.graph_service'
```

**Root Cause**: `_auto_resume_zombie_analyses()` in `main.py` imports `get_graph_driver` from `src.worker.services.graph_service`, but that function doesn't exist there. It's a local helper defined in `src/api_gateway/routers/folders.py:75`.

**Fix**: Replace the import in `main.py` with either:
```python
# Option A: Use GraphService singleton directly
from src.worker.services.graph_service import GraphService
driver = GraphService().driver
```
or
```python
# Option B: Import from folders.py
from src.api_gateway.routers.folders import get_graph_driver
driver = get_graph_driver()
```

**Location**: `src/api_gateway/main.py`, inside `_auto_resume_zombie_analyses()`, line ~67

### Silent Pipeline Crashes
The pipeline continues to crash silently during the file processing loop (`_run_folder_analysis`). The try/except in `_run_folder_analysis` should write `analysis_error` to the folder node, but in this run it stayed `None` — suggesting the crash happened in a way that bypassed the error handler (possibly the entire background task was killed, or an unhandled exception in an async context).

**Potential improvement**: Add a heartbeat mechanism — the pipeline periodically updates a timestamp on the folder node, and a separate monitor detects stale heartbeats.

## Current State of Neo4j Data

| Metric | Value |
|--------|-------|
| Folder status | `analyzing` (zombie — needs cancel or auto-resume) |
| Files processed | 0/6 |
| Pipeline checkpoint | None |
| Entities | 981 (from previous partial runs) |
| Sentences | 304 |
| Relationships | 30,503 |
| Communities | 0 |

Group ID: `e8944f39-e7f0-4434-a3c9-5366e036ffb5`
Partition ID: `ed4d7ff4-6760-4281-8dcc-e0d9db54682f`

## Deployed Version
- **All 3 apps**: `bc1ca772` (`graphragacr12153.azurecr.io/graphrag-api:bc1ca772`)
- Auto-resume is deployed but non-functional due to import error (fails gracefully — no crash, just logs warning)

## Files Modified This Session
| File | Change |
|------|--------|
| `src/api_gateway/main.py` | Added `_auto_resume_zombie_analyses()` + `asyncio.create_task()` in lifespan startup |

## Resume Checklist
1. **Fix the import error** in `_auto_resume_zombie_analyses()` in `main.py`
2. **Reset zombie folder** status to `not_analyzed` (or fix auto-resume to handle it)
3. **Build & deploy** the fix
4. **Monitor** the auto-resumed pipeline run to completion
5. **Investigate** why `_run_folder_analysis` error handler didn't capture the crash — consider adding heartbeat monitoring
6. Consider reducing frontend `/folders` polling interval (currently ~6s floods logs)

## Architecture Recap (from prior sessions)

### 3-Layer Pipeline Resilience
1. **Layer 1 — Neo4j Retry**: `_resilient_session()` with exponential backoff (5→80s) for session creation; `max_transaction_retry_time=300s` for native transaction retry
2. **Layer 2 — Step Checkpoint**: 8 ordered stages stored on GroupMeta node; `_step_done()` skips completed stages on resume
3. **Layer 3 — File Resume**: `_run_folder_analysis` reads `analysis_files_processed` and skips that many files

### Auto-Resume (NEW — needs import fix)
4. **Layer 4 — Startup Detection**: On container restart, queries for zombie `analyzing` folders and auto-triggers `_run_folder_analysis`

### Key Technical Decisions
- All Neo4j writes use MERGE (idempotent) — safe to re-run without cleanup
- BackgroundTasks.add_task() required (not threading.Thread) for async HTTP client compatibility
- Heavy sync ops wrapped in `asyncio.to_thread()` to avoid blocking health probes
- `max_connection_lifetime=300` forces Neo4j pool recycling for Aura
