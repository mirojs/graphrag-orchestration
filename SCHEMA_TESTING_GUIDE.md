# Azure Content Understanding Schema Testing Guide

This guide provides a comprehensive approach to testing Azure Content Understanding schemas, based on lessons learned from troubleshooting API errors and compliance issues.

## 🚀 How to Use This Guide

### For Quick Testing (Recommended)
If you just want to test a schema quickly:

1. **Set your service name:**
   ```bash
   export COGNITIVE_SERVICE_NAME="your-actual-service-name"
   ```

2. **Run the automated test:**
   ```bash
   # Test the production-ready schema
   ./quick_test_schema.sh PRODUCTION_READY_SCHEMA.json
   
   # Or test your own schema
   ./quick_test_schema.sh your_schema.json
   ```

3. **Check the results:**
   - ✅ Green = Success, ready for production
   - ❌ Red = Issues found, check the error messages
   - ⚠️ Yellow = Warnings, may need attention

### For Comprehensive Testing
If you need detailed testing or troubleshooting:

1. **Start with the [Quick Start Checklist](#-quick-start-checklist)** below
2. **Choose your testing method** from [Testing Methods](#-schema-testing-methods)
3. **Use the [Common Issues](#-common-issues-and-solutions)** section if you encounter problems
4. **Reference the [Property Support Matrix](#-property-support-matrix)** for allowed fields

### For First-Time Setup
If this is your first time:

1. **Read the [Prerequisites](#-testing-prerequisites)** section
2. **Set up your [Environment](#1-environment-setup)**
3. **Get a valid [Token](#2-token-retrieval)**
4. **Verify your [Endpoint](#3-endpoint-verification)**
5. **Try the [Minimal Valid Schema](#minimal-valid-schema)** first

### For Troubleshooting
If you're having issues:

1. **Check [Common Issues](#-common-issues-and-solutions)** first
2. **Use the [Troubleshooting Commands](#-troubleshooting-commands)**
3. **Test with the [Minimal Valid Schema](#minimal-valid-schema)** to isolate problems
4. **Compare against the [Property Support Matrix](#-property-support-matrix)**

---

## 🎯 Quick Start Checklist

Before testing any schema:
- [ ] Backend is deployed with latest compliance cleaning logic
- [ ] Azure Cognitive Services token is valid and has correct audience
- [ ] Endpoint URL is correctly formatted
- [ ] Schema follows Azure API documentation structure

## 📋 Testing Prerequisites

### 1. Environment Setup
```bash
# Verify your Azure CLI is logged in
az account show

# Get your subscription ID
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# Set your resource group and service name
export RESOURCE_GROUP="your-resource-group"
export COGNITIVE_SERVICE_NAME="your-cognitive-service"
```

### 2. Token Retrieval
Use the provided script to get a valid token:
```bash
# Make the script executable
chmod +x get_cognitive_services_token.sh

# Run to get token
./get_cognitive_services_token.sh

# Token will be saved to cognitive_services_token.txt
export TOKEN=$(cat cognitive_services_token.txt)
```

### 3. Endpoint Verification
Your endpoint should follow this format:
```
https://{your-service}.cognitiveservices.azure.com/contentunderstanding/analyzers/{analyzer-id}?api-version=2025-05-01-preview
```

## 🧪 Schema Testing Methods

### Method 1: Direct API Testing (Recommended)

#### Test Schema Structure
```bash
# Test with the production-ready schema
curl -X PUT \
  "https://{your-service}.cognitiveservices.azure.com/contentunderstanding/analyzers/test-analyzer-$(date +%s)?api-version=2025-05-01-preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-ms-client-request-id: $(uuidgen)" \
  -d @PRODUCTION_READY_SCHEMA.json
```

#### Test Individual Properties
Create minimal test schemas to verify specific properties:

**Test Method Property:**
```json
{
  "kind": "documentFieldSchema",
  "apiVersion": "2025-05-01-preview",
  "fieldSchema": {
    "fields": {
      "testField": {
        "type": "string",
        "method": "invoice.testField"
      }
    }
  }
}
```

**Test Pattern Property:**
```json
{
  "kind": "documentFieldSchema",
  "apiVersion": "2025-05-01-preview",
  "fieldSchema": {
    "fields": {
      "testField": {
        "type": "string",
        "pattern": "^[A-Z]{2,3}$"
      }
    }
  }
}
```

**Test Numeric Constraints:**
```json
{
  "kind": "documentFieldSchema",
  "apiVersion": "2025-05-01-preview",
  "fieldSchema": {
    "fields": {
      "testField": {
        "type": "number",
        "minimum": 0,
        "maximum": 100
      }
    }
  }
}
```

### Method 2: Backend Testing

#### Test Compliance Cleaning
```python
# Create a test script to verify compliance cleaning
import json
import requests

# Test payload with various properties
test_payload = {
    "kind": "documentFieldSchema",
    "apiVersion": "2025-05-01-preview",
    "fieldSchema": {
        "fields": {
            "testField": {
                "type": "string",
                "method": "invoice.testField",  # Should be preserved
                "pattern": "^[A-Z]+$",         # Should be preserved
                "format": "email",             # Should be removed
                "minimum": 1,                  # Should be preserved
                "maximum": 100                 # Should be preserved
            }
        }
    }
}

# Send to your backend
response = requests.post(
    "https://your-backend.azurecontainerapps.io/api/upload-schema",
    json=test_payload
)

print("Response:", response.json())
```

### Method 3: Frontend Testing

#### Check Field Count Display
1. Upload a schema with known field count
2. Verify the frontend displays the correct number
3. Check browser console for any errors

#### Test Analysis Initiation
1. Upload a schema successfully
2. Try to start analysis with a document
3. Check for "[object Object]" errors

## 🔍 Common Issues and Solutions

### Issue: "fieldSchema.fields format error"
**Cause:** Incorrect payload structure or unsupported properties
**Solution:** 
- Use `PRODUCTION_READY_SCHEMA.json` as template
- Ensure proper nesting: `fieldSchema.fields.{fieldName}.{property}`
- Remove `format` property (not supported by Azure API)

### Issue: "401 Unauthorized"
**Cause:** Invalid token or incorrect audience
**Solution:**
- Regenerate token using `get_cognitive_services_token.sh`
- Verify token audience matches Cognitive Services
- Check token expiration

### Issue: "501 Not Implemented"
**Cause:** Incorrect endpoint URL or missing API version
**Solution:**
- Verify endpoint format: `/contentunderstanding/analyzers/{id}`
- Include `api-version=2025-05-01-preview`
- Check service name in URL

### Issue: "[object Object]" in frontend
**Cause:** Backend error not properly serialized
**Solution:**
- Check backend logs for actual error
- Ensure proper error handling in API responses
- Verify JSON serialization in error responses

## 📝 Testing Templates

### Minimal Valid Schema
```json
{
  "kind": "documentFieldSchema",
  "apiVersion": "2025-05-01-preview",
  "fieldSchema": {
    "fields": {
      "simpleField": {
        "type": "string"
      }
    }
  }
}
```

### Complex Schema with All Supported Properties
```json
{
  "kind": "documentFieldSchema",
  "apiVersion": "2025-05-01-preview",
  "fieldSchema": {
    "fields": {
      "invoiceNumber": {
        "type": "string",
        "method": "invoice.invoiceNumber",
        "pattern": "^INV-[0-9]{6}$"
      },
      "amount": {
        "type": "number",
        "method": "invoice.amount",
        "minimum": 0,
        "maximum": 999999.99
      },
      "date": {
        "type": "date"
      },
      "vendor": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "address": {
            "type": "string"
          }
        }
      },
      "lineItems": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "description": {
              "type": "string"
            },
            "quantity": {
              "type": "number",
              "minimum": 1
            },
            "unitPrice": {
              "type": "number",
              "minimum": 0
            }
          }
        }
      }
    }
  }
}
```

## 🚀 Automated Testing Script

Create this script for quick validation:

```bash
#!/bin/bash
# save as test_schema.sh

set -e

echo "🧪 Starting Schema Testing..."

# Get fresh token
echo "📋 Getting fresh token..."
./get_cognitive_services_token.sh
TOKEN=$(cat cognitive_services_token.txt)

# Test endpoint connectivity
echo "🌐 Testing endpoint connectivity..."
ANALYZER_ID="test-$(date +%s)"
ENDPOINT="https://$COGNITIVE_SERVICE_NAME.cognitiveservices.azure.com/contentunderstanding/analyzers/$ANALYZER_ID?api-version=2025-05-01-preview"

# Test with production schema
echo "📄 Testing production schema..."
curl -X PUT "$ENDPOINT" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-ms-client-request-id: $(uuidgen)" \
  -d @PRODUCTION_READY_SCHEMA.json \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo "✅ Testing complete!"
```

## 📚 Reference Files

- `PRODUCTION_READY_SCHEMA.json` - Complete working schema
- `get_cognitive_services_token.sh` - Token retrieval script
- `azure_compliant_schema_with_method.json` - Test schema with method property
- Backend: `proMode.py` - Compliance cleaning logic

## 🔧 Troubleshooting Commands

```bash
# Check backend logs
az containerapp logs show --name your-app --resource-group your-rg

# Verify token details
echo $TOKEN | base64 -d

# Test endpoint without schema
curl -X GET "https://$COGNITIVE_SERVICE_NAME.cognitiveservices.azure.com/contentunderstanding/analyzers?api-version=2025-05-01-preview" \
  -H "Authorization: Bearer $TOKEN"

# Validate JSON schema
python -m json.tool your_schema.json
```

## 📋 Property Support Matrix

| Property | Supported | Notes |
|----------|-----------|-------|
| `method` | ✅ | Required for extraction fields |
| `pattern` | ✅ | Regex validation for strings |
| `minimum` | ✅ | Numeric lower bound |
| `maximum` | ✅ | Numeric upper bound |
| `format` | ❌ | Not in Azure API docs, causes errors |
| `type` | ✅ | Required field property |
| `properties` | ✅ | For object type fields |
| `items` | ✅ | For array type fields |

Remember: When in doubt, refer to the [official Microsoft documentation](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP) for the most up-to-date property support.
