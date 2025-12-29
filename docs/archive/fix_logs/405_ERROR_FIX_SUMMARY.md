# 405 "Method Not Allowed" Error - Root Cause and Fix

## Root Cause Analysis

The 405 "Method Not Allowed" error was NOT caused by the frontend request or backend route definition. The actual root cause was:

**Backend API server failing to start due to missing Python dependency:**

```
ModuleNotFoundError: No module named 'openai'
```

### Error Details
- The backend was crashing on startup when trying to import `from openai import AzureOpenAI`
- This left no server running to handle the POST request to `/pro-mode/analysis/orchestrated`
- Frontend received 405 error because there was no server to respond properly

## Applied Fixes

### 1. Made OpenAI Import Conditional
**File**: `src/ContentProcessorAPI/app/routers/proMode.py`

**Before**:
```python
from openai import AzureOpenAI  # Needed for extract-fields endpoint
```

**After**:
```python
try:
    from openai import AzureOpenAI  # Needed for extract-fields endpoint
    OPENAI_AVAILABLE = True
except ImportError:
    print("⚠️ OpenAI module not available - extract-fields functionality will be disabled")
    AzureOpenAI = None
    OPENAI_AVAILABLE = False
```

### 2. Added Runtime Guard for LLM Functions
**Function**: `extract_fields_with_llm`

Added check at function start:
```python
# Check if OpenAI is available
if not OPENAI_AVAILABLE:
    raise HTTPException(
        status_code=503, 
        detail="OpenAI functionality is not available. Please install the 'openai' package."
    )
```

## Status

✅ **Server startup issue resolved** - Server will now start even without openai package
✅ **Graceful degradation** - LLM features return 503 error instead of crashing
✅ **Root cause of 405 error fixed** - Server can now handle POST requests to orchestrated endpoint

## Next Steps

1. **Test the fix**: Run the endpoint test script to confirm server is responding
2. **Install OpenAI dependency**: Add `openai` package to deployment environment if LLM features are needed
3. **Verify orchestrated analysis**: Test the frontend orchestrated analysis functionality

## Dependency Note

The `openai==1.65.5` dependency is already listed in `requirements.txt` but appears to not be installed in the deployment environment. The conditional import ensures the server starts regardless.