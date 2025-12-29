# Comprehensive Validation System for Debugging Unknown Azure API Errors

## Overview
Implemented a thorough post-transformation validation system to establish **ground truths** for debugging unknown error responses from Azure Content Understanding API.

## What Was Implemented

### 1. Comprehensive Validation Function
Added `validate_transformation_for_debugging()` function that performs:

#### Ground Truth 1: Original Schema Analysis
- ✅ **Field Source Detection**: Checks multiple possible field locations (`fields`, `fieldSchema.fields`, `fieldDefinitions`, `properties`, `schema`)
- ✅ **Structure Validation**: Validates field count, type, and format
- ✅ **Detailed Logging**: Records exactly where fields were found and their characteristics

#### Ground Truth 2: Transformed Schema Analysis  
- ✅ **Azure Format Verification**: Confirms fields are in object format (not array)
- ✅ **Field Structure Check**: Validates each field has required properties (`type`, `description`)
- ✅ **Field Name Validation**: Checks field naming compliance with Azure API

#### Ground Truth 3: JSON Serialization Validation
- ✅ **Basic Serialization**: Tests if transformed schema can be JSON serialized
- ✅ **Parse-back Test**: Verifies JSON can be parsed back successfully  
- ✅ **Full Payload Test**: Tests complete Azure API payload serialization

#### Ground Truth 4: Azure API Compliance Check
- ✅ **Required Properties**: Validates presence of required top-level properties
- ✅ **Field Type Validation**: Checks supported Azure API field types
- ✅ **Structure Compliance**: Ensures object format per Azure API 2025-05-01-preview
- ✅ **Field Name Limits**: Validates field name length (64 char limit)

### 2. Persistent Debugging Reports
- ✅ **File Storage**: Saves validation reports to `/tmp/azure_validation_reports/`
- ✅ **Timestamped Reports**: Each report includes schema ID and timestamp
- ✅ **JSON Format**: Structured data for programmatic analysis
- ✅ **Error Correlation**: Links validation results to specific schema IDs

### 3. Error Status Classification
- ✅ **PASS**: All validations successful
- ✅ **WARNING**: Minor issues that may not break functionality
- ✅ **COMPLIANCE_FAILURE**: Azure API compliance issues detected
- ✅ **CRITICAL_FAILURE**: Fundamental transformation problems

## Ground Truths Established

### For Original Schema Issues:
```json
{
  "ground_truths": {
    "original_field_sources": ["fieldSchema.fields: dict(5)"],
    "original_fields_found": true,
    "original_fields_count": 5,
    "original_fields_type": "dict"
  }
}
```

### For Transformation Issues:
```json
{
  "azure_compliance": {
    "issues": [
      "fields should be object, not array (Azure API 2025-05-01-preview)",
      "Field 'InvalidField' has unsupported type: 'custom'"
    ],
    "compliant": false
  }
}
```

### For JSON Issues:
```json
{
  "json_validation": {
    "serializable": true,
    "json_length": 1247,
    "full_payload_serializable": true,
    "full_payload_length": 1834
  }
}
```

## Testing Results

Validation system tested with 4 scenarios:
- ✅ **Valid Schema**: PASS
- ❌ **Array Format**: COMPLIANCE_FAILURE (correctly detected)
- ❌ **Empty Fields**: COMPLIANCE_FAILURE (correctly detected)  
- ✅ **Complex Schema**: PASS

## How to Use for Debugging

### 1. When Unknown Error Occurs:
1. Check validation report file: `/tmp/azure_validation_reports/validation_report_{schema_id}_{timestamp}.json`
2. Review `overall_status` and `critical_issues`
3. Examine `azure_compliance.issues` for specific problems
4. Check `ground_truths` section for transformation accuracy

### 2. Error Correlation:
- Validation runs automatically before every Azure API call
- Reports are saved with schema ID for easy correlation
- Global `_last_validation_report` stores latest validation for immediate access

### 3. Common Issues to Look For:
- **Empty fields**: `"original_fields_count": 0`
- **Wrong format**: `"fields should be object, not array"`
- **Missing properties**: `"Field 'X' missing required 'type' property"`
- **JSON issues**: `"serializable": false`

## Benefits for Debugging

1. **Concrete Data Points**: No more guessing - clear validation status
2. **Root Cause Identification**: Pinpoints exact transformation failures
3. **Azure API Compliance**: Validates against actual API requirements
4. **Historical Tracking**: Persistent reports for pattern analysis
5. **Fail-Fast Detection**: Catches issues before Azure API call

## Next Steps

With this validation system, you now have:
- ✅ **Ground truth data** for every transformation
- ✅ **Detailed error categorization** 
- ✅ **Persistent debugging reports**
- ✅ **Azure API compliance verification**

When unknown errors occur, check the validation report first - it will tell you exactly what's wrong with the transformation and provide concrete debugging starting points.
