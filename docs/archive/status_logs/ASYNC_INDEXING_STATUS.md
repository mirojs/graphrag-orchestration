# Async Indexing Implementation Status

**Date**: 2025-12-19  
**Issue**: 504 Gateway Timeout during v3 indexing (even for 2-5 documents)  
**Root Cause**: Entity extraction + RAPTOR + community detection takes >4 minutes

## Changes Made

### 1. Dockerfile Improvements
**File**: `graphrag-orchestration/Dockerfile`
- Added `--no-warn-script-location` and `--root-user-action=ignore` to pip commands
- Eliminates build warnings about running pip as root in containers

### 2. Deploy Script Enhancements  
**File**: `deploy-graphrag.sh`
- Fixed managed identity detection to support **system-assigned** identities (not just user-assigned)
- Replaced `docker build + docker push` with `az acr build` (no ACR admin credentials required)
- Now properly detects the existing system-assigned managed identity on the container app

### 3. V3 Async Indexing
**File**: `app/v3/routers/graphrag_v3.py` (lines 243-266)
- **Changed**: Removed synchronous processing for small batches
- **Now**: ALL indexing runs as background tasks (returns immediately with "accepted" status)
- **Benefit**: API returns within seconds; processing continues in background

```python
# Always use background tasks to avoid gateway timeouts
# Entity extraction + RAPTOR + community detection can take >4 minutes for even small batches
async def run_indexing():
    try:
        stats = await pipeline.index_documents(
            group_id=group_id,
            documents=docs_for_pipeline,
            reindex=False,
            ingestion=payload.ingestion,
        )
        logger.info("v3_index_complete", group_id=group_id, stats=stats)
    except Exception as e:
        logger.error("v3_index_background_failed", group_id=group_id, error=str(e))

background_tasks.add_task(run_indexing)

return V3IndexResponse(
    status="accepted",
    group_id=group_id,
    documents_processed=len(docs_for_pipeline),
    entities_created=0,  # Will be updated by background task
    relationships_created=0,
    communities_created=0,
    raptor_nodes_created=0,
    message="Indexing started in background. Check logs or query to verify completion.",
)
```

## Testing Status

### Completed
- ✅ Fixed deployment script managed identity detection
- ✅ Fixed Dockerfile warnings
- ✅ Modified v3 endpoint for async processing
- ✅ Container app updated with system-assigned identity + AcrPull role

### Blocked
- ❌ New image build in progress (ACR build taking ~5-10 minutes)
- ❌ Cannot test async endpoint until new image is deployed

### Next Steps
1. Wait for `graphrag-orchestration:async-fix` image to complete building
2. Update container app to use new image:
   ```bash
   az containerapp update \
     --name graphrag-orchestration \
     --resource-group rg-graphrag-feature \
     --image graphragacr12153.azurecr.io/graphrag-orchestration:async-fix
   ```
3. Test async indexing:
   ```bash
   curl -X POST https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/graphrag/v3/index \
     -H "X-Group-ID: async-test" \
     -H "Content-Type: application/json" \
     -d '{
       "documents": [
         {"text": "Document 1 content...", "metadata": {"source": "doc1.pdf"}},
         {"text": "Document 2 content...", "metadata": {"source": "doc2.pdf"}}
       ],
       "run_raptor": true,
       "run_community_detection": true,
       "ingestion": "none"
     }'
   ```
   **Expected**: Immediate response with `"status": "accepted"` (not 504 timeout)

4. Wait 2-3 minutes, then verify completion with query:
   ```bash
   curl -X POST https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/graphrag/v3/query/raptor \
     -H "X-Group-ID: async-test" \
     -H "Content-Type: application/json" \
     -d '{"query": "What are these documents about?"}'
   ```

## Technical Notes

### Why Background Tasks?
- Azure Container Apps has 240s (4 minute) ingress timeout
- Entity extraction alone can take 1-2 minutes for 5 documents
- RAPTOR hierarchical summarization adds another 30-60s
- Community detection adds 30-60s  
- **Total**: Often exceeds 4 minutes → 504 timeout

### FastAPI BackgroundTasks Behavior
- Tasks start AFTER response is sent to client
- If async function, FastAPI handles event loop properly
- Logs show success/failure (check with `az containerapp logs show`)

### Alternative Monitoring
Since response returns immediately, monitor via:
1. **Container logs**: `az containerapp logs show --name graphrag-orchestration --resource-group rg-graphrag-feature --tail 100`
2. **Query endpoints**: Try searching to see if data appeared
3. **Future improvement**: Add a `/v3/status/{group_id}` endpoint to check indexing progress

## Files Modified
1. `/afh/projects/graphrag-orchestration/graphrag-orchestration/Dockerfile` - pip warning fixes
2. `/afh/projects/graphrag-orchestration/deploy-graphrag.sh` - managed identity + ACR build fixes
3. `/afh/projects/graphrag-orchestration/graphrag-orchestration/app/v3/routers/graphrag_v3.py` - async indexing implementation

## Deployment Info
- **Container Registry**: graphragacr12153.azurecr.io
- **Current Image**: graphrag-orchestration:test (OLD - no async fix)
- **New Image**: graphrag-orchestration:async-fix (IN PROGRESS)
- **Container App**: graphrag-orchestration
- **Resource Group**: rg-graphrag-feature
- **Region**: swedencentral
- **Managed Identity**: System-assigned (principalId: 4b41f7b5-e81e-4c1a-a08e-d63f080fcab6)
