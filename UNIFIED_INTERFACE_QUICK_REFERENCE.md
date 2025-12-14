# Unified Schema Interface - Quick Reference

## 🔥 Current Standard Format

```typescript
interface ProModeSchemaField {
  // ✅ REQUIRED UNIFIED PROPERTIES
  name: string;        // Field identifier (Azure API compliant)
  type: FieldType;     // Field data type (Azure API compliant)
  description: string; // Field description
  
  // ✅ OPTIONAL PROPERTIES
  required?: boolean;   // Field is mandatory
  method?: 'extract' | 'generate' | 'classify';
  displayName?: string; // UI display name
}
```

## 📋 Supported Field Types

| Type | Description | Example Use Case |
|------|-------------|------------------|
| `string` | Text content | Names, descriptions, IDs |
| `number` | Decimal numbers | Prices, percentages |
| `integer` | Whole numbers | Quantities, counts |
| `date` | Date values | Invoice dates, due dates |
| `time` | Time values | Timestamps, durations |
| `boolean` | True/false | Status flags, checkboxes |
| `array` | Lists of values | Line items, tags |
| `object` | Nested structures | Addresses, complex data |

## 🎯 Quick Examples

### Basic Text Field
```typescript
{
  name: "vendor_name",
  type: "string",
  description: "Name of the vendor",
  required: true,
  method: "extract"
}
```

### Numeric Field with Validation
```typescript
{
  name: "invoice_amount", 
  type: "number",
  description: "Total invoice amount",
  required: true,
  validation: { min: 0 },
  format: "currency"
}
```

### Date Field
```typescript
{
  name: "invoice_date",
  type: "date", 
  description: "Invoice issue date",
  required: true,
  format: "YYYY-MM-DD"
}
```

## 🚫 DEPRECATED - Do Not Use

```typescript
// ❌ Legacy format - NO LONGER SUPPORTED
{
  fieldKey: "vendor_name",    // Use 'name' instead
  fieldType: "string",        // Use 'type' instead
  // ...
}
```

## ✅ Validation Rules

### Field Name Requirements
- **Pattern**: `/^[a-zA-Z0-9_]+$/`
- **Length**: 1-50 characters
- **Format**: snake_case preferred
- **Unique**: No duplicates in schema

### Required Properties
- `name` - Always required
- `type` - Must be valid FieldType
- `description` - Required for user-created fields

## 🔧 Common Patterns

### Creating a Field
```typescript
const createField = (
  name: string, 
  type: FieldType, 
  description: string
): ProModeSchemaField => ({
  name,
  type,
  description,
  required: false,
  method: 'extract'
});
```

### Validation Function
```typescript
const validateField = (field: ProModeSchemaField): string[] => {
  const errors: string[] = [];
  
  if (!field.name?.match(/^[a-zA-Z0-9_]+$/)) {
    errors.push('Invalid field name format');
  }
  
  if (!['string', 'number', 'date', 'boolean'].includes(field.type)) {
    errors.push('Invalid field type');
  }
  
  return errors;
};
```

## 🏗️ Schema Structure

```typescript
interface ProModeSchema {
  name: string;
  description: string;
  fields: ProModeSchemaField[];  // Array of unified fields
  baseAnalyzerId?: string;
}
```

## 🔗 Azure API Mapping

```typescript
// Direct mapping to Azure FieldDefinition
const azureField = {
  name: field.name,              // ✅ 1:1 mapping
  type: field.type,              // ✅ 1:1 mapping  
  description: field.description, // ✅ 1:1 mapping
  required: field.required,      // ✅ Optional
  method: field.method           // ✅ Optional
};
```

## 📚 Documentation Files

1. **[UNIFIED_SCHEMA_INTERFACE_DOCUMENTATION.md](./UNIFIED_SCHEMA_INTERFACE_DOCUMENTATION.md)** - Complete interface specification
2. **[LEGACY_TO_UNIFIED_MIGRATION_GUIDE.md](./LEGACY_TO_UNIFIED_MIGRATION_GUIDE.md)** - Migration from legacy format
3. **[UNIFIED_INTERFACE_USAGE_EXAMPLES.md](./UNIFIED_INTERFACE_USAGE_EXAMPLES.md)** - Practical examples and patterns

## 🎯 Key Benefits

- ✅ **Azure API Compliant** - Direct mapping to Microsoft standards
- ✅ **Type Safe** - Full TypeScript support
- ✅ **Consistent** - Unified format across frontend/backend
- ✅ **Validated** - Built-in validation rules
- ✅ **Future Proof** - No legacy compatibility baggage

## 🚨 Important Notes

- **No Legacy Support**: `fieldKey`/`fieldType` completely removed
- **Breaking Change**: All existing code updated to unified format
- **Azure Ready**: Direct compatibility with Content Understanding API
- **Validation Required**: All fields must pass validation checks

---

*This quick reference reflects the current unified interface standard. For detailed examples and migration guidance, see the complete documentation files.*