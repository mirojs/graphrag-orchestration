# DRIFT Implementation Progress - December 21, 2025

## Problem
DRIFT search fails with `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` when MS GraphRAG's primer.py tries to parse LLM response at line 143:
```python
parsed_response = json.loads(response)
```

## Root Cause Analysis
MS GraphRAG's DRIFT expects `achat()` to return a value that can be passed directly to `json.loads()`. The value must be:
1. **Usable as a string** by `json.loads()`
2. **Have ModelResponse properties** (output, parsed_response, history)
3. **The output property must have a content attribute**

## Fixes Applied

### Fix 1: Added `output.content` structure
Created `DRIFTModelOutput` class with `content` attribute so `response.output.content` works.

### Fix 2: Made `DRIFTModelResponse` inherit from `str`
Changed from regular class to `str` subclass so `json.loads(response)` works directly:
```python
class DRIFTModelResponse(str):
    def __new__(cls, text: str, raw_response=None):
        instance = str.__new__(cls, text)
        return instance
```

### Fix 3: Added JSON mode instruction
When `json=True` is passed, append instruction to prompt:
```python
if json_mode and 'json' not in prompt.lower():
    prompt = f"{prompt}\n\nIMPORTANT: Return ONLY valid JSON, no other text."
```

### Fix 4: Removed fallback
Removed the `'{}'` fallback for empty responses to force proper LLM responses.

### Fix 5: Added debug logging
Added print() statements to track LLM responses (logger.info wasn't appearing in logs).

## Current Status
- Code changes completed and deployed (revision 33 in progress)
- Waiting for deployment to complete to test
- Need to verify LLM is actually returning JSON content

## Next Steps
1. Wait for deployment to complete
2. Test DRIFT endpoint
3. Check logs for debug output to see what LLM returns
4. If still empty response, investigate LLM configuration or prompt issues

## Test Command
```bash
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/graphrag/v3/query/drift" \
  -H "X-Group-ID: phase1-5docs-1766248188" \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare the invoice and contract. Are there any payment or amount inconsistencies?"}'
```

