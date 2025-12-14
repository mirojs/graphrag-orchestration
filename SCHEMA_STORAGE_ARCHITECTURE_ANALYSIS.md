# Schema Storage Architecture - Complete Analysis

**Date**: November 18, 2025
**Issue**: Understanding how schemas are stored and displayed, and why "0 fields" appears

## Critical Discovery: Dual Storage Pattern

### Storage Architecture

The system uses **TWO SEPARATE storage locations** for schema data:

#### 1. Cosmos DB (Metadata Only)
**Purpose**: Fast queries for schema list display  
**Stored Data**:
```json
{
  "id": "schema-uuid",
  "name": "My Schema",
  "description": "...",
  "fieldCount": 7,          // ← Metadata count
  "fieldNames": ["field1", "field2", ...],  // ← Array of names only
  "blobUrl": "https://...",  // ← Link to full schema
  "createdAt": "2025-11-18T...",
  "createdBy": "user@email.com",
  "group_id": "group-uuid"
}
```

**What's NOT stored**: Full `fieldSchema.fields` object structure

#### 2. Blob Storage (Complete Schema)
**Purpose**: Full schema content for Azure AI API calls  
**Stored Data**:
```json
{
  "fieldSchema": {
    "name": "My Schema",
    "description": "...",
    "fields": {
      "AllInconsistencies": {
        "type": "array",
        "description": "List of all inconsistencies found",
        "method": "analyze",
        "items": {...}
      },
      "InconsistencySummary": {
        "type": "string",
        "description": "Summary of inconsistencies",
        "method": "analyze"
      }
    }
  }
}
```

**What IS stored**: Complete hierarchical schema with all field definitions

## Data Flow: AI Enhancement Save

### 1. Frontend Sends Schema
**Location**: `SchemaTab.tsx` line 1293  
**Data**: `aiState.originalHierarchicalSchema`
```typescript
await schemaService.saveSchema({
  schema: hierarchicalSchema,  // Contains: {fieldSchema: {fields: {...}}}
  newName: "My Enhanced Schema",
  ...
});
```

### 2. Backend Receives Schema
**Location**: `proMode.py` line 3297 (`save_enhanced_schema`)  
**Validates**:
- Extracts fields from `req.schema.fieldSchema.fields` (line 3326)
- Counts fields (line 3330-3334)
- **REJECTS if field_count == 0** (line 3338-3343)

### 3. Backend Saves to BOTH Locations

#### 3a. Save to Blob Storage
**Location**: `proMode.py` line 3117 (`_save_schema_to_storage`)  
**What**: Full `{fieldSchema: {fields: {...}}}` structure
```python
blob_helper.upload_schema_blob(
    schema_id=schema_id,
    schema_data=schema_obj,  # ← Complete structure
    filename=blob_file_name
)
```

#### 3b. Save to Cosmos DB
**Location**: `proMode.py` line 3186-3207  
**What**: Metadata ONLY (not full fields)
```python
meta_doc = {
    "id": schema_id,
    "name": schema_name,
    "fieldCount": field_count,        # ← Just the count
    "fieldNames": field_names,        # ← Just the names
    "blobUrl": blob_url,              # ← Link to blob
    # NO full fieldSchema.fields here!
}
collection.insert_one(meta_doc)
```

## Data Flow: Schema List Display

### 1. Frontend Requests Schemas
**Location**: `schemaService.ts` line 97 (`fetchSchemas`)
```typescript
const response = await httpUtility.get('/pro-mode/schemas');
```

### 2. Backend Returns Schema List
**Location**: `proMode.py` line 3633 (`get_pro_schemas`)  
**Returns**: Cosmos DB metadata + optional conversion

**Key Logic** (line 3700-3709):
```python
# ✅ NEW: Convert fieldSchema.fields (object) to fields (array) for frontend
if not schema.get("fields") and schema.get("fieldSchema", {}).get("fields"):
    field_dict = schema["fieldSchema"]["fields"]
    if isinstance(field_dict, dict):
        # Convert object to array format for frontend
        schema["fields"] = [
            {"name": field_name, **field_def}
            for field_name, field_def in field_dict.items()
        ]
```

**Problem**: This conversion only works if `fieldSchema.fields` exists in Cosmos DB, but we established that **Cosmos DB only stores metadata**, not the full `fieldSchema.fields`!

### 3. Frontend Displays Field Count
**Location**: `SchemaTab.tsx` line 2173
```typescript
const fieldCount = schema.fieldCount || getSchemaFieldCount(schema);
```

**Logic**:
- **First**: Try `schema.fieldCount` (from Cosmos DB metadata)
- **Fallback**: Call `getSchemaFieldCount(schema)` which checks:
  - `schema.fields.length` (array format)
  - OR `Object.keys(schema.fieldSchema.fields).length` (object format)

## Data Flow: Schema Preview/Full Load

### 1. Frontend Requests Full Schema
**Location**: `SchemaTab.tsx` line 280
```typescript
const fullSchema = await schemaService.getSchemaById(
  activeSchemaId, 
  { includeFullContent: true }
);
```

### 2. Backend Downloads from Blob Storage
**Location**: `proMode.py` line 10687 (`get_schema_by_id`)  
**With `full_content=true`**:
- Downloads complete schema from blob storage (line 10760)
- Returns full `{fieldSchema: {fields: {...}}}` structure

### 3. Frontend Displays Full Fields
**Location**: `SchemaTab.tsx` line 300-350  
**Converts object to array for UI display**:
```typescript
const extractedFields = Object.entries(schemaContent.fieldSchema.fields)
  .map(([fieldName, fieldDef]) => ({
    name: fieldName,
    ...fieldDef
  }));
```

## Root Cause Analysis

### Why "Multi-Document Summarization Analysis Schema_test" Has 0 Fields

The schema has **0 fields in BOTH locations**:

**Cosmos DB**:
```json
{
  "name": "Multi-Document Summarization Analysis Schema_test",
  "fieldCount": 0,
  "fieldNames": []
}
```

**Blob Storage** (full schema):
```json
{
  "fieldSchema": {
    "fields": {}  // ← Empty!
  }
}
```

### Possible Causes

1. **Fields Lost Before Save Validation**
   - Frontend sends `hierarchicalSchema` with empty `fieldSchema.fields: {}`
   - Validation checks pass because code checks wrong property
   - Empty schema gets saved

2. **State Corruption in Redux**
   - `aiState.originalHierarchicalSchema` gets corrupted
   - Fields present initially but lost when accessed for save
   - Empty state sent to backend

3. **Wrong Property Extracted**
   - Backend extracts fields from wrong nested location
   - AI returns fields in unexpected structure
   - Extraction logic misses the actual fields

4. **Legacy Schema** (Most Likely)
   - Schema saved before validation was added
   - No validation existed to prevent empty schemas
   - Old data still in database

## Enhanced Logging Summary

### What We Added

1. **Backend AI Enhancement Return** (`proMode.py` line 12708)
   - Logs full structure being returned
   - Shows first-level field names
   - Displays total field count

2. **Frontend Service Reception** (`intelligentSchemaEnhancerService.ts` line 273)
   - Logs what was received from backend
   - Verifies field structure
   - Tracks field names

3. **UI Save Handler** (`SchemaTab.tsx` line 1286)
   - Logs schema before save
   - Displays field names
   - Shows structure being sent

4. **Backend Save to Blob** (`proMode.py` line 3117) **NEW**
   - Logs exact structure being uploaded to blob storage
   - Shows field count and names
   - Displays full `schema_obj`

5. **Backend Save to Cosmos** (`proMode.py` line 3206) **NEW**
   - Logs metadata being saved
   - Shows `fieldCount` and `fieldNames`
   - Displays full metadata document

## Testing Strategy

### Step 1: Run AI Enhancement with New Logging

1. Select existing schema
2. Click "AI Schema Optimization"
3. Enter prompt: "Add fields for payment information"
4. **Watch Console Logs**:

```
================================================================================
[AI Enhancement] 📤 BACKEND RETURN VALUE:
[AI Enhancement] 📤 First-level field names: ['PaymentTerms', 'DueDate', ...]
[AI Enhancement] 📤 Total field count: 12
================================================================================

================================================================================
[IntelligentSchemaEnhancerService] 📥 FRONTEND RECEIVED FROM BACKEND:
[IntelligentSchemaEnhancerService] 📥 First-level field names: ['PaymentTerms', 'DueDate', ...]
[IntelligentSchemaEnhancerService] 📥 Total field count: 12
================================================================================

================================================================================
[SchemaTab] 💾 UI ABOUT TO SAVE:
[SchemaTab] 💾 First-level field names: ['PaymentTerms', 'DueDate', ...]
[SchemaTab] 💾 Total field count: 12
================================================================================

================================================================================
[_save_schema_to_storage] 💾 SAVING TO BLOB STORAGE:
[_save_schema_to_storage] 💾 Field count: 12
[_save_schema_to_storage] 💾 Field names: ['PaymentTerms', 'DueDate', ...]
[_save_schema_to_storage] 💾 Full schema_obj structure:
{
  "fieldSchema": {
    "fields": {
      "PaymentTerms": {...},
      "DueDate": {...},
      ...
    }
  }
}
================================================================================

================================================================================
[_save_schema_to_storage] 📊 SAVING TO COSMOS DB:
[_save_schema_to_storage] 📊 Field count: 12
[_save_schema_to_storage] 📊 Field names: ['PaymentTerms', 'DueDate', ...]
================================================================================
```

### Step 2: Analyze Logs

**Success Pattern**: All logs show **same field count and names**
```
Backend: 12 fields ['PaymentTerms', ...]
Frontend: 12 fields ['PaymentTerms', ...]  ✅ MATCH
UI: 12 fields ['PaymentTerms', ...]        ✅ MATCH
Blob: 12 fields ['PaymentTerms', ...]      ✅ MATCH
Cosmos: 12 fields ['PaymentTerms', ...]    ✅ MATCH
```

**Failure Pattern**: Fields lost at specific layer
```
Backend: 12 fields
Frontend: 0 fields  ❌ LOST HERE - Check service extraction
```
OR
```
Backend: 12 fields
Frontend: 12 fields
UI: 0 fields  ❌ LOST HERE - Check Redux state
```
OR
```
Backend: 12 fields
Frontend: 12 fields
UI: 12 fields
Blob: 0 fields  ❌ LOST HERE - Check save-enhanced endpoint extraction
```

### Step 3: Inspect Broken Schema

**Through UI**:
1. Go to Pro Mode → Schemas
2. Find "Multi-Document Summarization Analysis Schema_test"
3. Click to load full content
4. Check browser console for schema structure

**What to look for**:
```typescript
// Expected structure
{
  fieldSchema: {
    fields: {
      // Should have fields here!
    }
  }
}

// If empty
{
  fieldSchema: {
    fields: {}  // ❌ This is the problem
  }
}
```

**Check creation date**:
- If created before October 19, 2025 → Legacy schema (before validation)
- If created after October 19, 2025 → Validation bypass or bug

## Next Actions

1. **Deploy Enhanced Logging**
   ```bash
   cd code/content-processing-solution-accelerator
   APP_CONSOLE_LOG_ENABLED=true ./infra/scripts/docker-build.sh
   ```

2. **Test Fresh AI Enhancement**
   - Run end-to-end with logging
   - Capture all console output
   - Verify field count matches at all layers

3. **Inspect Broken Schema**
   - Load "Multi-Document Summarization Analysis Schema_test"
   - Check both Cosmos DB metadata and Blob Storage content
   - Determine if it's legacy data or validation bypass

4. **Fix Based on Findings**
   - If fields lost at frontend: Fix extraction logic
   - If fields lost at UI: Fix Redux state handling
   - If fields lost at backend: Fix save-enhanced processing
   - If legacy schema: Delete and regenerate

## Key Insights

1. **Dual Storage is Intentional**
   - Cosmos DB: Fast metadata queries
   - Blob Storage: Complete schema for Azure AI

2. **Field Count Sources**
   - Schema list: `fieldCount` from Cosmos DB metadata
   - Schema preview: Downloads from blob storage and counts

3. **Two Field Formats**
   - **Storage format**: Object with field names as keys  
     `{fieldSchema: {fields: {FieldName: {...}}}}`
   - **Display format**: Array with name property  
     `{fields: [{name: 'FieldName', ...}]}`

4. **Validation Exists But May Be Bypassed**
   - 5 layers of validation to prevent empty schemas
   - All check for `fieldCount > 0`
   - But broken schema exists with `fieldCount: 0`

5. **Complete Schema vs Schema Fields**
   - You were right! The confusion is between:
     - **Complete schema**: Full `{fieldSchema: {...}}` structure
     - **Schema fields**: Just the `fieldSchema.fields` object
   - Logs and validation must check the RIGHT property

---

**Status**: Enhanced logging added, ready for deployment and testing  
**Files Modified**:
- `proMode.py` (AI enhancement return logging)
- `intelligentSchemaEnhancerService.ts` (Frontend receive logging)
- `SchemaTab.tsx` (UI save logging)
- `proMode.py` `_save_schema_to_storage` (Blob/Cosmos save logging)
