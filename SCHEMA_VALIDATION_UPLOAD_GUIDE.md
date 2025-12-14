# Schema Validation for Uploaded Schemas - Complete Guide

## **How Schema Validation Works for Uploaded Schemas**

### **🔄 Validation Flow Overview**

```
1. User selects schema files → 2. Read file content → 3. Parse JSON → 4. Validate structure → 5. Check Azure compliance → 6. Show feedback → 7. Upload or reject
```

### **📋 Step-by-Step Validation Process**

#### **Step 1: File Processing**
```typescript
// In schemaService.uploadSchemas()
for (const file of files) {
  try {
    const content = await file.text();           // Read file content
    const schemaData = JSON.parse(content);      // Parse JSON
    
    // Validate the schema format
    const validation = await this.validateSchema(schemaData);
    
    if (!validation.isValid) {
      allErrors.push(`${file.name}: ${validation.errors.join('; ')}`);
      continue; // Skip invalid files
    }
    
    // Normalize to consistent backend format
    const normalizedSchema = normalizeUploadedSchema(schemaData);
    
  } catch (parseError) {
    allErrors.push(`${file.name}: Invalid JSON - ${parseError.message}`);
  }
}
```

#### **Step 2: Multi-Level Validation**

##### **A. JSON Structure Validation**
```typescript
// Basic structure checks
if (!schemaData || typeof schemaData !== 'object') {
  errors.push('Schema must be a valid JSON object');
}

if (!schemaData.fields || !Array.isArray(schemaData.fields)) {
  errors.push('Schema must have a "fields" property that is an array');
}
```

##### **B. Required Properties Validation**
```typescript
// Schema-level required properties
if (!schemaData.name || schemaData.name.trim().length === 0) {
  errors.push('Schema name is required and must be a non-empty string');
}

// Field-level required properties
schemaData.fields.forEach((field, index) => {
  if (!field.name && !field.fieldKey) {
    errors.push(`Field ${index + 1}: Must have either "name" or "fieldKey" property`);
  }
  
  if (!field.type && !field.fieldType) {
    errors.push(`Field ${index + 1}: Field type is required`);
  }
});
```

##### **C. Azure Content Understanding API Compliance**
```typescript
const VALID_FIELD_TYPES = ['string', 'date', 'time', 'number', 'integer', 'boolean', 'array', 'object'];
const VALID_GENERATION_METHODS = ['generate', 'extract', 'classify'];

// Field type validation
const fieldType = field.type || field.fieldType;
if (!VALID_FIELD_TYPES.includes(fieldType)) {
  errors.push(`Invalid field type "${fieldType}". Must be one of: ${VALID_FIELD_TYPES.join(', ')}`);
}

// Generation method validation
if (field.generationMethod && !VALID_GENERATION_METHODS.includes(field.generationMethod)) {
  errors.push(`Invalid generation method "${field.generationMethod}". Must be one of: ${VALID_GENERATION_METHODS.join(', ')}`);
}
```

##### **D. Data Type and Format Validation**
```typescript
// Boolean validation
if (field.required !== undefined && typeof field.required !== 'boolean') {
  warnings.push(`"required" should be a boolean value`);
}

// Validation rules format
if (field.validation_rules && typeof field.validation_rules !== 'object') {
  warnings.push(`Validation rules should be an object`);
}
```

#### **Step 3: Validation Result Processing**

##### **Error Categories**
- **🚫 Errors**: Blocking issues that prevent upload
- **⚠️ Warnings**: Non-blocking issues that should be reviewed
- **✅ Success**: Valid schemas ready for upload

##### **Response Structure**
```typescript
interface ValidationResult {
  isValid: boolean;        // Whether schema can be uploaded
  errors: string[];        // Blocking validation errors
  warnings: string[];      // Non-blocking warnings
}

interface UploadResult {
  schemas: ProModeSchema[]; // Successfully uploaded schemas
  errors: string[];         // File-specific errors
  warnings: string[];       // File-specific warnings
}
```

### **🎨 User Interface Validation Feedback**

#### **Validation Display Component**
```tsx
<SchemaValidationFeedback 
  validation={{
    isValid: false,
    errors: [
      "Field 1: Invalid field type 'currency'. Must be one of: string, date, time, number, integer, boolean, array, object",
      "Field 2: Field name is required"
    ],
    warnings: [
      "Version should be a string (e.g., '1.0.0')",
      "Field 3: 'required' should be a boolean value"
    ]
  }}
  fileName="my-schema.json"
/>
```

#### **Visual Feedback Examples**

##### **❌ Error State**
```
🔴 Schema Validation Errors
my-schema.json:
• Field 1: Invalid field type 'currency'. Must be one of: string, date, time, number, integer, boolean, array, object
• Field 2: Field name is required
• Schema name is required and must be a non-empty string
```

##### **⚠️ Warning State**  
```
🟡 Schema Validation Warnings
my-schema.json:
• Version should be a string (e.g., '1.0.0')
• Field 3: 'required' should be a boolean value
✅ my-schema.json: Schema is valid (with warnings above)
```

##### **✅ Success State**
```
✅ my-schema.json: Schema is valid
```

### **📝 Validation Rules Reference**

#### **Schema-Level Validation**
| Property | Rule | Error/Warning |
|----------|------|---------------|
| **name** | Required, non-empty string | Error |
| **fields** | Required array | Error |
| **fields.length** | > 0 recommended | Warning |
| **version** | String format recommended | Warning |
| **status** | One of: active, draft, inactive | Warning |

#### **Field-Level Validation**
| Property | Rule | Error/Warning |
|----------|------|---------------|
| **name/fieldKey** | Required, non-empty string | Error |
| **type/fieldType** | Must be Azure API compatible | Error |
| **generationMethod** | Must be: extract, generate, classify | Error |
| **required** | Boolean type recommended | Warning |
| **validation_rules** | Object format recommended | Warning |

#### **Azure API Field Types**
```typescript
// ✅ Valid Field Types
'string'    // Text content
'date'      // Date values  
'time'      // Time values
'number'    // Floating point numbers
'integer'   // Whole numbers
'boolean'   // True/false values
'array'     // Collections
'object'    // Complex structures

// ❌ Invalid Field Types (Legacy)
'text'      // Use 'string' instead
'currency'  // Use 'number' instead  
'percentage' // Use 'number' instead
'datetime'  // Use 'date' or 'time' instead
```

### **🔧 Sample Validation Scenarios**

#### **Scenario 1: Valid Schema**
```json
// ✅ This will pass validation
{
  "name": "Invoice Schema",
  "description": "Schema for invoice processing",
  "fields": [
    {
      "name": "invoice_number",
      "type": "string",
      "description": "Invoice number",
      "required": true,
      "generationMethod": "extract",
      "validation_rules": {
        "pattern": "^INV-[0-9]+$"
      }
    }
  ],
  "version": "1.0.0",
  "createdBy": "user"
}
```

#### **Scenario 2: Schema with Errors**
```json
// ❌ This will fail validation
{
  "name": "",                    // Error: Empty name
  "fields": [
    {
      // Error: Missing name/fieldKey
      "type": "currency",          // Error: Invalid field type
      "required": "yes",           // Warning: Should be boolean
      "generationMethod": "manual" // Error: Invalid generation method
    }
  ]
}

// Validation Result:
{
  "isValid": false,
  "errors": [
    "Schema name is required and must be a non-empty string",
    "Field 1: Must have either 'name' or 'fieldKey' property", 
    "Field 1: Invalid field type 'currency'. Must be one of: string, date, time, number, integer, boolean, array, object",
    "Field 1: Invalid generation method 'manual'. Must be one of: extract, generate, classify"
  ],
  "warnings": [
    "Field 1: 'required' should be a boolean value"
  ]
}
```

#### **Scenario 3: Schema with Warnings Only**
```json
// ⚠️ This will pass with warnings
{
  "name": "My Schema",
  "fields": [
    {
      "name": "field1",
      "type": "string",
      "required": "true",        // Warning: Should be boolean
      "generationMethod": "extract"
    }
  ],
  "version": 1.0,              // Warning: Should be string
  "status": "published"        // Warning: Should be 'active', 'draft', or 'inactive'
}

// Validation Result:
{
  "isValid": true,
  "errors": [],
  "warnings": [
    "Field 1 (field1): 'required' should be a boolean value",
    "Version should be a string (e.g., '1.0.0')",
    "Invalid status 'published'. Recommended values: active, draft, inactive"
  ]
}
```

### **⚡ Upload Process Flow**

#### **1. Pre-Upload Validation**
```typescript
// All files validated before any upload
const result = await schemaService.uploadSchemas(files);

if (result.errors.length > 0) {
  // Show validation errors - no upload occurs
  displayValidationErrors(result.errors);
  return;
}

// All files valid - proceed with upload
displaySuccessMessage(`${result.schemas.length} schemas uploaded successfully`);
```

#### **2. Batch Upload Results**
```typescript
// Example upload result
{
  schemas: [
    { id: "schema-1", name: "Valid Schema 1", ... },
    { id: "schema-2", name: "Valid Schema 2", ... }
  ],
  errors: [
    "invalid-schema.json: Field type 'currency' is invalid",
    "broken-schema.json: Invalid JSON - Unexpected token"
  ],
  warnings: [
    "schema-with-warnings.json: Version should be a string"
  ]
}
```

#### **3. User Feedback**
```tsx
// UI displays results per file
{result.schemas.map(schema => (
  <div key={schema.id}>✅ {schema.name} uploaded successfully</div>
))}

{result.errors.map(error => (
  <div key={error}>❌ {error}</div>
))}

{result.warnings.map(warning => (
  <div key={warning}>⚠️ {warning}</div>
))}
```

### **🎯 Benefits of This Validation System**

1. **✅ Early Error Detection**: Invalid schemas caught before API calls
2. **✅ Clear Feedback**: Users see exactly what needs to be fixed
3. **✅ Azure API Compliance**: Ensures all uploaded schemas work with Azure
4. **✅ Flexible Format Support**: Handles multiple field naming conventions
5. **✅ Non-Blocking Warnings**: Issues that don't prevent upload are flagged as warnings
6. **✅ File-Specific Errors**: Each file gets individual validation feedback
7. **✅ Consistent Backend Format**: All valid schemas normalized to unified format

The validation system ensures that only properly formatted, Azure-compliant schemas reach the backend, preventing API errors and ensuring smooth schema processing.
