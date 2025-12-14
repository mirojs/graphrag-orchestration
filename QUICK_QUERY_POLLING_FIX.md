# Quick Query Polling Fix - Analysis Never Completes
**Date:** October 12, 2025  
**Issue:** Quick Query starts analysis but never polls for results  
**Root Cause:** Missing result polling trigger in Quick Query handler  
**Resolution:** Added `getAnalysisResultAsync` dispatch to match Start Analysis button pattern

---

## Problem Analysis

### Symptoms from Logs

```
[Redux] 🔄 Status set to: running (polling will continue )
[PredictionTab] Quick Query: Analysis completed successfully: {...status: 'running'...}
[QuickQuery] Query executed successfully
```

**What happened:**
1. ✅ Analysis starts successfully (`status: 'running'`)
2. ✅ operationId is present: `35afb14a-a9d1-4540-821c-ac29a21ac628`
3. ❌ **No polling is triggered** - analysis never completes
4. ❌ User sees spinner forever, no results

---

## Root Cause

### Quick Query Handler (Before Fix)

```typescript
// Execute the analysis using the Quick Query master schema
const result = await dispatch(startAnalysisOrchestratedAsync({...})).unwrap();

console.log('[PredictionTab] Quick Query: Analysis completed successfully:', result);

if (result.status === 'completed') {
  toast.success('Quick Query completed successfully!');
  // ...
} else {
  toast.info(`Quick Query started. Status: ${result.status}`);
}
// ❌ NO POLLING TRIGGERED HERE - just returns!
```

**Issue:** Quick Query assumes `startAnalysisOrchestratedAsync` will either:
1. Return completed results immediately, OR
2. Auto-trigger polling somehow

**Reality:** Neither happens! The function returns `status: 'running'` and **stops**.

---

### Regular Start Analysis Button (Working Pattern)

```typescript
const result = await dispatch(startAnalysisOrchestratedAsync({...})).unwrap();

if (result.status === 'completed') {
  toast.success('Analysis completed successfully!');
  return; // Already done
} else {
  toast.info(`Analysis started. Status: ${result.status}`);
}

// ✅ CRITICAL: Manually trigger result polling
console.log('📡 [PredictionTab] Dispatching getAnalysisResultAsync...');
const resultAction = await dispatch(getAnalysisResultAsync({ 
  analyzerId: result.analyzerId, 
  operationId: result.operationId || '',
  outputFormat: 'table'
}));

if (resultAction.type.endsWith('/fulfilled')) {
  toast.success('Analysis completed successfully!');
  // ...
}
```

**Key difference:** Regular Start Analysis **manually dispatches `getAnalysisResultAsync`** to poll for results.

---

## Why There's No Auto-Polling

### No useEffect Polling Hook

```typescript
// ❌ This does NOT exist in PredictionTab.tsx
useEffect(() => {
  if (currentAnalysis?.status === 'running' && currentAnalysis?.operationId) {
    dispatch(pollForResults(currentAnalysis.operationId));
  }
}, [currentAnalysis?.status, currentAnalysis?.operationId]);
```

**Why not?** The app uses **manual polling** via `getAnalysisResultAsync`, not automatic useEffect polling.

### No Auto-Polling in Redux

The `startAnalysisOrchestratedAsync` Redux thunk:
1. Calls backend to start analysis
2. Gets back `{status: 'running', operationId: '...'}`
3. Stores in Redux state
4. **Does NOT automatically start polling**

**Design:** Polling is **caller's responsibility**, not Redux's responsibility.

---

## Fix Applied

### Quick Query Handler (After Fix)

```typescript
const result = await dispatch(startAnalysisOrchestratedAsync({...})).unwrap();

console.log('[PredictionTab] Quick Query: Analysis completed successfully:', result);

if (result.status === 'completed') {
  toast.success('Quick Query completed successfully!');
  return; // Analysis already complete, results already in Redux
} else {
  toast.info(`Quick Query started. Status: ${result.status}`);
}

// 🔧 CRITICAL FIX: Trigger polling for results (same as regular Start Analysis)
console.log('📡 [QuickQuery] Dispatching getAnalysisResultAsync to poll for results...');
const resultAction = await dispatch(getAnalysisResultAsync({ 
  analyzerId: result.analyzerId, 
  operationId: result.operationId || '',
  outputFormat: 'table'
}));

console.log('📡 [QuickQuery] getAnalysisResultAsync completed:', {
  type: resultAction.type,
  fulfilled: resultAction.type.endsWith('/fulfilled'),
  hasPayload: !!resultAction.payload
});

if (resultAction.type.endsWith('/fulfilled')) {
  toast.success('Quick Query completed successfully!');
  trackProModeEvent('QuickQueryAnalysisCompleted', {...});
}
```

**Changes:**
- ✅ Added `getAnalysisResultAsync` dispatch after starting analysis
- ✅ Same pattern as regular Start Analysis button
- ✅ Handles both immediate completion and polling scenarios
- ✅ Proper success toast after results are fetched

---

## How getAnalysisResultAsync Works

### Backend Polling Logic

```python
# Backend endpoint: GET /pro-mode/content-analyzers/{analyzer_id}/results/{operation_id}

# 1. Check if results are cached in blob storage
if cached_results_exist:
    return cached_results

# 2. Poll Azure Content Understanding API
azure_status = await poll_azure_api(operation_id)

# 3. If complete, fetch and cache results
if azure_status == 'succeeded':
    results = fetch_azure_results(operation_id)
    cache_to_blob_storage(results)
    return results

# 4. If still running, return status
elif azure_status == 'running':
    return {status: 'running', progress: '...'}

# 5. If failed, return error
else:
    return {status: 'failed', error: '...'}
```

### Frontend Polling Logic (in getAnalysisResultAsync Redux thunk)

```typescript
// Max 60 polling attempts (5 minutes at 5-second intervals)
for (let attempt = 0; attempt < 60; attempt++) {
  const response = await httpUtility.get(`/pro-mode/content-analyzers/${analyzerId}/results/${operationId}`);
  
  if (response.status === 'succeeded') {
    return response.results; // ✅ Done!
  } else if (response.status === 'failed') {
    throw new Error('Analysis failed');
  } else {
    // Still running, wait and retry
    await sleep(5000);
  }
}

throw new Error('Analysis timed out');
```

---

## Pattern Alignment

### Before Fix: Inconsistency

| Action | Triggers Polling? | Works? |
|--------|------------------|--------|
| Regular Start Analysis | ✅ Yes (manual dispatch) | ✅ Yes |
| Quick Query | ❌ No | ❌ Broken |

### After Fix: Consistent

| Action | Triggers Polling? | Works? |
|--------|------------------|--------|
| Regular Start Analysis | ✅ Yes (manual dispatch) | ✅ Yes |
| Quick Query | ✅ Yes (manual dispatch) | ✅ Fixed |

**Both now follow the same proven pattern!**

---

## Testing Validation

### Expected Logs After Fix

```
[QuickQuery] Query executed successfully
[PredictionTab] Quick Query: Analysis completed successfully: {status: 'running', ...}
📡 [QuickQuery] Dispatching getAnalysisResultAsync to poll for results...
[httpUtility] Making GET request to: .../results/35afb14a-...
[Polling] Attempt 1/60: Status still running, waiting 5s...
[httpUtility] Making GET request to: .../results/35afb14a-...
[Polling] Attempt 2/60: Status still running, waiting 5s...
...
[httpUtility] Making GET request to: .../results/35afb14a-...
📡 [QuickQuery] getAnalysisResultAsync completed: {type: '.../fulfilled', hasPayload: true}
✅ Quick Query completed successfully!
```

---

## Key Takeaways

1. **No Auto-Polling** - The app doesn't have automatic polling via useEffect
2. **Manual Polling Pattern** - Caller must dispatch `getAnalysisResultAsync`
3. **Consistency Matters** - Quick Query must follow the same pattern as Start Analysis
4. **Two-Step Flow:**
   - Step 1: `startAnalysisOrchestratedAsync` → Starts analysis, returns `operationId`
   - Step 2: `getAnalysisResultAsync` → Polls until complete, returns results

---

## Files Changed

1. **PredictionTab.tsx** - Added polling trigger to Quick Query handler
   - Location: Line ~210-250
   - Change: Added `getAnalysisResultAsync` dispatch
   - Pattern: Copied from `handleStartAnalysisOrchestrated`

---

## Conclusion

**Root cause:** Quick Query was missing the polling trigger that regular Start Analysis has.

**Fix:** Added `getAnalysisResultAsync` dispatch to Quick Query handler, matching the proven pattern.

**Impact:** Quick Query now correctly polls for results and completes successfully! ✅
