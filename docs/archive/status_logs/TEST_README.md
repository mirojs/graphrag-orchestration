# GraphRAG v3 Managed Identity Test Suite

## Overview

This test suite validates the complete GraphRAG v3 pipeline with Azure managed identity authentication (no API keys required).

## What It Tests

### ✅ Test 1: Document Indexing
- **LLM**: GPT-4o with managed identity for entity extraction
- **Embeddings**: text-embedding-3-large with managed identity
- **Validation**: Entities, relationships, communities, and RAPTOR nodes created
- **Key Achievement**: Embedding model works with `api_key: ""` workaround while using token provider

### ✅ Test 2: DRIFT Queries
- **Purpose**: Semantic search using embeddings
- **Validation**: Confirms embedder is initialized (no "Embedder not initialized" error)
- **Tests**: 3 different semantic queries with confidence scores
- **Key Check**: Embeddings work without API keys stored

### ✅ Test 3: Local Query
- **Purpose**: Entity-based query without semantic search
- **Validation**: Neo4j graph traversal works

### ✅ Test 4: Global Query
- **Purpose**: Community-level summarization
- **Validation**: RAPTOR hierarchical summarization works

## Running the Tests

### Quick Run
```bash
cd /afh/projects/graphrag-orchestration
python3 test_managed_identity.py
```

### With Details
The script will automatically:
1. Create a unique test group ID (timestamp-based)
2. Index 3 sample documents (invoices/contracts)
3. Wait 3 seconds for Neo4j propagation
4. Execute all 4 test categories
5. Print a summary with pass/fail status

### Expected Output
```
================================================================================
  GraphRAG v3 - Managed Identity Integration Test Suite
  Testing: No API keys, only Azure AD managed identity
================================================================================

... (test execution) ...

================================================================================
  TEST SUMMARY
================================================================================
✅ Document Indexing (LLM + Embeddings)
✅ DRIFT Queries (Embeddings)
✅ Local Query
✅ Global Query

================================================================================
  Total: 4/4 tests passed
  🎉 All tests passed! Managed identity authentication working perfectly!
================================================================================
```

## Exit Codes
- `0`: All tests passed
- `1`: One or more tests failed

## What Each Test Validates

### Document Indexing
- **Entities Created**: Should be > 0 (typically 20-30 for 3 documents)
- **Relationships Created**: Should be > 0 (typically 15-30)
- **Communities Created**: Should be > 0 (typically 3-5)
- **Status**: 200 OK

### DRIFT Queries
- **No "Embedder not initialized" error**: Confirms embedding model working
- **Confidence Score**: Should be > 0 (typically 0.5-0.9)
- **Answer Returned**: Not "No data indexed" error
- **Status**: 200 OK

### Local/Global Queries
- **Answer Returned**: Any response (even "No relevant information")
- **Status**: 200 OK

## Troubleshooting

### Test 1 Fails: Indexing Error
**Problem**: `entities_created: 0` or 500 error  
**Cause**: LLM managed identity not working  
**Check**: 
```bash
# Verify Azure OpenAI has custom subdomain
az cognitiveservices account show \
  --name graphrag-openai-8476 \
  --resource-group rg-graphrag \
  --query "properties.endpoint"

# Should show: https://graphrag-openai-8476.openai.azure.com/
```

### Test 2 Fails: "Embedder not initialized"
**Problem**: Embedding model returns initialization error  
**Cause**: `api_key: ""` workaround not applied  
**Check**: 
```python
# In llm_service.py, verify:
embed_kwargs = {
    "api_key": "",  # Empty string required by SDK v0.3.3
    "azure_ad_token_provider": token_provider,
}
```

### Test 3/4 Fail: Query Errors
**Problem**: 500 error or timeout  
**Cause**: Neo4j connection or LLM timeout  
**Check**: Wait longer between indexing and querying (increase sleep time)

## Configuration

### Change Test Data
Edit `TEST_DOCUMENTS` in `test_managed_identity.py`:
```python
TEST_DOCUMENTS = [
    "Your document 1...",
    "Your document 2...",
]
```

### Change Test Queries
Edit `TEST_QUERIES`:
```python
TEST_QUERIES = [
    "Your question 1?",
    "Your question 2?",
]
```

### Change Base URL
Edit `BASE_URL` for different environments:
```python
BASE_URL = "http://localhost:8000"  # Local testing
# or
BASE_URL = "https://your-app.azurecontainerapps.io"  # Production
```

## Technical Notes

### Managed Identity Architecture
1. **System-Assigned Identity**: Container App has identity enabled
2. **Role Assignment**: "Cognitive Services OpenAI User" role on OpenAI resource
3. **Token Provider**: `DefaultAzureCredential` + `get_bearer_token_provider`
4. **SDK Workaround**: `api_key: ""` satisfies llama-index v0.3.3 validation

### Package Versions (Stable)
- `llama-index-core==0.12.52`
- `llama-index-llms-azure-openai==0.3.4`
- `llama-index-embeddings-azure-openai==0.3.3`

**Note**: Versions 0.14.x+ cause deployment hangs (>5 min) due to dependency conflicts.

### Known Limitations
1. **DRIFT Queries**: May return generic answers if semantic similarity is low
2. **Local Queries**: Require exact entity matches in graph
3. **Global Queries**: Need at least 2-3 documents to form communities
4. **Propagation Delay**: 2-3 seconds between indexing and querying

## Success Criteria

All tests passing means:
- ✅ No API keys stored anywhere
- ✅ LLM using managed identity (GPT-4o)
- ✅ Embeddings using managed identity (text-embedding-3-large)
- ✅ Entity extraction working (19-28 entities per test)
- ✅ Relationship creation working (16-26 relationships per test)
- ✅ DRIFT queries functional (semantic search operational)
- ✅ Community detection working (3-4 communities per test)

## Future Improvements

When llama-index SDK is fixed (v0.4.x+ properly supports managed identity):
1. Remove `api_key: ""` workaround
2. Update to latest package versions
3. Remove this note from documentation

## References

- Workaround Documentation: `MANAGED_IDENTITY_IMPLEMENTATION_COMPLETE.md`
- API Documentation: `/graphrag/v3/docs`
- SDK Issue: llama-index-embeddings-azure-openai v0.3.3 requires api_key parameter
