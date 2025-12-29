# Quick Query Schema Generation Update

## Overview
Updated Quick Query to generate **both** extraction results and a reusable schema in a single API call.

---

## Updated Ephemeral Schema Structure

The Quick Query now creates a schema with **two main fields**:

### 1. QuickQueryResults (Data Extraction)
Extracts the actual data from documents based on user's prompt.

### 2. GeneratedSchema (Schema Generation)
Generates a reusable schema structure that can be saved and applied to similar documents.

---

## Complete Schema Definition

```json
{
  "fields": {
    "QuickQueryResults": {
      "type": "array",
      "method": "generate",
      "description": "Extract all requested information based on the user query...",
      "items": {
        "type": "object",
        "description": "Individual extracted data field with metadata",
        "properties": {
          "FieldName": {
            "type": "string",
            "description": "Name of the extracted field"
          },
          "FieldValue": {
            "type": "string",
            "description": "The actual value extracted from the document"
          },
          "FieldType": {
            "type": "string",
            "description": "Data type: string, number, date, boolean, array, or object"
          },
          "SourcePage": {
            "type": "number",
            "description": "Page number where value was found (1-based)"
          }
        }
      }
    },
    "GeneratedSchema": {
      "type": "object",
      "method": "generate",
      "description": "Generate a reusable schema structure based on the query and extracted data",
      "properties": {
        "SchemaName": {
          "type": "string",
          "description": "Suggested name for this schema"
        },
        "SchemaDescription": {
          "type": "string",
          "description": "Description of what this schema extracts"
        },
        "DocumentType": {
          "type": "string",
          "description": "Type of document this schema is designed for"
        },
        "Fields": {
          "type": "array",
          "method": "generate",
          "description": "Array of field definitions for the schema",
          "items": {
            "type": "object",
            "properties": {
              "name": {
                "type": "string",
                "description": "Field name in snake_case format"
              },
              "type": {
                "type": "string",
                "description": "Field type: string, number, date, boolean, array, or object"
              },
              "description": {
                "type": "string",
                "description": "Description of what this field represents"
              },
              "required": {
                "type": "boolean",
                "description": "Whether this field is required"
              },
              "example": {
                "type": "string",
                "description": "Example value based on analyzed document"
              }
            }
          }
        },
        "UseCases": {
          "type": "array",
          "description": "Suggested use cases for this schema",
          "items": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

---

## Updated Response Structure

### QuickQueryResponse Model
```python
class QuickQueryResponse(BaseModel):
    success: bool
    status: str  # 'processing', 'completed', 'failed', 'timeout'
    operation_id: Optional[str] = None
    analyzer_id: Optional[str] = None
    message: str
    result: Optional[dict] = None  # Contains BOTH extraction results AND generated schema
    error_details: Optional[str] = None
```

### Successful Response Example
```json
{
  "success": true,
  "status": "completed",
  "operation_id": "abc-123-xyz",
  "analyzer_id": "quick-query-group123-1234567890-5678",
  "message": "Quick Query completed successfully for prompt: Extract invoice details...",
  "result": {
    "contents": [
      {
        "fields": {
          "QuickQueryResults": {
            "valueArray": [
              {
                "valueObject": {
                  "FieldName": { "valueString": "invoice_number" },
                  "FieldValue": { "valueString": "INV-2024-001" },
                  "FieldType": { "valueString": "string" },
                  "SourcePage": { "valueNumber": 1 }
                }
              },
              {
                "valueObject": {
                  "FieldName": { "valueString": "total_amount" },
                  "FieldValue": { "valueString": "1250.00" },
                  "FieldType": { "valueString": "number" },
                  "SourcePage": { "valueNumber": 1 }
                }
              },
              {
                "valueObject": {
                  "FieldName": { "valueString": "vendor_name" },
                  "FieldValue": { "valueString": "Acme Corporation" },
                  "FieldType": { "valueString": "string" },
                  "SourcePage": { "valueNumber": 1 }
                }
              }
            ]
          },
          "GeneratedSchema": {
            "valueObject": {
              "SchemaName": {
                "valueString": "Invoice Extraction"
              },
              "SchemaDescription": {
                "valueString": "Extracts key invoice information including number, amount, vendor details, and dates"
              },
              "DocumentType": {
                "valueString": "Invoice"
              },
              "Fields": {
                "valueArray": [
                  {
                    "valueObject": {
                      "name": { "valueString": "invoice_number" },
                      "type": { "valueString": "string" },
                      "description": { "valueString": "Unique invoice identifier" },
                      "required": { "valueBoolean": true },
                      "example": { "valueString": "INV-2024-001" }
                    }
                  },
                  {
                    "valueObject": {
                      "name": { "valueString": "total_amount" },
                      "type": { "valueString": "number" },
                      "description": { "valueString": "Total invoice amount in currency" },
                      "required": { "valueBoolean": true },
                      "example": { "valueString": "1250.00" }
                    }
                  },
                  {
                    "valueObject": {
                      "name": { "valueString": "vendor_name" },
                      "type": { "valueString": "string" },
                      "description": { "valueString": "Name of the vendor or supplier" },
                      "required": { "valueBoolean": true },
                      "example": { "valueString": "Acme Corporation" }
                    }
                  }
                ]
              },
              "UseCases": {
                "valueArray": [
                  { "valueString": "Invoice processing and validation" },
                  { "valueString": "Accounts payable automation" },
                  { "valueString": "Financial reporting and analysis" }
                ]
              }
            }
          }
        }
      }
    ]
  },
  "error_details": null
}
```

---

## Frontend Access Pattern

### Accessing Extraction Results
```javascript
const extractionResults = response.result.contents[0].fields.QuickQueryResults.valueArray;

extractionResults.forEach(item => {
  const field = item.valueObject;
  const fieldName = field.FieldName.valueString;
  const fieldValue = field.FieldValue.valueString;
  const fieldType = field.FieldType.valueString;
  const sourcePage = field.SourcePage.valueNumber;
  
  console.log(`${fieldName}: ${fieldValue} (type: ${fieldType}, page: ${sourcePage})`);
});
```

### Accessing Generated Schema
```javascript
const generatedSchema = response.result.contents[0].fields.GeneratedSchema.valueObject;

const schemaInfo = {
  name: generatedSchema.SchemaName.valueString,
  description: generatedSchema.SchemaDescription.valueString,
  documentType: generatedSchema.DocumentType.valueString,
  fields: generatedSchema.Fields.valueArray.map(fieldObj => ({
    name: fieldObj.valueObject.name.valueString,
    type: fieldObj.valueObject.type.valueString,
    description: fieldObj.valueObject.description.valueString,
    required: fieldObj.valueObject.required.valueBoolean,
    example: fieldObj.valueObject.example.valueString
  })),
  useCases: generatedSchema.UseCases.valueArray.map(uc => uc.valueString)
};

console.log('Generated Schema:', schemaInfo);
```

### Save Schema Workflow
```javascript
// 1. User reviews extraction results
displayExtractionResults(extractionResults);

// 2. Extract the generated schema from response
const generatedSchemaObj = response.result.contents[0].fields.GeneratedSchema.valueObject;

// 3. Show "Save Schema" option with preview
const saveButton = document.getElementById('save-schema-btn');
saveButton.onclick = async () => {
  // User can optionally customize name and description
  const customName = document.getElementById('schema-name-input')?.value || null;
  const customDescription = document.getElementById('schema-desc-input')?.value || null;
  
  // Call the save endpoint
  const saveResponse = await fetch('/pro-mode/quick-query/save-schema', {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'X-Group-ID': currentGroupId  // Required for group isolation
    },
    body: JSON.stringify({
      generated_schema: generatedSchemaObj,  // Pass the entire GeneratedSchema object
      custom_name: customName,
      custom_description: customDescription,
      original_prompt: originalUserPrompt
    })
  });
  
  const result = await saveResponse.json();
  if (result.schema_id) {
    console.log(`Schema saved with ID: ${result.schema_id}`);
    showSuccessMessage(`Schema "${result.name}" saved successfully!`);
  }
};
```

---

## Key Benefits

1. **Single API Call**: Both extraction and schema generation happen together
2. **No Duplicate Work**: Schema is generated alongside extraction, using the same analysis
3. **User Choice**: User can review both results and decide whether to save the schema
4. **Reusability**: Generated schema can be saved and applied to similar documents
5. **Intelligent Naming**: AI suggests appropriate schema name, description, and use cases
6. **Field Metadata**: Each field includes type, description, required flag, and example

---

## Workflow

1. **User submits Quick Query** with natural language prompt
2. **Backend creates ephemeral schema** with both extraction and generation fields
3. **Azure analyzes document** and returns:
   - Extracted data (QuickQueryResults)
   - Generated schema structure (GeneratedSchema)
4. **Frontend displays both**:
   - Immediate extraction results for user
   - Schema preview with "Save Schema" option
5. **User decides**:
   - Use results immediately (ephemeral)
   - Save schema for reuse on similar documents

---

## Implementation Status

✅ **Backend Updated**: Schema generation added to Quick Query endpoint  
✅ **Response Structure**: Includes both extraction results and generated schema  
✅ **Save Endpoint**: New `/pro-mode/quick-query/save-schema` endpoint added  
✅ **Schema Conversion**: Converts Azure format to saveable schema structure  
⏳ **Frontend Integration**: Needs update to display and save generated schema  

---

## Save Schema Endpoint

### Endpoint
`POST /pro-mode/quick-query/save-schema`

### Request Model
```python
class SaveQuickQuerySchemaRequest(BaseModel):
    generated_schema: dict  # The GeneratedSchema object from Quick Query response
    custom_name: Optional[str] = None  # User can override AI-suggested name
    custom_description: Optional[str] = None  # User can override AI-suggested description
    original_prompt: str  # The original Quick Query prompt for reference
```

### Request Example
```json
{
  "generated_schema": {
    "SchemaName": { "valueString": "Invoice Extraction" },
    "SchemaDescription": { "valueString": "Extracts invoice details..." },
    "DocumentType": { "valueString": "Invoice" },
    "Fields": {
      "valueArray": [
        {
          "valueObject": {
            "name": { "valueString": "invoice_number" },
            "type": { "valueString": "string" },
            "description": { "valueString": "Unique invoice identifier" },
            "required": { "valueBoolean": true },
            "example": { "valueString": "INV-2024-001" }
          }
        }
      ]
    },
    "UseCases": {
      "valueArray": [
        { "valueString": "Invoice processing" },
        { "valueString": "Accounts payable automation" }
      ]
    }
  },
  "custom_name": null,
  "custom_description": null,
  "original_prompt": "Extract invoice details including number, amount, vendor"
}
```

### What It Does
1. **Extracts values** from Azure's `valueString`/`valueArray`/`valueObject` format
2. **Converts fields** to standard schema field definitions
3. **Builds schema object** in Azure-compatible format with `fieldSchema` wrapper
4. **Saves metadata** including source, original prompt, document type, use cases, and field examples
5. **Uploads to blob storage** and saves to Cosmos DB with group isolation

### Response
Returns the standard schema save response with:
- `schema_id`: Unique identifier for the saved schema
- `blob_url`: URL to the schema JSON in blob storage
- `message`: Success confirmation

---

## Next Steps

1. Update frontend to extract and display GeneratedSchema from response
2. Add "Save Schema" button/modal in Quick Query results view
3. Implement schema conversion if needed for save endpoint
4. Add user feedback for schema name/description customization before saving
