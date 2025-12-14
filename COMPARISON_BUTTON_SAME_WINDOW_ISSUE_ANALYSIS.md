# Comparison Buttons Showing Same Window - Root Cause Analysis

## Date: October 11, 2025

## Problem
All comparison buttons under the Prediction tab are opening the same comparison window with the same documents, regardless of which row's button was clicked.

## Root Cause Analysis

### Issue Location
**File**: `PredictionTab.tsx`  
**Function**: `handleCompareFiles()` (lines 694-780)

### The Problem

When a comparison button is clicked:

1. ✅ Each button correctly calls `handleCompareFiles` with **unique** `inconsistencyData` and `rowIndex`
2. ✅ The function correctly **clones** the inconsistency data to prevent reference sharing
3. ✅ A **unique modal ID** is generated: `${fieldName}-${rowIndex}-${Date.now()}`
4. ❌ **BUT**: The `identifyComparisonDocuments()` function returns **THE SAME DOCUMENTS** for all rows

### Why Same Documents Are Returned

The issue is in the `identifyComparisonDocuments()` function (lines 783-???). This function:

1. Receives the evidence string and inconsistency data
2. Attempts to match documents based on content
3. **Returns the SAME pair of documents** for all rows because:
   - It's searching across ALL files (`selectedInputFiles` + `selectedReferenceFiles`)
   - The matching logic finds the same two documents every time
   - The pre-computed matches (`inconsistencyData._matchedDocuments`) may not exist or may be the same for all rows

### Code Flow

```typescript
// Line 694: handleCompareFiles is called with unique data
const handleCompareFiles = (evidence: string, fieldName: string, inconsistencyData: any, rowIndex?: number) => {
  // ... unique data logged here ✅
  
  // Line 713-723: Check for pre-computed matches
  if (inconsistencyData?._matchedDocuments) {
    // ✅ Uses pre-computed match if available
    const matched = inconsistencyData._matchedDocuments;
    specificDocuments = {
      documentA: matched.documentA,
      documentB: matched.documentB,
      // ...
    };
  } else {
    // ❌ PROBLEM: Falls back to identifyComparisonDocuments
    console.log('[handleCompareFiles] ⚠️ No pre-computed matches, using FALLBACK matching (50-500ms delay)');
    specificDocuments = identifyComparisonDocuments(evidence, fieldName, inconsistencyData, rowIndex);
  }
  
  // Line 765-768: Sets state with the documents
  updateAnalysisState({ 
    selectedInconsistency: clonedInconsistency,
    selectedFieldName: fieldName,
    comparisonDocuments: specificDocuments // ❌ SAME DOCUMENTS for all rows!
  });
}
```

### Verification

Check the console logs:
- Look for `[handleCompareFiles] ✅ Using PRE-COMPUTED document matches` vs
- Look for `[handleCompareFiles] ⚠️ No pre-computed matches, using FALLBACK matching`

If you see the fallback message, that's the problem!

## Solution Options

### Option 1: Fix Pre-Computed Matches (RECOMMENDED)
Ensure that `_matchedDocuments` is properly set for each row during result processing.

**Location**: Where analysis results are enhanced with document matches  
**File**: `PredictionTab.tsx` around line 348-365

```typescript
// Line 348-365: Should be pre-computing matches
const enhancedPayload = enhanceAnalysisResultsWithDocumentMatches(
  resultAction.payload,
  allFiles
);
```

**Check**: Is `enhanceAnalysisResultsWithDocumentMatches` properly adding `_matchedDocuments` to each inconsistency item?

### Option 2: Fix identifyComparisonDocuments Function
Update the fallback matching to use row-specific data properly.

**Location**: `identifyComparisonDocuments()` function in `PredictionTab.tsx`

The function needs to:
1. Extract row-specific values from the inconsistency data
2. Match documents based on those SPECIFIC values
3. Not return the same documents for every row

### Option 3: Force Unique Document Selection
Add logic to select different document pairs based on rowIndex or field-specific criteria.

## Debugging Steps

### Step 1: Check Console Logs
When clicking different comparison buttons, check:

```javascript
// Should see DIFFERENT values for each button:
[handleCompareFiles] 🔧 FIX: Processing row {0, 1, 2, ...} with unique data
[handleCompareFiles] 📊 Match quality: {
  documentA: "different_for_each_row.pdf",  // ← Should be different!
  documentB: "different_for_each_row_2.pdf" // ← Should be different!
}
```

### Step 2: Check if Pre-Computed Matches Exist
Add debug logging:

```typescript
console.log('[Debug] Row inconsistency data:', {
  row: rowIndex,
  hasPreComputed: !!inconsistencyData?._matchedDocuments,
  matchedDocs: inconsistencyData?._matchedDocuments
});
```

### Step 3: Verify enhanceAnalysisResultsWithDocumentMatches
Check if this function is:
1. Being called
2. Properly adding `_matchedDocuments` to each row
3. Using unique matching logic per row

## Expected Behavior

Each comparison button should:
1. Extract evidence specific to **that row**
2. Identify documents specific to **that row's data**
3. Open a modal showing **those specific documents**
4. NOT reuse the same document pair for all rows

## Quick Fix (Temporary)

If you need a quick workaround, you can disable the memo and force fresh calculation:

```typescript
// In FileComparisonModal.tsx, line 114
const relevantDocuments = useMemo(() => {
  // Add inconsistencyData to dependencies to force recalculation
  // ...
}, [documentA, documentB, comparisonType, inputFiles, referenceFiles, 
    selectedInputFileIds, selectedReferenceFileIds, 
    inconsistencyData]); // ← Add this!
```

But this doesn't solve the root cause - you still need to fix the document identification logic.

## Related Files

1. **PredictionTab.tsx**
   - `handleCompareFiles()` - Sets up modal data
   - `identifyComparisonDocuments()` - Identifies which documents to compare
   - `enhanceAnalysisResultsWithDocumentMatches()` - Pre-computes matches

2. **FileComparisonModal.tsx**
   - `relevantDocuments` useMemo - Determines which documents to display
   - useEffect with `[isOpen, relevantDocuments]` - Loads documents

3. **DataTable.tsx** & **ComparisonButton.tsx**
   - Properly pass row-specific data ✅ (These are working correctly)

## Next Steps

1. ✅ Verify pre-computed matches are being generated
2. ✅ Check if `_matchedDocuments` exists in inconsistency data
3. ✅ Fix `identifyComparisonDocuments` to return unique documents per row
4. ✅ Ensure `enhanceAnalysisResultsWithDocumentMatches` works correctly
5. ✅ Test with multiple rows to verify different documents are shown
