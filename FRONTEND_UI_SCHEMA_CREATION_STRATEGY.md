# Frontend UI Schema Creation - Strategic Implementation Plan

## 🎯 **Strategic Priority: Get PUT Request Working First**

You're absolutely right! The frontend UI schema creation is complex with many possibilities for subfields and nested structures. **Smart approach: Focus on getting the PUT request working with uploaded schemas first, then enhance UI creation capabilities.**

---

## 📋 **Current Frontend UI Schema Creation Workflow**

### **Step 1: Schema Metadata Input**
```tsx
// User provides basic schema information
const [schemaName, setSchemaName] = useState('');               // Schema name
const [schemaDescription, setSchemaDescription] = useState(''); // Schema description
```

### **Step 2: Field Definition Input**
```tsx
// User defines individual fields
const [newFieldName, setNewFieldName] = useState('');                    // Field name
const [newFieldDescription, setNewFieldDescription] = useState('');     // Field description  
const [newFieldType, setNewFieldType] = useState('string');             // Value type
const [newFieldGenerationMethod, setNewFieldGenerationMethod] = useState('extract'); // Method
```

### **Current Field Types Supported:**
```tsx
const FIELD_TYPES = [
  { key: 'string', text: 'Text', description: 'Text field' },
  { key: 'number', text: 'Number', description: 'Numeric value' },
  { key: 'date', text: 'Date', description: 'Date field' },
  { key: 'boolean', text: 'Boolean', description: 'True/false value' },
  { key: 'array', text: 'Array', description: 'List of subfields of the same type' },
  { key: 'object', text: 'Object', description: 'Nested object with multiple properties' }
];
```

### **Current Generation Methods:**
```tsx
const GENERATION_METHODS = [
  { key: 'extract', text: 'Extract', description: 'Extract from document' },
  { key: 'generate', text: 'Generate', description: 'Generate using AI' },
  { key: 'classify', text: 'Classify', description: 'Classify content' }
];
```

---

## 🔄 **Current UI Field Creation Process**

### **Simple Field Creation:**
```tsx
const handleAddField = useCallback(() => {
  if (newFieldName.trim()) {
    const newField: ProModeSchemaField = {
      // Azure API properties
      name: newFieldName.trim(),
      type: fieldType,
      description: newFieldDescription.trim(),
      
      // UI properties  
      fieldType: newFieldType,
      displayName: newFieldName.trim(),
      fieldKey: newFieldName.trim(),
      valueType: fieldType,
      isRequired: newFieldRequired
    };
    setSchemaFields(prev => [...prev, newField]);
    // Reset form
  }
}, [newFieldName, newFieldType, newFieldRequired, newFieldDescription]);
```

---

## 🎯 **Complex Scenarios That Need Future Enhancement**

### **Scenario 1: Array Fields with Complex Items**
```json
{
  "name": "LineItems",
  "type": "array",
  "description": "Invoice line items",
  "method": "extract",
  "items": {
    "type": "object",
    "properties": {
      "ProductName": {
        "type": "string",
        "description": "Name of the product"
      },
      "Quantity": {
        "type": "number", 
        "description": "Quantity ordered"
      },
      "UnitPrice": {
        "type": "number",
        "description": "Price per unit"
      }
    }
  }
}
```

### **Scenario 2: Object Fields with Nested Properties**
```json
{
  "name": "BillingAddress",
  "type": "object",
  "description": "Customer billing address",
  "method": "extract",
  "properties": {
    "Street": {
      "type": "string",
      "description": "Street address"
    },
    "City": {
      "type": "string", 
      "description": "City name"
    },
    "ZipCode": {
      "type": "string",
      "description": "Postal code"
    }
  }
}
```

### **Scenario 3: Schema References ($ref)**
```json
{
  "name": "Inconsistencies",
  "type": "array",
  "description": "List of inconsistencies found",
  "method": "generate",
  "items": {
    "$ref": "#/$defs/InconsistencyItem"
  }
}
```

---

## 🚀 **Implementation Strategy**

### **Phase 1: Current State (Working)**
✅ **Simple field creation with basic types**
- Field name, description, type, method
- Support for: string, number, date, boolean
- Basic array and object types (no subfield definition yet)

### **Phase 2: GET PUT Request Working (Priority 1)**
🎯 **Focus: Schema upload and processing**
- Ensure uploaded schemas work with backend
- Validate Azure Content Understanding API integration
- Test complete workflow with clean format schemas

### **Phase 3: Enhanced UI Creation (Future)**
🔮 **Complex field definition capabilities**
- Subfield definition for array types
- Property definition for object types
- Visual schema builder with drag-and-drop
- $ref reference management
- Schema definition ($defs) editor

---

## 💡 **Why This Approach Makes Sense**

### **Current Limitations of UI Creation:**
1. **Subfields/Items**: UI doesn't support defining array item structures
2. **Object Properties**: UI doesn't support defining object property structures
3. **Schema References**: UI doesn't support $ref definitions
4. **Complex Validation**: UI doesn't support nested validation rules

### **Benefits of Upload-First Approach:**
1. ✅ **Immediate functionality**: Users can create complex schemas via file upload
2. ✅ **Validation**: Backend processes and validates uploaded schemas
3. ✅ **Learning**: See what works before building complex UI
4. ✅ **Incremental**: Add UI capabilities based on actual usage patterns

---

## 📋 **Current UI Creation vs Upload Comparison**

### **What UI Can Create Now:**
```json
{
  "fields": [
    {
      "name": "CustomerName",
      "type": "string", 
      "description": "Customer name",
      "method": "extract"
    },
    {
      "name": "TotalAmount",
      "type": "number",
      "description": "Invoice total",
      "method": "extract"
    }
  ]
}
```

### **What Upload Can Handle:**
```json
{
  "fields": [
    {
      "name": "LineItems",
      "type": "array",
      "description": "Invoice line items",
      "method": "extract",
      "items": {
        "type": "object",
        "properties": {
          "ProductName": { "type": "string" },
          "Quantity": { "type": "number" },
          "UnitPrice": { "type": "number" }
        }
      }
    }
  ],
  "$defs": {
    "Address": {
      "type": "object",
      "properties": {
        "Street": { "type": "string" },
        "City": { "type": "string" }
      }
    }
  }
}
```

---

## ✅ **Immediate Action Plan**

### **Priority 1: Ensure PUT Request Works**
1. Focus on uploaded schema processing
2. Validate backend transformation and API calls
3. Test with complex schemas (arrays, objects, $refs)
4. Confirm Azure Content Understanding API integration

### **Priority 2: Basic UI Enhancements**
1. Add field validation to UI creation
2. Improve error handling for field definition
3. Add field reordering capabilities

### **Priority 3: Advanced UI Capabilities (Future)**
1. Subfield definition for arrays
2. Property definition for objects  
3. Schema reference management
4. Visual schema builder

**Your strategic approach is perfect - get the core functionality working with uploads first, then enhance the UI creation capabilities based on real usage patterns!** 🎯
