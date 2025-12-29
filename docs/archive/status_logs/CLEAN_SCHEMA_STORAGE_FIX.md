# Clean Schema Storage Fix - COMPLETE ✅

## Issue
User reported: "Here's the newly created schema, still a little bit wrong and it also include the meta data"

The blob storage was saving the schema with wrapper objects:
```json
{
  "fieldSchema": { ... },      ← Schema content
  "enhancementMetadata": { ... } ← Should not be in blob!
}
```

## Root Cause Analysis

### What Was Happening

**Frontend (SchemaTab.tsx) sends:**
```typescript
await schemaService.saveSchema({
  mode: 'enhanced',
  schema: hierarchicalSchema,  // Contains: { fieldSchema: {...}, enhancementMetadata: {...} }
  enhancementSummary: aiState.enhancementMetadata
});
```

**Backend (proMode.py line 2469) was saving:**
```python
# PROBLEM: Saved entire req.schema including wrappers
return _save_schema_to_storage(
    schema_obj=req.schema,  # ← Includes fieldSchema + enhancementMetadata!
    ...
)
```

**Result in Blob Storage:**
```json
{
  "fieldSchema": {
    "name": "InvoiceContractVerification",
    "fields": { ... }
  },
  "enhancementMetadata": {  ← ❌ Should NOT be here!
    "originalSchemaId": "...",
    "enhancementType": "general",
    ...
  }
}
```

### Why This Is Wrong

1. **Blob storage should contain ONLY the clean hierarchical schema**
   - Purpose: Used by Azure AI Document Intelligence for analysis
   - Format required: `{ name, description, fields }`
   - Extra metadata confuses the analyzer

2. **Enhancement metadata belongs in Cosmos DB**
   - Already saved separately via `enhancement_summary` parameter
   - Stored in `origin.enhancementSummary` field
   - Used for UI display and tracking

3. **Inconsistent with extraction flow**
   - Save-extracted endpoint saves only the `fieldSchema` part
   - Save-enhanced was saving the entire wrapper
   - Creates different schema formats in blob storage

## Solution Implemented

### Extract Clean Schema Before Saving

Modified `save-enhanced` endpoint to extract only the `fieldSchema` content:

**File:** `proMode.py` (lines 2463-2478)

**Before:**
```python
print(f"[save-enhanced] ✅ Extracted {field_count} fields: {field_names}")

# Save using shared helper
return _save_schema_to_storage(
    schema_obj=req.schema,  # ❌ Saves entire structure with wrappers
    schema_name=req.newName.strip(),
    ...
)
```

**After:**
```python
print(f"[save-enhanced] ✅ Extracted {field_count} fields: {field_names}")

# ✅ CRITICAL: Extract only the fieldSchema for blob storage
# The frontend sends: { fieldSchema: {...}, enhancementMetadata: {...} }
# But blob storage should only contain the clean hierarchical schema
schema_to_save = req.schema.get('fieldSchema', req.schema)

if schema_to_save == req.schema and 'enhancementMetadata' in req.schema:
    # Schema has enhancementMetadata but no fieldSchema wrapper - extract it
    schema_to_save = {k: v for k, v in req.schema.items() if k != 'enhancementMetadata'}
    print(f"[save-enhanced] ⚠️ Removed enhancementMetadata wrapper from schema")

print(f"[save-enhanced] Schema to save keys: {list(schema_to_save.keys())}")

# Save using shared helper
return _save_schema_to_storage(
    schema_obj=schema_to_save,  # ✅ Save clean schema without metadata wrapper
    schema_name=req.newName.strip(),
    ...
)
```

### Logic Flow

```python
# Case 1: Frontend sends { fieldSchema: {...}, enhancementMetadata: {...} }
req.schema = {
    "fieldSchema": {
        "name": "InvoiceContractVerification",
        "fields": { ... }
    },
    "enhancementMetadata": { ... }
}

schema_to_save = req.schema.get('fieldSchema', req.schema)
# Result: { "name": "InvoiceContractVerification", "fields": { ... } }  ✅

# Case 2: Frontend sends { name, fields, enhancementMetadata }
req.schema = {
    "name": "InvoiceContractVerification",
    "fields": { ... },
    "enhancementMetadata": { ... }
}

schema_to_save = req.schema.get('fieldSchema', req.schema)
# First: schema_to_save = req.schema (no fieldSchema key)
# Check: if 'enhancementMetadata' in req.schema → remove it
schema_to_save = {k: v for k, v in req.schema.items() if k != 'enhancementMetadata'}
# Result: { "name": "InvoiceContractVerification", "fields": { ... } }  ✅

# Case 3: Frontend sends clean schema (no wrappers)
req.schema = {
    "name": "InvoiceContractVerification",
    "fields": { ... }
}

schema_to_save = req.schema.get('fieldSchema', req.schema)
# Result: { "name": "InvoiceContractVerification", "fields": { ... } }  ✅
```

## Expected Results

### Before Fix

**Blob Storage Content:**
```json
{
  "fieldSchema": {
    "name": "InvoiceContractVerification",
    "description": "Analyze invoice to confirm total consistency with signed contract",
    "fields": {
      "PaymentTermsInconsistencies": { ... },
      "ItemInconsistencies": { ... },
      "PaymentDueDate": { ... },
      "PaymentTerms": { ... }
    }
  },
  "enhancementMetadata": {
    "originalSchemaId": "4861460e-4b9a-4cfa-a2a9-e03cd688f592",
    "enhancementType": "general",
    "enhancementPrompt": "I also want to extract payment due dates and payment terms",
    "enhancedDate": "2025-10-06T13:24:38.286043",
    "newFieldsAdded": ["PaymentDueDate", "PaymentTerms"],
    "aiReasoning": "..."
  }
}
```

### After Fix

**Blob Storage Content:**
```json
{
  "name": "InvoiceContractVerification",
  "description": "Analyze invoice to confirm total consistency with signed contract",
  "fields": {
    "PaymentTermsInconsistencies": {
      "type": "array",
      "method": "generate",
      "description": "List all areas of inconsistency...",
      "items": {
        "type": "object",
        "properties": {
          "Evidence": { ... },
          "InvoiceField": { ... }
        }
      }
    },
    "ItemInconsistencies": { ... },
    "BillingLogisticsInconsistencies": { ... },
    "PaymentScheduleInconsistencies": { ... },
    "TaxOrDiscountInconsistencies": { ... },
    "PaymentDueDate": {
      "type": "string",
      "method": "generate",
      "description": "Extracts the payment due date from the invoice."
    },
    "PaymentTerms": {
      "type": "string",
      "method": "generate",
      "description": "Extracts the payment terms details from the invoice."
    }
  }
}
```

**Clean hierarchical format** - ready for Azure AI Document Intelligence!

### Cosmos DB Metadata (Unchanged)

```json
{
  "id": "abc123",
  "name": "InvoiceSchema_enhanced_20250106T143022",
  "description": "Enhanced schema with payment fields",
  "fieldCount": 7,
  "fieldNames": [
    "PaymentTermsInconsistencies",
    "ItemInconsistencies",
    "BillingLogisticsInconsistencies",
    "PaymentScheduleInconsistencies",
    "TaxOrDiscountInconsistencies",
    "PaymentDueDate",
    "PaymentTerms"
  ],
  "blobUrl": "https://...blob.../abc123/updated_InvoiceSchema.json",
  "origin": {
    "baseSchemaId": "4861460e-4b9a-4cfa-a2a9-e03cd688f592",
    "method": "ai_enhancement",
    "enhancementSummary": {  ← Enhancement metadata goes here!
      "originalSchemaId": "...",
      "enhancementType": "general",
      "enhancementPrompt": "...",
      "newFieldsAdded": ["PaymentDueDate", "PaymentTerms"],
      "aiReasoning": "..."
    }
  }
}
```

## Testing Verification

### Test Steps
1. **Enhance a schema** with AI prompt
2. **Save the enhanced schema**
3. **Check blob storage** via Azure Portal or CLI:
   ```bash
   az storage blob download \
     --account-name <account> \
     --container-name pro-schemas-cps-configuration \
     --name <schema_id>/updated_<schema_name>.json \
     --file downloaded_schema.json
   ```
4. **Verify content** has NO `fieldSchema` or `enhancementMetadata` wrappers

### Expected Blob Content
```json
{
  "name": "SchemaName",
  "description": "Schema description",
  "fields": {
    "Field1": { "type": "string", "method": "generate", ... },
    "Field2": { "type": "array", "method": "generate", ... }
  }
}
```

### Backend Logs to Watch
```
[save-enhanced] Received schema for InvoiceSchema_enhanced_20250106T143022
[save-enhanced] Schema keys: ['fieldSchema', 'enhancementMetadata']
[save-enhanced] fieldSchema keys: ['name', 'description', 'fields']
[save-enhanced] ✅ Extracted 7 fields: ['PaymentTermsInconsistencies', ...]
[save-enhanced] Schema to save keys: ['name', 'description', 'fields']  ← Clean!
[save-enhanced] Using Pro Mode blob storage
[save-enhanced] ✅ Schema uploaded to blob storage: https://...
```

## Benefits

### 1. Clean Schema Format ✅
Blob storage contains only the hierarchical schema structure needed by Azure AI.

### 2. Consistent with Extraction Flow ✅
Both save-extracted and save-enhanced now store schemas in the same clean format.

### 3. Metadata Preserved ✅
Enhancement metadata is still saved to Cosmos DB via `origin.enhancementSummary`.

### 4. Backward Compatible ✅
Handles multiple input formats from frontend:
- `{ fieldSchema: {...}, enhancementMetadata: {...} }`
- `{ name, fields, enhancementMetadata }`
- `{ name, fields }` (already clean)

### 5. No Frontend Changes Required ✅
Frontend can continue sending the hierarchical schema with wrappers - backend extracts the clean part.

## Files Modified

**Backend:**
- `proMode.py` - Lines 2463-2478: Extract clean schema before saving to blob storage

**Frontend:**
- No changes required ✅

## Architecture Notes

### Storage Separation of Concerns

**Cosmos DB:**
- **Purpose:** Fast queries, listing, metadata
- **Content:** Schema metadata only
- **Fields:** id, name, description, fieldCount, fieldNames, blobUrl, origin
- **Enhancement info:** Stored in `origin.enhancementSummary`

**Azure Blob Storage:**
- **Purpose:** Full schema content for Azure AI Document Intelligence
- **Content:** Complete hierarchical schema structure
- **Format:** Clean JSON with name, description, fields
- **NO metadata:** Just the schema definition

### Why Two Stores?

1. **Cosmos DB** - Fast listing and filtering
   - List all schemas with field counts
   - Search by name or field names
   - Track origins and enhancements

2. **Blob Storage** - Complete schema for analysis
   - Azure AI needs full field definitions
   - Supports large, complex schemas
   - Cost-effective for large JSON

### Data Flow

```
AI Enhancement
  ↓
Enhanced Schema Generated
  { fieldSchema: {...}, enhancementMetadata: {...} }
  ↓
Frontend Sends to Backend
  schema: { fieldSchema: {...}, enhancementMetadata: {...} }
  enhancementSummary: { ...metadata... }
  ↓
Backend Extracts Clean Schema
  schema_to_save = { name, description, fields }  ← No wrappers!
  ↓
Save to Blob Storage
  { name, description, fields }  ← Clean schema only
  ↓
Save Metadata to Cosmos DB
  {
    name, fieldCount, fieldNames, blobUrl,
    origin: { enhancementSummary: {...} }
  }
  ↓
UI Loads Schema
  GET /pro-mode/schemas/{id}?full_content=true
  → Downloads from blob storage
  → Returns clean hierarchical schema
```

---

**Status:** ✅ COMPLETE - Blob storage now contains clean schemas without metadata wrappers
**Date:** January 2025
**Issue:** Enhanced schemas saved with `fieldSchema` and `enhancementMetadata` wrappers
**Resolution:** Backend now extracts only the clean hierarchical schema before saving to blob storage
