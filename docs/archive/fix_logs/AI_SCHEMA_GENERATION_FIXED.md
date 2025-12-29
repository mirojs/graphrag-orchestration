# AI Schema Generation - Fixed Implementation

## Summary

Fixed the AI schema generation implementation to follow the correct Azure Content Understanding pattern as documented in the [official Azure tutorial](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/tutorial/create-custom-analyzer?tabs=document).

## The Problem

Previous attempts were trying to:
- Send text files to Azure (not supported - only PDF, images, audio, video)
- Create analyzers and immediately check status (wrong - need to poll Operation-Location)
- Use local file paths instead of blob URLs

## The Solution

Follow the correct Azure pattern:

### 1. **Analyzer Creation**
```python
# Create analyzer via PUT request
response = requests.put(analyzer_url, json=analyzer_config, headers=headers)

# Get Operation-Location from response headers
operation_location = response.headers.get('Operation-Location')

# Poll Operation-Location until status = "Succeeded" (capital S)
while polling:
    op_response = requests.get(operation_location, headers=headers)
    status = op_response.json().get('status')
    if status.lower() == 'succeeded':
        break  # Analyzer is ready
```

### 2. **Document Analysis**
```python
# Analyze using blob URL (not local file!)
analyze_payload = {
    "inputs": [{"url": blob_url_with_sas_token}]
}

# POST to :analyze endpoint
response = requests.post(analyze_url, json=analyze_payload, headers=headers)

# Get Operation-Location for analysis
operation_location = response.headers.get('Operation-Location')

# Poll until status = "succeeded" (lowercase s)
while polling:
    result = requests.get(operation_location, headers=headers)
    status = result.json().get('status')
    if status.lower() == 'succeeded':
        return result.json().get('result')
```

## Key Changes Made

### 1. **Removed Incorrect Status Polling**
❌ **Before:**
```python
# Poll analyzer endpoint directly - WRONG!
status_resp = requests.get(f"{endpoint}/analyzers/{analyzer_id}")
if status_resp.json().get("status") == "ready":  # Never becomes "ready"!
```

✅ **After:**
```python
# Poll Operation-Location from PUT response - CORRECT!
op_resp = requests.get(operation_location)
if op_resp.json().get('status').lower() == 'succeeded':  # Proper status
```

### 2. **Fixed Case Sensitivity**
- Analyzer creation status: `"Succeeded"` (capital S)
- Analysis status: `"succeeded"` (lowercase s)

### 3. **Changed to Blob URL Pattern**
❌ **Before:**
```python
# Try to upload local file as binary
with open(document_path, 'rb') as f:
    requests.post(analyze_url, data=f.read())  # WRONG!
```

✅ **After:**
```python
# Use blob URL with SAS token
payload = {"inputs": [{"url": blob_url}]}
requests.post(analyze_url, json=payload)  # CORRECT!
```

### 4. **Removed Text File Creation**
Azure Content Understanding does NOT support plain text files. Only:
- PDF documents
- Images (JPEG, PNG, TIFF, BMP)
- Audio files
- Video files

## Usage

### Method Signature
```python
def _generate_schema_with_ai_self_correction(
    self,
    query: str,
    session_id: Optional[str] = None,
    sample_document_path: Optional[str] = None  # REQUIRED: Blob URL with SAS
) -> Dict[str, Any]:
```

### Example
```python
from backend.utils.query_schema_generator import QuerySchemaGenerator

generator = QuerySchemaGenerator()

# Step 1: Upload sample document to Azure Blob Storage
# (Use Azure Portal or Azure CLI)

# Step 2: Generate SAS URL with read permissions
blob_url = "https://mystorageaccount.blob.core.windows.net/mycontainer/invoice.pdf?sv=2024-05-04&sr=b&sig=..."

# Step 3: Generate schema
schema = generator._generate_schema_with_ai_self_correction(
    query="Extract vendor name, invoice number, total amount, and payment due date",
    session_id="invoice_extraction_v1",
    sample_document_path=blob_url  # Blob URL with SAS token
)
```

### Generating SAS URL
```bash
# Using Azure CLI
az storage blob generate-sas \
  --account-name your-storage-account \
  --container-name your-container \
  --name your-file.pdf \
  --permissions r \
  --expiry $(date -u -d '1 hour' '+%Y-%m-%dT%H:%MZ') \
  --https-only \
  --full-uri \
  --auth-mode key \
  --output tsv
```

## Testing

Run the test script:
```bash
# Set blob URL environment variable
export TEST_BLOB_URL="https://storage.blob.core.windows.net/container/file.pdf?sv=..."

# Run test
python test_ai_schema_generation_fixed.py
```

## What Azure Does

When you call this method:

1. **Creates custom analyzer** with instructions:
   - "Generate field definitions for: [user query]"
   - Field types: GeneratedSchemaName (string), GeneratedFields (string with JSON array)

2. **Analyzes sample document** with that analyzer:
   - Azure AI reads the sample document
   - Understands what kind of data it contains
   - Generates appropriate field definitions based on the query
   - Returns schema as JSON string

3. **Parses result**:
   - Extracts GeneratedSchemaName and GeneratedFields from response
   - Converts JSON string to actual field objects
   - Creates production-ready schema

## References

- [Azure Content Understanding Tutorial](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/tutorial/create-custom-analyzer?tabs=document)
- [Azure Content Understanding API Reference](https://learn.microsoft.com/en-us/rest/api/aiservices/content-understanding)
- Working test: `test_schema_generation_step1.py`
- Working Quick Query test: `test_quick_query_azure_direct.py`

## Files Modified

1. `backend/utils/query_schema_generator.py`:
   - `_generate_schema_with_ai_self_correction()` - Fixed to require blob URL
   - `_submit_to_azure_and_extract_schema()` - Fixed Operation-Location polling
   - `_analyze_document_with_azure()` - Changed to use blob URL instead of file upload

2. `test_ai_schema_generation_fixed.py` - New test following correct pattern

## Status

✅ Implementation follows Azure documentation
✅ Polling logic matches working test files
✅ Blob URL requirement documented
✅ Case sensitivity issues resolved
✅ Ready for testing with real blob URL
