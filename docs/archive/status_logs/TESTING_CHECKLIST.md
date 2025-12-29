# AI Schema Generation - Ready to Test ✅

## Implementation Status

✅ **Code Fixed** - Follows Azure documentation exactly
✅ **Syntax Validated** - No Python errors
✅ **Documentation Complete** - Usage examples provided
✅ **Test Scripts Ready** - Can test with real blob URLs

## What Was Fixed

### The Problem
We were NOT following the [official Azure tutorial](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/tutorial/create-custom-analyzer?tabs=document):

- ❌ Polling wrong endpoint (analyzer status instead of Operation-Location)
- ❌ Using text files (not supported - only PDF/images/audio/video)
- ❌ Uploading local files (Azure requires blob URLs with SAS tokens)
- ❌ Wrong status values (checking "ready" instead of "Succeeded"/"succeeded")

### The Solution
Now correctly implements Azure pattern:

1. **Create Analyzer** → Poll Operation-Location → Wait for status="Succeeded"
2. **Analyze Document** → Use blob URL → Poll Operation-Location → Wait for status="succeeded"
3. **Extract Results** → Parse generated schema from response

## Testing Checklist

### Prerequisites
- [ ] Azure Storage account available
- [ ] Sample document (PDF, image, etc.)
- [ ] Azure AI API key configured

### Step 1: Upload Sample Document

**Option A: Using helper script**
```bash
# Install Azure SDK (if not already installed)
pip install azure-storage-blob

# Set credentials
export AZURE_STORAGE_ACCOUNT_NAME="your-account-name"
export AZURE_STORAGE_ACCOUNT_KEY="your-account-key"

# Upload document
python upload_sample_document.py /path/to/sample.pdf

# Copy the blob URL from output
```

**Option B: Using Azure CLI**
```bash
# Upload file
az storage blob upload \
  --account-name your-storage \
  --container-name documents \
  --name sample.pdf \
  --file /path/to/sample.pdf \
  --auth-mode key

# Generate SAS URL (valid 1 hour)
az storage blob generate-sas \
  --account-name your-storage \
  --container-name documents \
  --name sample.pdf \
  --permissions r \
  --expiry $(date -u -d '1 hour' '+%Y-%m-%dT%H:%MZ') \
  --https-only \
  --full-uri \
  --output tsv
```

**Option C: Using Azure Portal**
1. Go to Azure Portal → Storage Account
2. Click "Containers" → Select container (or create new)
3. Click "Upload" → Select file
4. Right-click uploaded file → "Generate SAS"
5. Set expiry time → Copy URL

### Step 2: Set Environment Variables

```bash
# Required: Blob URL with SAS token
export TEST_BLOB_URL="https://storage.blob.core.windows.net/container/file.pdf?sv=2024...&sig=..."

# Optional: Azure AI credentials (if not already set)
export AZURE_AI_API_KEY="your-api-key"
# OR use Azure CLI credentials (already logged in)
```

### Step 3: Run Test

```bash
python test_ai_schema_generation_fixed.py
```

### Expected Output

```
🧪 Testing AI Schema Generation with Azure Pattern
============================================================
Query: Extract vendor name, invoice number, total amount, and payment due date
Session ID: test_ai_schema_gen_fixed
Sample Document: https://storage.blob.core.windows.net/...

🚀 Starting AI schema generation...
✅ Analyzer created (HTTP 201)
⏳ Polling operation for analyzer build completion...
   Build status: running
   Build status: succeeded
✅ Analyzer build completed in 8.3s
🚀 Starting analysis with blob URL...
✅ Analysis started
⏳ Polling for results...
   Poll 1/60: running
   Poll 3/60: succeeded
✅ Analysis completed successfully!

✅ Schema generation completed successfully!

📋 Generated Schema:
{
  "schemaId": "test_ai_schema_gen_fixed",
  "schemaName": "InvoiceDataExtraction",
  "fieldSchema": {
    "fields": {
      "VendorName": {...},
      "InvoiceNumber": {...},
      "TotalAmount": {...},
      "PaymentDueDate": {...}
    }
  }
}

✅ Test completed successfully!
```

## Files Reference

### Implementation
- `backend/utils/query_schema_generator.py` - Main implementation
  - `_generate_schema_with_ai_self_correction()` - Entry point
  - `_submit_to_azure_and_extract_schema()` - Analyzer creation & polling
  - `_analyze_document_with_azure()` - Document analysis with blob URL
  - `_parse_ai_generated_schema()` - Extract fields from AI response

### Testing
- `test_ai_schema_generation_fixed.py` - Main test script
- `upload_sample_document.py` - Helper to upload files and get blob URLs

### Documentation
- `AI_SCHEMA_GENERATION_FIXED.md` - Detailed technical documentation
- `AI_SCHEMA_GENERATION_IMPLEMENTATION_SUMMARY.md` - Change summary
- `TESTING_CHECKLIST.md` - This file

### Examples
- `example_quick_query_schema_integration.py` - Integration example

## Troubleshooting

### "TEST_BLOB_URL not set"
**Solution:** Upload document and generate SAS URL (see Step 1 above)

### "ValueError: Azure requires blob URL"
**Cause:** Passing local file path instead of blob URL
**Solution:** Upload file to blob storage first, use returned URL

### "RuntimeError: No Operation-Location header"
**Cause:** Azure API error or incorrect endpoint
**Solution:** Check API key, endpoint URL, and Azure subscription

### "Analysis failed: unsupported file format"
**Cause:** Using unsupported file type (e.g., .txt)
**Solution:** Use PDF, JPEG, PNG, TIFF, BMP, or other supported formats

### "Timeout waiting for analyzer build"
**Cause:** Azure service may be slow or analyzer too complex
**Solution:** 
- Check Azure service status
- Simplify schema if very large
- Increase timeout in code

### "HTTP 401 Unauthorized"
**Cause:** Invalid or missing API key
**Solution:** 
```bash
export AZURE_AI_API_KEY="your-correct-key"
# OR login with Azure CLI
az login
```

### "HTTP 404 Resource not found"
**Cause:** Incorrect endpoint or analyzer ID
**Solution:** Verify endpoint URL matches your Azure region

## Next Steps After Testing

1. **✅ Test passes** → Ready for integration
2. **Add to Quick Query** → "Save as Schema" button
3. **Create API endpoint** → `/api/schemas/generate-from-query`
4. **Add file upload** → Frontend uploads to blob, gets URL
5. **Update UI** → Show schema preview before saving

## Success Criteria

- ✅ Analyzer creates successfully (status: Succeeded)
- ✅ Document analysis completes (status: succeeded)
- ✅ Schema fields generated and parsed correctly
- ✅ Quality score > 70/100
- ✅ No runtime errors or exceptions

## Support

If issues persist:
1. Check Azure service health
2. Verify all environment variables set correctly
3. Test with known-good sample document
4. Review Azure Content Understanding logs in portal
5. Compare with working test: `test_schema_generation_step1.py`
