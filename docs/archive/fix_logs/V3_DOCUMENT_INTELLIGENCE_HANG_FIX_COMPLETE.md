# v3 Document Intelligence Hang Fix - Complete

## Root Cause

The v3 `/graphrag/v3/index` endpoint was hanging (504 Gateway Timeout) when processing PDF documents because:

1. **Poor Error Handling in Blob Download**: When `DocumentIntelligenceService` tried to download blobs using managed identity, it would silently fall back to passing the URL to Document Intelligence if the download failed
2. **Private Blobs Without SAS**: The fallback URL (without SAS token) couldn't be accessed by Document Intelligence, causing it to hang
3. **No Timeout on DI Analysis**: The `await poller.result()` call had no timeout, so it would wait indefinitely
4. **SAS Token Interference**: If URLs contained SAS tokens, they would interfere with managed identity authentication

## The Fix

### Changes Made to `document_intelligence_service.py`

#### 1. Strip SAS Tokens Before Managed Identity Access
```python
# Extract blob URL without query params (SAS tokens not needed with MI)
clean_url = url.split('?')[0]
logger.info(f"Using clean blob URL (no SAS): {clean_url}")

async with BlobClient.from_blob_url(clean_url, credential=credential) as blob_client:
    content = await blob_client.download_blob()
    document_bytes = await content.readall()
```

**Why**: Managed identity and SAS tokens are mutually exclusive. When using managed identity, we must use clean URLs without query parameters.

#### 2. Fail Fast on Download Errors
```python
except Exception as e:
    logger.error(f"❌ Failed to download blob content: {str(e)}")
    logger.error(f"   This likely means the Container App doesn't have 'Storage Blob Data Reader' role")
    logger.error(f"   or the blob doesn't exist. Cannot proceed without blob content.")
    raise RuntimeError(f"Failed to download blob {url}: {str(e)}")
```

**Why**: Instead of silently falling back to passing an inaccessible URL to DI (which hangs), we now fail fast with a clear error message.

#### 3. Add Timeout to DI Analysis
```python
# Wait for completion with timeout (SDK handles polling automatically)
# Azure DI typically takes 2-10 seconds per document
try:
    result: AnalyzeResult = await asyncio.wait_for(
        poller.result(), 
        timeout=60  # 60 seconds max per document
    )
    logger.info(f"✅ Document Intelligence analysis completed for {url[:80]}")
except asyncio.TimeoutError:
    logger.error(f"❌ Document Intelligence analysis timed out after 60s for {url[:80]}")
    raise TimeoutError(f"Document Intelligence analysis timed out for {url}")
```

**Why**: Prevents indefinite hangs. Azure DI typically completes in 2-10 seconds per document, so 60 seconds is a generous timeout.

#### 4. Enhanced Logging
- Added ✅/❌ emojis for success/failure
- Logged blob size after download
- Logged analysis start/completion
- Clear error messages for troubleshooting

## Deployment

### Option 1: Deploy via Azure DevOps Pipeline
```bash
git add .
git commit -m "fix: v3 DI hanging issue - strip SAS tokens, add timeouts, fail fast"
git push origin main
```

The pipeline will automatically deploy to Container Apps.

### Option 2: Manual Deployment
```bash
cd /afh/projects/graphrag-orchestration
az containerapp update \
  --name graphrag-orchestration \
  --resource-group <your-rg> \
  --image <your-registry>.azurecr.io/graphrag-orchestration:latest
```

## Testing

### Test with Managed Identity (Recommended)
```bash
cd /afh/projects/graphrag-orchestration
python test_managed_identity_pdfs.py
```

This test:
- Uses raw blob URLs (no SAS tokens)
- Relies on Container App managed identity for storage access
- Should complete in ~6-10 seconds for 5 PDFs

### Expected Output
```
✅ Successfully downloaded blob content (45231 bytes)
⏳ Starting Document Intelligence analysis (45231 bytes)...
✅ Document Intelligence analysis completed for https://neo4jstorage21224...
```

### Expected Performance
- **Blob Download**: ~1-2 seconds per PDF (managed identity)
- **DI Analysis**: ~2-10 seconds per PDF (parallel processing)
- **Total for 5 PDFs**: ~6-15 seconds

## Infrastructure Requirements

Ensure the Container App has the following role assignments (already configured in `infra/core/security/role-assignments.bicep`):

1. ✅ **Storage Blob Data Reader** on Storage Account
   - Role ID: `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`
   - Allows: Downloading blobs with managed identity

2. ✅ **Cognitive Services User** on Document Intelligence
   - Role ID: `a97b65f3-24c7-4388-baec-2e87135dc908`
   - Allows: Calling DI API with managed identity

3. ✅ **Cognitive Services OpenAI User** on Azure OpenAI
   - Role ID: `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`
   - Allows: Embeddings generation

## Comparison: v2 vs v3

### v2 `/graphrag/index` (Deprecated but Working)
- Uses `_to_documents()` helper
- Calls DI service directly
- Returns LlamaIndex Documents
- Simple, battle-tested

### v3 `/graphrag/v3/index` (Fixed)
- Uses IndexingPipelineV3
- Converts docs to dicts, then back to Documents
- Adds RAPTOR + hierarchical community detection
- More complex but more powerful

**Key Difference**: v3 has an extra conversion step at the endpoint level (str → dict), but both eventually call the same `DocumentIntelligenceService.extract_documents()` method.

## Troubleshooting

### Still Getting 504 Timeout?
1. Check Container App logs:
   ```bash
   az containerapp logs show \
     --name graphrag-orchestration \
     --resource-group <your-rg> \
     --follow
   ```

2. Look for these log lines:
   - `✅ Successfully downloaded blob content` → Download worked
   - `❌ Failed to download blob content` → Role assignment issue
   - `❌ Document Intelligence analysis timed out` → DI service issue

### Role Assignment Issues
```bash
# Check if Container App has Storage Blob Data Reader role
az role assignment list \
  --assignee <container-app-principal-id> \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<storage-account>
```

### DI Service Issues
```bash
# Test Document Intelligence directly
curl -X POST "https://doc-intel-graphrag.cognitiveservices.azure.com/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=2024-11-30" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)" \
  --data '{"urlSource": "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf"}'
```

## Summary

The fix ensures:
1. **No more hangs**: Timeouts prevent indefinite waiting
2. **Clear errors**: Fail fast with detailed messages
3. **Correct MI usage**: Strip SAS tokens before using managed identity
4. **Better debugging**: Enhanced logging for troubleshooting

Expected result: **5 PDFs processed in ~6-15 seconds**, matching the performance of v2.
