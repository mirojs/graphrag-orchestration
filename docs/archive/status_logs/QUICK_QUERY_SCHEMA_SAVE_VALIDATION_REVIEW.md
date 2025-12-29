# Quick Query Schema Save Process - Current State Review

**Date**: January 11, 2025
**Status**: ⚠️ **VALIDATION REQUIRED** - Code needs verification and potential fixes

---

## Summary

After implementing 7D enhancement integration, we need to review the Quick Query → Save Schema workflow to ensure it's compatible with the new `apply7d` flag system.

---

## Current Workflow (As Documented)

### Phase 1: Quick Query Execution
1. User enters natural language prompt in Quick Query
2. System executes analysis using `quick_query_master` schema
3. Results displayed to user

### Phase 2: Save as Schema
1. User clicks "Save as Schema" button
2. **Re-execution** with `includeSchemaGeneration=true` flag
3. Backend generates schema using AI (query_schema_generator.py)
4. Returns `GeneratedSchema` object with structure:
   ```typescript
   {
     schemaName: string,
     schemaDescription: string,
     fields: Record<string, FieldDefinition>
   }
   ```

### Phase 3: Schema Review & Save
1. `SchemaReviewDialog` opens with generated schema
2. User edits name, description, field descriptions
3. User clicks "Save"
4. Schema converted to `ProModeSchema` format
5. **`createSchema` Redux action** dispatched
6. Backend saves schema to database
7. Schema appears in Schema List

---

## Issues Found

### 🔴 Issue 1: Schema Format Mismatch

**In schemaActions.ts (lines 78-81)**:
```typescript
const payload = {
  schema: schemaData,  // ❌ PROBLEM: schemaData includes apply7d field
  apply7d: schemaData.apply7d !== undefined ? schemaData.apply7d : true
};
```

**Backend Expects**:
```python
{
  "schema": {
    "displayName": "...",
    "description": "...",
    "fields": [...]
    // NO apply7d here
  },
  "apply7d": true  // At request level, not in schema object
}
```

**Fix Needed**:
```typescript
// Extract apply7d before creating payload
const { apply7d, ...schemaDataWithoutFlag } = schemaData;

const payload = {
  schema: schemaDataWithoutFlag,  // ✅ Clean schema without apply7d
  apply7d: apply7d !== undefined ? apply7d : true
};
```

---

### 🟡 Issue 2: Missing Implementation in PredictionTab.tsx

**Documentation States** (from QUICK_QUERY_SAVE_PROMPT_INTEGRATION_COMPLETE.md):
- `handleSaveGeneratedSchema` function should exist
- `SchemaReviewDialog` component should be rendered
- State variables: `showSchemaReviewDialog`, `generatedSchemaForReview`, `lastQuickQueryPrompt`

**Current Reality**:
```bash
grep "handleSaveGeneratedSchema" PredictionTab.tsx
# No matches found

grep "SchemaReviewDialog" PredictionTab.tsx  
# No matches found
```

**Status**: ⚠️ Feature may not be fully implemented in PredictionTab.tsx

---

### 🟡 Issue 3: Schema Format Conversion Unclear

**Documented Flow** (from QUICK_QUERY_SAVE_PROMPT_INTEGRATION_COMPLETE.md line 186):
```typescript
const handleSaveGeneratedSchema = async (editedSchema: any) => {
  const schemaToSave = {
    name: editedSchema.schemaName,
    description: editedSchema.schemaDescription,
    fields: editedSchema.fields,
    azureFormat: {
      description: editedSchema.schemaDescription,
      fieldSchema: editedSchema.fields
    }
  };
  
  const result = await dispatch(createSchema(schemaToSave)).unwrap();
};
```

**Backend Expects** (from proMode.py line 10420):
```python
complete_schema = request["schema"]
# Must have: displayName, description, fields (array), kind
```

**Problem**: 
- Documentation uses `name` but backend expects `displayName`
- Documentation uses `azureFormat.fieldSchema` but unclear if backend needs this
- Backend expects `fields` as array with `name`, `type`, `description` properties

**Correct Format Should Be**:
```typescript
const schemaToSave = {
  displayName: editedSchema.schemaName,  // ✅ Match backend
  description: editedSchema.schemaDescription,
  kind: 'structured',  // ✅ Add required field
  fields: Object.entries(editedSchema.fields).map(([name, def]) => ({
    name: name,
    type: def.type,
    description: def.description,
    method: def.method || 'generate'
  })),
  apply7d: true  // ✅ Enable 7D enhancement for saved schemas
};
```

---

## Backend Processing Flow (Verified)

### POST /pro-mode/schemas/create (proMode.py lines 10373-10600)

**1. Extract apply7d flag** ✅
```python
apply_7d = request.get("apply7d", False)
```

**2. Extract schema object** ✅
```python
complete_schema = request["schema"]
displayName = complete_schema['displayName']
description = complete_schema.get('description', '')
kind = complete_schema.get('kind', 'structured')
```

**3. Process unified format** ✅
```python
def process_unified_schema_to_azure_format(schema_obj):
    azure_fields = {}
    if "fields" in schema_obj and isinstance(schema_obj["fields"], list):
        for field in schema_obj["fields"]:
            azure_fields[field["name"]] = {
                "type": field["type"],
                "description": field.get("description", ""),
                "method": "generate"
            }
    return {"fields": azure_fields}
```

**4. Apply 7D if requested** ✅
```python
if apply_7d:
    from backend.utils.schema_7d_enhancer import enhance_schema_with_7d
    enhanced_schema = enhance_schema_with_7d(
        extracted_fields,
        schema_context=complete_schema.get('description', 'general extraction')
    )
    extracted_fields = enhanced_schema
```

**5. Save to database** ✅
```python
db_schema = {
    "id": schema_id,
    "ClassName": schema_data["displayName"],
    "Description": schema_data["description"],
    "SchemaData": schema_data,  # Full schema with unified format
    "FieldCount": len(field_names),
    "has7dEnhancement": apply_7d  # ✅ Track enhancement status
}
collection.insert_one(db_schema)
```

---

## Required Fixes

### Fix 1: Update schemaActions.ts ✅ (PRIORITY: HIGH)

**File**: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeStores/schemaActions.ts`

**Current Code** (lines 74-97):
```typescript
export const createSchema = createAsyncThunk(
  'schemas/createSchema',
  async (schemaData: Partial<ProModeSchema> & { apply7d?: boolean }, { rejectWithValue }) => {
    try {
      // Include apply7d flag in request payload for 7D enhancement
      const payload = {
        schema: schemaData,  // ❌ WRONG
        apply7d: schemaData.apply7d !== undefined ? schemaData.apply7d : true
      };
```

**Fixed Code**:
```typescript
export const createSchema = createAsyncThunk(
  'schemas/createSchema',
  async (schemaData: Partial<ProModeSchema> & { apply7d?: boolean }, { rejectWithValue }) => {
    try {
      // Extract apply7d flag before building payload
      const { apply7d, ...schemaDataClean } = schemaData;
      
      // Include apply7d flag in request payload for 7D enhancement
      const payload = {
        schema: schemaDataClean,  // ✅ Clean schema without apply7d field
        apply7d: apply7d !== undefined ? apply7d : true  // Default to true
      };
```

---

### Fix 2: Verify/Implement PredictionTab.tsx Integration (PRIORITY: MEDIUM)

**Required Code** (based on documentation):

```typescript
// 1. Add imports
import SchemaReviewDialog from './SchemaReviewDialog';
import { createSchema } from '../ProModeStores/schemaActions';

// 2. Add state
const [showSchemaReviewDialog, setShowSchemaReviewDialog] = useState(false);
const [generatedSchemaForReview, setGeneratedSchemaForReview] = useState<any>(null);
const [lastQuickQueryPrompt, setLastQuickQueryPrompt] = useState<string>('');

// 3. Update handleQuickQueryExecute to accept includeSchemaGeneration parameter
const handleQuickQueryExecute = async (
  prompt: string, 
  includeSchemaGeneration: boolean = false
) => {
  setLastQuickQueryPrompt(prompt);
  
  // ... existing dispatch logic ...
  
  const result = await dispatch(executeQuickQueryEphemeralAsync({
    prompt,
    inputFileIds,
    referenceFileIds,
    includeSchemaGeneration  // Pass flag to backend
  })).unwrap();
  
  // Check for generated schema
  if (includeSchemaGeneration && result.generatedSchema) {
    setGeneratedSchemaForReview(result.generatedSchema);
    setShowSchemaReviewDialog(true);
  }
};

// 4. Add save handler
const handleSaveGeneratedSchema = async (editedSchema: any) => {
  try {
    // Convert GeneratedSchema format to ProModeSchema format
    const schemaToSave = {
      displayName: editedSchema.schemaName,
      description: editedSchema.schemaDescription,
      kind: 'structured',
      fields: Object.entries(editedSchema.fields).map(([name, def]: [string, any]) => ({
        name: name,
        type: def.type,
        description: def.description,
        method: def.method || 'generate',
        ...(def.items && { items: def.items }),
        ...(def.properties && { properties: def.properties })
      })),
      apply7d: true  // Enable 7D enhancement for Quick Query saved schemas
    };
    
    console.log('[PredictionTab] Saving schema with 7D enhancement:', schemaToSave);
    
    const result = await dispatch(createSchema(schemaToSave)).unwrap();
    
    toast.success(`Schema "${editedSchema.schemaName}" saved to library with 7D enhancement`);
    setShowSchemaReviewDialog(false);
    setGeneratedSchemaForReview(null);
    
    // Refresh schema list
    await dispatch(fetchSchemas());
    
  } catch (error: any) {
    console.error('[PredictionTab] Failed to save schema:', error);
    toast.error(`Failed to save schema: ${error.message || 'Unknown error'}`);
  }
};

// 5. Add dialog to JSX
<SchemaReviewDialog
  isOpen={showSchemaReviewDialog}
  onClose={() => {
    setShowSchemaReviewDialog(false);
    setGeneratedSchemaForReview(null);
  }}
  generatedSchema={generatedSchemaForReview}
  originalPrompt={lastQuickQueryPrompt}
  onSave={handleSaveGeneratedSchema}
/>
```

---

### Fix 3: Update QuickQuerySection.tsx (PRIORITY: MEDIUM)

**Required**: Verify that `onQueryExecute` prop accepts `includeSchemaGeneration` parameter

**Expected signature**:
```typescript
interface QuickQuerySectionProps {
  onQueryExecute: (prompt: string, includeSchemaGeneration?: boolean) => Promise<void>;
  isExecuting: boolean;
}
```

**Handler**:
```typescript
const handleSavePrompt = async () => {
  if (!lastExecutedPrompt.trim()) {
    toast.warning('Please execute a query first');
    return;
  }
  
  setIsSavingSchema(true);
  try {
    // Re-execute with schema generation enabled
    await onQueryExecute(lastExecutedPrompt, true);  // true = include schema generation
  } catch (error) {
    console.error('[QuickQuery] Schema generation failed:', error);
    toast.error('Failed to generate schema');
  } finally {
    setIsSavingSchema(false);
  }
};
```

---

## Testing Checklist

### Unit Tests
- [ ] **schemaActions.ts**: Verify `createSchema` properly separates `apply7d` from schema data
- [ ] **schemaActions.ts**: Verify backend receives correct payload structure
- [ ] **Backend**: Verify `apply_7d` flag is extracted from request
- [ ] **Backend**: Verify 7D enhancement is applied when `apply7d=true`
- [ ] **Backend**: Verify `has7dEnhancement` field is saved to database

### Integration Tests
- [ ] **Quick Query → Save**: Execute query, click "Save as Schema"
- [ ] **Schema Generation**: Verify backend returns `GeneratedSchema` object
- [ ] **Schema Review Dialog**: Opens with correct data (name, description, fields)
- [ ] **Schema Edit**: User can edit name, description, field descriptions
- [ ] **Schema Save**: Click save → schema appears in Schema List
- [ ] **7D Enhancement**: Saved schema has `has7dEnhancement: true` in database
- [ ] **7D Descriptions**: Field descriptions include 7D templates

### End-to-End Tests
- [ ] User completes full workflow: Query → Save → Edit → Save → Use in Analysis
- [ ] Saved schema can be selected from Schema List
- [ ] Saved schema works for extraction on new documents
- [ ] 7D-enhanced schema improves extraction quality vs basic schema

---

## Rollback Plan

If issues found:

### Option 1: Disable 7D for Quick Query Schemas
```typescript
// In handleSaveGeneratedSchema
apply7d: false  // Temporarily disable
```

### Option 2: Revert schemaActions.ts Changes
```typescript
// Revert to simple pass-through (no 7D)
const response = await httpUtility.post(SCHEMA_ENDPOINTS.CREATE, schemaData);
```

### Option 3: Disable "Save as Schema" Button
```typescript
// In QuickQuerySection.tsx
const canSavePrompt = false;  // Hide button
```

---

## Next Steps

### Immediate (Required)
1. ✅ **Fix schemaActions.ts** - Extract `apply7d` before building payload
2. ⏳ **Verify PredictionTab.tsx** - Check if `handleSaveGeneratedSchema` exists
3. ⏳ **Verify QuickQuerySection.tsx** - Check if "Save as Schema" button exists
4. ⏳ **Test end-to-end** - Execute full workflow in development

### Short-term (Recommended)
5. Add unit tests for schema format conversion
6. Add integration test for Quick Query → Save workflow
7. Verify 7D enhancement is applied to saved schemas
8. Check database for `has7dEnhancement` field

### Long-term (Future)
9. Add UI indicator showing 7D enhancement status
10. Add analytics tracking for schema save success rate
11. Monitor extraction quality improvements from 7D schemas

---

## Conclusion

**Current Status**: ⚠️ **NEEDS VALIDATION**

**Issues Found**:
1. 🔴 **schemaActions.ts**: Payload structure incorrect - `apply7d` field included in schema object
2. 🟡 **PredictionTab.tsx**: Integration code may not be implemented (documentation vs reality mismatch)
3. 🟡 **Schema format conversion**: Documented format doesn't match backend expectations

**Recommendation**: 
1. Apply Fix #1 to schemaActions.ts immediately
2. Search codebase for actual Quick Query save implementation
3. Test end-to-end workflow before production deployment
4. Update documentation to match actual implementation

---

**Generated**: January 11, 2025  
**Reviewed By**: AI Assistant  
**Status**: Pending Human Review & Testing
