#!/bin/bash

# Test comprehensive mode on Azure endpoint
API_URL="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query"

QUERY="List all areas of inconsistency identified in the invoice, organized by:
(1) all inconsistencies with corresponding evidence,
(2) inconsistencies in goods or services sold including detailed specifications for every line item, and
(3) inconsistencies regarding billing logistics and administrative or legal issues."

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-v2-enhanced-ex" \
  -d @- <<EOF | tee /tmp/comprehensive_azure_test_$(date +%Y%m%d_%H%M%S).json | jq '{
  response_length: (.response | length),
  raw_extractions_count: (.raw_extractions | length),
  processing_mode: .metadata.processing_mode,
  route_used: .route_used,
  has_raw_extractions: (.raw_extractions != null)
}'
{
  "query": "$QUERY",
  "response_type": "comprehensive",
  "algorithm_version": "v2"
}
EOF
