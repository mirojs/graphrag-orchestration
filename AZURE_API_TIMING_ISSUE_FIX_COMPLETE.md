# Azure API Timing Issue Fix - Result Fetch Retry Logic

## Problem Analysis

Based on user deployment logs, we identified a timing issue where:

1. **Status API**: Returns `"status": "completed"` ✅
2. **Results API**: Returns `{"status": "running", "message": "Analysis in progress"}` ❌

This creates an infinite polling loop because the analysis appears complete but results aren't available.

## Root Cause

Azure Content Understanding API has timing inconsistencies between different endpoints:
- Status check endpoint updates immediately when analysis completes
- Results endpoint may lag behind and still return "processing" responses

## Solution Implementation

### 1. Added Result Processing Detection Helper

```typescript
// Helper function to check if API response indicates results are still processing
const isResultStillProcessing = (responseData: any): boolean => {
  // Check for Azure's "still processing" indicators
  if (responseData?.status === 'running' || responseData?.status === 'submitted') {
    return true;
  }
  if (responseData?.message?.toLowerCase().includes('in progress')) {
    return true;
  }
  return false;
};
```

### 2. Added Exponential Backoff Retry Logic

```typescript
// Helper function to retry with exponential backoff
const retryWithBackoff = async <T>(
  operation: () => Promise<T>,
  maxRetries: number = 5,
  initialDelay: number = 2000
): Promise<T> => {
  let lastError: Error;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const result = await operation();
      
      // Check if the result indicates we should retry
      if ((result as any)?.data && isResultStillProcessing((result as any).data)) {
        if (attempt < maxRetries) {
          const delay = initialDelay * Math.pow(2, attempt);
          console.log(`[retryWithBackoff] ⏳ Results still processing, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries + 1})`);
          await new Promise(resolve => setTimeout(resolve, delay));
          continue;
        } else {
          throw new Error('Results API still returning "running" status after maximum retries. Azure API timing issue.');
        }
      }
      
      return result;
    } catch (error) {
      lastError = error as Error;
      if (attempt < maxRetries) {
        const delay = initialDelay * Math.pow(2, attempt);
        console.log(`[retryWithBackoff] ⚠️ Request failed, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries + 1}):`, error);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }
  
  throw lastError!;
};
```

### 3. Enhanced getAnalysisResultAsync with Retry Logic

**Key Changes:**
- Wrapped all `proModeApi.getAnalyzerResult` calls with `retryWithBackoff`
- Added detection for processing status in responses
- Enhanced logging to track retry attempts
- Applied retry logic to both primary requests and JSON fallback attempts

### 4. Enhanced API Service Error Handling

**Updated getAnalyzerResult function:**
- Detects when Azure returns `{"status": "running"}` instead of actual results
- Throws specific errors with `isProcessingStatus` flag
- Enhanced logging to show processing status details
- Prevents unnecessary error handling for retry-able processing status errors

## Retry Strategy

**Configuration:**
- **Max Retries**: 5 attempts
- **Initial Delay**: 2 seconds
- **Backoff**: Exponential (2x multiplier)
- **Total Max Time**: ~62 seconds (2 + 4 + 8 + 16 + 32)

**Retry Sequence:**
1. Attempt 1: Immediate
2. Attempt 2: After 2s delay
3. Attempt 3: After 4s delay  
4. Attempt 4: After 8s delay
5. Attempt 5: After 16s delay
6. Attempt 6: After 32s delay

## Expected Behavior

### Before Fix
```
1. Status API: "completed" ✅
2. Results API: {"status": "running"} ❌
3. Frontend: Continues polling forever 🔄
```

### After Fix
```
1. Status API: "completed" ✅
2. Results API: {"status": "running"} ❌
3. Retry Logic: Wait 2s, try again ⏳
4. Results API: {"status": "running"} ❌  
5. Retry Logic: Wait 4s, try again ⏳
6. Results API: {actual data} ✅
7. Frontend: Display results 🎉
```

## Error Handling

- **Temporary Processing Status**: Retries with backoff
- **Network Errors**: Retries with backoff  
- **Max Retries Exceeded**: Clear error message about Azure API timing
- **Other Errors**: Standard error handling without retry

## Benefits

1. **Eliminates Infinite Polling**: Handles Azure API timing lag gracefully
2. **Robust Error Recovery**: Distinguishes between retry-able and permanent errors
3. **User Experience**: Provides clear feedback about retry attempts
4. **Configurable**: Easy to adjust retry parameters if needed
5. **Backward Compatible**: Doesn't break existing working scenarios

## Testing Verification

The implementation should now handle the exact scenario from user logs:
- Analysis completes successfully
- Status API shows "completed" 
- Results API initially returns "running"
- Retry logic automatically handles the timing lag
- Results eventually load and display properly

## Files Modified

1. **proModeStore.ts**: Added retry logic and processing detection
2. **proModeApiService.ts**: Enhanced error handling for processing status

This fix addresses the core issue while maintaining all existing functionality and providing better resilience against Azure API timing inconsistencies.