# 404 Error Troubleshooting Analysis and Fixes

## 🔍 Root Cause Analysis

Based on the error:
```
404 Client Error: Resource Not Found for url: 
https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com/content-analyzers/prebuilt-layout:analyze?api-version=2025-05-01-preview
```

## 🎯 Most Likely Causes:

### 1. **API Version Issue** (High Probability)
- `2025-05-01-preview` might not be available yet
- Azure API preview versions have specific release schedules

### 2. **Analyzer Name Change** (Medium Probability)  
- `prebuilt-layout` might have a different name in 2025-05-01-preview
- Common variations: `layout`, `document-layout`, `prebuilt-document`

### 3. **URL Pattern Change** (Medium Probability)
- URL structure might be different from expected
- Need to verify correct endpoint pattern

## 🔧 Immediate Fixes to Try:

### Fix 1: Revert to Working API Version
```python
# In content_understanding.py, line 28
api_version: str = "2024-12-01-preview"  # Known working version
```

### Fix 2: Try Different Analyzer Names
Test these analyzer variations:
- `prebuilt-read` (most likely to work)
- `layout` 
- `prebuilt-document`
- `document`

### Fix 3: Test Basic Connectivity
Add this method to test what's actually available:
```python
def debug_available_analyzers(self):
    try:
        response = requests.get(
            f"{self._endpoint}/content-analyzers?api-version={self._api_version}",
            headers=self._headers
        )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"List failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Debug failed: {e}")
```

## 🚀 Quick Resolution Steps:

1. **Temporary Fix**: Change API version to `2024-12-01-preview`
2. **Test Analyzer**: Try `prebuilt-read` instead of `prebuilt-layout`
3. **Verify Endpoint**: Confirm the Azure resource supports preview versions
4. **Check Documentation**: Verify the exact API specification

## 📋 Code Changes Needed:

### Option A: Revert to Stable API
```python
# Change default API version (safest option)
api_version: str = "2024-12-01-preview"

# Use stable URL pattern
def _get_analyze_url(self, endpoint, api_version, analyzer_id):
    return f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze?api-version={api_version}"
```

### Option B: Keep 2025-05-01-preview but use different analyzer
```python
# Try these analyzers in order:
test_analyzers = ["prebuilt-read", "layout", "prebuilt-document", "prebuilt-layout"]
```

## 🎯 Most Likely Solution:
The `2025-05-01-preview` API version probably doesn't exist yet. Revert to `2024-12-01-preview` until the new version is officially released.
