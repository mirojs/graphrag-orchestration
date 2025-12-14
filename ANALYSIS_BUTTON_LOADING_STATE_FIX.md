# Analysis Button Loading State Fix

## Problem
The "Quick Inquiry" and "Start Analysis" buttons were becoming clickable (enabled) too quickly after starting an analysis, even though the analysis was still running in the background. They should remain disabled (greyed out) until the analysis is fully complete, matching the behavior of the status bar.

## Root Cause
In `proModeStore.ts`, the `state.loading` flag was being set to `false` immediately when the analysis **started** (in `startAnalysisAsync.fulfilled` and `startAnalysisOrchestratedAsync.fulfilled`), rather than waiting until the analysis **completed**.

### Previous Behavior:
1. User clicks "Start Analysis" → `state.loading = true`
2. Backend responds with `operationId` → `state.loading = false` ❌ (TOO EARLY!)
3. Polling happens in background → analysis still running
4. Results arrive → `state.loading = false` (again, but already false)

### Desired Behavior:
1. User clicks "Start Analysis" → `state.loading = true`
2. Backend responds with `operationId` → `state.loading` stays `true` ✅
3. Polling happens in background → analysis still running → buttons stay disabled
4. Results arrive → `state.loading = false` ✅ (NOW buttons become enabled)

## Solution
Modified the Redux reducers to **conditionally** set `state.loading = false`:

### 1. `startAnalysisAsync.fulfilled` (Line ~1323)
**Before:**
```typescript
state.loading = false; // Always set to false
if (state.currentAnalysis) {
  const payloadResults = (action.payload as any)?.result?.results;
  if (action.payload?.status === 'completed' && payloadResults) {
    // Handle immediate results
  } else {
    // Handle async polling
  }
}
```

**After:**
```typescript
const hasImmediateResults = action.payload?.status === 'completed' && (action.payload as any)?.result?.results;

if (state.currentAnalysis) {
  const payloadResults = (action.payload as any)?.result?.results;
  if (hasImmediateResults) {
    state.loading = false; // ✅ Safe to clear - we have results
    state.currentAnalysis.status = 'completed';
    state.currentAnalysis.result = payloadResults;
    state.currentAnalysis.completedAt = new Date().toISOString();
  } else {
    console.log('[Redux] ⏳ Keeping loading=true until results are polled');
    // Keep state.loading = true - will be cleared by getAnalysisResultAsync.fulfilled
    state.currentAnalysis.status = 'running';
    // ... store operationId and operationLocation for polling
  }
}
```

### 2. `startAnalysisOrchestratedAsync.fulfilled` (Line ~1405)
**Before:**
```typescript
state.loading = false; // Always set to false
state.error = null;
// ... rest of logic
```

**After:**
```typescript
state.error = null;

const hasImmediateResults = action.payload.status === 'completed' && orchestratedResults;
if (hasImmediateResults) {
  console.log('[Redux] ✅ Orchestrated analysis completed synchronously - clearing loading');
  state.loading = false;
} else {
  console.log('[Redux] ⏳ Orchestrated analysis requires polling - keeping loading=true');
  // Keep state.loading = true - will be cleared by getAnalysisResultAsync.fulfilled
}
```

### 3. `getAnalysisResultAsync.fulfilled` (Unchanged - Line ~1445)
This already correctly sets `state.loading = false` when results are fetched:
```typescript
.addCase(getAnalysisResultAsync.fulfilled, (state, action) => {
  state.loading = false; // ✅ Clear loading when results arrive
  if (state.currentAnalysis && state.currentAnalysis.analyzerId === action.payload.analyzerId) {
    state.currentAnalysis.status = 'completed';
    // ... store results
  }
})
```

## Impact
- ✅ **Quick Inquiry button** stays disabled until analysis completes
- ✅ **Start Analysis button** stays disabled until analysis completes
- ✅ **Status bar** continues to show progress correctly
- ✅ **Loading spinner** remains visible during the entire analysis
- ✅ **User cannot accidentally trigger duplicate analyses** while one is running

## Files Modified
- `src/ContentProcessorWeb/src/ProModeStores/proModeStore.ts`
  - Modified `startAnalysisAsync.fulfilled` reducer
  - Modified `startAnalysisOrchestratedAsync.fulfilled` reducer
  - Added conditional `state.loading = false` based on immediate results

## Testing
To verify the fix:
1. Start an analysis (Quick Inquiry or Comprehensive Analysis)
2. **Expected**: Buttons should remain greyed out (disabled) during the entire analysis
3. **Expected**: Status bar should show "Analyzing..." during the entire analysis
4. **Expected**: Only when results appear should buttons become clickable again

## Technical Notes
- The fix distinguishes between **synchronous** responses (immediate results) and **asynchronous** responses (requires polling)
- For synchronous responses: `state.loading = false` immediately (safe, we have results)
- For asynchronous responses: `state.loading` stays `true` until `getAnalysisResultAsync.fulfilled` clears it
- This aligns the button state with the actual completion status tracked by the status bar
