#!/bin/bash

echo "🧹 Cleaning up RAPTOR data via API..."
echo ""

curl -X POST "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/admin/cleanup-raptor" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-3072-fresh" \
  -d '{
    "group_id": "test-3072-fresh",
    "recreate_index": true
  }' | python3 -m json.tool

echo ""
echo "✅ Done! Now run: python test_managed_identity_pdfs.py"
