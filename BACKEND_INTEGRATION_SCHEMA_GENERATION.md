# Backend Integration - Quick Query Schema Generation

**Date**: January 11, 2025  
**Status**: Required for Feature Completion  
**Priority**: HIGH

---

## Overview

The frontend "Save Prompt" feature is complete and waiting for backend support. This document specifies the required backend changes.

---

## Required Changes

### 1. Update Quick Query Ephemeral API Endpoint

**File**: `backend/routes/pro_mode.py` (or equivalent endpoint handler)

**Current behavior**: Returns analysis results only

**Required behavior**: When `include_schema_generation=true`, also return the generated schema

---

### API Request Format

**Endpoint**: `POST /pro-mode/quick-query/ephemeral`

**Request body** (add new field):
```json
{
  "prompt": "Extract invoice number, total, vendor, date",
  "inputFileIds": ["blob-id-1", "blob-id-2"],
  "referenceFileIds": [],
  "includeSchemaGeneration": true  // ← NEW FIELD (optional, default false)
}
```

---

### API Response Format

**When includeSchemaGeneration = false** (existing behavior):
```json
{
  "analyzerId": "analyzer-uuid",
  "operationId": "operation-uuid",
  "result": {
    "analyzeResult": { /* normal analysis results */ }
  },
  "totalDocuments": 2
}
```

**When includeSchemaGeneration = true** (NEW required behavior):
```json
{
  "analyzerId": "analyzer-uuid",
  "operationId": "operation-uuid",
  "result": {
    "analyzeResult": { /* normal analysis results */ }
  },
  "totalDocuments": 2,
  "generatedSchema": {  // ← NEW FIELD
    "schemaName": "InvoiceExtractionSchema",
    "schemaDescription": "Extracts invoice number, total amount, vendor name, and invoice date from invoice documents",
    "fields": {
      "InvoiceNumber": {
        "type": "string",
        "description": "The unique invoice identifier",
        "method": "extract"
      },
      "TotalAmount": {
        "type": "number",
        "description": "The total invoice amount",
        "method": "extract"
      },
      "VendorName": {
        "type": "string",
        "description": "The name of the vendor or supplier",
        "method": "extract"
      },
      "InvoiceDate": {
        "type": "string",
        "format": "date",
        "description": "The date the invoice was issued",
        "method": "extract"
      }
    }
  }
}
```

---

## Implementation Guide

### Step 1: Accept includeSchemaGeneration Parameter

```python
from pydantic import BaseModel
from typing import Optional, List

class QuickQueryEphemeralRequest(BaseModel):
    prompt: str
    inputFileIds: List[str]
    referenceFileIds: Optional[List[str]] = []
    includeSchemaGeneration: Optional[bool] = False  # NEW FIELD

@router.post("/quick-query/ephemeral")
async def quick_query_ephemeral(request: QuickQueryEphemeralRequest):
    include_schema_generation = request.includeSchemaGeneration or False
    
    # ... existing code ...
```

---

### Step 2: Pass Flag to Schema Generator

The schema generator (`backend/utils/query_schema_generator.py`) is already updated to accept this parameter:

```python
from backend.utils.query_schema_generator import QuerySchemaGenerator

generator = QuerySchemaGenerator()

# Generate schema with or without GeneratedSchema field
schema = generator.generate_quick_query_schema(
    query=request.prompt,
    include_schema_generation=include_schema_generation  # Pass the flag
)
```

**Backend utility is ready** ✅ - No changes needed to `query_schema_generator.py`

---

### Step 3: Extract GeneratedSchema from Analysis Results

After analysis completes, extract the GeneratedSchema field from Azure's response:

```python
def extract_generated_schema_from_results(analysis_result: dict) -> Optional[dict]:
    """
    Extract the GeneratedSchema field from Azure analysis results.
    
    Azure returns the schema in the analyzeResult.documents array.
    Look for a field named "GeneratedSchema" with type object.
    """
    try:
        documents = analysis_result.get("analyzeResult", {}).get("documents", [])
        
        if not documents:
            return None
        
        # Get first document (Quick Query typically processes one virtual document)
        first_doc = documents[0]
        fields = first_doc.get("fields", {})
        
        # Look for GeneratedSchema field
        generated_schema_field = fields.get("GeneratedSchema", {})
        
        if not generated_schema_field:
            return None
        
        # Extract valueObject which contains the actual schema
        value_object = generated_schema_field.get("valueObject", {})
        
        if not value_object:
            return None
        
        # Parse the schema structure
        # Azure returns: {schemaName: {valueString: "..."}, schemaDescription: {...}, fields: {...}}
        schema_name = value_object.get("schemaName", {}).get("valueString", "")
        schema_description = value_object.get("schemaDescription", {}).get("valueString", "")
        fields_object = value_object.get("fields", {}).get("valueObject", {})
        
        # Convert Azure format to our format
        generated_schema = {
            "schemaName": schema_name,
            "schemaDescription": schema_description,
            "fields": {}
        }
        
        # Parse each field
        for field_name, field_data in fields_object.items():
            field_obj = field_data.get("valueObject", {})
            generated_schema["fields"][field_name] = {
                "type": field_obj.get("type", {}).get("valueString", "string"),
                "description": field_obj.get("description", {}).get("valueString", ""),
                "method": field_obj.get("method", {}).get("valueString", "extract")
            }
        
        return generated_schema
        
    except Exception as e:
        print(f"[extractGeneratedSchema] Error extracting schema: {e}")
        return None
```

---

### Step 4: Include in Response

```python
@router.post("/quick-query/ephemeral")
async def quick_query_ephemeral(request: QuickQueryEphemeralRequest):
    include_schema_generation = request.includeSchemaGeneration or False
    
    # Generate schema
    schema = generator.generate_quick_query_schema(
        query=request.prompt,
        include_schema_generation=include_schema_generation
    )
    
    # Execute analysis (existing code)
    result = await execute_analysis(schema, request.inputFileIds, request.referenceFileIds)
    
    # Build response
    response = {
        "analyzerId": result["analyzerId"],
        "operationId": result["operationId"],
        "result": result["result"],
        "totalDocuments": len(request.inputFileIds)
    }
    
    # Extract and include generated schema if requested
    if include_schema_generation:
        generated_schema = extract_generated_schema_from_results(result["result"])
        if generated_schema:
            response["generatedSchema"] = generated_schema
        else:
            print("[QuickQuery] Warning: Schema generation requested but no schema found in results")
    
    return response
```

---

## Testing the Integration

### Manual Test

1. **Execute Quick Query without schema generation** (existing flow):
   ```bash
   curl -X POST http://localhost:8000/pro-mode/quick-query/ephemeral \
     -H "Content-Type: application/json" \
     -d '{
       "prompt": "Extract invoice number and total",
       "inputFileIds": ["test-blob-id"],
       "includeSchemaGeneration": false
     }'
   ```
   
   **Expected**: Normal response without `generatedSchema` field

2. **Execute Quick Query WITH schema generation**:
   ```bash
   curl -X POST http://localhost:8000/pro-mode/quick-query/ephemeral \
     -H "Content-Type: application/json" \
     -d '{
       "prompt": "Extract invoice number, total, vendor, and date",
       "inputFileIds": ["test-invoice-blob-id"],
       "includeSchemaGeneration": true
     }'
   ```
   
   **Expected**: Response includes `generatedSchema` field with schema structure

---

## Validation Checklist

- [ ] API accepts `includeSchemaGeneration` parameter
- [ ] Parameter defaults to `false` if not provided
- [ ] Schema generator receives flag correctly
- [ ] Analysis completes successfully with schema generation enabled
- [ ] `generatedSchema` field extracted from Azure response
- [ ] Response includes `generatedSchema` field when requested
- [ ] Schema has correct structure (schemaName, schemaDescription, fields)
- [ ] Field definitions include type, description, method
- [ ] Frontend receives response and opens Schema Review Dialog
- [ ] No errors in backend logs during schema generation

---

## Error Handling

### Potential Issues

1. **Azure returns no GeneratedSchema field**
   - Cause: Analysis timed out before convergence
   - Handling: Log warning, return response without generatedSchema
   - Frontend: Will not show dialog (graceful degradation)

2. **GeneratedSchema has invalid structure**
   - Cause: Azure returned unexpected format
   - Handling: Log error with full response for debugging
   - Frontend: Display error toast

3. **Schema extraction throws exception**
   - Cause: Unexpected response structure
   - Handling: Catch exception, log, return response without generatedSchema
   - Frontend: Graceful degradation

### Recommended Error Handling

```python
try:
    if include_schema_generation:
        generated_schema = extract_generated_schema_from_results(result["result"])
        if generated_schema:
            response["generatedSchema"] = generated_schema
        else:
            print("[QuickQuery] ⚠️ Schema generation requested but no schema found")
            print(f"[QuickQuery] Full result: {json.dumps(result['result'], indent=2)}")
except Exception as e:
    print(f"[QuickQuery] ❌ Error extracting generated schema: {e}")
    print(f"[QuickQuery] Full traceback: {traceback.format_exc()}")
    # Continue without schema - don't fail entire request
```

---

## Expected Azure Response Format

### Azure Document Intelligence Response Structure

When `GeneratedSchema` is included in the analyzer definition, Azure returns:

```json
{
  "analyzeResult": {
    "apiVersion": "2025-05-01-preview",
    "documents": [
      {
        "docType": "quickquery.ephemeral",
        "fields": {
          "InvoiceNumber": {
            "type": "string",
            "valueString": "INV-12345",
            "content": "INV-12345",
            "confidence": 0.95
          },
          "TotalAmount": {
            "type": "number",
            "valueNumber": 1250.00,
            "confidence": 0.98
          },
          "GeneratedSchema": {
            "type": "object",
            "valueObject": {
              "schemaName": {
                "type": "string",
                "valueString": "InvoiceExtractionSchema"
              },
              "schemaDescription": {
                "type": "string",
                "valueString": "Extracts invoice number, total amount, vendor name, and invoice date from invoice documents"
              },
              "fields": {
                "type": "object",
                "valueObject": {
                  "InvoiceNumber": {
                    "type": "object",
                    "valueObject": {
                      "type": {"type": "string", "valueString": "string"},
                      "description": {"type": "string", "valueString": "The unique invoice identifier"},
                      "method": {"type": "string", "valueString": "extract"}
                    }
                  },
                  "TotalAmount": {
                    "type": "object",
                    "valueObject": {
                      "type": {"type": "string", "valueString": "number"},
                      "description": {"type": "string", "valueString": "The total invoice amount"},
                      "method": {"type": "string", "valueString": "extract"}
                    }
                  }
                }
              }
            }
          }
        }
      }
    ]
  }
}
```

---

## Performance Expectations

Based on validation testing (November 9, 2025):

- **Without schema generation**: 15-45 seconds (typical Quick Query)
- **With schema generation**: 30-90 seconds (validated upper bound)
- **Additional time**: ~15-45 seconds for 3-step self-reviewing schema generation

**Important**: Schema generation uses Azure's LLM to analyze, name, and refine the schema. This is computationally intensive and takes time. Users should be informed this is expected.

---

## Analytics

Backend should log:

1. **Schema generation requested**:
   ```python
   print(f"[QuickQuery] Schema generation requested for prompt: {request.prompt[:50]}...")
   ```

2. **Schema generation completed**:
   ```python
   print(f"[QuickQuery] ✅ Generated schema: {generated_schema['schemaName']} with {len(generated_schema['fields'])} fields")
   ```

3. **Schema generation failed**:
   ```python
   print(f"[QuickQuery] ❌ Schema generation failed: {error}")
   ```

---

## Rollback Plan

If issues arise, disable schema generation by:

1. **API level**: Always set `includeSchemaGeneration = False`:
   ```python
   include_schema_generation = False  # Force disable
   ```

2. **Schema generator level**: Comment out GeneratedSchema field in `query_schema_generator.py`:
   ```python
   # if include_schema_generation:
   #     schema["GeneratedSchema"] = self._get_generated_schema_field(query)
   ```

3. **Frontend level**: Hide Save Prompt button (already documented in main integration doc)

---

## Summary

### What Backend Needs to Do

1. ✅ Accept `includeSchemaGeneration` parameter in API request
2. ✅ Pass flag to `generate_quick_query_schema()` (utility already supports this)
3. ✅ Extract `GeneratedSchema` from Azure analysis results
4. ✅ Include `generatedSchema` in API response when requested
5. ✅ Handle errors gracefully (log warnings, don't fail entire request)

### What's Already Done

- ✅ `query_schema_generator.py` updated to generate GeneratedSchema field
- ✅ 3-step self-reviewing prompt validated with Azure API
- ✅ Frontend UI complete and waiting for backend data
- ✅ Schema Review Dialog complete
- ✅ Parent component integration complete

### Estimated Implementation Time

**2-4 hours** for a backend developer familiar with the codebase:
- 30 min: Update API endpoint to accept parameter
- 30 min: Implement `extract_generated_schema_from_results()` function
- 30 min: Add field to response
- 1-2 hours: Testing and debugging
- 30 min: Error handling and logging

---

## Contact

Questions? See the main integration document: `QUICK_QUERY_SAVE_PROMPT_INTEGRATION_COMPLETE.md`
