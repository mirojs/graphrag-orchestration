# Polling Data Format Comparison: Old vs New

## Executive Summary

**Root Cause of "Missing 'id' field" Error:**
- Azure's analysis results API response does NOT include a top-level `id` field
- Frontend normalizer (`normalizeAnalyzerResult`) **requires** both `id` and `status` fields at top level
- Old synchronous polling worked because it used a different endpoint pattern
- New hybrid polling must inject these fields into the Azure response before returning to frontend

---

## Side-by-Side Comparison

### 1. Azure Raw Response Structure

```json
// What Azure Content Understanding API actually returns
// GET /contentunderstanding/analyzerResults/{operationId}
{
  "status": "succeeded",
  "createdDateTime": "2024-10-26T10:30:00Z",
  "lastUpdatedDateTime": "2024-10-26T10:31:00Z",
  "analyzeResult": {
    "apiVersion": "2025-05-01-preview",
    "modelId": "prebuilt-document",
    "contents": [
      {
        "kind": "document",
        "fields": {
          "InvoiceNumber": {
            "type": "string",
            "valueString": "INV-12345"
          },
          "TotalAmount": {
            "type": "number",
            "valueNumber": 1500.00
          }
        }
      }
    ]
  },
  "usage": {
    "totalPages": 1,
    "analyzeTime": 2.5
  }
}
```

**❌ Problem:** No `id` field at top level!

---

### 2. Frontend Normalizer Requirements

```typescript
// From: analysisInputNormalizer.ts (lines 671-710)
export function normalizeAnalyzerResult(rawData: any): NormalizedAnalyzerResult {
  const data = rawData?.data || rawData;
  
  // ❌ THROWS ERROR if missing!
  if (!data.id) {
    console.error('[normalizeAnalyzerResult] Missing required field: id', data);
    throw new Error('Invalid analyzer result: missing required field "id"');
  }
  
  // ❌ THROWS ERROR if missing!
  if (!data.status) {
    console.error('[normalizeAnalyzerResult] Missing required field: status', data);
    throw new Error('Invalid analyzer result: missing required field "status"');
  }
  
  // Build normalized result
  return {
    id: data.id,                    // ← REQUIRED
    status: data.status,            // ← REQUIRED
    result: data.result || {        // ← REQUIRED (with contents array)
      analyzerId: data.id,
      apiVersion: '2025-05-01-preview',
      createdAt: new Date().toISOString(),
      contents: []
    },
    usage: data.usage,
    group_id: data.group_id,
    saved_at: data.saved_at,
    polling_metadata: data.polling_metadata
  };
}
```

**Expected Input Shape:**
```typescript
{
  id: string;           // ← REQUIRED: Operation/analyzer ID
  status: string;       // ← REQUIRED: "succeeded" | "failed" | "running"
  result: {             // ← REQUIRED object
    analyzerId: string;
    apiVersion: string;
    createdAt: string;
    contents: Array<{   // ← REQUIRED array (can be empty)
      kind: string;
      fields: Record<string, any>;
    }>;
  };
  usage?: object;
  group_id?: string;
  saved_at?: string;
  polling_metadata?: object;
}
```

---

### 3. Old Synchronous Polling Pattern (Before Hybrid)

**Backend Code (Removed in commit 7df1548b):**
```python
# Old pattern: Synchronous polling blocked HTTP connection
def get_analyzer_result_sync(analyzer_id: str):
    # Polled Azure in HTTP request handler (7.5 min timeout risk!)
    result = poll_azure_until_complete(analyzer_id)
    
    # Returned Azure response directly
    # ❌ This worked by accident because...
    return JSONResponse(content=result)
```

**Frontend Code (Commit 93b2abd5):**
```typescript
// Old endpoint call
const response = await httpUtility.get(
  `/contentAnalyzers/${analyzerId}?includeResults=true`
);
// This endpoint doesn't exist in backend! 
// Was it a different service or removed?
```

**Why Old Code Worked:**
1. Different endpoint pattern (`/contentAnalyzers` vs `/pro-mode/content-analyzers/.../results`)
2. Possibly returned analyzer definition (which has `id` field) merged with results
3. OR: Frontend didn't use normalizer in older commits (added in commit 136d6d2b)

---

### 4. New Hybrid Polling Pattern (Current)

**Backend Architecture:**
```python
# POST /pro-mode/content-analyzers/{analyzer_id}:analyze
# Returns immediately with operation_id
{
  "status": "submitted",
  "operationId": "abc-123-xyz",
  "analyzerId": "my-analyzer"
}

# Background task polls Azure (no HTTP timeout)
async def _poll_azure_analysis_in_background(operation_id):
    # Polls every 10s for up to 5 minutes
    # Stores results in _ANALYSIS_RESULTS_CACHE
    _ANALYSIS_RESULTS_CACHE[operation_id] = {
        "status": "completed",
        "result": azure_response,  # ← Raw Azure JSON
        "timestamp": time.time()
    }

# GET /pro-mode/content-analyzers/{analyzer_id}/results/{result_id}
# Frontend polls this every 5 seconds
```

**Problem Flow:**
```
Frontend Poll → Backend GET results/{result_id}
                   ↓
             Check cache → Found "completed"
                   ↓
             Return azure_result (raw Azure response)
                   ↓
             Frontend normalizer → ❌ THROWS: Missing 'id' field!
```

---

### 5. Backend Response Transformation (THE FIX)

**Before Fix:**
```python
if cache_status == "completed":
    azure_result = cached.get("result", {})
    del _ANALYSIS_RESULTS_CACHE[result_id]
    
    # ❌ Only added 'id', but Azure response structure varies!
    azure_result["id"] = result_id
    
    return azure_result  # ← Inconsistent shape!
```

**After Fix (Applied):**
```python
if cache_status == "completed":
    azure_result = cached.get("result", {})
    del _ANALYSIS_RESULTS_CACHE[result_id]
    
    # ✅ Add 'id' and normalize response shape
    azure_result["id"] = result_id
    
    # Extract 'contents' from various Azure response patterns
    contents = []
    try:
        if isinstance(azure_result.get('result'), dict) and 'contents' in azure_result.get('result'):
            contents = azure_result['result']['contents'] or []
        elif isinstance(azure_result.get('analyzeResult'), dict) and 'contents' in azure_result.get('analyzeResult'):
            contents = azure_result['analyzeResult']['contents'] or []
        elif isinstance(azure_result.get('analyzeResult'), dict) and 'documents' in azure_result.get('analyzeResult'):
            contents = azure_result['analyzeResult']['documents'] or []
    except Exception:
        contents = []
    
    # ✅ Build frontend-compatible response
    frontend_compatible = {
        "id": result_id,                                    # ← REQUIRED
        "status": azure_result.get('status') or 'succeeded', # ← REQUIRED
        "result": {                                         # ← REQUIRED object
            "analyzerId": analyzer_id or result_id,
            "apiVersion": API_VERSION,
            "createdAt": azure_result.get('createdDateTime') or datetime.utcnow().isoformat(),
            "contents": contents                            # ← REQUIRED array
        },
        "usage": azure_result.get('usage'),
        "group_id": group_id,
        "saved_at": azure_result.get('saved_at'),
        "polling_metadata": {
            "cached_age_seconds": time.time() - cached.get('timestamp', time.time())
        }
    }
    
    return frontend_compatible  # ← Consistent shape!
```

---

## Comparison Table

| Aspect | Old Synchronous Polling | New Hybrid Polling (Before Fix) | New Hybrid Polling (After Fix) |
|--------|------------------------|--------------------------------|-------------------------------|
| **Backend Endpoint** | `/contentAnalyzers/{id}` (not found in code!) | `/pro-mode/content-analyzers/{id}/results/{opId}` | Same |
| **Polling Strategy** | Frontend blocks for 7.5 min | Backend polls Azure, frontend polls cache | Same |
| **HTTP Timeout Risk** | ❌ High (504 errors) | ✅ None | ✅ None |
| **Response `id` Field** | ✅ Present (somehow) | ❌ Missing | ✅ Injected |
| **Response `status` Field** | ✅ Present | ⚠️ Varies by Azure response | ✅ Normalized |
| **Response `result.contents`** | ✅ Present | ⚠️ Varies by Azure response | ✅ Extracted & normalized |
| **Frontend Normalizer** | ✅ Passes (or didn't exist) | ❌ Throws error | ✅ Passes |
| **Scalability** | ❌ Poor (blocks workers) | ✅ Good | ✅ Good |
| **Reliability** | ❌ Low (timeouts) | ⚠️ Medium (normalizer fails) | ✅ High |

---

## Data Format Evolution

### Format 1: Azure Raw Response (What we receive)
```json
{
  "status": "succeeded",
  "createdDateTime": "2024-10-26T10:30:00Z",
  "analyzeResult": {
    "contents": [...]
  }
}
```
**Issues:** No `id`, nested structure varies

---

### Format 2: Old Backend Response (Pre-hybrid, working)
```json
{
  "id": "analyzer-123",          // ← How was this added?
  "status": "succeeded",
  "result": {
    "analyzerId": "analyzer-123",
    "contents": [...]
  }
}
```
**Mystery:** How did old code add `id`? Different endpoint?

---

### Format 3: New Backend Response (Before fix, broken)
```json
{
  "id": "operation-xyz",         // ← Manually added
  "status": "succeeded",         // ← From Azure
  "analyzeResult": {             // ← Azure structure (not 'result'!)
    "contents": [...]
  }
}
```
**Issue:** Frontend expects `result.contents`, not `analyzeResult.contents`

---

### Format 4: New Backend Response (After fix, working)
```json
{
  "id": "operation-xyz",         // ✅ Injected
  "status": "succeeded",         // ✅ Normalized
  "result": {                    // ✅ Restructured
    "analyzerId": "my-analyzer",
    "apiVersion": "2025-05-01-preview",
    "createdAt": "2024-10-26T10:30:00Z",
    "contents": [...]            // ✅ Extracted from Azure response
  },
  "usage": {...},
  "group_id": "group-123",
  "polling_metadata": {...}
}
```
**Result:** ✅ Matches frontend normalizer expectations exactly

---

## Key Differences Summary

### What Changed Between Old and New
1. **Endpoint Pattern:** `/contentAnalyzers/{id}` → `/pro-mode/content-analyzers/{id}/results/{opId}`
2. **Polling Location:** Frontend blocked → Backend background task
3. **Response Source:** Unknown endpoint → Azure analyzerResults API
4. **Data Shape:** Somehow had `id` + `result` → Raw Azure response
5. **Normalization:** Done somewhere (?) → Must be done in backend GET handler

### What We Fixed
1. **Inject `id` field:** Backend adds `operation_id` as top-level `id`
2. **Normalize `status` field:** Extract from Azure or default to "succeeded"
3. **Restructure `result` object:** Create consistent shape with `contents` array
4. **Preserve metadata:** Keep `usage`, `group_id`, `polling_metadata`
5. **Handle Azure variations:** Support multiple Azure response structures

---

## Testing Requirements

### Unit Test Should Verify:

1. **Required Fields Present:**
   - ✅ `id` field exists at top level
   - ✅ `status` field exists at top level
   - ✅ `result` field is an object
   - ✅ `result.contents` is an array

2. **Various Azure Response Patterns:**
   - ✅ Azure response with `analyzeResult.contents`
   - ✅ Azure response with `result.contents`
   - ✅ Azure response with `analyzeResult.documents`
   - ✅ Azure response with no contents (empty array)

3. **Frontend Normalizer Compatibility:**
   - ✅ Response passes `normalizeAnalyzerResult()` without throwing
   - ✅ Normalized result has all expected fields
   - ✅ `contents` array is accessible

4. **Edge Cases:**
   - ✅ Missing optional fields (usage, group_id) don't break response
   - ✅ Cache timestamp is used for polling metadata
   - ✅ Status variations ("succeeded", "Succeeded", null) are handled

---

## Deployment Checklist

- [x] Backend normalized response structure implemented
- [x] Side-by-side comparison documented
- [ ] Unit test written and passing
- [ ] Integration test with real Azure API (optional)
- [ ] Frontend error handling verified
- [ ] Deployed to staging/dev environment
- [ ] Verified with real analysis workflow
- [ ] Deployed to production

---

## Conclusion

**The Fix:**
Backend now transforms Azure's raw response into the exact shape that frontend expects, ensuring the normalizer never throws "missing 'id'" error again.

**Why This Works:**
- Preserves hybrid polling architecture (no HTTP timeouts)
- Maintains backward compatibility with frontend normalizer
- Handles multiple Azure response variations
- Adds proper metadata for debugging
- No changes needed to frontend code

**Next Step:**
Write and run unit test to verify the transformation works correctly before deployment.
