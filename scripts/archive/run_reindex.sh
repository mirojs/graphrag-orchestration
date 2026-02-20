#!/bin/bash
# Re-index with section-aware chunking
set -e

echo "=========================================="
echo "Section-Aware Chunking Re-Index"
echo "=========================================="

# Set environment variables
export USE_SECTION_CHUNKING=1
export GROUP_ID=test-5pdfs-1768557493369886422

echo "Environment:"
echo "  USE_SECTION_CHUNKING=$USE_SECTION_CHUNKING"
echo "  GROUP_ID=$GROUP_ID"
echo ""

# Run indexing
echo "Starting re-index..."
python scripts/index_with_hybrid_pipeline.py \
  --group-id $GROUP_ID \
  --max-docs 5

echo ""
echo "=========================================="
echo "Re-index complete! Now verifying..."
echo "=========================================="

# Verify section-aware chunks
python check_chunk_strategy.py

echo ""
echo "✅ Done! Ready for Route 2/3 testing."
