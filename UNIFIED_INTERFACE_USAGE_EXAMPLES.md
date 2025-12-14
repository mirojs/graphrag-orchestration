# Unified Schema Interface - Usage Examples & Best Practices

## Overview

This document provides practical examples and best practices for using the unified schema interface throughout the Content Processing Solution Accelerator. All examples use the current `{name, type}` format.

## Table of Contents

1. [Basic Usage Examples](#basic-usage-examples)
2. [Backend Implementation](#backend-implementation)
3. [Frontend Implementation](#frontend-implementation)
4. [Advanced Patterns](#advanced-patterns)
5. [Best Practices](#best-practices)
6. [Common Scenarios](#common-scenarios)
7. [Error Handling](#error-handling)
8. [Testing Patterns](#testing-patterns)

## Basic Usage Examples

### Simple Text Field
```typescript
const titleField: ProModeSchemaField = {
  name: "document_title",
  type: "string",
  description: "Title of the document",
  required: true,
  method: "extract",
  displayName: "Document Title"
};
```

### Numeric Field with Validation
```typescript
const amountField: ProModeSchemaField = {
  name: "invoice_amount",
  type: "number",
  description: "Total invoice amount in USD",
  required: true,
  method: "extract",
  displayName: "Invoice Amount",
  validation: {
    min: 0,
    pattern: "^\\d+(\\.\\d{2})?$"
  },
  format: "currency"
};
```

### Date Field
```typescript
const dateField: ProModeSchemaField = {
  name: "invoice_date",
  type: "date",
  description: "Date the invoice was issued",
  required: true,
  method: "extract",
  displayName: "Invoice Date",
  format: "YYYY-MM-DD"
};
```

### Boolean Field
```typescript
const paidField: ProModeSchemaField = {
  name: "is_paid",
  type: "boolean",
  description: "Whether the invoice has been paid",
  required: false,
  method: "classify",
  displayName: "Payment Status",
  defaultValue: false
};
```

### Array Field for Line Items
```typescript
const lineItemsField: ProModeSchemaField = {
  name: "line_items",
  type: "array",
  description: "List of invoice line items",
  required: false,
  method: "extract",
  displayName: "Line Items",
  validation: {
    items: {
      name: "line_item",
      type: "object",
      description: "Individual line item",
      validation: {
        properties: {
          "item_description": { 
            type: "string", 
            required: true,
            description: "Description of the item"
          },
          "quantity": { 
            type: "integer", 
            required: true,
            description: "Quantity of items"
          },
          "unit_price": { 
            type: "number", 
            required: true,
            description: "Price per unit"
          }
        }
      }
    }
  }
};
```

## Backend Implementation

### Field Validation Function
```python
def validate_schema_field(field_data: dict) -> list[str]:
    """
    Validate a schema field using unified format.
    
    Args:
        field_data: Dictionary containing field definition
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    # Required properties validation
    required_props = ['name', 'type', 'description']
    for prop in required_props:
        if prop not in field_data or not field_data[prop]:
            errors.append(f"Missing required property: {prop}")
    
    # Name validation
    if 'name' in field_data:
        name = field_data['name']
        if not isinstance(name, str):
            errors.append("Field 'name' must be a string")
        elif not re.match(r'^[a-zA-Z0-9_]+$', name):
            errors.append("Field 'name' must contain only letters, numbers, and underscores")
        elif len(name) > 50:
            errors.append("Field 'name' must be 50 characters or less")
    
    # Type validation
    valid_types = ['string', 'date', 'time', 'number', 'integer', 'boolean', 'array', 'object']
    if 'type' in field_data:
        field_type = field_data['type']
        if field_type not in valid_types:
            errors.append(f"Invalid field type: {field_type}. Must be one of: {', '.join(valid_types)}")
    
    # Method validation
    if 'method' in field_data:
        valid_methods = ['extract', 'generate', 'classify']
        if field_data['method'] not in valid_methods:
            errors.append(f"Invalid method: {field_data['method']}. Must be one of: {', '.join(valid_methods)}")
    
    return errors
```

### Schema Creation Function
```python
async def create_schema_with_unified_fields(schema_data: dict) -> dict:
    """
    Create a schema using unified field format.
    
    Args:
        schema_data: Schema definition with unified fields
        
    Returns:
        Created schema with validation results
    """
    # Validate schema structure
    if 'fields' not in schema_data:
        raise ValueError("Schema must contain 'fields' array")
    
    validated_fields = []
    field_names = set()
    
    for i, field in enumerate(schema_data['fields']):
        # Validate individual field
        field_errors = validate_schema_field(field)
        if field_errors:
            raise ValueError(f"Field {i+1} validation errors: {'; '.join(field_errors)}")
        
        # Check for duplicate names
        field_name = field['name']
        if field_name in field_names:
            raise ValueError(f"Duplicate field name: {field_name}")
        field_names.add(field_name)
        
        # Process unified field
        processed_field = {
            'name': field['name'],
            'type': field['type'],
            'description': field['description'],
            'required': field.get('required', False),
            'method': field.get('method', 'extract')
        }
        
        # Add optional properties
        optional_props = ['displayName', 'format', 'maxLength', 'validation', 'defaultValue']
        for prop in optional_props:
            if prop in field:
                processed_field[prop] = field[prop]
        
        validated_fields.append(processed_field)
    
    # Create final schema
    schema = {
        'name': schema_data['name'],
        'description': schema_data['description'],
        'fields': validated_fields,
        'createdAt': datetime.utcnow().isoformat(),
        'baseAnalyzerId': schema_data.get('baseAnalyzerId', 'prebuilt-read')
    }
    
    return schema
```

### Azure API Integration
```python
def convert_to_azure_format(unified_schema: dict) -> dict:
    """
    Convert unified schema to Azure API format.
    
    Args:
        unified_schema: Schema using unified field format
        
    Returns:
        Azure API compatible schema
    """
    azure_fields = []
    
    for field in unified_schema['fields']:
        azure_field = {
            'name': field['name'],           # Direct mapping
            'type': field['type'],           # Direct mapping
            'description': field['description']  # Direct mapping
        }
        
        # Add optional Azure properties
        if field.get('required'):
            azure_field['required'] = field['required']
        
        if field.get('method'):
            azure_field['method'] = field['method']
        
        if field.get('maxLength'):
            azure_field['maxLength'] = field['maxLength']
        
        if field.get('format'):
            azure_field['format'] = field['format']
        
        azure_fields.append(azure_field)
    
    return {
        'displayName': unified_schema['name'],
        'description': unified_schema['description'],
        'fields': azure_fields
    }
```

## Frontend Implementation

### React Hook for Schema Management
```typescript
import { useState, useCallback } from 'react';
import { ProModeSchemaField, ProModeSchema } from '../ProModeTypes/proModeTypes';

export const useUnifiedSchema = () => {
  const [schema, setSchema] = useState<ProModeSchema>({
    name: '',
    description: '',
    fields: []
  });

  const addField = useCallback((field: ProModeSchemaField) => {
    setSchema(prev => ({
      ...prev,
      fields: [...prev.fields, { ...field, id: generateId() }]
    }));
  }, []);

  const updateField = useCallback((index: number, updates: Partial<ProModeSchemaField>) => {
    setSchema(prev => ({
      ...prev,
      fields: prev.fields.map((field, i) => 
        i === index ? { ...field, ...updates } : field
      )
    }));
  }, []);

  const removeField = useCallback((index: number) => {
    setSchema(prev => ({
      ...prev,
      fields: prev.fields.filter((_, i) => i !== index)
    }));
  }, []);

  const validateSchema = useCallback((): string[] => {
    const errors: string[] = [];
    
    if (!schema.name.trim()) {
      errors.push('Schema name is required');
    }
    
    if (schema.fields.length === 0) {
      errors.push('At least one field is required');
    }
    
    const fieldNames = new Set<string>();
    schema.fields.forEach((field, index) => {
      // Validate required properties
      if (!field.name?.trim()) {
        errors.push(`Field ${index + 1}: Name is required`);
      } else if (!/^[a-zA-Z0-9_]+$/.test(field.name)) {
        errors.push(`Field ${index + 1}: Name must contain only letters, numbers, and underscores`);
      } else if (fieldNames.has(field.name)) {
        errors.push(`Field ${index + 1}: Duplicate field name '${field.name}'`);
      } else {
        fieldNames.add(field.name);
      }
      
      if (!field.type) {
        errors.push(`Field ${index + 1}: Type is required`);
      }
      
      if (!field.description?.trim()) {
        errors.push(`Field ${index + 1}: Description is required`);
      }
    });
    
    return errors;
  }, [schema]);

  return {
    schema,
    setSchema,
    addField,
    updateField,
    removeField,
    validateSchema
  };
};
```

### Field Editor Component
```typescript
import React from 'react';
import { 
  Input, 
  Dropdown, 
  Textarea, 
  Checkbox, 
  Field,
  DropdownOption
} from '@fluentui/react-components';
import { ProModeSchemaField } from '../ProModeTypes/proModeTypes';

interface UnifiedFieldEditorProps {
  field: ProModeSchemaField;
  onUpdate: (updates: Partial<ProModeSchemaField>) => void;
  onDelete: () => void;
}

const FIELD_TYPE_OPTIONS: DropdownOption[] = [
  { key: 'string', text: 'String (Text)' },
  { key: 'number', text: 'Number (Decimal)' },
  { key: 'integer', text: 'Integer (Whole Number)' },
  { key: 'date', text: 'Date' },
  { key: 'time', text: 'Time' },
  { key: 'boolean', text: 'Boolean (True/False)' },
  { key: 'array', text: 'Array (List)' },
  { key: 'object', text: 'Object (Nested)' }
];

const METHOD_OPTIONS: DropdownOption[] = [
  { key: 'extract', text: 'Extract from Document' },
  { key: 'generate', text: 'AI Generated' },
  { key: 'classify', text: 'Classification' }
];

export const UnifiedFieldEditor: React.FC<UnifiedFieldEditorProps> = ({
  field,
  onUpdate,
  onDelete
}) => {
  return (
    <div className="field-editor">
      <Field label="Field Name" required>
        <Input
          value={field.name || ''}
          onChange={(e) => onUpdate({ name: e.target.value })}
          placeholder="e.g., invoice_amount"
        />
      </Field>

      <Field label="Display Name">
        <Input
          value={field.displayName || ''}
          onChange={(e) => onUpdate({ displayName: e.target.value })}
          placeholder="e.g., Invoice Amount"
        />
      </Field>

      <Field label="Field Type" required>
        <Dropdown
          selectedKey={field.type || 'string'}
          options={FIELD_TYPE_OPTIONS}
          onChange={(_, option) => onUpdate({ type: option?.key as ProModeSchemaField['type'] })}
        />
      </Field>

      <Field label="Processing Method">
        <Dropdown
          selectedKey={field.method || 'extract'}
          options={METHOD_OPTIONS}
          onChange={(_, option) => onUpdate({ method: option?.key as ProModeSchemaField['method'] })}
        />
      </Field>

      <Field label="Description" required>
        <Textarea
          value={field.description || ''}
          onChange={(e) => onUpdate({ description: e.target.value })}
          placeholder="Describe what this field represents"
        />
      </Field>

      <Checkbox
        label="Required Field"
        checked={field.required || false}
        onChange={(_, data) => onUpdate({ required: data.checked })}
      />

      <Button
        appearance="secondary"
        icon={<DeleteRegular />}
        onClick={onDelete}
      >
        Delete Field
      </Button>
    </div>
  );
};
```

### Schema Service Integration
```typescript
class UnifiedSchemaService {
  async createSchema(schema: ProModeSchema): Promise<ProModeSchema> {
    // Validate schema before sending
    const errors = this.validateSchema(schema);
    if (errors.length > 0) {
      throw new Error(`Schema validation failed: ${errors.join(', ')}`);
    }

    // Convert to API format
    const apiPayload = {
      name: schema.name,
      description: schema.description,
      fields: schema.fields.map(field => ({
        name: field.name,
        type: field.type,
        description: field.description,
        required: field.required || false,
        method: field.method || 'extract'
      })),
      baseAnalyzerId: schema.baseAnalyzerId
    };

    const response = await fetch('/api/pro-mode/schemas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(apiPayload)
    });

    if (!response.ok) {
      throw new Error(`Failed to create schema: ${response.statusText}`);
    }

    return response.json();
  }

  private validateSchema(schema: ProModeSchema): string[] {
    const errors: string[] = [];
    
    // Schema-level validation
    if (!schema.name?.trim()) {
      errors.push('Schema name is required');
    }
    
    if (!schema.description?.trim()) {
      errors.push('Schema description is required');
    }
    
    if (!schema.fields || schema.fields.length === 0) {
      errors.push('At least one field is required');
    }
    
    // Field-level validation
    const fieldNames = new Set<string>();
    schema.fields.forEach((field, index) => {
      const fieldErrors = this.validateField(field, index + 1);
      errors.push(...fieldErrors);
      
      // Check for duplicates
      if (field.name && fieldNames.has(field.name)) {
        errors.push(`Duplicate field name: ${field.name}`);
      } else if (field.name) {
        fieldNames.add(field.name);
      }
    });
    
    return errors;
  }

  private validateField(field: ProModeSchemaField, fieldNumber: number): string[] {
    const errors: string[] = [];
    const prefix = `Field ${fieldNumber}`;
    
    // Required properties
    if (!field.name?.trim()) {
      errors.push(`${prefix}: Name is required`);
    } else if (!/^[a-zA-Z0-9_]+$/.test(field.name)) {
      errors.push(`${prefix}: Name must contain only letters, numbers, and underscores`);
    }
    
    if (!field.type) {
      errors.push(`${prefix}: Type is required`);
    } else {
      const validTypes = ['string', 'date', 'time', 'number', 'integer', 'boolean', 'array', 'object'];
      if (!validTypes.includes(field.type)) {
        errors.push(`${prefix}: Invalid type '${field.type}'`);
      }
    }
    
    if (!field.description?.trim()) {
      errors.push(`${prefix}: Description is required`);
    }
    
    // Optional property validation
    if (field.method) {
      const validMethods = ['extract', 'generate', 'classify'];
      if (!validMethods.includes(field.method)) {
        errors.push(`${prefix}: Invalid method '${field.method}'`);
      }
    }
    
    return errors;
  }
}
```

## Advanced Patterns

### Dynamic Field Creation
```typescript
const createFieldFromTemplate = (
  name: string, 
  type: ProModeSchemaField['type'], 
  description: string,
  options?: Partial<ProModeSchemaField>
): ProModeSchemaField => {
  const baseField: ProModeSchemaField = {
    name,
    type,
    description,
    required: false,
    method: 'extract',
    ...options
  };

  // Add type-specific defaults
  switch (type) {
    case 'number':
    case 'integer':
      return {
        ...baseField,
        validation: {
          min: 0,
          ...options?.validation
        }
      };
    
    case 'string':
      return {
        ...baseField,
        maxLength: 500,
        ...options
      };
    
    case 'date':
      return {
        ...baseField,
        format: 'YYYY-MM-DD',
        ...options
      };
    
    case 'boolean':
      return {
        ...baseField,
        defaultValue: false,
        ...options
      };
    
    default:
      return baseField;
  }
};
```

### Schema Templates
```typescript
const createInvoiceSchema = (): ProModeSchema => ({
  name: 'invoice_processor',
  description: 'Schema for processing invoice documents',
  fields: [
    createFieldFromTemplate(
      'vendor_name',
      'string',
      'Name of the vendor or supplier',
      { required: true, displayName: 'Vendor Name' }
    ),
    createFieldFromTemplate(
      'invoice_number',
      'string',
      'Unique invoice identifier',
      { required: true, displayName: 'Invoice Number' }
    ),
    createFieldFromTemplate(
      'invoice_date',
      'date',
      'Date the invoice was issued',
      { required: true, displayName: 'Invoice Date' }
    ),
    createFieldFromTemplate(
      'due_date',
      'date',
      'Payment due date',
      { required: false, displayName: 'Due Date' }
    ),
    createFieldFromTemplate(
      'subtotal',
      'number',
      'Subtotal amount before taxes',
      { 
        required: true, 
        displayName: 'Subtotal',
        format: 'currency',
        validation: { min: 0 }
      }
    ),
    createFieldFromTemplate(
      'tax_amount',
      'number',
      'Total tax amount',
      { 
        required: false, 
        displayName: 'Tax Amount',
        format: 'currency',
        validation: { min: 0 }
      }
    ),
    createFieldFromTemplate(
      'total_amount',
      'number',
      'Total invoice amount including taxes',
      { 
        required: true, 
        displayName: 'Total Amount',
        format: 'currency',
        validation: { min: 0 }
      }
    )
  ],
  baseAnalyzerId: 'prebuilt-invoice'
});
```

## Best Practices

### 1. Field Naming Conventions
```typescript
// ✅ Good field names
const goodNames = [
  'invoice_date',      // snake_case, descriptive
  'vendor_name',       // clear purpose
  'line_items',        // indicates array
  'billing_address',   // specific enough
  'is_paid'           // boolean prefix
];

// ❌ Avoid these names
const badNames = [
  'field1',           // Not descriptive
  'invoice-date',     // Hyphens not allowed
  'Invoice Date',     // Spaces not allowed
  'date',             // Too generic
  'data'              // Too vague
];
```

### 2. Type Selection Guidelines
```typescript
// Choose the most specific type
const fieldExamples = {
  // Use 'date' for dates, not 'string'
  invoice_date: { type: 'date', format: 'YYYY-MM-DD' },
  
  // Use 'integer' for whole numbers
  quantity: { type: 'integer', validation: { min: 1 } },
  
  // Use 'number' for decimals
  unit_price: { type: 'number', validation: { min: 0 } },
  
  // Use 'boolean' for yes/no values
  is_taxable: { type: 'boolean', defaultValue: true },
  
  // Use 'array' for lists
  line_items: { type: 'array' },
  
  // Use 'object' for structured data
  billing_address: { type: 'object' }
};
```

### 3. Validation Best Practices
```typescript
const wellValidatedField: ProModeSchemaField = {
  name: 'email_address',
  type: 'string',
  description: 'Contact email address',
  required: true,
  validation: {
    pattern: '^[^@]+@[^@]+\\.[^@]+$',  // Email pattern
    maxLength: 255                     // Reasonable limit
  },
  format: 'email'                      // Semantic format
};
```

### 4. Error Handling Patterns
```typescript
const handleFieldValidation = (field: ProModeSchemaField): void => {
  try {
    // Validate required properties
    if (!field.name || !field.type || !field.description) {
      throw new ValidationError('Missing required field properties');
    }
    
    // Validate name format
    if (!/^[a-zA-Z0-9_]+$/.test(field.name)) {
      throw new ValidationError('Invalid field name format');
    }
    
    // Type-specific validation
    if (field.type === 'number' && field.validation?.min !== undefined) {
      if (typeof field.validation.min !== 'number') {
        throw new ValidationError('Validation min must be a number');
      }
    }
    
  } catch (error) {
    console.error(`Field validation failed for '${field.name}':`, error);
    throw error;
  }
};
```

## Common Scenarios

### Document Processing Pipeline
```typescript
// 1. Define schema for document type
const contractSchema = createContractSchema();

// 2. Validate schema before processing
const validationErrors = validateSchema(contractSchema);
if (validationErrors.length > 0) {
  throw new Error(`Schema validation failed: ${validationErrors.join(', ')}`);
}

// 3. Create analyzer with unified fields
const analyzer = await createAnalyzer({
  displayName: contractSchema.name,
  description: contractSchema.description,
  fields: contractSchema.fields.map(field => ({
    name: field.name,        // Unified property
    type: field.type,        // Unified property
    description: field.description,
    required: field.required,
    method: field.method
  }))
});

// 4. Process document
const results = await processDocument(documentId, analyzer.id);
```

### Form Builder Integration
```typescript
const renderFieldInput = (field: ProModeSchemaField, value: any, onChange: (value: any) => void) => {
  switch (field.type) {
    case 'string':
      return (
        <Input
          label={field.displayName || field.name}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
          maxLength={field.maxLength}
        />
      );
    
    case 'number':
    case 'integer':
      return (
        <Input
          type="number"
          label={field.displayName || field.name}
          value={value || ''}
          onChange={(e) => onChange(field.type === 'integer' ? parseInt(e.target.value) : parseFloat(e.target.value))}
          required={field.required}
          min={field.validation?.min}
          max={field.validation?.max}
        />
      );
    
    case 'date':
      return (
        <DatePicker
          label={field.displayName || field.name}
          value={value ? new Date(value) : undefined}
          onSelectDate={(date) => onChange(date?.toISOString().split('T')[0])}
          isRequired={field.required}
        />
      );
    
    case 'boolean':
      return (
        <Checkbox
          label={field.displayName || field.name}
          checked={value || false}
          onChange={(_, data) => onChange(data.checked)}
        />
      );
    
    default:
      return null;
  }
};
```

## Testing Patterns

### Unit Test Examples
```typescript
describe('Unified Schema Interface', () => {
  describe('Field Validation', () => {
    it('should validate required properties', () => {
      const validField: ProModeSchemaField = {
        name: 'test_field',
        type: 'string',
        description: 'Test field description'
      };
      
      expect(() => validateField(validField)).not.toThrow();
    });
    
    it('should reject invalid field names', () => {
      const invalidField: ProModeSchemaField = {
        name: 'invalid-name!',
        type: 'string',
        description: 'Test field'
      };
      
      expect(() => validateField(invalidField)).toThrow('Invalid field name format');
    });
    
    it('should validate field types', () => {
      const invalidType = {
        name: 'test_field',
        type: 'invalid_type' as any,
        description: 'Test field'
      };
      
      expect(() => validateField(invalidType)).toThrow('Invalid field type');
    });
  });
  
  describe('Schema Creation', () => {
    it('should create schema with unified fields', () => {
      const schema = createInvoiceSchema();
      
      expect(schema.fields).toHaveLength(7);
      expect(schema.fields[0]).toHaveProperty('name', 'vendor_name');
      expect(schema.fields[0]).toHaveProperty('type', 'string');
      expect(schema.fields[0]).not.toHaveProperty('fieldKey');
      expect(schema.fields[0]).not.toHaveProperty('fieldType');
    });
  });
});
```

### Integration Test Example
```typescript
describe('Schema API Integration', () => {
  it('should create analyzer with unified schema', async () => {
    const schema: ProModeSchema = {
      name: 'test_schema',
      description: 'Test schema for integration',
      fields: [
        {
          name: 'test_field',
          type: 'string',
          description: 'Test field',
          required: true,
          method: 'extract'
        }
      ]
    };
    
    const response = await schemaService.createSchema(schema);
    
    expect(response).toHaveProperty('id');
    expect(response.fields[0]).toHaveProperty('name', 'test_field');
    expect(response.fields[0]).toHaveProperty('type', 'string');
  });
});
```

---

*This document provides comprehensive examples for using the unified schema interface. All examples use the current standardized format and follow established best practices.*