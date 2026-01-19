#!/bin/bash
# Re-index with section-aware chunking using the correct script
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

# Run the documented indexing script
echo "Starting re-index using scripts/index_5pdfs.py..."
python3 scripts/index_5pdfs.py

echo ""
echo "=========================================="
echo "Re-index complete! Now verifying..."
echo "=========================================="

# Wait a moment for data to settle
sleep 2

# Verify section-aware chunks
python check_chunk_strategy.py

echo ""
echo "✅ Done! Ready for Route 2/3 testing."
