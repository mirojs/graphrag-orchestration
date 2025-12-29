# Legacy to Unified Format Migration Guide

## Overview

This guide documents the migration from the legacy `{fieldKey, fieldType}` format to the unified `{name, type}` format that is Azure API compliant and used throughout the Content Processing Solution Accelerator.

## Migration Summary

### Before (Legacy Format)
```typescript
// ❌ DEPRECATED - Legacy format
interface LegacySchemaField {
  fieldKey: string;      // Legacy field identifier
  fieldType: string;     // Legacy field type
  displayName: string;
  description: string;
  required: boolean;
  // ... other properties
}
```

### After (Unified Format)
```typescript
// ✅ CURRENT - Unified format
interface ProModeSchemaField {
  name: string;          // Azure API compliant identifier
  type: string;          // Azure API compliant type
  displayName: string;
  description: string;
  required: boolean;
  // ... other properties
}
```

## Property Mapping

| Legacy Property | Unified Property | Notes |
|----------------|------------------|-------|
| `fieldKey` | `name` | Direct 1:1 mapping |
| `fieldType` | `type` | Direct 1:1 mapping |
| `displayName` | `displayName` | No change |
| `description` | `description` | No change |
| `required` | `required` | No change |

## Code Migration Examples

### Backend Migration (Python)

#### Before - Legacy Backend Code
```python
# ❌ Legacy field processing
def process_legacy_field(field_data):
    field_key = field_data.get('fieldKey')
    field_type = field_data.get('fieldType')
    
    # Legacy validation
    if not field_key:
        raise ValueError("fieldKey is required")
    if not field_type:
        raise ValueError("fieldType is required")
    
    return {
        'fieldKey': field_key,
        'fieldType': field_type,
        'description': field_data.get('description', '')
    }
```

#### After - Unified Backend Code
```python
# ✅ Unified field processing
def process_unified_field(field_data):
    name = field_data.get('name')
    field_type = field_data.get('type')
    
    # Unified validation
    if not name:
        raise ValueError("name is required")
    if not field_type:
        raise ValueError("type is required")
    
    return {
        'name': name,
        'type': field_type,
        'description': field_data.get('description', '')
    }
```

#### Backend Field Validation - Before and After
```python
# ❌ Legacy validation
def validate_legacy_field(field):
    errors = []
    
    # Check legacy properties
    if 'fieldKey' not in field:
        errors.append("Missing required property: fieldKey")
    elif not field['fieldKey'].strip():
        errors.append("fieldKey cannot be empty")
    
    if 'fieldType' not in field:
        errors.append("Missing required property: fieldType")
    elif field['fieldType'] not in ['string', 'number', 'date', 'boolean']:
        errors.append(f"Invalid fieldType: {field['fieldType']}")
    
    return errors

# ✅ Unified validation
def validate_unified_field(field):
    errors = []
    
    # Check unified properties
    if 'name' not in field:
        errors.append("Missing required property: name")
    elif not field['name'].strip():
        errors.append("name cannot be empty")
    elif not re.match(r'^[a-zA-Z0-9_]+$', field['name']):
        errors.append("name must contain only letters, numbers, and underscores")
    
    if 'type' not in field:
        errors.append("Missing required property: type")
    elif field['type'] not in ['string', 'number', 'integer', 'date', 'time', 'boolean', 'array', 'object']:
        errors.append(f"Invalid type: {field['type']}")
    
    return errors
```

### Frontend Migration (TypeScript/React)

#### Before - Legacy Frontend Code
```typescript
// ❌ Legacy field component
interface LegacyFieldProps {
  field: {
    fieldKey: string;
    fieldType: string;
    description: string;
    required: boolean;
  };
  onChange: (updates: any) => void;
}

const LegacyFieldEditor: React.FC<LegacyFieldProps> = ({ field, onChange }) => {
  return (
    <div>
      <Input
        label="Field Key"
        value={field.fieldKey}
        onChange={(e) => onChange({ fieldKey: e.target.value })}
      />
      <Dropdown
        label="Field Type"
        selectedKey={field.fieldType}
        options={fieldTypeOptions}
        onChange={(_, option) => onChange({ fieldType: option?.key })}
      />
    </div>
  );
};
```

#### After - Unified Frontend Code
```typescript
// ✅ Unified field component
interface UnifiedFieldProps {
  field: ProModeSchemaField;
  onChange: (updates: Partial<ProModeSchemaField>) => void;
}

const UnifiedFieldEditor: React.FC<UnifiedFieldProps> = ({ field, onChange }) => {
  return (
    <div>
      <Input
        label="Field Name"
        value={field.name}
        onChange={(e) => onChange({ name: e.target.value })}
      />
      <Dropdown
        label="Field Type"
        selectedKey={field.type}
        options={fieldTypeOptions}
        onChange={(_, option) => onChange({ type: option?.key as ProModeSchemaField['type'] })}
      />
    </div>
  );
};
```

#### State Management Migration
```typescript
// ❌ Legacy state management
interface LegacyFormState {
  newFieldKey: string;
  newFieldType: string;
  fields: Array<{
    fieldKey: string;
    fieldType: string;
    description: string;
  }>;
}

// ✅ Unified state management
interface UnifiedFormState {
  newFieldName: string;
  newFieldType: ProModeSchemaField['type'];
  fields: ProModeSchemaField[];
}
```

### API Request Migration

#### Before - Legacy API Requests
```typescript
// ❌ Legacy schema creation
const legacySchemaData = {
  name: "invoice_schema",
  description: "Schema for invoices",
  fields: [
    {
      fieldKey: "vendor_name",
      fieldType: "string",
      description: "Name of the vendor",
      required: true
    },
    {
      fieldKey: "invoice_amount",
      fieldType: "number", 
      description: "Total amount",
      required: true
    }
  ]
};
```

#### After - Unified API Requests
```typescript
// ✅ Unified schema creation
const unifiedSchemaData = {
  name: "invoice_schema",
  description: "Schema for invoices",
  fields: [
    {
      name: "vendor_name",
      type: "string",
      description: "Name of the vendor",
      required: true,
      method: "extract"
    },
    {
      name: "invoice_amount",
      type: "number",
      description: "Total amount", 
      required: true,
      method: "extract"
    }
  ]
};
```

## Database/Storage Migration

### Schema Update Examples

#### MongoDB Update Script
```javascript
// Update existing documents to use unified format
db.schemas.updateMany(
  {}, 
  {
    $rename: {
      "fields.$[].fieldKey": "fields.$[].name",
      "fields.$[].fieldType": "fields.$[].type"
    }
  }
);
```

#### SQL Update Script
```sql
-- Update field definitions in JSON columns
UPDATE schemas 
SET field_definitions = JSON_SET(
  JSON_SET(
    field_definitions, 
    '$[*].name', JSON_EXTRACT(field_definitions, '$[*].fieldKey')
  ),
  '$[*].type', JSON_EXTRACT(field_definitions, '$[*].fieldType')
)
WHERE JSON_EXTRACT(field_definitions, '$[0].fieldKey') IS NOT NULL;

-- Remove legacy properties
UPDATE schemas 
SET field_definitions = JSON_REMOVE(
  JSON_REMOVE(field_definitions, '$[*].fieldKey'),
  '$[*].fieldType'
);
```

## Test Migration

### Before - Legacy Tests
```typescript
// ❌ Legacy test data
const legacyTestField = {
  fieldKey: "test_field",
  fieldType: "string",
  description: "Test field description",
  required: true
};

describe('Legacy Field Processing', () => {
  it('should validate fieldKey', () => {
    expect(legacyTestField.fieldKey).toBeDefined();
    expect(legacyTestField.fieldType).toBe('string');
  });
});
```

### After - Unified Tests
```typescript
// ✅ Unified test data
const unifiedTestField: ProModeSchemaField = {
  name: "test_field",
  type: "string",
  description: "Test field description",
  required: true,
  method: "extract"
};

describe('Unified Field Processing', () => {
  it('should validate name and type', () => {
    expect(unifiedTestField.name).toBeDefined();
    expect(unifiedTestField.type).toBe('string');
    expect(unifiedTestField.name).toMatch(/^[a-zA-Z0-9_]+$/);
  });
});
```

## Common Migration Pitfalls

### 1. Property Name Confusion
```typescript
// ❌ Common mistake - mixing legacy and unified
const wrongField = {
  name: "field_name",      // ✅ Correct
  fieldType: "string",     // ❌ Wrong - should be 'type'
  description: "Description"
};

// ✅ Correct unified format
const correctField = {
  name: "field_name",      // ✅ Correct
  type: "string",          // ✅ Correct
  description: "Description"
};
```

### 2. Incomplete Migration
```typescript
// ❌ Incomplete - still has legacy fallback
function getFieldName(field: any): string {
  return field.name || field.fieldKey; // Remove legacy fallback
}

// ✅ Complete - unified only
function getFieldName(field: ProModeSchemaField): string {
  return field.name; // Only unified property
}
```

### 3. Type Safety Issues
```typescript
// ❌ Type unsafe - allows both formats
interface FlexibleField {
  name?: string;
  fieldKey?: string;  // Remove legacy property
  type?: string;
  fieldType?: string; // Remove legacy property
}

// ✅ Type safe - unified only
interface StrictField {
  name: string;       // Required unified property
  type: string;       // Required unified property
}
```

## Migration Checklist

### Backend Migration
- [ ] Update field validation functions to use `name` and `type`
- [ ] Remove all `fieldKey` and `fieldType` references
- [ ] Update database queries and updates
- [ ] Modify API response formatting
- [ ] Update schema templates and examples

### Frontend Migration  
- [ ] Update TypeScript interfaces and types
- [ ] Modify React component props and state
- [ ] Update form validation logic
- [ ] Change API request payloads
- [ ] Update test fixtures and mock data

### Testing Migration
- [ ] Update all test data to use unified format
- [ ] Modify assertion expectations
- [ ] Add validation tests for new property names
- [ ] Test Azure API compatibility
- [ ] Verify error handling with unified properties

### Documentation Migration
- [ ] Update API documentation
- [ ] Revise code comments
- [ ] Update user guides and tutorials
- [ ] Create migration documentation
- [ ] Update schema examples

## Post-Migration Validation

### Verification Scripts

#### Backend Validation
```python
def verify_unified_migration():
    """Verify no legacy properties remain in codebase"""
    legacy_patterns = ['fieldKey', 'fieldType']
    
    for pattern in legacy_patterns:
        # Search codebase for legacy patterns
        results = search_codebase(pattern)
        if results:
            print(f"WARNING: Found legacy pattern '{pattern}' in:")
            for result in results:
                print(f"  - {result}")
    
    print("Migration verification complete")
```

#### Frontend Validation
```typescript
function verifyUnifiedTypes() {
  // Ensure all field objects use unified properties
  const testField: ProModeSchemaField = {
    name: "test",
    type: "string", 
    description: "Test field"
  };
  
  // This should compile without errors
  console.log(`Field: ${testField.name} (${testField.type})`);
}
```

## Migration Timeline

The legacy format removal was completed in the following phases:

1. **Phase 1**: Backend analyzer creation functions updated
2. **Phase 2**: Frontend components migrated to unified interface
3. **Phase 3**: Template schemas and examples updated
4. **Phase 4**: Test fixtures and validation updated
5. **Phase 5**: Complete removal of legacy format support

**Status**: ✅ Complete - All legacy references removed, unified format enforced

---

*This migration guide reflects the completed transition to the unified interface. No legacy format support remains in the codebase.*