# Schema Template Management System

## Overview

This system provides comprehensive schema creation, editing, and management for Azure Content Understanding with full field type support and validation.

## 🚀 Quick Start Guide

### 1. Get Schema Template
```http
GET /pro-mode/schemas/template
```
Returns the complete template with all supported field types, examples, and common use cases.

### 2. Create New Schema
```http
POST /pro-mode/schemas/create
Content-Type: application/json

{
  "displayName": "Invoice Processing Schema",
  "description": "Schema for processing invoices",
  "kind": "structured",
  "fields": [
    {
      "fieldKey": "invoice_number",
      "displayName": "Invoice Number",
      "fieldType": "string",
      "description": "Unique invoice identifier",
      "required": true
    },
    {
      "fieldKey": "total_amount",
      "displayName": "Total Amount",
      "fieldType": "number",
      "description": "Total invoice amount",
      "required": true
    }
  ]
}
```

### 3. Edit Existing Schema
```http
PUT /pro-mode/schemas/{schema_id}/edit
Content-Type: application/json

{
  "displayName": "Updated Invoice Schema",
  "description": "Updated schema with new fields",
  "fields": [
    // Complete field definitions - replaces all existing fields
  ]
}
```

### 4. Validate Schema
```http
POST /pro-mode/schemas/validate
Content-Type: application/json

{
  "displayName": "Test Schema",
  "fields": [
    // Field definitions to validate
  ]
}
```

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/pro-mode/schemas/template` | Get complete schema template with examples |
| `POST` | `/pro-mode/schemas/create` | Create new schema from template |
| `GET` | `/pro-mode/schemas/{schema_id}` | Get schema for editing |
| `PUT` | `/pro-mode/schemas/{schema_id}/edit` | Edit existing schema |
| `POST` | `/pro-mode/schemas/validate` | Validate schema without saving |

## 📋 Supported Field Types

Based on [Microsoft Azure Content Understanding API](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP#fielddefinition):

### Basic Types
- **`string`** - Text values
- **`number`** - Decimal numbers
- **`integer`** - Whole numbers only
- **`date`** - Date values
- **`time`** - Time values
- **`boolean`** - True/false values
- **`selectionMark`** - Checkboxes/selections

### Complex Types
- **`array`** - Multiple values (requires `items` definition)
- **`object`** - Nested structure (requires `properties` definition)

## 🎯 Common Use Cases

### Invoice Processing
```json
{
  "displayName": "Invoice Processing Schema",
  "fields": [
    {
      "fieldKey": "invoice_number",
      "displayName": "Invoice Number",
      "fieldType": "string",
      "required": true
    },
    {
      "fieldKey": "invoice_date",
      "displayName": "Invoice Date",
      "fieldType": "date",
      "required": true
    },
    {
      "fieldKey": "line_items",
      "displayName": "Line Items",
      "fieldType": "array",
      "items": {
        "fieldType": "object",
        "properties": {
          "description": {"fieldType": "string"},
          "amount": {"fieldType": "number"}
        }
      }
    }
  ]
}
```

### Contract Analysis
```json
{
  "displayName": "Contract Analysis Schema",
  "fields": [
    {
      "fieldKey": "contract_title",
      "displayName": "Contract Title",
      "fieldType": "string",
      "required": true
    },
    {
      "fieldKey": "effective_date",
      "displayName": "Effective Date",
      "fieldType": "date",
      "required": true
    },
    {
      "fieldKey": "parties",
      "displayName": "Contract Parties",
      "fieldType": "array",
      "items": {
        "fieldType": "object",
        "properties": {
          "name": {"fieldType": "string"},
          "role": {"fieldType": "string"}
        }
      }
    }
  ]
}
```

### Form Processing
```json
{
  "displayName": "Form Processing Schema",
  "fields": [
    {
      "fieldKey": "applicant_name",
      "displayName": "Applicant Name",
      "fieldType": "string",
      "required": true
    },
    {
      "fieldKey": "contact_info",
      "displayName": "Contact Information",
      "fieldType": "object",
      "properties": {
        "email": {"fieldType": "string"},
        "phone": {"fieldType": "string"},
        "address": {"fieldType": "string"}
      }
    },
    {
      "fieldKey": "terms_accepted",
      "displayName": "Terms Accepted",
      "fieldType": "selectionMark"
    }
  ]
}
```

## ✅ Validation Rules

### Field Keys
- Must be unique within schema
- Alphanumeric characters and underscores only (`^[a-zA-Z0-9_]+$`)
- Examples: `invoice_number`, `total_amount`, `line_items`

### Field Types
- Must be one of the supported types
- Array fields **must** include `items` definition
- Object fields **must** include `properties` definition

### Required Properties
- `fieldKey` - Unique identifier
- `displayName` - Human-readable name
- `fieldType` - One of the supported types

### Optional Properties
- `description` - Field description (recommended)
- `required` - Boolean (default: false)

## 🔄 Workflow Integration

### Step 1: Create Schema
1. Get template: `GET /pro-mode/schemas/template`
2. Customize fields for your use case
3. Validate: `POST /pro-mode/schemas/validate`
4. Create: `POST /pro-mode/schemas/create`

### Step 2: Create Analyzer
Use the schema ID in analyzer creation:
```http
PUT /pro-mode/content-analyzers/{analyzer_id}
{
  "displayName": "My Analyzer",
  "description": "Analyzer description",
  "kind": "structured",
  "schema": {
    "Id": "your-schema-id-here"
  }
}
```

### Step 3: Edit Schema (if needed)
1. Get current schema: `GET /pro-mode/schemas/{schema_id}`
2. Modify fields as needed
3. Validate changes: `POST /pro-mode/schemas/validate`
4. Save changes: `PUT /pro-mode/schemas/{schema_id}/edit`

## 🛠️ Advanced Examples

### Complex Array with Nested Objects
```json
{
  "fieldKey": "invoice_line_items",
  "displayName": "Invoice Line Items",
  "fieldType": "array",
  "description": "Detailed line items from invoice",
  "items": {
    "fieldType": "object",
    "properties": {
      "item_description": {
        "fieldType": "string",
        "description": "Description of the item"
      },
      "quantity": {
        "fieldType": "integer",
        "description": "Number of items"
      },
      "unit_price": {
        "fieldType": "number",
        "description": "Price per unit"
      },
      "tax_rate": {
        "fieldType": "number",
        "description": "Tax rate as decimal (e.g., 0.08 for 8%)"
      },
      "line_total": {
        "fieldType": "number",
        "description": "Total amount for this line item"
      }
    }
  }
}
```

### Multi-level Nested Object
```json
{
  "fieldKey": "billing_address",
  "displayName": "Billing Address",
  "fieldType": "object",
  "description": "Complete billing address information",
  "properties": {
    "recipient": {
      "fieldType": "string",
      "description": "Name of the recipient"
    },
    "address": {
      "fieldType": "object",
      "properties": {
        "street_address": {"fieldType": "string"},
        "apt_suite": {"fieldType": "string"},
        "city": {"fieldType": "string"},
        "state": {"fieldType": "string"},
        "zip_code": {"fieldType": "string"},
        "country": {"fieldType": "string"}
      }
    },
    "is_primary": {
      "fieldType": "boolean",
      "description": "Whether this is the primary address"
    }
  }
}
```

## 🚨 Common Pitfalls

### ❌ Duplicate Field Keys
```json
// BAD - Duplicate fieldKey
{
  "fields": [
    {"fieldKey": "amount", "fieldType": "string"},
    {"fieldKey": "amount", "fieldType": "number"}  // ERROR: Duplicate!
  ]
}
```

### ❌ Missing Array Items
```json
// BAD - Array without items definition
{
  "fieldKey": "items",
  "fieldType": "array"
  // Missing: "items": {...}
}
```

### ❌ Missing Object Properties
```json
// BAD - Object without properties definition
{
  "fieldKey": "address",
  "fieldType": "object"
  // Missing: "properties": {...}
}
```

### ❌ Invalid Field Key Format
```json
// BAD - Invalid characters in fieldKey
{
  "fieldKey": "total-amount",  // Hyphens not allowed
  "fieldKey": "total amount",  // Spaces not allowed
  "fieldKey": "total.amount"   // Dots not allowed
}

// GOOD - Valid fieldKey format
{
  "fieldKey": "total_amount"   // Underscores are allowed
}
```

## 🔗 Integration with Analyzers

After creating a schema, use it in analyzer creation:

```http
PUT /pro-mode/content-analyzers/my-analyzer-id
{
  "displayName": "Invoice Processor",
  "description": "Processes invoice documents",
  "kind": "structured",
  "schema": {
    "Id": "your-schema-id-from-create-response"
  }
}
```

The analyzer will use your custom schema to extract the exact fields you defined!

## 📚 Additional Resources

- [Azure Content Understanding API Documentation](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP#fielddefinition)
- [Field Definition Reference](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP#fielddefinition)
- Schema Template: `GET /pro-mode/schemas/template` for complete examples and reference
