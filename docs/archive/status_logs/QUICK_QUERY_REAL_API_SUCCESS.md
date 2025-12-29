## Quick Query Real API Test — SUCCESS

Date: 2025-11-07

This document records a successful end-to-end Quick Query test against Azure AI Content Understanding using the array-based schema.

### What we ran

- Script: `test_quick_query_azure_direct.py`
- Mode: Direct Azure API (no backend), with API key auth
- Endpoint: `https://westus.api.cognitive.microsoft.com`
- API version: `2025-05-01-preview`
- Analyzer: Ephemeral analyzer created per run with "QuickQueryResults" array schema
- Document: `data/input_docs/contoso_lifts_invoice.pdf` (uploaded to storage and referenced via SAS URL)
- Output JSON: `quick_query_azure_direct_test_result.json`

### Key results

- Analyzer creation: 201 Created ✅
- Analyze (JSON with SAS URL): 202 Accepted ✅
- Poll status: Succeeded ✅
- Extracted fields (partial):
  - invoice_number: 1256003
  - total_amount: 29900.00 (currency)
  - vendor_name: Contoso Lifts LLC
  - invoice_date: 12/17/2015
  - line_item_1..6: line items parsed

Schema validation: PASS — `QuickQueryResults` array present with items including FieldName, FieldValue, FieldType, SourcePage.

### How to re-run

1) Ensure you have the storage account keys (or use your own):

```bash
# Replace with your storage account / key if different
ACCOUNT=stvscodedeve533189432253
CONTAINER=pro-input-files
ACCOUNT_KEY="<key1-or-key2>"
FILE=data/input_docs/contoso_lifts_invoice.pdf

# Upload
az storage blob upload \
  --account-name "$ACCOUNT" \
  --account-key "$ACCOUNT_KEY" \
  --container-name "$CONTAINER" \
  --name "test_quick_query_$(date +%s)_contoso_lifts_invoice.pdf" \
  --file "$FILE"

# Get latest uploaded blob name
BLOB_NAME=$(az storage blob list \
  --account-name "$ACCOUNT" \
  --account-key "$ACCOUNT_KEY" \
  --container-name "$CONTAINER" \
  --prefix test_quick_query_ \
  --query "max_by(@, &properties.lastModified).name" -o tsv)

# Generate a SAS URL (1 hour)
EXPIRY=$(date -u -d "1 hour" '+%Y-%m-%dT%H:%M:%SZ')
SAS=$(az storage blob generate-sas \
  --account-name "$ACCOUNT" \
  --account-key "$ACCOUNT_KEY" \
  --container-name "$CONTAINER" \
  --name "$BLOB_NAME" \
  --permissions r \
  --expiry "$EXPIRY" -o tsv)

export TEST_BLOB_URL="https://${ACCOUNT}.blob.core.windows.net/${CONTAINER}/${BLOB_NAME}?${SAS}"
```

2) Run the direct Azure test (JSON analyze via SAS):

```bash
export AZURE_ENDPOINT="https://westus.api.cognitive.microsoft.com"
export AZURE_API_KEY="<your-cognitive-services-key>"
# Optional retry tuning
export ANALYZE_MAX_RETRIES=12
export ANALYZE_RETRY_DELAY=3

python test_quick_query_azure_direct.py
```

Notes:
- If you see `ScenarioNotReady`, the script will automatically retry until the analyzer is ready.
- Binary analyze route (`:analyzebinary`) returned 404 on the public endpoint; use SAS URL analyze instead when using `westus.api.cognitive.microsoft.com`.
- The analyzer is ephemeral; each run creates a new analyzer ID.

### Files

- `test_quick_query_azure_direct.py`: Direct API test and result display.
- `quick_query_azure_direct_test_result.json`: Full response for the last successful run.

### Next steps

- Wire this flow into the backend or reuse the analyzer creation/analysis pattern directly in your service.
- Expand prompts and add validation to ensure field types/values match expectations for more document types.
- Optionally, add cleanup to delete analyzers after use if needed.
