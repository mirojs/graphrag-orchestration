# Comparison Button Fix - Evidence String Extraction

## Issue
The comparison button under the Prediction tab was throwing an error: `TypeError: e.trim is not a function. (In 'e.trim()', 'e.trim' is undefined)`

## Root Cause
The evidence data structure in the analysis results has this format:
```javascript
Evidence: {
  type: "string", 
  valueString: "The invoice states 'Due on contract signing'..."
}
```

However, the code was trying to pass the entire evidence object instead of extracting the actual string value, causing the `trim()` function to fail since it was being called on an object rather than a string.

## Solution Applied
Updated the comparison button click handler in `PredictionTab.tsx` to properly extract the string value from the evidence object:

### Before:
```tsx
handleCompareFiles(item.valueObject?.Evidence || '', fieldName, item.valueObject);
```

### After:
```tsx
const evidenceString = item.valueObject?.Evidence?.valueString || item.valueObject?.Evidence || '';
handleCompareFiles(evidenceString, fieldName, item.valueObject);
```

## Fix Details
The solution includes:
1. **Proper value extraction**: First tries to get `Evidence.valueString` (the actual text content)
2. **Fallback handling**: Falls back to `Evidence` directly if `valueString` is not available
3. **Safety check**: Defaults to empty string if neither is available
4. **Type safety**: Ensures a string is always passed to `handleCompareFiles`

## Expected Behavior
Now when clicking the comparison button:
1. ✅ **No more errors**: The `trim()` function will work correctly on the string value
2. ✅ **Modal opens**: The FileComparisonModal should open with the evidence text
3. ✅ **File comparison**: The modal will attempt to parse the evidence and show side-by-side file comparison

## Files Modified
- `/src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`

The comparison button should now work correctly and open the file comparison modal as intended.
