# API Version Restored: 2025-05-01-preview

## Changes Made

### ✅ 1. Default API Version Restored
- **File**: `content_understanding.py`
- **Line**: 28
- **Change**: Restored default API version to `"2025-05-01-preview"`

### ✅ 2. URL Patterns Standardized
- **File**: `content_understanding.py`
- **Lines**: 46-49
- **Change**: Updated all URL methods to use consistent `/content-analyzers/` pattern
  - `_get_analyzer_url()`: Now uses `/content-analyzers/{analyzer_id}:analyze`
  - `_get_analyzer_list_url()`: Now uses `/content-analyzers`
  - `_get_analyze_url()`: Already used correct pattern

### ✅ 3. Enhanced Debugging
- **File**: `content_understanding.py`
- **Lines**: 290-295
- **Change**: Added URL logging in `begin_analyze_stream()` method for better debugging

## Current API Configuration

```python
# Default API version
api_version = "2025-05-01-preview"

# URL patterns for 2025-05-01-preview
list_url = "{endpoint}/content-analyzers?api-version=2025-05-01-preview"
analyze_url = "{endpoint}/content-analyzers/{analyzer_id}:analyze?api-version=2025-05-01-preview"
```

## Troubleshooting the 404 Error

The 404 error might be caused by:

1. **Analyzer Name**: `prebuilt-layout` might not exist in 2025-05-01-preview
2. **Endpoint Configuration**: Check if the endpoint supports the new API version
3. **Authentication**: Verify credentials have access to the new API version

## Next Steps

1. **Test with Different Analyzer**: Try with other analyzers like `prebuilt-read`
2. **Check Available Analyzers**: Call the list analyzers endpoint to see what's available
3. **Verify Endpoint**: Confirm the Azure resource supports 2025-05-01-preview
4. **Authentication**: Ensure the credentials have proper permissions

## URLs Being Generated

Based on the error log, the system is now correctly generating:
```
https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com/content-analyzers/prebuilt-layout:analyze?api-version=2025-05-01-preview
```

This URL format is correct for the 2025-05-01-preview API version.
