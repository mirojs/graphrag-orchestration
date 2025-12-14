# Unified Schema Save Endpoint Implementation ✅

## Overview
Successfully **reused** the `/save-extracted` endpoint to handle both **field extraction** and **AI enhancement** workflows, eliminating the need for a separate `/save-enhanced` endpoint.

## Decision: Reuse vs. Create New

### ✅ **REUSED** `/save-extracted` endpoint

**Rationale:**
1. **Same functionality:** Both endpoints do identical work (save to blob + Cosmos DB)
2. **Only difference:** Input format (flat fields vs. hierarchical schema)
3. **Code maintainability:** Single endpoint reduces duplication
4. **Easier testing:** One endpoint to test and maintain

### ❌ **Did NOT create** separate `/save-enhanced` endpoint

**Why not:**
- Would duplicate 90% of code from `/save-extracted`
- Same storage logic (blob upload + Cosmos DB insert)
- Same validation and error handling
- Only difference is input parsing

---

## Implementation Details

### 1. Backend: Updated Pydantic Model

**File:** `proMode.py` (line ~2184)

```python
class SaveExtractedSchemaRequest(BaseModel):
    baseSchemaId: _Optional[str] = None
    newName: str
    description: _Optional[str] = None
    
    # ✅ Made both optional - exactly ONE must be provided
    fields: _Optional[_List[_Dict[str, _Any]]] = None  # For flat field extraction
    schema: _Optional[_Dict[str, _Any]] = None          # For hierarchical schema (AI-enhanced)
    
    createdBy: _Optional[str] = None
    overwriteIfExists: _Optional[bool] = False
    enhancementSummary: _Optional[_Dict[str, _Any]] = None  # ✅ Track AI enhancements
```

### 2. Backend: Updated Endpoint Logic

**File:** `proMode.py` (line ~2194)

```python
@router.post("/pro-mode/schemas/save-extracted", summary="Save schema from extracted fields or AI enhancement")
async def save_extracted_schema(req: SaveExtractedSchemaRequest, ...):
    """
    Save schema to blob storage and Cosmos DB.
    Accepts either:
    - Flat fields array (for deterministic extraction) - builds hierarchical schema
    - Hierarchical schema object (for AI enhancement) - uses as-is
    """
    # Validate that either fields OR schema is provided
    if not req.fields and not req.schema:
        raise HTTPException(status_code=422, detail="Either 'fields' or 'schema' must be provided")

    # Determine source type and build schema object
    source_method = "deterministic_extraction"
    schema_obj = None
    field_count = 0
    field_names = []
    
    if req.schema:
        # ✅ Hierarchical schema provided (AI enhancement path)
        schema_obj = req.schema
        source_method = "ai_enhancement"
        
        # Extract field count from hierarchical structure
        fields_obj = req.schema.get('fieldSchema', {}).get('fields', req.schema.get('fields', {}))
        if isinstance(fields_obj, dict):
            field_count = len(fields_obj)
            field_names = list(fields_obj.keys())
        elif isinstance(fields_obj, list):
            field_count = len(fields_obj)
            field_names = [f.get('name', f'field_{i}') for i, f in enumerate(fields_obj)]
            
    elif req.fields:
        # ✅ Flat fields provided (extraction path)
        # Validate unique paths (existing logic)
        ...
        # Build hierarchical schema structure from flat fields
        schema_obj = _build_schema_from_flat_fields(req.newName, req.description, req.fields)
        flat_leaf_fields = [f for f in req.fields if not f.get("collectionRoot")]
        field_count = len(flat_leaf_fields)
        field_names = [f.get("name") for f in flat_leaf_fields]

    # Rest of endpoint: Upload to blob + Save to Cosmos DB
    # (identical for both paths)
    ...
```

### 3. Backend: Dynamic Origin Tracking

**File:** `proMode.py` (line ~2295, 2320, 2352)

```python
# Cosmos DB metadata includes dynamic source_method
"origin": {
    "baseSchemaId": req.baseSchemaId,
    "method": source_method,  # ✅ "deterministic_extraction" or "ai_enhancement"
    **({"enhancementSummary": req.enhancementSummary} if req.enhancementSummary else {})
}
```

### 4. Frontend: Updated Save Handler

**File:** `SchemaTab.tsx` (line ~1114)

```typescript
const handleSaveEnhancedSchema = useCallback(async () => {
  // ... validation ...

  // Build payload using unified format (schema instead of fields)
  const payload = {
    baseSchemaId: selectedSchema?.id,
    newName: enhanceDraftName.trim(),
    description: enhanceDraftDescription.trim(),
    schema: aiState.enhancedSchemaDraft,  // ✅ Hierarchical schema for AI enhancement
    createdBy: 'ai_enhancement_ui',
    overwriteIfExists: enhanceOverwriteExisting,
    enhancementSummary: aiState.enhancementSummary  // ✅ Track AI changes
  };
  
  // ✅ Use unified /save-extracted endpoint (accepts both fields and schema)
  const resp = await fetch('/pro-mode/schemas/save-extracted', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  
  // ... handle response, refresh list, auto-select ...
}, [/* deps */]);
```

---

## Comparison: Two Workflows Using Same Endpoint

| Aspect | Field Extraction Workflow | AI Enhancement Workflow |
|--------|---------------------------|-------------------------|
| **Endpoint** | `/save-extracted` | `/save-extracted` (same) |
| **Input Format** | `fields: Array<Field>` | `schema: HierarchicalSchema` |
| **Schema Building** | Backend builds from flat fields | Frontend provides ready schema |
| **Source Method** | `"deterministic_extraction"` | `"ai_enhancement"` |
| **Enhancement Summary** | Not provided | Provided with AI metadata |
| **Blob Storage** | ✅ Full schema | ✅ Full schema |
| **Cosmos DB** | ✅ Metadata | ✅ Metadata |
| **Field Count** | From flat leaf fields | From hierarchical fields |

---

## Request/Response Examples

### Request Example 1: Field Extraction

```json
{
  "baseSchemaId": "schema-123",
  "newName": "Extracted_Invoice_Schema",
  "description": "Schema from extracted fields",
  "fields": [
    {"name": "InvoiceNumber", "type": "string", "path": "InvoiceNumber", "method": "extract"},
    {"name": "TotalAmount", "type": "number", "path": "TotalAmount", "method": "extract"}
  ],
  "createdBy": "extraction_ui",
  "overwriteIfExists": false
}
```

**Backend Processing:**
- Validates flat fields
- Builds hierarchical schema using `_build_schema_from_flat_fields()`
- Sets `source_method = "deterministic_extraction"`
- Uploads to blob + Cosmos DB

### Request Example 2: AI Enhancement

```json
{
  "baseSchemaId": "schema-123",
  "newName": "Enhanced_Invoice_Schema",
  "description": "AI-enhanced schema",
  "schema": {
    "fieldSchema": {
      "name": "EnhancedInvoice",
      "fields": {
        "InvoiceNumber": {"type": "string", "method": "extract"},
        "TotalAmount": {"type": "number", "method": "extract"},
        "TaxRate": {
          "type": "number",
          "method": "generate",
          "enhancementMetadata": {
            "isNew": true,
            "addedByAI": true
          }
        }
      }
    }
  },
  "createdBy": "ai_enhancement_ui",
  "overwriteIfExists": false,
  "enhancementSummary": {
    "newFieldsCount": 1,
    "modifiedFieldsCount": 0,
    "enhancementType": "general"
  }
}
```

**Backend Processing:**
- Uses schema as-is (no building required)
- Extracts field count from hierarchical structure
- Sets `source_method = "ai_enhancement"`
- Stores `enhancementSummary` in origin
- Uploads to blob + Cosmos DB

### Unified Response

Both workflows return the same response format:

```json
{
  "id": "new-schema-uuid",
  "name": "Schema_Name",
  "description": "Schema description",
  "fieldCount": 3,
  "blobUrl": "https://storage.blob.core.windows.net/schemas/schema_uuid.json",
  "createdAt": "2025-10-05T12:34:56.789Z",
  "storage": {
    "cosmos": "ok",
    "blob": "ok"
  },
  "origin": {
    "baseSchemaId": "schema-123",
    "method": "ai_enhancement",  // or "deterministic_extraction"
    "enhancementSummary": { /* if provided */ }
  },
  "overwritten": false
}
```

---

## Benefits of Unified Approach

### 1. Code Reuse ✅
- Single endpoint handles both workflows
- Shared validation, error handling, and storage logic
- Reduced code duplication (~160 lines saved)

### 2. Maintainability ✅
- Changes to storage logic only need to be made once
- Easier to test (one endpoint instead of two)
- Simpler API surface for consumers

### 3. Flexibility ✅
- Can add more input formats in the future
- Schema validation logic centralized
- Easy to extend with new metadata fields

### 4. Consistency ✅
- Same dual storage pattern (blob + DB)
- Same response format for all callers
- Unified error handling and logging

---

## Testing Checklist

- [ ] Test save with `fields` payload (extraction workflow)
- [ ] Test save with `schema` payload (AI enhancement workflow)
- [ ] Verify both paths save to Blob Storage
- [ ] Verify both paths save to Cosmos DB
- [ ] Check `source_method` is correct in DB ("deterministic_extraction" vs "ai_enhancement")
- [ ] Test overwrite mode for both workflows
- [ ] Test conflict detection (409) for both workflows
- [ ] Verify `enhancementSummary` is stored when provided
- [ ] Test auto-select and preview after save
- [ ] Verify field count calculation for both input formats

---

## Migration Notes

### Frontend Changes
- ✅ `handleSaveEnhancedSchema` now uses `/save-extracted` with `schema` payload
- ✅ `handleSaveExtracted` still uses `/save-extracted` with `fields` payload  
- ✅ Both handlers maintain their specific logic but share the backend endpoint

### Backend Changes
- ✅ `SaveExtractedSchemaRequest` model now flexible (accepts `fields` OR `schema`)
- ✅ Endpoint intelligently routes based on which field is provided
- ✅ Origin tracking dynamically set based on input type
- ✅ Enhancement summary conditionally included

### Backward Compatibility
- ✅ Existing field extraction workflow unchanged
- ✅ Same request/response format maintained
- ✅ No breaking changes to API contract

---

## Future Enhancements

1. **Add more input formats:**
   ```python
   class SaveExtractedSchemaRequest(BaseModel):
       fields: Optional[List[Dict]] = None  # Flat extraction
       schema: Optional[Dict] = None        # Hierarchical AI
       rawJson: Optional[str] = None        # Raw JSON import (future)
   ```

2. **Schema versioning:**
   - Track version history in Cosmos DB
   - Store multiple versions in blob storage
   - Allow rollback to previous versions

3. **Validation pipeline:**
   - JSON schema validation before save
   - Field type checking
   - Circular reference detection

4. **Unified service method:**
   - Create `schemaService.saveSchema()` method
   - Replace direct `fetch()` calls in both handlers
   - Centralize HTTP logic and error handling

---

## Related Files

**Backend:**
- `proMode.py` (line 2184-2360): Unified save-extracted endpoint

**Frontend:**
- `SchemaTab.tsx` (line 780): handleSaveExtracted (uses fields payload)
- `SchemaTab.tsx` (line 1114): handleSaveEnhancedSchema (uses schema payload)

**Documentation:**
- `DUAL_STORAGE_PATTERN_IMPLEMENTATION_COMPLETE.md`
- `SCHEMA_SAVE_ENDPOINTS_UNIFIED_PATTERN.md`

---

## Conclusion

Successfully **reused** the `/save-extracted` endpoint for AI enhancement by:
1. Making input fields (`fields` and `schema`) both optional
2. Adding intelligent routing based on which field is provided
3. Dynamically setting `source_method` and storing enhancement metadata
4. Maintaining backward compatibility with existing extraction workflow

This approach:
- ✅ Eliminates code duplication
- ✅ Maintains consistency across workflows
- ✅ Simplifies testing and maintenance
- ✅ Provides clear separation of concerns (frontend logic vs backend storage)

The unified endpoint is ready for testing and deployment! 🚀
