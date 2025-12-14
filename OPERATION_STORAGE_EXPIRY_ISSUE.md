# Operation Storage Expiry Issue - Critical Backend Fix Required

## Problem Analysis

Based on the full backend logs, the issue is now clear:

### Root Cause: Operation Storage Expiry
The backend logs show a critical storage issue:

```
2025-09-04T15:38:35.4866219Z [OperationStore] ✅ Found stored operation location 
2025-09-04T15:40:13.9403276Z [OperationStore] 🔍 Available keys in store: []
2025-09-04T15:40:13.9403289Z [OperationStore] 🔍 Store has 0 total entries
2025-09-04T15:40:13.9403318Z [OperationStore] ❌ No stored operation location
```

### What's Happening:
1. **Analysis starts**: Operation location properly stored
2. **~2 minutes later**: In-memory store loses the operation location
3. **Polling requests fail**: Backend can't find stored URL, creates fallback
4. **404 errors**: Fallback URLs don't work with Azure API
5. **Frontend never completes**: Shows "No structured field data found"

### Backend Error Pattern:
```
[OperationStore] ❌ No stored operation location for analyzer-*:operation-*
[AnalyzerStatus] ⚠️ No stored operation location, falling back to constructed URL
[AnalyzerStatus] - Constructed URL: https://.../contentunderstanding/analyzers/.../operations/...
[AnalyzerStatus] 📥 Azure response status: 404
{"error":{"code":"NotFound","message":"Resource not found.","innererror":{"code":"OperationNotFound"}}}
```

## Technical Details

### Operation Storage Store Issue
The backend uses an in-memory `OPERATION_LOCATION_STORE` that's not persisting across requests or time:

1. **Initial storage** (15:38:35): ✅ Stored successfully
2. **Later lookup** (15:40:13): ❌ Store is empty (0 entries)
3. **Time gap**: ~2 minutes - likely a memory cleanup or container restart

### Impact on Frontend
- Frontend polling continues but gets 404s from backend
- Frontend shows "No structured field data found" 
- User sees failure message instead of analysis results

## Immediate Frontend Mitigation

While waiting for backend fix, I can add better error handling to inform users what's happening:

```typescript
const isOperationNotFound = error instanceof Error && 
  (error.message.includes('OperationNotFound') || 
   error.message.includes('operation may have expired') ||
   (error as any).response?.status === 404);

if (isOperationNotFound) {
  // Add specific messaging for this known backend issue
  toast.error('Analysis operation expired in backend storage. Please retry the analysis.');
  console.error('[PredictionTab] Backend operation storage expired - this is a known issue');
}
```

## Required Backend Fix

The backend team needs to fix the `OPERATION_LOCATION_STORE` persistence:

### Option 1: Database Storage
Replace in-memory store with database persistence:
```python
# Instead of in-memory dict
OPERATION_LOCATION_STORE = {}

# Use database/Redis with TTL
def store_operation_location(key, url, ttl_hours=2):
    # Store in persistent storage with expiration
```

### Option 2: Enhanced URL Construction
Improve the fallback URL construction to match Azure's expected format:
```python
# The current fallback creates incorrect URLs
# Need to match the exact operation-location format from Azure headers
```

### Option 3: Return Operation Location to Frontend
Include the operation-location in the analyze response so frontend can poll directly:
```python
# Return operation URL to frontend in analyze response
return {
    "analyzerId": analyzer_id,
    "operationId": operation_id, 
    "operationUrl": operation_location,  # Add this
    "status": "running"
}
```

## Expected Timeline

### Immediate (Frontend):
- ✅ Added status-aware messaging (completed)
- ✅ Better error handling for running status (completed)
- 🔄 Can add specific messaging for operation storage expiry

### Backend Fix Required:
The fundamental issue is in the backend operation storage system. Until this is fixed:
- Users will continue to see "No structured field data found"
- Analysis will appear to fail even when Azure processing completes successfully
- The system will work for ~2 minutes then fail consistently

## Current Status

- **Analysis Processing**: ✅ Working (Azure accepts and processes requests)
- **Operation Storage**: ❌ Failing (backend loses operation locations)
- **Result Retrieval**: ❌ Failing (can't poll completed operations)
- **User Experience**: ❌ Poor (appears broken despite working backend)
