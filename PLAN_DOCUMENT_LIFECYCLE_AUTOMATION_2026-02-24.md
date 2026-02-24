# Document Lifecycle Automation Plan

## Problem

When users interact with files through the app (upload, delete, rename, move, copy), only blob storage is updated. **Neo4j graph data is never synchronized**, meaning:

- **Upload**: File goes to blob storage but is never indexed → invisible to all search routes
- **Delete**: File removed from blob but graph data (Document, TextChunk, Entity, Community) remains → stale results
- **Rename**: Partially handled — `files.py` calls `graphrag_client.rename_document()` but only when the graphrag_client is available
- **Move**: Only blob path changes, no Neo4j impact (since `Document.source` URL doesn't update)
- **Copy**: Creates a blob duplicate but no corresponding graph data
- **Bulk re-index**: Requires developer scripts with hardcoded URLs

Meanwhile, the infrastructure is 80% built:
- `DocumentLifecycleService` exists with deprecate/restore/hard_delete/rename methods
- `GraphRAGClient.notify_document_uploaded()` exists but the backend endpoint (`/documents/notify-upload`) **does not exist**
- Redis worker queue is fully built (DLQ, locks, retries) but the `index` job handler is a TODO stub
- `LazyGraphRAGIndexingPipeline` works end-to-end when triggered manually

## Approach

Wire the existing components together so every file operation through the app automatically keeps Neo4j in sync.

## Architecture

```
Frontend (upload/delete/rename/move/copy)
    ↓
files.py router (blob storage operations)
    ↓ (NEW: after each operation)
DocumentSyncService (orchestrates graph sync)
    ↓
For upload: enqueue indexing job → Redis worker → LazyGraphRAGIndexingPipeline
For delete: DocumentLifecycleService.hard_delete_document()
For rename: DocumentLifecycleService.rename_document()  
For move:   Update Document.source in Neo4j
For copy:   enqueue indexing job for new document
```

## Todos

### 1. `create-doc-sync-service` — Create DocumentSyncService
**File**: `src/worker/hybrid_v2/services/document_sync.py`

A thin orchestration layer that translates file operations into graph operations:
- `on_file_uploaded(group_id, user_id, filename, blob_url)` → enqueue indexing job
- `on_file_deleted(group_id, user_id, filename)` → call DocumentLifecycleService.hard_delete_document()
- `on_file_renamed(group_id, old_filename, new_filename, new_blob_url)` → call DocumentLifecycleService.rename_document()
- `on_file_moved(group_id, filename, new_blob_url)` → update Document.source in Neo4j
- `on_file_copied(group_id, user_id, original_filename, new_filename, new_blob_url)` → enqueue indexing job for copy
- `on_bulk_reindex(group_id, user_id)` → list all blobs, enqueue indexing jobs for each

Design considerations:
- Document ID = filename (the natural identifier users see)
- Each method is idempotent (safe to retry)
- Async — file operations return immediately, graph sync happens in background
- Logs all operations for audit trail

### 2. `wire-files-router` — Wire files.py to DocumentSyncService  
**File**: `src/api_gateway/routers/files.py`

After each blob operation succeeds, call the corresponding DocumentSyncService method:
- `upload_files()` → after `blob_manager.upload_blob()`, call `on_file_uploaded()`
- `delete_uploaded()` / `delete_uploaded_bulk()` → after blob deletion, call `on_file_deleted()`
- `rename_uploaded()` → keep existing graphrag_client logic, also call `on_file_renamed()`
- `move_uploaded()` → after blob move, call `on_file_moved()`
- `copy_uploaded()` → after blob copy, call `on_file_copied()`

Key: All sync calls are fire-and-forget (BackgroundTasks) so file operations remain fast.

### 3. `wire-worker-indexing` — Wire worker's index job handler
**File**: `src/worker/main.py`

Replace the TODO stub in `process_job()` for `job_type == 'index'` with actual pipeline execution:
- Get the pipeline from `pipeline_factory.get_lazygraphrag_indexing_pipeline_v2()`
- Call `pipeline.index_documents()` with the job's payload
- Handle errors with proper DLQ semantics

### 4. `add-reindex-all-endpoint` — Bulk re-index endpoint
**File**: `src/api_gateway/routers/hybrid.py`

Add `POST /hybrid/index/reindex-all` endpoint:
- Lists all blobs for the user via `blob_manager.list_blobs()`
- Optionally deletes existing group data first (`neo4j_store.delete_group_data()`)
- Enqueues indexing jobs for each document
- Returns job tracking ID for status polling

### 5. `add-indexing-status-ui` — Frontend indexing status indicator
**Files**: Frontend components

After upload, show indexing status (queued → processing → complete/failed):
- Call `GET /hybrid/index/status/{job_id}` to poll
- Show a small status badge next to each file in the file list
- Consider: toast notification when indexing completes

### 6. `handle-edge-cases` — Edge case handling
- **Upload duplicate filename**: Check if document already exists in Neo4j, offer reindex vs skip
- **Delete while indexing**: Cancel in-progress indexing job before deleting
- **Rename cascading**: Ensure all TextChunk.document_id, Section.doc_id update
- **Move between groups**: Not currently supported (group_id is set at upload time)
- **Large file batch**: Rate-limit indexing jobs to avoid overwhelming the pipeline
- **Partial failure**: If blob upload succeeds but indexing enqueue fails, log for retry

## Notes

- The `notify_document_uploaded()` method exists in `GraphRAGClient` (frontend backend) but the backend endpoint doesn't exist yet — we're building the equivalent server-side in `DocumentSyncService`
- Document ID strategy: use filename as document_id (matches how rename_document already works)
- All operations should be scoped by group_id for multi-tenant isolation
- Post-indexing steps (sync, initialize-hipporag) should be triggered automatically after indexing completes
