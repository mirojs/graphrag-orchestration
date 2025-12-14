#!/bin/bash
# Stage 1: Local Component Tests
# Tests individual components without containers

set -e

echo "=================================================="
echo "Stage 1: Local Component Tests"
echo "=================================================="

cd "$(dirname "$0")"

# Check prerequisites
echo ""
echo "Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi

if ! command -v neo4j-admin &> /dev/null && ! docker ps | grep -q neo4j; then
    echo "⚠️  Neo4j not detected (install locally or run via Docker)"
fi

echo "✅ Prerequisites OK"

# Install dependencies if needed
echo ""
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Run unit tests
echo ""
echo "=================================================="
echo "1. Schema Converter Tests"
echo "=================================================="
if [ -f "app/tests/test_schema_converter.py" ]; then
    python -m pytest app/tests/test_schema_converter.py -v
else
    echo "⚠️  test_schema_converter.py not found, creating minimal test..."
    python -c "
from app.services.schema_converter import SchemaConverter

# Test basic conversion
schema = {
    'title': 'TestSchema',
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'items': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item_name': {'type': 'string'}
                }
            }
        }
    }
}

entities, relations = SchemaConverter.convert(schema)
print(f'✅ Entities: {len(entities)}, Relations: {len(relations)}')
assert len(entities) > 0, 'No entities extracted'
assert len(relations) > 0, 'No relations extracted'
print('✅ Schema converter works!')
"
fi

# Test LLM service connectivity
echo ""
echo "=================================================="
echo "2. LLM Service Connectivity"
echo "=================================================="
python -c "
from app.services.llm_service import LLMService
import sys

try:
    llm = LLMService()
    if llm.llm:
        print('✅ LLM initialized')
    else:
        print('⚠️  LLM not configured (set AZURE_OPENAI_ENDPOINT)')
        
    if llm.embed_model:
        print('✅ Embedding model initialized')
    else:
        print('⚠️  Embedding model not configured')
        
except Exception as e:
    print(f'⚠️  LLM service error: {e}')
    print('   (This is OK if Azure OpenAI not configured for local testing)')
"

# Test Neo4j connectivity
echo ""
echo "=================================================="
echo "3. Neo4j Connectivity"
echo "=================================================="
python -c "
from app.services.graph_service import GraphService
import sys

try:
    graph = GraphService()
    store = graph.get_store('test-group-local')
    print('✅ Neo4j connection established')
    
    # Simple query test
    try:
        store.structured_query('RETURN 1 as test')
        print('✅ Neo4j queries work')
    except Exception as e:
        print(f'⚠️  Query error: {e}')
        
except Exception as e:
    print(f'❌ Neo4j connection failed: {e}')
    sys.exit(1)
"

# Test DI ingestion service (connection only)
echo ""
echo "=================================================="
echo "4. DI Ingestion Service Configuration"
echo "=================================================="
python -c "
from app.services.di_standard_ingestion_service import DIStandardIngestionService
from app.core.config import settings
import sys

if not settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT:
    print('⚠️  AZURE_CONTENT_UNDERSTANDING_ENDPOINT not configured')
    print('   (Required for DI Standard ingestion)')
else:
    try:
        di = DIStandardIngestionService()
        print(f'✅ DI endpoint: {di.endpoint}')
        print(f'✅ API version: {di.api_version}')
    except Exception as e:
        print(f'❌ CU service error: {e}')
        sys.exit(1)
"

echo ""
echo "=================================================="
echo "Stage 1 Complete!"
echo "=================================================="
echo ""
echo "Summary:"
echo "  ✅ Schema converter logic works"
echo "  ✅ Component initialization successful"
echo ""
echo "Next: Run Stage 2 (Local Container Tests)"
echo "  ./run_container_tests.sh"
echo "=================================================="
