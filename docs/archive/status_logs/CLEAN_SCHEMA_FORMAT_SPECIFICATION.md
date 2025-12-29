# CLEAN SCHEMA FORMAT SPECIFICATION

## Issue Identified
The current `PRODUCTION_READY_SCHEMA_CORRECTED.json` includes backend assembly properties that are already hardcoded in the backend. These should be removed from schema files.

## Backend Hardcoded Properties (proMode.py lines 3370-3375)

```python
official_payload = {
    "description": f"Custom analyzer for {schema_name}",
    "mode": "pro",  # ✅ HARDCODED
    "baseAnalyzerId": "prebuilt-documentAnalyzer",  # ✅ HARDCODED
    "config": {
        "enableFormula": False,    # ✅ HARDCODED
        "returnDetails": True,     # ✅ HARDCODED
        "tableFormat": "html"      # ✅ HARDCODED
    },
    # ... dynamic fields from schema
}
```

## Properties to REMOVE from Schema Files

❌ **Remove these** (handled by backend):
```json
{
  "mode": "pro",
  "baseAnalyzerId": "prebuilt-documentAnalyzer", 
  "config": {
    "enableFormula": false,
    "returnDetails": true,
    "tableFormat": "html"
  },
  "knowledgeSources": [],
  "processingLocation": "DataZone"
}
```

## Clean Schema Format

✅ **Keep only these** (schema-specific):
```json
{
  "fieldSchema": {
    "name": "InvoiceContractVerification",
    "description": "Schema description",
    "fields": {
      // Field definitions
    }
  }
}
```

## Updated Clean Schema

Created: `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION.json`
- Contains only fieldSchema definition
- Removes all backend assembly properties
- Ready for proper upload via the upload endpoint

## Benefits

1. ✅ **Cleaner separation**: Schema files focus only on field definitions
2. ✅ **No duplication**: Backend settings stay in backend
3. ✅ **Maintainable**: Changes to backend config don't require schema updates
4. ✅ **Standard compliant**: Follows Azure Content Understanding API schema format
