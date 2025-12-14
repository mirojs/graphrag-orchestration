# File Preview & Schema List Not Working - Troubleshooting Guide

## Issue Report
- **File Preview**: Not working after recent blob URL memory leak fix
- **Schema List**: Could not be displayed

## Root Cause Analysis

### File Preview Issue
The recent blob URL memory leak fix had an unintended side effect:
- We were revoking the old blob URL **before** fetching the new one
- This caused the state to be empty during the API call
- Result: Preview showed loading state indefinitely or failed

### Fix Applied
Moved the blob URL revocation to **after** the new blob URL is created:

**Before (Broken)**:
```typescript
// Delete blob URL BEFORE fetching new one
setAuthenticatedBlobUrls(prev => {
  const updated = { ...prev };
  if (updated[processId]?.url) {
    URL.revokeObjectURL(updated[processId].url);
  }
  delete updated[processId];  // ❌ Deletes too early!
  return updated;
});

// Now fetch new blob URL (state is empty during this time)
const response = await httpUtility.headers(relativePath);
```

**After (Fixed)**:
```typescript
// Fetch new blob URL first
const response = await httpUtility.headers(relativePath);
const blobURL = URL.createObjectURL(blob);

// THEN revoke old blob URL when setting new one
setAuthenticatedBlobUrls(prev => {
  const updated = { ...prev };
  
  // Revoke old blob URL if replacing
  if (updated[processId]?.url) {
    console.log(`[FilesTab] 🗑️ Revoking old blob URL for ${processId}`);
    URL.revokeObjectURL(updated[processId].url);
  }
  
  // Set new blob URL
  updated[processId] = blobData;
  return updated;
});
```

## Files Modified
- **FilesTab.tsx**:
  - `createAuthenticatedBlobUrl()` function (line ~334)
  - `PreviewWithAuthenticatedBlob` useEffect (line ~142)

## Deployment Steps

### 1. Rebuild Docker Images
The changes need to be built into new Docker images:

```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
conda deactivate
./docker-build.sh
```

### 2. Verify Build Success
Check that the build completed successfully (Exit Code: 0)

### 3. Deploy Updated Images
After building, deploy the updated containers:

```bash
# If using Docker Compose
docker-compose down
docker-compose up -d

# Or if using Kubernetes/AKS
kubectl rollout restart deployment/content-processor-web
```

### 4. Clear Browser Cache
After deployment, users should:
1. Hard refresh the browser (Ctrl+Shift+R or Cmd+Shift+R)
2. Or clear browser cache and cookies for the application

## Testing Checklist

### File Preview Testing
- [ ] Click on a file in the Files tab
- [ ] Verify file preview appears correctly
- [ ] Switch to a different file
- [ ] Verify new file preview appears
- [ ] Switch back to the first file
- [ ] Verify preview still works (tests blob URL replacement)
- [ ] Preview 20+ different files rapidly
- [ ] Verify all previews work without errors

### Schema List Testing
- [ ] Navigate to Schema tab
- [ ] Verify schema list is displayed
- [ ] Verify schema names are visible
- [ ] Click on a schema to view details
- [ ] Verify schema fields are displayed correctly

### Browser Console Checks
Open browser Developer Tools (F12) and check Console for:

**Expected Success Messages**:
```
[FilesTab] Creating authenticated blob URL for {processId}
[FilesTab] ✅ Successfully created blob URL for {processId}
```

**Expected on Replacement** (when clicking same file twice):
```
[FilesTab] 🗑️ Revoking old blob URL for {processId}
```

**Expected on Cache Limit**:
```
[FilesTab] Cache limit exceeded, removing X oldest blob URLs
```

**Error Messages to Watch For**:
```
[FilesTab] Failed to create authenticated blob URL:
[FilesTab] ⚠️ Authentication issue detected
401 Unauthorized - Authentication token may have expired
```

## Common Issues & Solutions

### Issue 1: File Preview Shows Loading Indefinitely
**Symptoms**: Spinner keeps spinning, no preview appears
**Cause**: API endpoint not responding or authentication failure
**Solution**:
1. Check browser console for error messages
2. Verify backend services are running
3. Check authentication token is valid
4. Try refreshing the page (F5)

### Issue 2: Schema List Empty
**Symptoms**: Schema tab shows no schemas
**Cause**: API endpoint failure or empty database
**Solution**:
1. Check browser console for fetch errors
2. Verify backend API is accessible
3. Check database has schemas
4. Verify API endpoint: `GET /pro-mode/schemas`

### Issue 3: 401 Unauthorized Errors
**Symptoms**: Console shows "401 Unauthorized" messages
**Cause**: Authentication token expired
**Solution**:
1. Refresh the browser page (F5)
2. Log out and log back in
3. Check token expiration settings in backend

### Issue 4: Some Files Preview, Others Don't
**Symptoms**: Inconsistent preview behavior
**Cause**: File-specific issues (corrupted files, unsupported formats)
**Solution**:
1. Check console for file-specific errors
2. Verify file MIME types are supported
3. Check file size (very large files may timeout)

## API Endpoints to Verify

### File Preview Endpoint
```
GET /pro-mode/files/{processId}/preview
```
**Expected Response**: Binary blob data with `Content-Type` header

### Schema List Endpoint
```
GET /pro-mode/schemas
```
**Expected Response**:
```json
[
  {
    "id": "schema-id-1",
    "name": "Schema Name",
    "fields": [...]
  },
  ...
]
```

## Debugging Commands

### Check Docker Container Logs
```bash
# Web frontend logs
docker logs content-processor-web

# API backend logs
docker logs content-processor-api
```

### Check Network Requests
In browser DevTools:
1. Open Network tab (F12)
2. Filter by "preview" or "schemas"
3. Click on failed requests
4. Check Response tab for error details

### Check React Component State
In browser DevTools:
1. Install React Developer Tools extension
2. Open Components tab
3. Find `FilesTab` or `SchemaTab` component
4. Check `authenticatedBlobUrls` state
5. Verify blob URLs are being created

## Performance Monitoring

### Memory Usage
Check browser Task Manager (Shift+Esc in Chrome):
- Memory usage should stabilize after initial file previews
- Blob URL count should not exceed 20
- No continuous memory growth

### Console Cleanup Logs
You should see periodic cleanup messages:
```
[FilesTab] Cleaned up all blob URLs on unmount
[FilesTab] Found X stale blob URLs, clearing them for refresh
```

## Rollback Plan

If issues persist after deployment:

### Quick Rollback
```bash
# Revert to previous Docker image
docker tag content-processor-web:previous content-processor-web:latest
docker-compose up -d
```

### Full Rollback
```bash
cd ./code/content-processing-solution-accelerator
git revert HEAD
./infra/scripts/docker-build.sh
```

## Support Information

### Log Files to Collect
1. Browser console logs (Console tab → Save as...)
2. Network requests (Network tab → Export HAR)
3. Docker container logs
4. Backend API logs

### Information to Provide
1. Browser version and OS
2. Time when issue occurred
3. Specific files that failed to preview
4. Complete error messages from console
5. Network response status codes

## Status
- ✅ Code fix applied
- ⏳ Docker rebuild needed
- ⏳ Deployment pending
- ⏳ Testing required

## Next Steps
1. Run `./docker-build.sh` to rebuild images
2. Deploy updated containers
3. Test file preview functionality
4. Test schema list functionality
5. Monitor browser console for errors
6. Update this document with test results
