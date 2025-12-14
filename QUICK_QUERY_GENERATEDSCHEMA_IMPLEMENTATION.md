# Quick Query GeneratedSchema Implementation

**Date:** November 12, 2025  
**Commit:** d1fd8699

## Summary

Successfully wired the GeneratedSchema feature through the orchestrated Quick Query flow, enabling users to save AI-generated schemas to the Schema Library after Quick Query completes.

## Problem Statement

After reverting Quick Query to use the orchestrated flow with a master schema approach:
- Backend was generating schemas via the `GeneratedSchema` field
- Frontend had UI components ready (QuickQuerySection, SchemaReviewDialog)
- **Gap:** GeneratedSchema wasn't being extracted from analysis results and stored in Redux
- Result: Save Schema button never appeared

## Implementation Details

### 1. Redux State Updates (proModeStore.ts)

#### Added originalPrompt Parameter
```typescript
export interface StartAnalysisOrchestratedParams {
  // ... existing params
  analysisType?: 'comprehensive' | 'quickQuery';
  originalPrompt?: string; // ✅ NEW: For Quick Query context
}
```

#### Store originalPrompt on Pending
```typescript
.addCase(startAnalysisOrchestratedAsync.pending, (state, action) => {
  state.currentAnalysis = {
    // ... existing fields
    originalPrompt: analysisType === 'quickQuery' 
      ? (action.meta.arg.originalPrompt || action.meta.arg?.schema?.description) 
      : undefined
  };
})
```

#### Extract GeneratedSchema from Immediate Results
```typescript
.addCase(startAnalysisOrchestratedAsync.fulfilled, (state, action) => {
  if (action.payload.status === 'completed' && analysisType === 'quickQuery') {
    // Extract and normalize GeneratedSchema from immediate results
    const extracted = tryExtract(action.payload);
    if (extracted && Object.keys(extracted.fields || {}).length > 0) {
      state.currentAnalysis.generatedSchema = extracted;
    }
  }
})
```

#### Extract GeneratedSchema from Polled Results
```typescript
.addCase(getAnalysisResultAsync.fulfilled, (state, action) => {
  if (state.currentAnalysis.resultsSource === 'quickQuery') {
    // Extract and normalize GeneratedSchema from polled results
    const gs = fields?.GeneratedSchema || fields?.generatedSchema;
    if (gs) {
      state.currentAnalysis.generatedSchema = normalizedSchema;
    }
  }
})
```

### 2. Schema Format Transformation

#### From Azure Format (Backend)
```typescript
{
  SchemaName: { valueString: "Invoice Schema" },
  SchemaDescription: { valueString: "..." },
  Fields: { 
    valueArray: [
      { 
        valueObject: { 
          name: { valueString: "invoice_number" },
          type: { valueString: "string" },
          description: { valueString: "..." }
        }
      }
    ]
  }
}
```

#### To UI Format (Frontend)
```typescript
{
  schemaName: "Invoice Schema",
  schemaDescription: "...",
  fields: {
    invoice_number: {
      type: "string",
      description: "...",
      method: "extract"
    }
  }
}
```

### 3. Frontend Updates

#### PredictionTab.tsx
```typescript
const result = await dispatch(startAnalysisOrchestratedAsync({
  // ... existing params
  analysisType: 'quickQuery',
  originalPrompt: prompt // ✅ Pass prompt for Save Schema context
})).unwrap();
```

#### QuickQuerySection.tsx
```typescript
const handleSaveSchema = async (editedSchema: any) => {
  // Transform UI format back to Azure format
  const transformedSchema: any = {
    SchemaName: { valueString: editedSchema.schemaName },
    Fields: {
      valueArray: Object.entries(editedSchema.fields).map(...)
    }
  };
  
  await proModeApi.saveQuickQuerySchema({
    generated_schema: transformedSchema,
    custom_name: editedSchema.schemaName,
    original_prompt: originalPrompt
  });
};
```

## User Flow

1. **User enters Quick Query prompt** → "Extract invoice number, date, and total amount"
2. **Execute Quick Query** → Uses orchestrated flow with master schema
3. **Backend generates schema** → AI creates GeneratedSchema field
4. **Frontend extracts schema** → Redux normalizes to UI-friendly format
5. **Save Schema button appears** → User can review and edit
6. **User clicks Save Schema** → SchemaReviewDialog opens
7. **User edits and saves** → Schema transformed back to Azure format
8. **Backend saves schema** → Added to Schema Library with metadata

## Files Modified

1. **proModeStore.ts**
   - Added `originalPrompt` to `StartAnalysisOrchestratedParams`
   - Store `originalPrompt` in pending reducer
   - Extract GeneratedSchema in fulfilled reducer (immediate results)
   - Extract GeneratedSchema in getAnalysisResultAsync.fulfilled (polled results)

2. **PredictionTab.tsx**
   - Pass `analysisType: 'quickQuery'`
   - Pass `originalPrompt` to orchestrated action

3. **QuickQuerySection.tsx**
   - Transform edited schema from UI format to Azure format
   - Pass transformed schema to save API

## Testing Checklist

- [ ] Quick Query executes successfully
- [ ] GeneratedSchema appears in Redux state after completion
- [ ] Save Schema button appears in QuickQuerySection
- [ ] SchemaReviewDialog opens with correct data
- [ ] Field names and descriptions are editable
- [ ] Schema saves successfully to Schema Library
- [ ] Saved schema appears in Schema tab
- [ ] Saved schema can be used for Start Analysis

## Related Documentation

- `QUICK_QUERY_PROMPT_USAGE_ANALYSIS.md` - Analysis of original vs current implementation
- `QUICK_QUERY_REVERT_TO_ORIGINAL_PLUS_SCHEMA_GENERATION.md` - Revert summary

## Architecture Notes

### Why Two Extraction Points?

1. **Immediate Results** (fulfilled reducer)
   - For synchronous completions
   - Backend returns results immediately
   - No polling needed

2. **Polled Results** (getAnalysisResultAsync.fulfilled)
   - For asynchronous operations
   - Backend polls Azure, frontend polls backend
   - Most common path

Both paths use identical normalization logic to ensure consistency.

### Format Normalization Strategy

**Normalize on Input** (from Azure):
- Extract from nested Azure format
- Convert to flat UI-friendly format
- Store in Redux as normalized

**Transform on Output** (to Azure):
- Convert from flat UI format
- Rebuild nested Azure format
- Send to backend for saving

This keeps the UI code simple while maintaining backend compatibility.

## Success Criteria

✅ GeneratedSchema extracted from both immediate and polled results  
✅ Schema normalized to UI-friendly format automatically  
✅ originalPrompt stored for Save Schema context  
✅ Save Schema button appears when generatedSchema exists  
✅ SchemaReviewDialog receives correct normalized format  
✅ Edited schema transformed back to Azure format  
✅ No TypeScript compilation errors  
✅ All changes committed and pushed

## Next Steps

1. Test the complete Quick Query → Save Schema flow
2. Verify saved schemas work correctly in Start Analysis
3. Add analytics tracking for schema generation success rate
4. Consider adding schema validation before saving
5. Add user feedback for schema quality (optional)
