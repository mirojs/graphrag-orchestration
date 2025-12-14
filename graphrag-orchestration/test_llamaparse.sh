#!/bin/bash
# Test LlamaParse integration

set -e

echo "======================================================================"
echo "LlamaParse Integration Test"
echo "======================================================================"
echo ""

# Check environment
echo "📋 Checking environment..."

if [ -z "$LLAMA_CLOUD_API_KEY" ]; then
    echo "⚠️  LLAMA_CLOUD_API_KEY not set"
    echo ""
    echo "To test LlamaParse, you need an API key:"
    echo "  1. Go to https://cloud.llamaindex.ai/"
    echo "  2. Sign up for free"
    echo "  3. Get your API key (starts with llx-)"
    echo "  4. Set: export LLAMA_CLOUD_API_KEY=llx-your-key"
    echo ""
    echo "Proceeding with basic tests only..."
    echo ""
else
    echo "✅ LLAMA_CLOUD_API_KEY is set"
fi

# Navigate to service directory
cd "$(dirname "$0")"
echo "📂 Working directory: $(pwd)"

# Run tests
echo ""
echo "🧪 Running LlamaParse integration tests..."
echo ""

python test_llamaparse_integration.py

echo ""
echo "======================================================================"
echo "Testing Complete"
echo "======================================================================"
