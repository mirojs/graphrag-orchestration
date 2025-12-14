# Azure Analyzer Timeout Solution

## Issue Analysis
The analyzer `analyzer-1756229281282-14qqgm6ic` is stuck in "creating" status and failed to become ready within the 60-second timeout period (30 attempts × 2 seconds).

## Root Causes
1. **Azure Provisioning Delay**: Custom analyzers can take 2-5+ minutes to create, especially with reference documents
2. **Insufficient Timeout**: Current 60-second timeout is too short for complex analyzers
3. **Resource Constraints**: Azure region might be under heavy load

## Solutions

### Immediate Fix 1: Increase Timeout (Recommended)
Extend the timeout period to accommodate Azure's analyzer creation time:

```python
# Current: 30 retries × 2 seconds = 60 seconds
max_retries = 30  
retry_delay = 2

# Recommended: 60 retries × 3 seconds = 180 seconds (3 minutes)
max_retries = 60
retry_delay = 3
```

### Immediate Fix 2: Progressive Backoff
Implement progressive delay to reduce API pressure:

```python
# Start with shorter delays, increase over time
base_delay = 2
max_delay = 10
retry_delay = min(base_delay * (1.2 ** attempt), max_delay)
```

### Long-term Solution: Async Operation Tracking
Use Azure's operation-location header for proper async tracking:

```python
# Track via operation-location instead of direct status
operation_location = creation_response.headers.get('operation-location')
if operation_location:
    result = await track_analyzer_operation(operation_location, headers)
```

## Implementation Steps

### Step 1: Quick Fix (Deploy Immediately)
Update timeout values in `proMode.py`:

**File**: `/src/ContentProcessorAPI/app/routers/proMode.py`
**Line**: ~3769

```python
# Change from:
max_retries = 30  # 60 seconds
retry_delay = 2

# Change to:
max_retries = 90  # 180 seconds (3 minutes)
retry_delay = 2
```

### Step 2: Enhanced Logging
Add more detailed logging to understand delay patterns:

```python
print(f"[AnalyzeContent] ⏳ Analyzer creation time: {(attempt + 1) * retry_delay} seconds")
print(f"[AnalyzeContent] 📊 Status details: {status_data}")
```

### Step 3: Fallback Strategy
If timeout occurs, suggest alternative approaches:

```python
if timeout_reached:
    error_message = f"""
    Analyzer creation is taking longer than expected ({max_retries * retry_delay} seconds).
    
    Possible solutions:
    1. Wait and try again in 5-10 minutes
    2. Use prebuilt analyzer (faster): 'prebuilt-documentAnalyzer'
    3. Reduce reference document count
    4. Try a different Azure region
    """
```

## Expected Results

### Before Fix
- ❌ Timeout after 60 seconds
- ❌ Analysis fails with 408 error
- ❌ Poor user experience

### After Fix  
- ✅ Successful analysis completion
- ✅ Proper timeout handling (3+ minutes)
- ✅ Better error messages
- ✅ Improved reliability

## Risk Assessment
- **Risk Level**: Very Low
- **Impact**: Positive only (fixes broken functionality)
- **Rollback**: Simple parameter change if needed

## Testing Instructions
1. Deploy the timeout increase
2. Create a new analyzer with reference documents
3. Verify analysis completes within 3 minutes
4. Test with different document types and sizes

## Monitoring
Watch for these log patterns:
- `✅ Analyzer {id} is ready! Status: ready` (success)
- `⏳ Analyzer creation time: X seconds` (progress)
- `❌ Timeout: Analyzer did not become ready` (if still occurring)

## Next Steps
1. **Immediate**: Deploy timeout increase
2. **Short-term**: Add operation tracking support
3. **Long-term**: Implement WebSocket status updates for real-time UI feedback
