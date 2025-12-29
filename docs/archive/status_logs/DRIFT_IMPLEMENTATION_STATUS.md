# DRIFT Implementation Status - December 20, 2025

## Objective
Implement MS GraphRAG's DRIFT (Dynamic Reasoning with Iterative Facts and Templates) search algorithm for invoice-contract comparison queries on the deployed GraphRAG system with Azure managed identity authentication.

## Current Status: 🔄 IN PROGRESS - JSON Response Debugging

### What Works ✅
- **Local Search**: Fully operational, returns 10 entities per query
- **Global Search**: Working with 0.85 confidence
- **Entity Embeddings**: All entities have 3072-dim embeddings (text-embedding-3-large)
- **Multi-tenant Isolation**: Group-based filtering working correctly
- **Test Data**: phase1-5docs-1766248188 has 275 entities ready for testing

### Current Problem ❌
DRIFT search fails with JSON parsing error when MS GraphRAG's primer.py tries to parse LLM response:
```
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Location**: MS GraphRAG library at `primer.py` line 143:
```python
response = await model.achat(prompt, json=True)  # Line 140-141
parsed_response = json.loads(response)  # Line 143 - FAILS HERE
```

**Root Cause**: DRIFT expects `model.achat()` to return a string of valid JSON when `json=True` is passed, but our wrapper is returning empty content or the wrong type.

## Architecture

### DRIFT LLM Wrapper Implementation
Created custom wrapper to bridge LlamaIndex LLM (supports managed identity) with MS GraphRAG ChatModel protocol:

**File**: `/afh/projects/graphrag-orchestration/graphrag-orchestration/app/v3/services/drift_adapter.py`

**Classes**:
1. **DRIFTModelResponse** (lines ~460-475)
   - Implements MS GraphRAG ModelResponse protocol
   - Properties: `output`, `parsed_response`, `history`
   - **Current Issue**: `output.content` expected by DRIFT but we return string directly

2. **DRIFTLLMWrapper** (lines ~477-500)
   - Implements MS GraphRAG ChatModel protocol
   - Methods: `achat(prompt, history, **kwargs)`, `chat(prompt, history, **kwargs)`
   - **Current Issue**: Ignores `json=True` kwarg, doesn't instruct LLM to return JSON

## Iteration History

### Attempt 1-6: LLM Configuration Errors
- Tried MS GraphRAG's LitellmChatModel → doesn't support Azure managed identity
- Created custom wrapper approach

### Attempt 7: Method Signature Issues
- Fixed: Missing `achat()` method
- Fixed: Wrong parameters (`messages: list` → `prompt: str, history: list`)
- Fixed: Wrong return type (generic object → ModelResponse protocol)

### Attempt 8: Response Structure Issues  
- Fixed: `result.answer` → `result.response` (SearchResult field name)
- **Current**: `output` property needs `.content` attribute

### Attempt 9: JSON Response Issues (CURRENT)
- DRIFT calls `model.achat(prompt, json=True)`
- Expects returned string to be valid JSON
- Our LLM returns empty or non-JSON content
- **Last Change**: Added `json=True` handling and logging (not deployed yet)

## Latest Code Change (Not Yet Deployed)

**Modified**: `DRIFTLLMWrapper.achat()` method to:
1. Detect `json=True` in kwargs
2. Append JSON instruction to prompt: `"\n\nIMPORTANT: Return ONLY valid JSON, no other text."`
3. Add fallback: if response is empty, return `'{}'`
4. Add logging to debug what LLM actually returns

**Status**: Code modified locally but deployment cancelled

## What DRIFT Actually Expects

Based on MS GraphRAG source analysis:

1. **ChatModel Protocol**:
   ```python
   async def achat(prompt: str, history: list | None, **kwargs) -> ModelResponse
   ```

2. **ModelResponse Properties**:
   - `output` - needs `.content` attribute (not just string)
   - `parsed_response` - optional
   - `history` - conversation history list

3. **JSON Mode**:
   - When `json=True` passed, LLM should return valid JSON string
   - DRIFT will parse: `json.loads(response)` where response is the content string

## Next Steps

### Immediate Fix Needed
1. **Fix `output` structure**:
   ```python
   # Instead of:
   @property
   def output(self) -> str:
       return self._output
   
   # Need:
   @property  
   def output(self):
       return type('Content', (), {'content': self._output})()
   ```

2. **Test JSON instruction handling**:
   - Deploy current changes with JSON prompting
   - Check container logs for: "DRIFT LLM Response length: X"
   - Verify LLM returns valid JSON when `json=True`

3. **Alternative if JSON fails**:
   - Use `response_format={"type": "json_object"}` in Azure OpenAI call
   - Requires modifying LlamaIndex LLM call

### Test Query
```bash
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/graphrag/v3/query/drift" \
  -H "X-Group-ID: phase1-5docs-1766248188" \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare the invoice and contract. Are there any payment or amount inconsistencies?"}'
```

### Expected Success Criteria
- ✅ No JSON parsing errors in logs
- ✅ DRIFT returns multi-step reasoning path
- ✅ Answer contains specific invoice/contract comparison
- ✅ Response time < 60 seconds

## Environment

- **Endpoint**: https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- **Test Group**: phase1-5docs-1766248188 (275 entities, 3 RAPTOR nodes)
- **Azure OpenAI**: gpt-4o with managed identity
- **Neo4j**: neo4j+s://a86dcf63.databases.neo4j.io
- **MS GraphRAG**: v0.5.0+ (DRIFT support)

## References

- **Schema**: `/afh/projects/graphrag-orchestration/docs/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json`
- **Test Script**: Would need to create for DRIFT-specific testing
- **Container Logs**: `az containerapp logs show -n graphrag-orchestration -g rg-graphrag-feature --tail 100`

## Key Learnings

1. **MS GraphRAG DRIFT is opinionated**: Expects specific ChatModel protocol, not flexible with authentication methods
2. **LiteLLM limitation**: Doesn't support Azure managed identity despite claiming Azure support
3. **Custom wrapper required**: Only way to use managed identity with DRIFT
4. **JSON mode critical**: DRIFT relies heavily on structured JSON responses from LLM
5. **Response structure matters**: DRIFT code directly accesses `response.output.content`, not just `response.output`

---
**Last Updated**: December 20, 2025 17:45 UTC
**Next Session**: Fix `output.content` structure and deploy with JSON handling
