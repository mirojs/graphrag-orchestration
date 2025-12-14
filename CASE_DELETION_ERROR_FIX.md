# Case Deletion Error Fix

## Problem Analysis

### Issue 1: JSON Parsing Error
- **Error**: `Failed to execute 'json' on 'Response': Unexpected end of JSON input`
- **Root Cause**: Delete API returns 204 (No Content) status, but httpUtility tries to parse empty response as JSON
- **Location**: httpUtility.ts line 206

### Issue 2: Cases Reappearing After Refresh  
- **Symptom**: Cases deleted in UI reappear after page refresh
- **Root Cause**: Backend deletion may not complete successfully, causing database inconsistency

## Solution

### Fix 1: Handle Empty Response Bodies Properly

Update httpUtility.ts to handle 204 responses correctly:

```typescript
// In httpUtility.ts around line 202-210
let data = null;
try {
  // Handle 204 No Content responses - they have empty bodies
  if (status === 204) {
    data = null;
  } else {
    data = isJson ? await response.json() : await response.text();
  }
} catch (parseError) {
  console.warn('[httpUtility] Failed to parse response:', parseError);
  data = null;
}
```

### Fix 2: Improve Case Management Service Delete Handling

Update caseManagementService.ts to handle 204 responses:

```typescript
export const deleteCase = async (caseId: string): Promise<{ message: string }> => {
  try {
    console.log('[caseManagementService] Deleting case:', caseId);
    
    const response = await httpUtility.delete(`${CASES_BASE_PATH}/${caseId}`);
    console.log('[caseManagementService] Delete case response:', response);
    
    // Handle successful deletion (204 No Content)
    if (response.status === 204) {
      return { message: 'Case deleted successfully' };
    }
    
    return response.data as { message: string };
  } catch (error) {
    console.error('[caseManagementService] Failed to delete case:', error);
    throw error;
  }
};
```

### Fix 3: Add Error Handling to Delete Button

Update PredictionTab.tsx to handle deletion errors properly:

```typescript
<Button
  appearance="secondary"
  onClick={async () => {
    if (window.confirm(`Delete case "${currentCase.case_name}"?`)) {
      try {
        await (dispatch as any)(deleteCase(currentCase.case_id));
        toast.success('Case deleted successfully');
        // Optionally refresh the cases list to ensure consistency
        await (dispatch as any)(fetchCases());
      } catch (error) {
        console.error('Failed to delete case:', error);
        toast.error('Failed to delete case. Please try again.');
      }
    }
  }}
>
  🗑️ Delete Case
</Button>
```

## Implementation Steps

1. Fix httpUtility.ts to handle 204 responses
2. Update caseManagementService.ts delete function
3. Add error handling to PredictionTab.tsx delete button
4. Test deletion functionality
5. Verify cases don't reappear after refresh

## Testing Checklist

- [ ] Delete case - no console errors
- [ ] Verify 204 response handled correctly
- [ ] Case removed from UI immediately
- [ ] Page refresh - case stays deleted
- [ ] Delete multiple cases with same name
- [ ] Error handling for failed deletions