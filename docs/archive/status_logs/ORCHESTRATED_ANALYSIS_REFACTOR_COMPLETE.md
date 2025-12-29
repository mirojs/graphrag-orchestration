# Orchestrated Analysis Updated to Use Internal Extract-Schema Endpoints

## Summary of Changes

Updated the `/pro-mode/analysis/orchestrated` endpoint to use the dedicated `/pro-mode/extract-schema/` endpoints instead of calling Azure Content Understanding APIs directly.

## Changes Made

### ✅ **Backend Orchestrated Analysis Refactored**
**File**: `src/ContentProcessorAPI/app/routers/proMode.py`

**Before**: Direct Azure Content Understanding API calls (PUT → POST → GET)
```python
# Old approach - Direct Azure API calls
put_url = f"{azure_endpoint}/contentunderstanding/analyzers/{request.analyzer_id}"
post_url = f"{azure_endpoint}/contentunderstanding/analyzers/{request.analyzer_id}:analyze"
# ... direct httpx calls to Azure
```

**After**: Internal extract-schema endpoint calls
```python
# New approach - Using internal tested endpoints
# Step 1: Create analyzer using internal PUT endpoint
create_response = await create_schema_analyzer(
    analyzer_id=request.analyzer_id,
    request=schema_creation_request,
    app_config=app_config
)

# Step 2: Start analysis using internal POST endpoint  
analyze_response = await start_schema_analysis(
    analyzer_id=request.analyzer_id,
    request=analyze_request,
    app_config=app_config
)

# Step 3: Poll for results using internal GET endpoint
result_response = await get_schema_results(
    operation_id=operation_id,
    app_config=app_config
)
```

## Benefits

### 🎯 **Leverages Proven Endpoints**
- Uses the dedicated `/pro-mode/extract-schema/` endpoints that follow `schema_structure_extractor.py` patterns
- No OpenAI dependencies or calls
- Pure Azure Content Understanding API approach

### 🔧 **Better Maintainability**
- Single point of truth for schema extraction logic
- Reuses tested and working endpoint implementations
- Consistent error handling and logging

### 🚀 **Improved Reliability**
- Leverages existing authentication and credential handling
- Uses proven request/response models (`SchemaExtractionRequest`, `AnalyzeRequest`)
- Follows established timeout and polling patterns

## Endpoint Flow

1. **PUT** `/pro-mode/extract-schema/{analyzer_id}` - Create schema extraction analyzer
2. **POST** `/pro-mode/extract-schema/{analyzer_id}:analyze` - Start schema extraction analysis  
3. **GET** `/pro-mode/extract-schema/results/{operation_id}` - Get schema extraction results

## Status

✅ **405 Error Root Cause Fixed** - Server startup issue resolved with conditional OpenAI import
✅ **Orchestrated Analysis Refactored** - Now uses internal extract-schema endpoints
✅ **Clean Architecture** - No direct Azure API calls in orchestrated endpoint
✅ **OpenAI Dependencies Restored** - Kept for compatibility but not used in main analysis flow

## Testing

The orchestrated analysis endpoint now:
- Uses your proven `/pro-mode/extract-schema/` pattern
- Follows the successful `schema_structure_extractor.py` approach
- Leverages only Azure Content Understanding APIs (no OpenAI)
- Provides the same orchestrated experience with better reliability