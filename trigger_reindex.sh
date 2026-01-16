#!/bin/bash
# Trigger re-indexing for test-5pdfs-1768558518157 to populate document dates

GROUP_ID="test-5pdfs-1768558518157"
BASE_URL="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Document URLs (from blob storage)
DOCS='[
  {"source": "https://graphragdemoblobs.blob.core.windows.net/pdfs/purchase_contract.pdf"},
  {"source": "https://graphragdemoblobs.blob.core.windows.net/pdfs/BUILDERS%20LIMITED%20WARRANTY.pdf"},
  {"source": "https://graphragdemoblobs.blob.core.windows.net/pdfs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf"},
  {"source": "https://graphragdemoblobs.blob.core.windows.net/pdfs/contoso_lifts_invoice.pdf"},
  {"source": "https://graphragdemoblobs.blob.core.windows.net/pdfs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"}
]'

echo "🔄 Triggering re-index for group $GROUP_ID to populate document dates..."
curl -X POST "$BASE_URL/hybrid/index/documents" \
  -H "X-Group-ID: $GROUP_ID" \
  -H "Content-Type: application/json" \
  -d "{\"documents\": $DOCS, \"reindex\": true, \"ingestion\": \"document-intelligence\"}"

echo -e "\n✅ Re-indexing triggered"
