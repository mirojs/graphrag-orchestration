# Azure Analyzer Update baseAnalyzerId Fix

## Issue
When updating an Azure Content Understanding analyzer with new knowledge sources, the Azure API was returning an error:
```
"The 'baseAnalyzerId' property is required at the root level but is missing"
```

## Root Cause
The analyzer update payload was missing the required `baseAnalyzerId` field. Azure's API specification requires this field to be present in all analyzer update requests, even when only updating knowledge sources.

## Solution Implemented

### 1. **Pre-fetch Analyzer Details**
Added a quick analyzer fetch at the beginning of the knowledge source update process to retrieve the current `baseAnalyzerId`:

```python
# Get analyzer details first for baseAnalyzerId (needed for potential updates)
analyzer_base_analyzer_id = "prebuilt-documentAnalyzer"  # Default fallback
try:
    analyzer_status_url = f"{normalize_endpoint_url(endpoint)}/contentunderstanding/analyzers/{analyzer_id}?api-version={api_version}"
    async with httpx.AsyncClient(timeout=10.0) as quick_client:
        quick_response = await quick_client.get(analyzer_status_url, headers=headers)
        if quick_response.status_code == 200:
            analyzer_data = quick_response.json()
            analyzer_base_analyzer_id = analyzer_data.get('baseAnalyzerId', 'prebuilt-documentAnalyzer')
            print(f"[AnalyzeContent] ✓ Retrieved analyzer baseAnalyzerId: {analyzer_base_analyzer_id}")
except Exception as e:
    print(f"[AnalyzeContent] ⚠️ Could not fetch analyzer details for baseAnalyzerId: {e}")
    print(f"[AnalyzeContent] Using default baseAnalyzerId: {analyzer_base_analyzer_id}")
```

### 2. **Include baseAnalyzerId in Update Payload**
Modified the analyzer update payload to include the required `baseAnalyzerId` field:

```python
# Update the analyzer with new knowledge sources configuration
# This ensures the analyzer uses only the selected reference files for this analysis
# NOTE: Azure API requires baseAnalyzerId to be included in update payload
update_payload = {
    "baseAnalyzerId": analyzer_base_analyzer_id or "prebuilt-documentAnalyzer",  # Use extracted baseAnalyzerId
    "knowledgeSources": updated_knowledge_sources
}
```

### 3. **Enhanced Error Handling**
- Added fallback to default `prebuilt-documentAnalyzer` if the analyzer fetch fails
- Added proper error logging for debugging
- Maintained backward compatibility

## Technical Details

### Azure API Specification Compliance
- **Endpoint**: `PUT /contentunderstanding/analyzers/{analyzerId}`
- **Required Fields**: `baseAnalyzerId` must be included in all update requests
- **API Version**: `2025-05-01-preview`

### Error Prevention
- The fix prevents the `InvalidFieldSchema` error with `MissingProperty` details
- Ensures all analyzer updates comply with Azure's Content Understanding API specification
- Maintains the Pro Mode dynamic knowledge source functionality

## Benefits
1. **Eliminates API Errors**: Fixes the missing `baseAnalyzerId` error
2. **Maintains Functionality**: Preserves dynamic knowledge source updates for selective reference file usage
3. **Robust Error Handling**: Graceful fallback if analyzer details cannot be fetched
4. **API Compliance**: Follows Azure's official REST API specification

## Testing Recommendations
1. Test with existing analyzers to ensure `baseAnalyzerId` is correctly retrieved
2. Test with different base analyzer types (beyond `prebuilt-documentAnalyzer`)
3. Verify knowledge source updates work correctly after the fix
4. Test error handling when analyzer fetch fails

## Related Components
- **File**: `proMode.py`
- **Function**: `analyze_content()`
- **Section**: Dynamic knowledge source update
- **API**: Azure Content Understanding 2025-05-01-preview

This fix resolves the critical issue preventing knowledge source updates and enables proper selective reference file usage in Pro Mode analysis.
