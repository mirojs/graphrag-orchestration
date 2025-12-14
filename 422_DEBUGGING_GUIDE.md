# 422 Validation Error Debugging Guide

## Current Status

✅ **Schema structure is CORRECT** - Test validation passed
✅ **Hierarchical format is CORRECT** - `{fieldSchema: {fields: {...}}}`
❌ **422 error persists** - Need to find exact validation issue

## What We Know

### From Console Logs:
```
[SchemaTab] Converting ProModeSchema to hierarchical format for save...
[SchemaTab] Hierarchical schema for save: {fieldSchema: {…}}
POST /pro-mode/schemas/save-enhanced 422 (Unprocessable Content)
{detail: Array(1), message: 'Validation error'}
```

### Test Results:
- ✅ Schema structure validation PASSED
- ✅ Has `fieldSchema.fields` as dictionary
- ✅ All 7 fields present with correct structure
- ✅ New fields (PaymentDueDate, PaymentTerms) present

## Possible Issues

### 1. enhancementSummary Format
**Check:** Is `enhancementSummary` being sent as string or dict?

From backend model:
```python
enhancementSummary: Optional[Dict[str, Any]] = None  # Must be dict!
```

From frontend:
```typescript
enhancementSummary: aiState.enhancementSummary  // What type is this?
```

**Action:** Need to verify `aiState.enhancementSummary` is an object, not a string

### 2. Field Type Values
**Check:** Are field types valid?

Current types in test:
- `"array"` - ✅ Valid
- `"date"` - ⚠️  Might need to be `"string"` or specific Azure type
- `"string"` - ✅ Valid

### 3. Method Values
**Check:** Is `"method": "required"` valid?

Backend might expect:
- `"method": "prebuilt"` or
- No `method` field at all for AI-enhanced schemas

### 4. Missing Required Fields
**Check:** Are all required fields present?

Required by backend:
- ✅ `newName` - Present
- ✅ `schema` - Present
- Optional: `baseSchemaId`, `description`, `createdBy`, `overwriteIfExists`, `enhancementSummary`

## Next Steps to Debug

### Step 1: Check Frontend Payload
Add this logging in SchemaTab.tsx before the save call:
```typescript
console.log('[SchemaTab] Full payload being sent:');
console.log('  newName:', enhanceDraftName.trim());
console.log('  description:', enhanceDraftDescription.trim());
console.log('  schema:', JSON.stringify(hierarchicalSchema, null, 2));
console.log('  enhancementSummary type:', typeof aiState.enhancementSummary);
console.log('  enhancementSummary value:', JSON.stringify(aiState.enhancementSummary, null, 2));
```

### Step 2: Enhanced Error Logging
Already added in httpUtility.ts:
```typescript
if (Array.isArray(data?.detail)) {
  console.error(`[httpUtility] Validation errors:`, JSON.stringify(data.detail, null, 2));
}
```

This will show:
```json
[
  {
    "loc": ["body", "schema", "fieldName"],
    "msg": "field required",
    "type": "value_error.missing"
  }
]
```

### Step 3: Test Without enhancementSummary
Try sending minimal payload:
```typescript
const data = await schemaService.saveSchema({
  mode: 'enhanced',
  newName: enhanceDraftName.trim(),
  schema: hierarchicalSchema,
  // Remove optional fields to isolate issue
});
```

### Step 4: Check Field Types
Azure Content Understanding API field types:
- `string`
- `number`
- `integer`
- `boolean`
- `date`
- `time`
- `array`
- `object`

Our test uses:
- ✅ `array`
- ⚠️  `date` - Verify this is valid
- ✅ `string`

## Expected Debugging Output

After rebuilding with enhanced logging, you should see:

### If enhancementSummary is the issue:
```
[schemaService] enhancementSummary type: string  // ❌ Should be object!
[httpUtility] Validation errors: [
  {
    "loc": ["body", "enhancementSummary"],
    "msg": "value is not a valid dict",
    "type": "type_error.dict"
  }
]
```

### If field type is the issue:
```
[httpUtility] Validation errors: [
  {
    "loc": ["body", "schema", "fieldSchema", "fields", "PaymentDueDate", "type"],
    "msg": "unexpected value; permitted: 'string', 'number', 'boolean', 'array', 'object'",
    "type": "value_error.const"
  }
]
```

### If method field is the issue:
```
[httpUtility] Validation errors: [
  {
    "loc": ["body", "schema", "fieldSchema", "fields", "PaymentDueDate", "method"],
    "msg": "extra fields not permitted",
    "type": "value_error.extra"
  }
]
```

## Quick Fix Attempts

### Fix 1: Ensure enhancementSummary is object
```typescript
enhancementSummary: typeof aiState.enhancementSummary === 'string' 
  ? JSON.parse(aiState.enhancementSummary) 
  : aiState.enhancementSummary
```

### Fix 2: Remove method field
```typescript
hierarchicalSchema.fieldSchema.fields[field.name] = {
  type: field.type,
  description: field.description
  // Remove: method: field.method
};
```

### Fix 3: Normalize field types
```typescript
const normalizedType = field.type === 'date' ? 'string' : field.type;
hierarchicalSchema.fieldSchema.fields[field.name] = {
  type: normalizedType,
  description: field.description
};
```

## Test Command

After adding logging and rebuilding:
```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm run build
```

Then test in browser and check console for:
1. `[schemaService] Sending save-enhanced payload:` - See full payload
2. `[httpUtility] Validation errors:` - See exact validation failures
3. Frontend should display detailed error info

## Backend Validation Code Location

File: `proMode.py`
Line: ~2394
```python
@router.post("/pro-mode/schemas/save-enhanced")
async def save_enhanced_schema(req: SaveEnhancedSchemaRequest, ...):
    if not req.newName.strip():
        raise HTTPException(status_code=422, detail="newName is required")
    if not req.schema:
        raise HTTPException(status_code=422, detail="schema object is required")
```

Pydantic will automatically validate the request body against `SaveEnhancedSchemaRequest` model before the function executes. The `detail` array contains Pydantic validation errors.
