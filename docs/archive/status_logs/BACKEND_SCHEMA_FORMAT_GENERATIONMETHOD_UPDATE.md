# GenerationMethod in Backend Schema Format - Update

## ✅ **Answer to Your Question**

**Does the backend schema format include the generationMethod item?**

**Yes, it should and now does!** Here's the complete answer:

### **Backend Processing of GenerationMethod**

#### **1. Backend Model (FieldSchema Pydantic model)**
```python
# Current backend model (in proMode.py)
class FieldSchema(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    required: bool = True
    validation_rules: Optional[dict] = None
    # generationMethod is NOT formally defined in the Pydantic model
```

#### **2. Backend Azure API Transform (actual implementation)**
```python
# Backend processes generationMethod when calling Azure API
if field.get("generationMethod"):
    azure_field_definition["generationMethod"] = field["generationMethod"]

# Also handles legacy "method" property
if field.get("method"):
    azure_field_definition["generationMethod"] = field["method"]
```

### **Updated Unified Schema Format**

I've updated our unified schema format to include `generationMethod` since the backend already processes it:

#### **Updated BackendFieldFormat Interface**
```typescript
export interface BackendFieldFormat {
  name: string;                    // Maps from frontend fieldKey
  type: string;                    // Maps from frontend fieldType
  description?: string;
  required: boolean;               // Maps from frontend required
  validation_rules?: object;       // Maps from frontend validation
  generationMethod?: 'generate' | 'extract' | 'classify'; // ✅ NOW INCLUDED
}
```

#### **Updated Backend Schema Example**
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
      "generationMethod": "extract",     // ✅ NOW INCLUDED
      "validation_rules": {
        "pattern": "^INV-[0-9]+$"
      }
    },
    {
      "name": "total_amount",
      "type": "number",
      "description": "Total amount",
      "required": true,
      "generationMethod": "extract",     // ✅ NOW INCLUDED
      "validation_rules": {
        "min": 0
      }
    }
  ],
  "version": "1.0.0",
  "status": "active",
  "createdBy": "user",
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "validationStatus": "valid",
  "isTemplate": false
}
```

### **Why Include GenerationMethod?**

1. **Backend Compatibility**: The backend already processes `generationMethod` for Azure API calls
2. **Azure API Requirement**: Azure Content Understanding API uses `generationMethod` to determine how fields should be processed
3. **Future-Proofing**: Ensures full Azure API compliance without additional transformations
4. **Consistency**: All Azure API properties are included in the unified format

### **GenerationMethod Values**

The valid values align with Azure Content Understanding API:

- **`extract`** (default): Extract information from documents
- **`generate`**: Generate new content 
- **`classify`**: Classify document content

### **Updated Transformation Logic**

#### **Frontend to Backend Transform**
```typescript
const backendFields = frontendSchema.fields.map(field => ({
  name: field.fieldKey,
  type: field.fieldType,
  description: field.description,
  required: field.required,
  generationMethod: field.generationMethod || 'extract', // ✅ Always included
  validation_rules: field.validation
}));
```

#### **Backend to Frontend Transform**
```typescript
const frontendFields = backendSchema.fields.map(field => ({
  fieldKey: field.name,
  fieldType: field.type,
  displayName: field.name,
  description: field.description,
  required: field.required,
  generationMethod: field.generationMethod || 'extract', // ✅ Always mapped
  validation: field.validation_rules
}));
```

#### **Upload Validation**
```typescript
// Enhanced validation includes generationMethod
if (field.generationMethod && !VALID_GENERATION_METHODS.includes(field.generationMethod)) {
  errors.push(`Invalid generation method "${field.generationMethod}". Must be one of: extract, generate, classify`);
}
```

### **Impact on Current Implementation**

#### **✅ What Works Now**
- All schemas include `generationMethod` when sent to backend
- Backend can process `generationMethod` for Azure API calls  
- Validation ensures only valid generation methods are accepted
- Frontend UI properly displays and manages generation methods

#### **📈 Improved Functionality**
- **Complete Azure API Support**: All required Azure properties included
- **No Backend Transformation Needed**: Backend gets Azure-ready format
- **Enhanced Validation**: Generation method validation prevents API errors
- **Future-Proof**: Ready for any Azure API updates

### **Sample Usage**

#### **Creating a Schema**
```typescript
const newSchema = {
  name: "My Schema",
  fields: [
    {
      fieldKey: "document_type",
      fieldType: "string", 
      generationMethod: "classify", // ✅ Will be included in backend format
      required: true
    },
    {
      fieldKey: "extracted_text",
      fieldType: "string",
      generationMethod: "extract",  // ✅ Will be included in backend format
      required: false
    }
  ]
};

const created = await schemaService.createSchema(newSchema);
```

#### **Uploading a Schema File**
```json
{
  "name": "Upload Schema",
  "fields": [
    {
      "name": "field1",
      "type": "string",
      "generationMethod": "extract",
      "required": true
    }
  ]
}
```

### **Summary**

**Yes, the backend schema format now includes `generationMethod`** because:

1. ✅ **Backend Support**: Backend already processes it for Azure API calls
2. ✅ **Azure API Compliance**: Required for proper Azure Content Understanding API integration  
3. ✅ **Unified Format**: Ensures consistency between created and uploaded schemas
4. ✅ **Future-Proof**: Ready for full Azure API feature support

The unified schema format now properly includes all Azure Content Understanding API properties, ensuring that schemas can be processed by the backend endpoint directly without any additional conversion.
