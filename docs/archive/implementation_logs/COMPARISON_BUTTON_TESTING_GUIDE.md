# Comparison Button Issue - Testing & Debugging Guide

## Quick Test (Run in Browser Console)

1. **Open the application** in Chrome/Edge
2. **Navigate to Prediction tab** with analysis results showing comparison buttons
3. **Open DevTools Console** (F12 → Console tab)
4. **Copy and paste** the contents of `test_comparison_buttons.js` into the console
5. **Press Enter** to run the test
6. **Wait ~5 seconds** for results

The test will automatically:
- Find all comparison buttons
- Click each button sequentially
- Capture which documents are shown
- Report if all buttons show the same documents

## Manual Testing Steps

### Step 1: Verify Buttons Exist

```javascript
// Run in console:
document.querySelectorAll('button').forEach((btn, i) => {
  if (btn.textContent.trim() === 'Compare') {
    console.log(`Button ${i}:`, btn.getAttribute('data-testid'));
  }
});
```

**Expected**: You should see multiple Compare buttons with test IDs like:
- `compare-btn-FieldName-0`
- `compare-btn-FieldName-1`
- `compare-btn-FieldName-2`

### Step 2: Check Console Logs When Clicking

Click the **first comparison button** and check console for:

```
[ComparisonButton] Compare button clicked for FieldName, row 0!
[handleCompareFiles] 🔧 FIX: Processing row 0 with unique data
[handleCompareFiles] ⚠️ No pre-computed matches for row 0, using FALLBACK matching
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docA
[handleCompareFiles] 🔧 FIX: Modal state set for row 0: {
  documentA: "file1.pdf",   // ← Note this file name
  documentB: "file2.pdf",   // ← Note this file name
  rowIndex: 0
}
```

Click the **second comparison button** and check for:

```
[ComparisonButton] Compare button clicked for FieldName, row 1!
[handleCompareFiles] 🔧 FIX: Processing row 1 with unique data
[identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection for docA
[handleCompareFiles] 🔧 FIX: Modal state set for row 1: {
  documentA: "file2.pdf",   // ← Should be DIFFERENT from row 0!
  documentB: "file3.pdf",   // ← Should be DIFFERENT from row 0!
  rowIndex: 1
}
```

### Step 3: Verify Modal Props

Add this to console to track modal renders:

```javascript
// Monitor FileComparisonModal renders
const originalConsoleLog = console.log;
console.log = function(...args) {
  if (args[0] && args[0].includes('FileComparisonModal')) {
    console.warn('🔔 MODAL EVENT:', ...args);
  }
  originalConsoleLog.apply(console, args);
};
```

### Step 4: Check Redux State

```javascript
// Check what's in the Redux state
const checkReduxState = () => {
  // Access Redux DevTools
  const state = window.__REDUX_STATE__ || {};
  
  console.log('Redux Analysis State:', {
    comparisonDocuments: state.proMode?.comparisonDocuments,
    selectedInconsistency: state.proMode?.selectedInconsistency,
    showComparisonModal: state.proMode?.ui?.showComparisonModal
  });
};

// Run after clicking a button
setTimeout(checkReduxState, 100);
```

## Diagnostic Checklist

### ✅ Issue is Fixed If:

1. **Console logs show different rowIndex** for each button click (0, 1, 2, ...)
2. **documentA and documentB names are DIFFERENT** for each row
3. **Modal displays different documents** when you click different buttons
4. **identifyComparisonDocuments logs show row-specific offset** calculations

### ❌ Issue Persists If:

1. **All buttons log the same documentA and documentB names**
2. **rowIndex is always undefined or always 0**
3. **Row-specific logic is not triggered** (no "Using rowIndex-based selection" logs)
4. **Modal always shows the same document pair**

## Common Problems & Solutions

### Problem 1: rowIndex is undefined

**Check**: ComparisonButton is passing rowIndex correctly

```typescript
// In ComparisonButton.tsx - should be:
onCompare(evidenceString, fieldName, clonedItem, rowIndex);
//                                                ^^^^^^^^ Must be included!
```

**Fix**: Verify ComparisonButton.tsx line ~76 includes `rowIndex` in the onCompare call.

### Problem 2: identifyComparisonDocuments not using rowIndex

**Check**: Look for this log message:
```
[identifyComparisonDocuments] 🔧 FIX: Row X - Using rowIndex-based selection
```

If you don't see it, the condition `rowIndex !== undefined` might be failing.

**Debug**:
```javascript
// Add temporary logging in identifyComparisonDocuments
console.log('Row-specific check:', {
  hasInvoiceFile: !invoiceFile,
  hasContractFile: !contractFile,
  rowIndexDefined: rowIndex !== undefined,
  rowIndex: rowIndex,
  fileCount: allFiles.length
});
```

### Problem 3: Pre-computed matches always exist

**Check**: If you see:
```
[handleCompareFiles] ✅ Using PRE-COMPUTED document matches
```

This means `inconsistencyData._matchedDocuments` exists. Check if it's the SAME for all rows:

```javascript
// In browser console, after clicking buttons:
console.log('Pre-computed matches might be the problem!');
// Check if _matchedDocuments is being cloned properly
```

**Fix**: Ensure `_matchedDocuments` is unique per row, not shared reference.

### Problem 4: Modal not remounting

**Check**: Modal key should change for each button click

```javascript
// In PredictionTab.tsx line ~1461
key={`modal-${(analysisState.selectedInconsistency as any)?._modalId || Date.now()}`}
```

Verify `_modalId` is different for each row click.

## Expected Behavior

### With 3 Documents (A, B, C) and 3 Rows:

| Row | Button Clicked | Should Show |
|-----|---------------|-------------|
| 0   | Compare       | A vs B      |
| 1   | Compare       | B vs C      |
| 2   | Compare       | C vs A      |

### Console Log Sequence:

```
User clicks Row 0 Compare:
  [ComparisonButton] row 0 clicked
  [identifyComparisonDocuments] offset 0 → docA: file0
  [identifyComparisonDocuments] offset 1 → docB: file1
  [handleCompareFiles] Row 0: documentA=file0, documentB=file1

User clicks Row 1 Compare:
  [ComparisonButton] row 1 clicked
  [identifyComparisonDocuments] offset 1 → docA: file1
  [identifyComparisonDocuments] offset 2 → docB: file2
  [handleCompareFiles] Row 1: documentA=file1, documentB=file2  ✅ DIFFERENT!

User clicks Row 2 Compare:
  [ComparisonButton] row 2 clicked
  [identifyComparisonDocuments] offset 2 → docA: file2
  [identifyComparisonDocuments] offset 0 → docB: file0
  [handleCompareFiles] Row 2: documentA=file2, documentB=file0  ✅ DIFFERENT!
```

## Next Steps Based on Test Results

### If automated test shows ALL SAME:
1. Check console logs for rowIndex values
2. Verify row-specific strategy is being triggered
3. Check if pre-computed matches are interfering

### If automated test shows DIFFERENT:
1. ✅ Fix is working!
2. Report false alarm
3. Issue might be specific to certain data

### If automated test fails to run:
1. Manually click buttons and observe console
2. Check for JavaScript errors
3. Verify analysis results are loaded

## Files to Check

1. **PredictionTab.tsx** - Lines 693-800 (handleCompareFiles, identifyComparisonDocuments)
2. **ComparisonButton.tsx** - Line ~76 (onCompare call with rowIndex)
3. **DataTable.tsx** - Line ~123 (ComparisonButton rowIndex prop)
4. **FileComparisonModal.tsx** - Line ~114 (relevantDocuments useMemo)

## Report Format

When reporting results, include:

```
Browser: Chrome 120 / Edge 120 / Firefox 120
Test Date: [Date]
Analysis Type: [Type of analysis run]
Number of Rows: X
Number of Files: Y

Console Logs: [Paste logs]
Test Results: [All same / All different / Mixed]
Screenshots: [If applicable]
```
