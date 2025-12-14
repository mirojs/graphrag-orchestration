# Orchestrated vs Legacy Analysis - 1:1 Parity Fix

## Problem Identified

The user correctly identified a fundamental architectural inconsistency: **Orchestrated analysis was not a true 1:1 replacement for legacy analysis** in terms of schema handling.

### Root Cause Analysis

**Legacy Analysis (`startAnalysis`):**
- Fetches complete schema with field definitions
- Extracts `fieldSchema` from complete schema 
- Sends `fieldSchema` to backend in `createPayload`
- Backend receives complete field definitions for analyzer creation

**Orchestrated Analysis (`startAnalysisOrchestrated`) - BEFORE FIX:**
- Only passed `schema_id` to backend
- Expected backend to fetch schema internally
- No `fieldSchema` extraction or processing
- Missing complete field definitions

### Console Log Evidence

422 validation errors in orchestrated analysis were caused by:
- Backend expecting complete schema field definitions
- Frontend only sending schema ID
- Mismatch between expected and actual data format

## Solution Implementation

### 1. Updated Interface

**StartAnalysisOrchestratedRequest:**
```typescript
export interface StartAnalysisOrchestratedRequest {
  // ...existing fields
  schema?: any; // ✅ ADD: Complete schema object with field definitions (1:1 parity)
}
```

### 2. Updated Schema Processing Logic

**startAnalysisOrchestrated function now includes:**
- Identical schema validation logic as legacy analysis
- Same priority-based fieldSchema extraction:
  1. `azureSchema.fieldSchema` (clean Azure format)
  2. `originalSchema.fieldSchema` (with object conversion)
  3. `fieldSchema` (direct production-ready format)
  4. `fields` array (UI construction)
- Same error handling and logging
- Sends `field_schema` to backend like legacy analysis

**Backend Request Format:**
```typescript
const backendRequest = {
  analyzer_id: request.analyzerId,
  schema_id: request.schemaId,
  field_schema: fieldSchema, // ✅ NOW INCLUDED - same as legacy analysis
  input_file_ids: request.inputFileIds,
  reference_file_ids: request.referenceFileIds || [],
  // ...other fields
};
```

### 3. Updated Store Logic

**startAnalysisOrchestratedAsync now:**
- Fetches complete schema with field definitions (same as legacy)
- Passes complete schema to orchestrated API service
- Uses identical schema validation and error handling

**Store Call:**
```typescript
const result = await proModeApi.startAnalysisOrchestrated({
  analyzerId: params.analyzerId,
  schemaId: params.schemaId,
  schema: completeSchema, // ✅ NOW INCLUDED - complete schema object
  inputFileIds: params.inputFileIds,
  // ...other fields
});
```

## Expected Results

### Before Fix:
```
[Orchestrated] POST /pro-mode/analysis/orchestrated
{
  "schema_id": "3f96d053-3c28-44fd-8d59-952601e9e293",
  // ❌ Missing field_schema
}
→ 422 Validation Error (missing field definitions)
```

### After Fix:
```
[Orchestrated] POST /pro-mode/analysis/orchestrated  
{
  "schema_id": "3f96d053-3c28-44fd-8d59-952601e9e293",
  "field_schema": {
    "fields": {
      "DocumentIdentification": { "type": "object", ... },
      "DocumentTypes": { "type": "array", ... },
      // ✅ Complete field definitions included
    }
  }
}
→ 200 Success (proper analyzer creation)
```

## Architectural Consistency Achieved

### Both Analysis Paths Now:

1. **Fetch Complete Schema**: Use `fetchSchemaById` to get full field definitions
2. **Extract FieldSchema**: Apply same priority-based extraction logic  
3. **Send Complete Data**: Pass `fieldSchema` to backend for analyzer creation
4. **Handle Errors**: Same validation and error messaging
5. **Process Results**: Identical response handling and state management

### True 1:1 Replacement:
- ✅ Same schema data requirements
- ✅ Same validation logic  
- ✅ Same error handling
- ✅ Same backend data format
- ✅ Same user experience

## User Impact

**Orchestrated Analysis (Primary Path):**
- Should now work properly with complete schema data
- 422 validation errors should be resolved
- Backend can create analyzer with proper field definitions

**Legacy Analysis (Fallback Path):**
- Continues to work as before
- Still provides reliable backup when orchestrated fails
- Maintains existing successful behavior

**User Experience:**
- Users get analysis results through orchestrated path (preferred)
- Fallback still available if orchestrated has other issues
- No need to manually try different analysis methods
- Consistent behavior regardless of which path is used

## Files Modified

1. **proModeApiService.ts**:
   - Updated `StartAnalysisOrchestratedRequest` interface
   - Added complete schema processing to `startAnalysisOrchestrated`
   - Added `field_schema` to backend request payload

2. **proModeStore.ts**:
   - Updated `startAnalysisOrchestratedAsync` to fetch complete schema
   - Pass complete schema to orchestrated API service

## Validation Steps

1. **Test Orchestrated Analysis**: Should now succeed without 422 errors
2. **Compare Payloads**: Orchestrated and legacy should send similar data structures
3. **Verify Fallback**: Legacy analysis should still work as backup
4. **Check Logs**: Should see schema processing logs in both paths
5. **User Testing**: End-to-end analysis should complete successfully

This fix ensures that orchestrated analysis is truly a 1:1 replacement for legacy analysis, addressing the fundamental architectural inconsistency that was causing the 422 validation errors.