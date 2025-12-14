# Azure API Clean Schema Format - Correction

## ❌ **You Are Absolutely Correct!**

I made an error in removing valid Azure Content Understanding API properties from the clean schema format. According to the [Microsoft Azure Content Understanding API documentation](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP#fielddefinition), the following properties **should be preserved**:

---

## 🔧 **Corrected Clean Schema Format**

### **What We Should Allow in Clean Schemas:**

```json
{
    "fields": [
        {
            "name": "PaymentTermsInconsistencies",
            "type": "array",
            "description": "List all areas of inconsistency identified in the invoice with corresponding evidence.",
            "required": false,
            "method": "generate",
            "items": {
                "$ref": "#/$defs/InvoiceInconsistency"
            }
        }
    ],
    "$defs": {
        "InvoiceInconsistency": {
            "type": "object",
            "properties": {
                "Evidence": {
                    "type": "string",
                    "description": "Evidence or reasoning for the inconsistency"
                },
                "InvoiceField": {
                    "type": "string",
                    "description": "Invoice field that is inconsistent"
                }
            }
        }
    }
}
```

### **Azure API Properties We Incorrectly Removed:**

1. **`$ref`**: Valid JSON Schema reference to definitions
   - Example: `"$ref": "#/$defs/InvoiceInconsistency"`
   - Used for: Referencing reusable schema definitions

2. **`method`**: Alternative to `generationMethod`
   - Example: `"method": "generate"`
   - Valid values: `"generate"`, `"extract"`, `"classify"`

3. **`$defs`**: Schema definitions section
   - Example: `"$defs": { "InvoiceInconsistency": {...} }`
   - Used for: Defining reusable schema components

4. **`items`**: Array item definitions
   - Example: `"items": { "$ref": "#/$defs/InvoiceInconsistency" }`
   - Used for: Defining array element structure

5. **`properties`**: Object property definitions
   - Example: `"properties": { "Evidence": {...}, "InvoiceField": {...} }`
   - Used for: Defining object field structure

---

## 🛠️ **What I Fixed**

### **1. Updated BackendFieldFormat Interface**
```typescript
export interface BackendFieldFormat {
  name: string;
  type: string;
  description?: string;
  required: boolean;
  generationMethod?: 'generate' | 'extract' | 'classify';
  method?: 'generate' | 'extract' | 'classify'; // ✅ Added support
  $ref?: string;         // ✅ Added Azure API JSON Schema reference
  items?: {              // ✅ Added Azure API array items
    type?: string;
    $ref?: string;
    properties?: { [key: string]: Partial<BackendFieldFormat> };
  };
  properties?: { [key: string]: Partial<BackendFieldFormat> }; // ✅ Added object properties
}
```

### **2. Updated Schema Normalization**
```typescript
// Preserve Azure API specific properties
if (field.$ref) {
  normalizedField.$ref = field.$ref; // ✅ Preserve $ref
}

if (field.method && !field.generationMethod) {
  normalizedField.method = field.method; // ✅ Preserve method
}

if (field.items) {
  normalizedField.items = field.items; // ✅ Preserve items
}

if (field.properties) {
  normalizedField.properties = field.properties; // ✅ Preserve properties
}
```

---

## 📋 **Corrected Understanding**

### **What "Clean Format" Actually Means:**
- ✅ **Remove backend metadata**: No `name`, `description`, `version`, `baseAnalyzerId` at schema level
- ✅ **Preserve Azure API field properties**: Keep `$ref`, `method`, `items`, `properties`, etc.
- ✅ **Keep field-level data**: All Azure API FieldDefinition properties are valid user input

### **Example: Corrected Clean Schema**
```json
{
    "fields": [
        {
            "name": "PaymentTermsInconsistencies",
            "type": "array",
            "description": "List all areas of inconsistency identified in the invoice with corresponding evidence.",
            "required": false,
            "method": "generate",
            "items": {
                "$ref": "#/$defs/InvoiceInconsistency"
            }
        },
        {
            "name": "ItemInconsistencies", 
            "type": "array",
            "description": "List all areas of inconsistency identified in the invoice in the goods or services sold.",
            "required": false,
            "generationMethod": "extract",
            "items": {
                "type": "object",
                "properties": {
                    "Evidence": {
                        "type": "string",
                        "description": "Evidence or reasoning for the inconsistency"
                    },
                    "InvoiceField": {
                        "type": "string",
                        "description": "Invoice field that is inconsistent"
                    }
                }
            }
        }
    ],
    "$defs": {
        "InvoiceInconsistency": {
            "type": "object",
            "properties": {
                "Evidence": {
                    "type": "string",
                    "description": "Evidence or reasoning for the inconsistency in the invoice."
                },
                "InvoiceField": {
                    "type": "string",
                    "description": "Invoice field or the aspect that is inconsistent with the contract."
                }
            }
        }
    }
}
```

---

## ✅ **Summary**

**You were absolutely right!** 

- ❌ **My error**: Incorrectly removed valid Azure API properties (`$ref`, `method`, `$defs`, etc.)
- ✅ **Correction**: Clean format should preserve **all valid Azure API FieldDefinition properties**
- ✅ **Updated**: Backend interfaces and normalization now support full Azure API specification
- ✅ **Clarification**: "Clean" means no **backend metadata pollution**, not removing **user-configurable Azure API properties**

The clean schema format should allow users to input any valid Azure Content Understanding API field properties while keeping backend configuration separate.
