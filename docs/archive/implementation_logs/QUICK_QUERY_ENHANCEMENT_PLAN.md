# Quick Query Enhancement Plan: Add group_id, Backend Polling, and ETag

## Summary

The Quick Query function needs to be updated to match the Start Analysis button's implementation, including:
1. **group_id support** (already partially implemented)
2. **Backend polling with Cosmos DB status tracking**
3. **ETag optimization for efficient polling**

## Current State Analysis

### Backend (`proMode.py`)

The Quick Query backend endpoints already have `group_id` support:
- ✅ `/pro-mode/quick-query/initialize` - Has `group_id` parameter
- ✅ `/pro-mode/quick-query/update-prompt` - Has `group_id` parameter
- ❌ Missing: Backend polling support
- ❌ Missing: ETag optimization

### Frontend (`proModeApiService.ts`)

Current implementation:
- ✅ `initializeQuickQuery()` - Calls backend initialize endpoint
- ✅ `updateQuickQueryPrompt()` - Updates prompt via PUT request
- ❌ Missing: group_id not explicitly passed (relies on httpUtility interceptor)
- ❌ Missing: Backend polling integration
- ❌ Missing: Operation status tracking

## Required Changes

### 1. Backend Changes (proMode.py)

#### Update `/pro-mode/quick-query/update-prompt` endpoint

The endpoint should trigger a full analysis workflow similar to the Start Analysis button:

```python
@router.put("/pro-mode/quick-query/update-prompt", summary="Update Quick Query prompt and trigger analysis")
async def update_quick_query_prompt(
    request: Request,
    background_tasks: BackgroundTasks,  # ✅ ADD: For backend polling
    group_id: Optional[str] = Header(None, alias="X-Group-ID"),
    current_user: Optional[UserContext] = Depends(get_current_user),
    app_config: AppConfiguration = Depends(get_app_config)
):
    """
    Update the Quick Query master schema with a new prompt and trigger analysis.
    
    ✅ ENHANCED: Now includes backend polling with ETag optimization
    
    Returns:
    - operation_id: For tracking analysis status
    - analyzer_id: The quick-query analyzer ID
    - status: Initial status ("queued" or "running")
    """
    # 1. Validate group_id and access
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")
    
    await validate_group_access(group_id, current_user)
    
    # 2. Update the master schema prompt (existing logic)
    # ... existing prompt update logic ...
    
    # 3. Generate operation_id for tracking
    operation_id = f"quick-query-{str(uuid.uuid4())}"
    
    # 4. Start backend polling (similar to analyze_content endpoint)
    background_tasks.add_task(
        poll_azure_analysis_status_background,
        operation_id=operation_id,
        analyzer_id=f"quick-query-{schema_id}",
        group_id=group_id,
        app_config=app_config,
        credential=get_azure_credential()
    )
    
    # 5. Return operation tracking info
    return {
        "operation_id": operation_id,
        "analyzer_id": f"quick-query-{schema_id}",
        "status": "queued",
        "message": "Quick Query analysis started"
    }
```

### 2. Frontend Changes (proModeApiService.ts)

#### Update `updateQuickQueryPrompt` function

```typescript
/**
 * Update the Quick Query master schema with a new prompt and trigger analysis
 * ✅ ENHANCED: Now includes backend polling with ETag optimization
 */
export const updateQuickQueryPrompt = async (prompt: string): Promise<{
  operationId: string;
  analyzerId: string;
  status: string;
  message: string;
}> => {
  const endpoint = '/pro-mode/quick-query/update-prompt';
  try {
    console.log('[updateQuickQueryPrompt] Updating prompt and starting analysis:', prompt.substring(0, 100));
    
    // ✅ REUSE: Use the same pattern as startAnalysis
    const response = await httpUtility.put(endpoint, { prompt });
    
    const data = validateApiResponse(
      response,
      'Update Quick Query Prompt and Start Analysis (PUT)',
      [200, 202]  // ✅ Accept both sync and async responses
    );
    
    console.log('[updateQuickQueryPrompt] Analysis started:', data);
    
    // ✅ NORMALIZE: Use the same normalization as startAnalysis
    const normalizedOperation = normalizeAnalysisOperation(
      data as any,
      { analysisType: 'quickQuery' }
    );
    
    return normalizedOperation;
  } catch (error) {
    console.error('[updateQuickQueryPrompt] Failed:', error);
    handleApiError(error, 'update quick query prompt', endpoint);
    throw error;
  }
};
```

### 3. Polling Integration

The Quick Query should use the same polling endpoint as Start Analysis:

```typescript
// ✅ REUSE: Use existing pollAnalysisStatus function
// No changes needed - just call it with the operation_id from updateQuickQueryPrompt

const result = await updateQuickQueryPrompt(prompt);
const operationId = result.operationId;

// Poll for status using existing infrastructure
const pollResult = await pollAnalysisStatus(
  result.analyzerId,
  operationId,
  'quickQuery'  // ✅ Tag as quick query for tracking
);
```

### 4. Component Updates (QuickQuerySection.tsx)

Update the execute query handler to use polling:

```tsx
const handleExecuteQuery = async () => {
  if (!prompt.trim()) {
    toast.warning('Please enter a query prompt');
    return;
  }

  if (!isInitialized) {
    toast.error('Quick Query not initialized. Please wait or refresh the page.');
    return;
  }

  try {
    console.log('[QuickQuery] Executing query:', prompt);
    
    // Track query execution
    trackProModeEvent('QuickQueryExecuted', {
      promptLength: prompt.length,
      isRepeatQuery: queryHistory.includes(prompt)
    });

    // ✅ UPDATE: Start analysis with backend polling
    const result = await updateQuickQueryPrompt(prompt);
    
    // ✅ NEW: Poll for results
    const analysisResult = await pollAnalysisStatus(
      result.analyzerId,
      result.operationId,
      'quickQuery'
    );
    
    // Add to history
    const updatedHistory = [
      prompt,
      ...queryHistory.filter(q => q !== prompt)
    ].slice(0, MAX_HISTORY_SIZE);
    setQueryHistory(updatedHistory);

    // ✅ REUSE: Execute the actual analysis display (existing logic)
    await onQueryExecute(prompt);
    
    console.log('[QuickQuery] Query executed successfully');
  } catch (error: any) {
    console.error('[QuickQuery] Query execution failed:', error);
    toast.error(`Quick Query failed: ${error.message || 'Unknown error'}`);
    
    trackProModeEvent('QuickQueryError', {
      error: error.message || 'Unknown'
    });
  }
};
```

## Implementation Priority

1. **High Priority**: Backend polling integration
   - This is critical for the 500 error fix (group_id tracking)
   - Provides consistent architecture across features
   
2. **Medium Priority**: ETag optimization
   - Improves polling efficiency
   - Reduces server load
   
3. **Low Priority**: UI polish
   - Loading states
   - Progress indicators

## Testing Plan

1. **Backend Testing**
   - Test with `Testing-access` group (previously failing)
   - Test with `test-users` group (previously working)
   - Verify group_id is properly tracked in Cosmos DB
   
2. **Frontend Testing**
   - Test Quick Query execution with polling
   - Verify results are displayed correctly
   - Test error handling

3. **Integration Testing**
   - Test full flow: Initialize → Update Prompt → Poll → Display Results
   - Verify operation tracking works across container restarts
   - Test concurrent quick queries

## Code Reuse Opportunities

### Backend
- ✅ Reuse `poll_azure_analysis_status_background()` function
- ✅ Reuse `get_analysis_status_collection()` for Cosmos DB
- ✅ Reuse ETag optimization logic from analyze_content endpoint

### Frontend
- ✅ Reuse `validateApiResponse()` helper
- ✅ Reuse `normalizeAnalysisOperation()` helper
- ✅ Reuse `pollAnalysisStatus()` function
- ✅ Reuse `handleApiError()` helper

## Benefits

1. **Consistency**: Quick Query uses same architecture as Start Analysis
2. **Reliability**: Backend polling prevents lost operations during container restarts
3. **Performance**: ETag optimization reduces unnecessary polling
4. **Maintainability**: Code reuse reduces duplication
5. **Debugging**: Consistent error handling and logging

## Risk Mitigation

1. **Breaking Changes**: Maintain backward compatibility
   - Keep existing endpoints working
   - Add new polling functionality as enhancement
   
2. **Performance**: Monitor polling frequency
   - Use same 5-second interval as Start Analysis
   - Implement ETag to skip unchanged status
   
3. **User Experience**: Clear loading states
   - Show "Analyzing..." status
   - Display progress updates from polling

## Next Steps

1. Update backend `/pro-mode/quick-query/update-prompt` endpoint
2. Update frontend `updateQuickQueryPrompt()` function
3. Add polling integration to `QuickQuerySection.tsx`
4. Test with both user groups
5. Deploy and monitor

## Related Files

### Backend
- `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`
  - Line 13297: `update_quick_query_prompt` endpoint
  - Line 313: `poll_azure_analysis_status_background` function
  - Line 7188: `analyze_content` endpoint (reference implementation)

### Frontend
- `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeServices/proModeApiService.ts`
  - Line 1027: `updateQuickQueryPrompt` function
  - Line 773: `startAnalysis` function (reference implementation)

- `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/QuickQuerySection.tsx`
  - Line 149: `handleExecuteQuery` function

## Conclusion

By implementing these enhancements, Quick Query will have the same robust architecture as Start Analysis, fixing the 500 error for `Testing-access` users and providing a consistent, maintainable codebase.
