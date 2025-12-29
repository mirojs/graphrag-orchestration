# Unified Schema Interface Documentation

## Overview

This document defines the unified schema field interface that is used throughout the Content Processing Solution Accelerator. The interface has been standardized to use the Azure API-compliant format with `{name, type}` properties, eliminating legacy `{fieldKey, fieldType}` references for better consistency and compliance.

## Core Interface: ProModeSchemaField

### Primary Properties (Azure API Compliant)

```typescript
interface ProModeSchemaField {
  // 🔥 CORE UNIFIED PROPERTIES (Required)
  name: string;        // Field identifier (Azure API standard)
  type: FieldType;     // Field data type (Azure API standard)
  description: string; // Field description (Azure API standard)
  
  // 🔥 AZURE API PROPERTIES
  required?: boolean;              // Whether field is required
  method?: GenerationMethod;       // 'generate' | 'extract' | 'classify'
  maxLength?: number;              // Maximum field length
  format?: string;                 // Specialized field format
}
```

### Supported Field Types

```typescript
type FieldType = 
  | 'string'   // Text content
  | 'date'     // Date values
  | 'time'     // Time values  
  | 'number'   // Numeric values (decimal)
  | 'integer'  // Whole numbers
  | 'boolean'  // True/false values
  | 'array'    // List of values
  | 'object';  // Nested objects
```

### Generation Methods

```typescript
type GenerationMethod = 
  | 'extract'   // Extract from document content
  | 'generate'  // AI-generated content
  | 'classify'; // Classification/categorization
```

## Complete Interface Definition

```typescript
export interface ProModeSchemaField extends Omit<BaseField, 'valueType' | 'isRequired'> {
  // 🔥 AZURE API STANDARD PROPERTIES
  name: string;        // Field identifier (inherited from BaseField)
  type: 'string' | 'date' | 'time' | 'number' | 'integer' | 'boolean' | 'array' | 'object';
  description: string; // Field description (inherited from BaseField)
  
  // 🔥 AZURE API OPTIONAL PROPERTIES
  id?: string;                     // Internal ID for React keys
  required?: boolean;              // Azure API: Whether field is required
  method?: GenerationMethod;       // Azure API: Method (official property name)
  generationMethod?: GenerationMethod; // Alternative property name for backward compatibility
  maxLength?: number;              // Azure API MaxLength
  format?: string;                 // Azure API Format for specialized field types
  
  // 🔥 UI AND DISPLAY PROPERTIES
  displayName?: string;            // UI display name (derived from 'name' if not provided)
  valueType?: 'string' | 'date' | 'time' | 'number' | 'integer' | 'boolean' | 'array' | 'object';
  isRequired?: boolean;            // Alternative property name for backward compatibility
  displayOrder?: number;
  group?: string;
  isHidden?: boolean;
  isReadOnly?: boolean;
  
  // 🔥 VALIDATION PROPERTIES
  validationPattern?: string;
  validation?: {
    required?: boolean;
    minLength?: number;
    maxLength?: number;
    pattern?: string;
    min?: number;
    max?: number;
    items?: Partial<ProModeSchemaField>; // For array items
    properties?: { [key: string]: Partial<ProModeSchemaField> }; // For object properties
  };
  
  // 🔥 EXTENDED PROPERTIES
  items?: string;                  // For array field types
  properties?: string;             // For object field types
  options?: string[];              // For select/dropdown fields
  defaultValue?: any;
  confidence?: number;
  extractedValue?: any;
  boundingBoxes?: any[];
}
```

## Schema Structure

### Complete Schema Interface

```typescript
interface ProModeSchema {
  id?: string;
  name: string;
  description: string;
  fields: ProModeSchemaField[];    // Array of unified field definitions
  createdBy?: string;
  createdAt?: string | Date;
  updatedAt?: string | Date;
  baseAnalyzerId?: string;
  
  // Support for multiple schema formats
  originalSchema?: any;   // Original uploaded schema
  azureSchema?: any;      // Azure API compatible format
  fieldSchema?: any;      // Direct fieldSchema for production-ready schemas
}
```

## Validation Rules

### Field Name Validation
- **Pattern**: Must match `/^[a-zA-Z0-9_]+$/`
- **Requirements**: Letters, numbers, and underscores only
- **Uniqueness**: No duplicate field names within a schema

### Field Type Validation
- Must be one of the supported FieldType values
- Required for all fields
- Determines UI rendering and data processing

### Required Fields
- `name`: Always required
- `type`: Always required  
- `description`: Always required for user-created fields

## Examples

### Basic Field Definition

```typescript
const simpleField: ProModeSchemaField = {
  name: "document_title",
  type: "string",
  description: "Title of the document",
  required: true,
  method: "extract"
};
```

### Complex Field with Validation

```typescript
const complexField: ProModeSchemaField = {
  name: "invoice_amount",
  type: "number",
  description: "Total invoice amount",
  required: true,
  method: "extract",
  displayName: "Invoice Amount",
  format: "currency",
  validation: {
    required: true,
    min: 0,
    pattern: "^\\d+(\\.\\d{2})?$"
  },
  defaultValue: 0
};
```

### Array Field Definition

```typescript
const arrayField: ProModeSchemaField = {
  name: "line_items",
  type: "array",
  description: "Invoice line items",
  required: false,
  method: "extract",
  validation: {
    items: {
      name: "line_item",
      type: "object",
      description: "Individual line item",
      validation: {
        properties: {
          "item_name": { type: "string", required: true },
          "quantity": { type: "integer", required: true },
          "price": { type: "number", required: true }
        }
      }
    }
  }
};
```

### Complete Schema Example

```typescript
const invoiceSchema: ProModeSchema = {
  name: "invoice_processor",
  description: "Schema for processing invoice documents",
  fields: [
    {
      name: "vendor_name",
      type: "string",
      description: "Name of the vendor",
      required: true,
      method: "extract",
      displayName: "Vendor Name"
    },
    {
      name: "invoice_date",
      type: "date",
      description: "Date of the invoice",
      required: true,
      method: "extract",
      format: "YYYY-MM-DD"
    },
    {
      name: "total_amount",
      type: "number",
      description: "Total invoice amount",
      required: true,
      method: "extract",
      validation: {
        min: 0,
        pattern: "^\\d+(\\.\\d{2})?$"
      }
    }
  ],
  baseAnalyzerId: "prebuilt-invoice"
};
```

## Azure API Compliance

### Field Definition Mapping

The unified interface directly maps to Azure's FieldDefinition structure:

```typescript
// Azure API FieldDefinition
interface AzureFieldDefinition {
  name: string;                    // ✅ Direct mapping
  type: string;                    // ✅ Direct mapping  
  description?: string;            // ✅ Direct mapping
  required?: boolean;              // ✅ Direct mapping
  method?: 'extract' | 'generate'; // ✅ Direct mapping
  maxLength?: number;              // ✅ Direct mapping
  format?: string;                 // ✅ Direct mapping
}
```

### API Request Format

```typescript
// Creating an analyzer with unified schema
const analyzerRequest = {
  displayName: "Invoice Processor",
  description: "Processes invoice documents",
  fields: schema.fields.map(field => ({
    name: field.name,              // ✅ Unified property
    type: field.type,              // ✅ Unified property
    description: field.description, // ✅ Unified property
    required: field.required,      // ✅ Optional property
    method: field.method           // ✅ Optional property
  }))
};
```

## Migration Notes

### Legacy Format (DEPRECATED)
```typescript
// ❌ OLD FORMAT - No longer supported
interface LegacyField {
  fieldKey: string;    // DEPRECATED: Use 'name' instead
  fieldType: string;   // DEPRECATED: Use 'type' instead
  // ... other properties
}
```

### Current Unified Format
```typescript
// ✅ NEW FORMAT - Current standard
interface UnifiedField {
  name: string;        // Azure API compliant
  type: string;        // Azure API compliant
  description: string; // Azure API compliant
  // ... other properties
}
```

### Conversion Example
```typescript
// Legacy to Unified conversion
function convertLegacyField(legacyField: any): ProModeSchemaField {
  return {
    name: legacyField.fieldKey || legacyField.name,
    type: legacyField.fieldType || legacyField.type,
    description: legacyField.description,
    required: legacyField.required,
    method: legacyField.method || 'extract'
  };
}
```

## Best Practices

### 1. Field Naming
- Use descriptive, snake_case names: `invoice_date`, `vendor_name`
- Avoid spaces and special characters
- Keep names concise but meaningful

### 2. Type Selection
- Use `string` for text content
- Use `date` for date values (not `string`)
- Use `number` for decimal values, `integer` for whole numbers
- Use `array` and `object` for structured data

### 3. Validation
- Always specify `required` for mandatory fields
- Use validation patterns for formatted data
- Provide meaningful descriptions for user guidance

### 4. Method Assignment
- Use `extract` for document content extraction
- Use `generate` for AI-generated content
- Use `classify` for categorization tasks

### 5. UI Properties
- Set `displayName` for user-friendly labels
- Use `displayOrder` to control field arrangement
- Group related fields with the `group` property

## Error Handling

### Common Validation Errors
```typescript
// Field name validation
if (!/^[a-zA-Z0-9_]+$/.test(field.name)) {
  throw new Error(`Invalid field name: ${field.name}. Use only letters, numbers, and underscores.`);
}

// Required properties validation
if (!field.name || !field.type || !field.description) {
  throw new Error('Field must have name, type, and description properties.');
}

// Type validation
const validTypes = ['string', 'date', 'time', 'number', 'integer', 'boolean', 'array', 'object'];
if (!validTypes.includes(field.type)) {
  throw new Error(`Invalid field type: ${field.type}`);
}
```

## Implementation Status

### ✅ Completed
- Backend analyzer creation functions updated to unified format
- Frontend components using unified interface
- Type definitions standardized
- Legacy format references removed
- Azure API compliance achieved

### 📋 Current State
- All schema operations use `{name, type}` format exclusively
- No backwards compatibility with `{fieldKey, fieldType}` format
- Complete integration with Azure Content Understanding API
- Consistent validation and error handling across all components

---

*This documentation reflects the current unified interface as of the legacy format removal completion. All new development should use this standardized format.*