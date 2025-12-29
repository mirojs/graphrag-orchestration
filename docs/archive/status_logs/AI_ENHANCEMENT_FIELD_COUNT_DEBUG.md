# 🔍 AI Enhancement Field Count Investigation

## Problem Report

After saving an AI-enhanced schema, the saved schema only shows **5 fields** (same as original) instead of the expected **7+ fields** (original + new fields added by AI).

## Investigation Steps

### Data Flow Analysis

```
1. User selects schema with 5 fields
        ↓
2. User requests AI enhancement: "I also want to extract payment due dates and payment terms"
        ↓
3. Backend calls Azure AI
        ↓
4. Azure AI returns: 2 new fields (PaymentDueDates, PaymentTerms)
        ↓
5. Backend merges: 5 original + 2 new = 7 total fields
        ↓
6. Backend returns enhanced_schema with 7 fields
        ↓
7. Frontend stores originalHierarchicalSchema (should have 7 fields)
        ↓
8. User saves enhanced schema
        ↓
9. Frontend sends hierarchicalSchema to save-enhanced endpoint
        ↓
10. Backend saves to blob storage & Cosmos DB
        ↓
11. ❓ Saved schema shows only 5 fields ❓
```

### Potential Root Causes

#### Hypothesis 1: Frontend Not Preserving Enhanced Schema ❌
- **Check**: `aiState.originalHierarchicalSchema` in SchemaTab.tsx
- **Code**: Line 1121 - Stores `enhancementResult.originalHierarchicalSchema`
- **Source**: intelligentSchemaEnhancerService.ts line 143 - Gets `responseData.enhanced_schema`
- **Verdict**: Frontend IS preserving the enhanced schema correctly

#### Hypothesis 2: Backend Losing Fields During Merge ⚠️ INVESTIGATING
- **Check**: proMode.py lines 11040-11095 (enhanced schema building)
- **Process**: 
  1. Deep copy original schema (line 11044)
  2. Add new fields to copy (lines 11054-11085)
  3. Should have all original + new fields
- **Added Debug Logging**:
  - Line 11088: Print total fields in enhanced schema
  - Line 11089: Print all field names in enhanced schema

#### Hypothesis 3: Save Endpoint Miscounting Fields ⚠️ INVESTIGATING  
- **Check**: proMode.py lines 2394-2428 (save-enhanced endpoint)
- **Process**:
  1. Extract fields from `req.schema.fieldSchema.fields`
  2. Count fields
  3. Save to Cosmos DB metadata
- **Added Debug Logging**:
  - Lines 2405-2415: Print received schema structure
  - Line 2426: Print extracted field count and names

#### Hypothesis 4: Original Schema Missing Some Fields ⚠️ POSSIBLE
- **Check**: What does `original_schema` actually contain when downloaded from blob?
- **Issue**: If original schema in blob storage only has 5 fields, then:
  - Deep copy will have 5 fields
  - Add 2 new fields → 7 total ✅
  - BUT: If backend downloads WRONG schema version, might still have 5

### Debug Logging Added

#### Backend: AI Enhancement Endpoint (proMode.py)

```python
# After building enhanced schema (line ~11088)
total_fields_in_enhanced = len(enhanced_schema_result.get("fieldSchema", {}).get("fields", {}))
print(f"[AI Enhancement] 🔍 Total fields in enhanced schema: {total_fields_in_enhanced}")
print(f"[AI Enhancement] 🔍 Field names in enhanced schema: {list(enhanced_schema_result.get('fieldSchema', {}).get('fields', {}).keys())}")
```

**Expected Output**:
```
[AI Enhancement] 🔍 Total fields in enhanced schema: 7
[AI Enhancement] 🔍 Field names in enhanced schema: ['OriginalField1', 'OriginalField2', 'OriginalField3', 'OriginalField4', 'OriginalField5', 'PaymentDueDates', 'PaymentTerms']
```

#### Backend: Save-Enhanced Endpoint (proMode.py)

```python
# When receiving save request (lines ~2405-2426)
print(f"[save-enhanced] Received schema for {req.newName}")
print(f"[save-enhanced] Schema keys: {list(req.schema.keys())}")
if 'fieldSchema' in req.schema:
    print(f"[save-enhanced] fieldSchema keys: {list(req.schema['fieldSchema'].keys())}")
    if 'fields' in req.schema['fieldSchema']:
        fields_in_schema = req.schema['fieldSchema']['fields']
        print(f"[save-enhanced] fieldSchema.fields type: {type(fields_in_schema)}")
        if isinstance(fields_in_schema, dict):
            print(f"[save-enhanced] fieldSchema.fields keys: {list(fields_in_schema.keys())}")
# ... field extraction code ...
print(f"[save-enhanced] ✅ Extracted {field_count} fields: {field_names}")
```

**Expected Output**:
```
[save-enhanced] Received schema for Updated Schema_enhanced
[save-enhanced] Schema keys: ['fieldSchema', 'enhancementMetadata']
[save-enhanced] fieldSchema keys: ['name', 'description', 'fields']
[save-enhanced] fieldSchema.fields type: <class 'dict'>
[save-enhanced] fieldSchema.fields keys: ['OriginalField1', 'OriginalField2', 'OriginalField3', 'OriginalField4', 'OriginalField5', 'PaymentDueDates', 'PaymentTerms']
[save-enhanced] ✅ Extracted 7 fields: ['OriginalField1', 'OriginalField2', 'OriginalField3', 'OriginalField4', 'OriginalField5', 'PaymentDueDates', 'PaymentTerms']
```

#### Frontend: schemaService.ts

Already has logging at line 69:
```typescript
console.log('[schemaService] Sending save-enhanced payload:', JSON.stringify(payload, null, 2));
```

**Expected Output**:
```json
{
  "baseSchemaId": "original-schema-id",
  "newName": "Updated Schema_enhanced",
  "description": "",
  "schema": {
    "fieldSchema": {
      "name": "InvoiceContractVerification",
      "description": "...",
      "fields": {
        "OriginalField1": {...},
        "OriginalField2": {...},
        "OriginalField3": {...},
        "OriginalField4": {...},
        "OriginalField5": {...},
        "PaymentDueDates": {...},
        "PaymentTerms": {...}
      }
    }
  },
  "createdBy": "ai_enhancement_ui",
  "overwriteIfExists": false,
  "enhancementSummary": {...}
}
```

### Next Steps for Testing

1. **Run AI Enhancement** with prompt: "I also want to extract payment due dates and payment terms"

2. **Check Browser Console** for:
   - `[schemaService] Sending save-enhanced payload:` - Should show 7 fields in schema object

3. **Check Backend Logs** for:
   - `[AI Enhancement] 🔍 Total fields in enhanced schema:` - Should show 7
   - `[AI Enhancement] 🔍 Field names in enhanced schema:` - Should list all 7 field names
   - `[save-enhanced] fieldSchema.fields keys:` - Should list all 7 field names  
   - `[save-enhanced] ✅ Extracted X fields:` - Should show 7

4. **Verify Saved Schema**:
   - Check Cosmos DB: `fieldCount` should be 7
   - Check Blob Storage: `fieldSchema.fields` should have 7 keys
   - Check Frontend: Selected schema should show 7 fields

### Possible Outcomes

#### Scenario A: Backend Shows 7, Frontend Sends 7, Saved Has 5
→ Problem is in `_save_schema_to_storage` function (how it saves to blob/Cosmos)

#### Scenario B: Backend Shows 7, Frontend Sends 5
→ Problem is `originalHierarchicalSchema` not being set correctly in frontend

#### Scenario C: Backend Shows 5 (Not 7)
→ Problem is in Azure AI response parsing or field merging logic

#### Scenario D: Everything Shows 7, But Preview Shows 5
→ Problem is in how frontend loads schema from blob storage

---

**Status**: ⏳ DEBUG LOGGING ADDED - Ready for testing to identify where fields are lost
