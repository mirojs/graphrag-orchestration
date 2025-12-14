# Unified Schema Data Format Guide

## Overview

This document describes the unified schema data format implementation that ensures consistency between uploaded schemas and created schemas, with proper validation for Azure Content Understanding API compliance.

## Problem Statement

Previously, there were inconsistencies between:
- **Created schemas**: Used frontend `ProModeSchemaField` format
- **Uploaded schemas**: Used various formats without validation
- **Backend expectations**: Required specific `FieldSchema` format

This led to API errors, data format mismatches, and potential processing failures.

## Solution: Unified Schema Format

### 1. Standardized Backend Format

All schemas are now transformed to a consistent backend format before sending to the API:

```typescript
interface BackendSchemaFormat {
  id?: string;
  name: string;                    // Required: Schema name
  description?: string;            // Optional: Schema description
  fields: BackendFieldFormat[];    // Required: Array of field definitions
  version?: string;                // Default: "1.0.0"
  status?: string;                 // Default: "active"
  createdBy: string;              // Required: Creator identifier
  baseAnalyzerId?: string;        // Default: "prebuilt-documentAnalyzer"
  validationStatus?: string;      // Default: "valid"
  isTemplate?: boolean;           // Default: false
}

interface BackendFieldFormat {
  name: string;                   // Field identifier (maps from fieldKey)
  type: string;                   // Azure API field type (maps from fieldType)
  description?: string;           // Field description
  required: boolean;              // Whether field is required
  validation_rules?: object;      // Validation constraints
}
```

### 2. Azure Content Understanding API Compliance

All schemas are validated against Azure Content Understanding API specifications:

#### Valid Field Types
- `string` - Text content
- `date` - Date values
- `time` - Time values  
- `number` - Numeric values (floating point)
- `integer` - Integer values
- `boolean` - True/false values
- `array` - Collections of items
- `object` - Complex nested structures

#### Valid Generation Methods
- `extract` - Extract information from documents
- `generate` - Generate new content
- `classify` - Classify document content

#### Valid Status Values
- `active` - Schema is ready for use
- `draft` - Schema is in development
- `inactive` - Schema is disabled

### 3. Transformation Functions

#### Frontend to Backend Transform
```typescript
transformToBackendFormat(frontendSchema: Partial<ProModeSchema>): BackendSchemaFormat
```
- Converts frontend `ProModeSchemaField` format to backend `FieldSchema` format
- Maps `fieldKey` → `name`, `fieldType` → `type`
- Applies default values for required backend fields
- Handles validation rules transformation

#### Backend to Frontend Transform
```typescript
transformFromBackendFormat(backendSchema: any): ProModeSchema
```
- Converts backend response to frontend `ProModeSchema` format
- Maps `name` → `fieldKey`, `type` → `fieldType`
- Adds required frontend properties
- Maintains backward compatibility

### 4. Schema Validation

#### Upload Validation
```typescript
validateUploadedSchema(schemaData: any): {
  isValid: boolean;
  errors: string[];
  warnings: string[];
}
```

**Validates:**
- JSON structure correctness
- Required fields presence
- Field type compliance with Azure API
- Generation method validity
- Field name uniqueness
- Validation rules format

**Error Examples:**
- `Schema name is required and must be a non-empty string`
- `Field type "currency" is invalid. Must be one of: string, date, time, number, integer, boolean, array, object`
- `Field must have either "name" or "fieldKey" property`

#### Normalization
```typescript
normalizeUploadedSchema(rawSchema: any): BackendSchemaFormat
```
- Converts any valid uploaded schema to standard backend format
- Handles multiple field naming conventions (`name`/`fieldKey`, `type`/`fieldType`)
- Applies consistent defaults
- Throws `SchemaFormatError` for invalid schemas

## Implementation Benefits

### 1. Data Consistency
✅ **Unified Format**: All schemas use the same backend format regardless of creation method  
✅ **Field Mapping**: Consistent field property mapping between frontend and backend  
✅ **Default Values**: Automatic application of required defaults  

### 2. Azure API Compliance
✅ **Field Type Validation**: Only Azure-supported field types accepted  
✅ **Generation Methods**: Proper generation method validation  
✅ **Format Enforcement**: Ensures schemas work with Azure Content Understanding API  

### 3. Error Prevention
✅ **Pre-Upload Validation**: Catches format errors before API calls  
✅ **Detailed Error Messages**: Clear feedback on what needs to be fixed  
✅ **Warning System**: Non-blocking issues are flagged as warnings  

### 4. Developer Experience
✅ **Type Safety**: Full TypeScript support for schema transformations  
✅ **Validation Feedback**: Rich UI components for validation results  
✅ **Error Handling**: Comprehensive error reporting with context  

## Usage Examples

### 1. Creating a Schema (Frontend)
```typescript
const newSchema: Partial<ProModeSchema> = {
  name: "Invoice Schema",
  description: "Schema for invoice processing",
  fields: [
    {
      fieldKey: "invoice_number",
      fieldType: "string", 
      displayName: "Invoice Number",
      required: true
    }
  ]
};

// Service automatically transforms to backend format
const createdSchema = await schemaService.createSchema(newSchema);
```

### 2. Uploading a Schema File
```json
{
  "name": "Invoice Schema",
  "description": "Schema for invoice processing", 
  "fields": [
    {
      "name": "invoice_number",
      "type": "string",
      "description": "Invoice number",
      "required": true,
      "validation_rules": {
        "pattern": "^INV-[0-9]+$"
      }
    },
    {
      "name": "total_amount", 
      "type": "number",
      "description": "Total amount",
      "required": true,
      "validation_rules": {
        "min": 0
      }
    }
  ],
  "version": "1.0.0",
  "createdBy": "user"
}
```

### 3. Validation Feedback
```typescript
const validation = await schemaService.validateSchema(uploadedSchema);

if (!validation.isValid) {
  console.log("Errors:", validation.errors);
  // ["Field type 'currency' is invalid. Must be one of: string, date, time..."]
}

if (validation.warnings.length > 0) {
  console.log("Warnings:", validation.warnings);
  // ["Version should be a string (e.g., '1.0.0')"]
}
```

## Migration Guide

### For Existing Schemas
1. **Automatic**: Existing schemas are automatically transformed when fetched
2. **Upload**: New uploads are validated and normalized
3. **Updates**: Schema updates use unified format transformation

### For Developers
1. **Import**: Use `schemaFormatUtils` for transformations
2. **Validation**: Call `validateUploadedSchema()` before processing
3. **UI**: Use `SchemaValidationFeedback` component for user feedback

### Breaking Changes
⚠️ **Field Types**: Legacy field types (`currency`, `percentage`) are no longer supported  
⚠️ **API Format**: Backend always expects `FieldSchema` format with `name`/`type` properties  
⚠️ **Validation**: Invalid schemas will be rejected during upload  

## Testing

### Sample Valid Schema
```typescript
import { createSampleSchema } from './schemaFormatUtils';

const sampleSchema = createSampleSchema();
// Returns a complete, valid schema in the correct format
```

### Validation Testing
```typescript
const validation = validateUploadedSchema(testSchema);
console.assert(validation.isValid === true);
console.assert(validation.errors.length === 0);
```

## Error Handling

### Common Validation Errors
1. **Missing required fields**: `Schema name is required`
2. **Invalid field types**: `Field type "text" is invalid. Must be "string"`
3. **Invalid JSON**: `Invalid JSON in file: Unexpected token`
4. **Missing field properties**: `Field must have "name" property`

### Error Recovery
- **Validation errors**: Fix the schema file and re-upload
- **Format errors**: Use the correct field type names
- **Structure errors**: Ensure required properties are present

## Monitoring

### Logging
- All transformations are logged for debugging
- Validation results are tracked
- Upload success/failure metrics

### Analytics
- Schema validation failure rates
- Common error patterns
- Upload success metrics

## Future Enhancements

1. **Backend Validation Endpoint**: Add `/pro-mode/schemas/validate` for server-side validation
2. **Schema Templates**: Generate templates with correct format
3. **Migration Tools**: Batch convert legacy schemas
4. **Enhanced Validation**: More detailed Azure API compliance checks
