# 405 "Method Not Allowed" Error Fix for Orchestrated Start Analysis

## Problem Analysis

The frontend is receiving a **405 "Method Not Allowed"** error when calling the `/pro-mode/analysis/orchestrated` endpoint with a POST request. This indicates that:

1. The server is responding (not a 404 or connection error)
2. The endpoint exists but doesn't accept the POST method
3. There might be a routing conflict or configuration issue

## Root Cause Investigation

Based on the codebase analysis, the following potential causes have been identified:

### 1. **Route Definition Mismatch**
The backend route is correctly defined as:
```python
@router.post("/pro-mode/analysis/orchestrated", summary="Orchestrated Start Analysis")
```

But there might be a routing conflict or the route isn't being registered properly.

### 2. **Server Configuration Issues**
- Wrong server instance running (mock vs. production)
- CORS preflight issues
- Middleware interference

### 3. **Request Model Validation**
The request might be failing validation before reaching the endpoint handler.

## Comprehensive Fix Strategy

### Fix 1: Verify and Update Backend Route Registration

Ensure the route is properly registered and doesn't conflict with other routes.

#### Backend Update (proMode.py)

```python
# Add debug logging to verify route registration
import logging
logger = logging.getLogger(__name__)

# Before the route definition, add logging
logger.info("Registering orchestrated start analysis endpoint")

@router.post("/pro-mode/analysis/orchestrated", 
             summary="Orchestrated Start Analysis", 
             response_model=StartAnalysisResponse,
             status_code=200)
async def orchestrated_start_analysis(
    request: StartAnalysisRequest,
    app_config: AppConfiguration = Depends(get_app_config)
):
    """
    Orchestrated start analysis endpoint - handles PUT → POST → GET flow internally
    """
    logger.info(f"Received orchestrated start analysis request for analyzer: {request.analyzer_id}")
    
    try:
        # ... existing implementation
    except Exception as e:
        logger.error(f"Error in orchestrated start analysis: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
```

### Fix 2: Add CORS Debugging and OPTIONS Handler

Add explicit CORS handling for the specific endpoint:

```python
# Add OPTIONS handler specifically for this endpoint
@router.options("/pro-mode/analysis/orchestrated")
async def orchestrated_analysis_options():
    """Handle CORS preflight for orchestrated analysis endpoint"""
    from fastapi.responses import Response
    
    response = Response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "86400"
    
    return response
```

### Fix 3: Update Frontend Error Handling

Add better error handling and debugging in the frontend service:

#### Frontend Update (proModeApiService.ts)

```typescript
export const startAnalysisOrchestrated = async (request: StartAnalysisOrchestratedRequest): Promise<StartAnalysisOrchestratedResponse> => {
  try {
    console.log('[startAnalysisOrchestrated] Starting orchestrated analysis with:', {
      analyzerId: request.analyzerId,
      schemaId: request.schemaId,
      inputFileCount: request.inputFileIds.length,
      referenceFileCount: request.referenceFileIds?.length || 0,
      endpoint: '/pro-mode/analysis/orchestrated',
      method: 'POST'
    });
    
    // Test endpoint availability first
    try {
      const optionsResponse = await httpUtility.options('/pro-mode/analysis/orchestrated');
      console.log('[startAnalysisOrchestrated] OPTIONS check passed:', optionsResponse);
    } catch (optionsError) {
      console.warn('[startAnalysisOrchestrated] OPTIONS check failed:', optionsError);
    }
    
    const response = await httpUtility.post('/pro-mode/analysis/orchestrated', {
      analyzer_id: request.analyzerId,
      schema_id: request.schemaId,
      schema_data: request.schemaData,
      input_file_ids: request.inputFileIds,
      reference_file_ids: request.referenceFileIds || [],
      blob_url: request.blobUrl,
      model_id: request.modelId,
      api_version: request.apiVersion || '2025-05-01-preview',
      configuration: request.configuration || { mode: 'pro' },
      pages: request.pages,
      locale: request.locale || 'en-US',
      output_format: request.outputFormat || 'json',
      include_text_details: request.includeTextDetails ?? true
    });
    
    // ... rest of implementation
    
  } catch (error: any) {
    console.error('[startAnalysisOrchestrated] Detailed error analysis:', {
      status: error?.status,
      statusText: error?.statusText,
      message: error?.message,
      data: error?.data,
      endpoint: '/pro-mode/analysis/orchestrated',
      method: 'POST',
      timestamp: new Date().toISOString()
    });
    
    // Enhanced error handling for 405
    if (error?.status === 405) {
      console.error('[startAnalysisOrchestrated] 405 Method Not Allowed - Possible causes:', {
        cause1: 'Endpoint does not accept POST method',
        cause2: 'Route conflict with other endpoints',
        cause3: 'Server configuration issue',
        cause4: 'CORS preflight failure',
        suggestion: 'Check backend route definition and server deployment'
      });
    }
    
    return {
      success: false,
      status: 'failed',
      analyzerId: request.analyzerId,
      message: error.message || 'Orchestrated analysis failed',
      errorDetails: error.response?.data?.detail || error.message
    };
  }
};
```

### Fix 4: Add httpUtility.options Method

If the options method doesn't exist in httpUtility:

```typescript
// In httpUtility.ts, add to the export object:
export default {
  // ... existing methods
  options: <T>(url: string): Promise<{ data: T | null; status: number }> => 
    fetchWithAuth<T>(url, 'OPTIONS', null),
  // ... rest of methods
};
```

## Immediate Action Plan

1. **Check Server Status**: Verify which server instance is running
2. **Update Backend**: Add the CORS OPTIONS handler and logging
3. **Update Frontend**: Add enhanced error handling and debugging
4. **Test Endpoint**: Use the test script to verify functionality
5. **Deploy Changes**: Ensure the updated code is deployed

## Alternative Workaround

If the issue persists, temporarily modify the frontend to use a different HTTP method or endpoint path to isolate the routing issue:

```typescript
// Temporary workaround - try different endpoint path
const response = await httpUtility.post('/pro-mode/analysis-orchestrated', payload);
// or
const response = await httpUtility.post('/pro-mode/start-analysis/orchestrated', payload);
```

Then update the backend route accordingly to match.

## Verification Steps

1. Check browser network tab for exact request details
2. Verify server logs for route registration
3. Test with curl/Postman to isolate frontend issues
4. Check CORS preflight requests in browser
5. Validate request payload against backend model

This comprehensive approach should resolve the 405 error by addressing all potential causes systematically.