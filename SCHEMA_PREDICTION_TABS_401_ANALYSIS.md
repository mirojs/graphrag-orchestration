# Schema Tab & Prediction Tab - 401 Error Analysis

## Executive Summary
✅ **Good News:** Both tabs already have basic error handling  
⚠️ **Issue Found:** Neither tab has specific 401 handling or retry logic like FilesTab now has  
📋 **Recommendation:** Add similar 401 error handling for consistency

---

## Current State Analysis

### SchemaTab.tsx

**HTTP Calls Found:**
1. **Schema Fetch** (line 251): `httpUtility.get(fullSchemaUrl)` - Loads full schema details
2. **Endpoint Testing** (line 665): `httpUtility.get(endpoint)` - Tests extraction endpoints

**Current Error Handling:**
```typescript
} catch (error) {
  console.error('[SchemaTab] ❌ Error fetching full schema details:', error);
  setFullSchemaDetails(null);
} finally {
  setLoadingSchemaDetails(false);
}
```

**Issues:**
- ❌ Generic error handling - no 401 detection
- ❌ No retry logic
- ❌ No helpful user guidance
- ❌ Silent failure - user just sees no schema details

**Impact:**
- **Severity:** Medium
- **User Experience:** Schema details fail to load when token expires
- **Workaround:** User must refresh page manually
- **Frequency:** Occurs when user switches tabs and returns after token expiration

### PredictionTab.tsx

**HTTP Calls Found:**
1. **Analysis Execution:** Via Redux thunks (runUnifiedAnalysisAsync, startAnalysisAsync, etc.)
2. **Complete File Fetch** (line 176): `dispatch(getCompleteAnalysisFileAsync(...))`

**Current Error Handling:**
```typescript
} catch (error) {
  console.error(`[PredictionTab] ❌ Failed to fetch complete ${fileType} file:`, error);
  toast.error(`Failed to fetch complete ${fileType} file. See console for details.`);
}
```

**Issues:**
- ❌ Generic error handling - no 401 detection
- ❌ No retry logic
- ❌ Toast shows generic message
- ❌ No "refresh page" guidance

**Impact:**
- **Severity:** Medium-High
- **User Experience:** Analysis results fail to load
- **Workaround:** User must refresh page manually
- **Frequency:** Occurs when analysis is run after token expiration

---

## Recommended Enhancements

### Option 1: Add 401-Specific Error Handling (Recommended)

#### For SchemaTab.tsx

```typescript
} catch (error: any) {
  console.error('[SchemaTab] ❌ Error fetching full schema details:', error);
  
  // Check for 401 authentication error
  const is401Error = error?.status === 401 || 
                      error?.message?.includes('401') || 
                      error?.message?.includes('Authentication') ||
                      error?.message?.includes('Unauthorized');
  
  if (is401Error) {
    console.warn('[SchemaTab] ⚠️ Authentication token may have expired');
    toast.error(
      'Session expired. Please refresh the page to sign in again.',
      {
        autoClose: false, // Don't auto-close
        closeButton: true,
        onClick: () => window.location.reload()
      }
    );
  } else {
    toast.error('Failed to load schema details. Please try again.');
  }
  
  setFullSchemaDetails(null);
} finally {
  setLoadingSchemaDetails(false);
}
```

#### For PredictionTab.tsx

```typescript
} catch (error: any) {
  console.error(`[PredictionTab] ❌ Failed to fetch complete ${fileType} file:`, error);
  
  // Check for 401 authentication error
  const is401Error = error?.status === 401 || 
                      error?.message?.includes('401') || 
                      error?.message?.includes('Authentication') ||
                      error?.message?.includes('Unauthorized');
  
  if (is401Error) {
    console.warn('[PredictionTab] ⚠️ Authentication token may have expired');
    toast.error(
      'Session expired. Click here to refresh the page.',
      {
        autoClose: false,
        closeButton: true,
        onClick: () => window.location.reload()
      }
    );
  } else {
    toast.error(`Failed to fetch complete ${fileType} file. See console for details.`);
  }
}
```

### Option 2: Add Retry Logic (Advanced)

```typescript
const fetchWithRetry = async (fetchFn: () => Promise<any>, maxRetries = 1): Promise<any> => {
  let lastError;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fetchFn();
    } catch (error: any) {
      lastError = error;
      
      const is401Error = error?.status === 401 || 
                          error?.message?.includes('401');
      
      if (is401Error && attempt < maxRetries) {
        console.log(`[Retry] Attempt ${attempt + 1} failed with 401, retrying...`);
        await new Promise(resolve => setTimeout(resolve, 500));
        continue;
      }
      
      throw error;
    }
  }
  
  throw lastError;
};

// Usage
try {
  const response = await fetchWithRetry(() => httpUtility.get(fullSchemaUrl));
  // ... handle response
} catch (error) {
  // ... handle final error with 401 check
}
```

---

## Comparison with FilesTab Fix

| Feature | FilesTab (Fixed) | SchemaTab (Current) | PredictionTab (Current) |
|---------|------------------|---------------------|-------------------------|
| **401 Detection** | ✅ Yes | ❌ No | ❌ No |
| **Retry Logic** | ✅ Yes (1 retry) | ❌ No | ❌ No |
| **Helpful Error Message** | ✅ Yes | ❌ Generic | ⚠️ Partial (toast) |
| **User Action Button** | ✅ "Refresh Page" | ❌ No | ❌ No |
| **Stale Data Cleanup** | ✅ Yes (5 min) | N/A | N/A |
| **Tab Visibility Handler** | ✅ Yes | ❌ No | ❌ No |

---

## Implementation Priority

### High Priority ⚠️
**PredictionTab** - Users run analysis after switching tabs, high likelihood of 401 errors

**Why:**
- Analysis can take time to complete
- User might switch tabs while waiting
- Token could expire during long analysis
- Failed analysis fetch is highly disruptive

### Medium Priority 📋
**SchemaTab** - Users browse schemas, moderate likelihood of 401 errors

**Why:**
- Schema fetching is quick
- Less time between tab switches
- Failure is less critical (just schema details missing)
- User can still see schema list

---

## Recommended Immediate Actions

1. **Add 401 error detection to both tabs** (30 minutes)
   - Add `is401Error` check in catch blocks
   - Show helpful toast messages
   - Add click-to-refresh functionality

2. **Add retry logic to PredictionTab** (1 hour)
   - Implement `fetchWithRetry` helper
   - Use for analysis file fetching
   - Add logging for debugging

3. **Test token expiration scenarios** (30 minutes)
   - Manually expire token in DevTools
   - Verify error messages appear
   - Verify refresh button works

4. **Optional: Add tab visibility handler to SchemaTab** (1 hour)
   - Similar to FilesTab implementation
   - Clear cached schema details if stale
   - Re-fetch on tab visibility

---

## Code Locations

### SchemaTab.tsx
- **Main fetch location:** Line 251 - `httpUtility.get(fullSchemaUrl)`
- **Error handling:** Line 318 - `catch (error) { ... }`
- **State update:** Line 319 - `setFullSchemaDetails(null)`

### PredictionTab.tsx
- **Main fetch location:** Line 176 - `dispatch(getCompleteAnalysisFileAsync(...))`
- **Error handling:** Line 183 - `catch (error) { ... }`
- **Toast notification:** Line 184 - `toast.error(...)`

---

## Testing Checklist

### SchemaTab
- [ ] Select a schema - verify it loads
- [ ] Clear auth token in DevTools
- [ ] Switch tabs and return
- [ ] Verify 401 error is detected
- [ ] Verify helpful error message appears
- [ ] Click refresh and verify it works

### PredictionTab
- [ ] Run analysis - verify it completes
- [ ] Click "View Complete Result"
- [ ] Clear auth token in DevTools
- [ ] Click "View Complete Result" again
- [ ] Verify 401 error is detected
- [ ] Verify helpful error message appears
- [ ] Click refresh and verify it works

---

## Summary

### Current Status
- ✅ **FilesTab:** Fixed with 401 handling, retry, and stale URL cleanup
- ⚠️ **SchemaTab:** Has basic error handling, needs 401 detection
- ⚠️ **PredictionTab:** Has basic error handling, needs 401 detection

### Recommendation
**Implement Option 1 (401-Specific Error Handling) for both tabs** to:
1. Provide consistent UX across all tabs
2. Give users clear guidance when auth expires
3. Reduce support burden (users know to refresh)
4. Match the quality of FilesTab fix

**Priority:** Medium-High (not critical but improves UX significantly)

---

**Analysis Date:** 2025-10-04  
**Related Fix:** FILES_TAB_401_ERROR_FIX.md
