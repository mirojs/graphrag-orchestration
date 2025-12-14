# Testing the Comparison Button Fix

## Problem
All comparison buttons are showing the same documents when clicked.

## Testing Options

### Option 1: Browser Console Test (EASIEST) ⭐

1. Open your application in the browser
2. Navigate to the Prediction tab with results showing
3. Press **F12** to open DevTools Console
4. Copy the entire contents of `test_comparison_buttons.js`
5. Paste into console and press Enter
6. Wait 5 seconds for automatic test results

**What to expect**:
```
✅ SUCCESS: Buttons show DIFFERENT documents!
   Button 0: ["invoice1.pdf", "contract1.pdf"]
   Button 1: ["contract1.pdf", "purchase.pdf"]
   Button 2: ["purchase.pdf", "invoice1.pdf"]
```

OR

```
❌ ISSUE CONFIRMED: All buttons show the SAME documents!
   Documents shown by all buttons: ["invoice1.pdf", "contract1.pdf"]
```

### Option 2: Manual Console Observation

1. Open DevTools Console (F12)
2. Click the **first** Compare button
3. Look for these logs:
   ```
   [handleCompareFiles] 🔧 FIX: Processing row 0
   [identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection
   [handleCompareFiles] 🔧 FIX: Modal state set for row 0: {
     documentA: "file1.pdf",
     documentB: "file2.pdf",
     rowIndex: 0
   }
   ```

4. Click the **second** Compare button
5. Look for these logs:
   ```
   [handleCompareFiles] 🔧 FIX: Processing row 1
   [identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection
   [handleCompareFiles] 🔧 FIX: Modal state set for row 1: {
     documentA: "file2.pdf",   ← Should be DIFFERENT!
     documentB: "file3.pdf",   ← Should be DIFFERENT!
     rowIndex: 1
   }
   ```

**✅ Working if**: documentA and documentB are **different** for each row  
**❌ Not working if**: All rows show **same** documentA and documentB

### Option 3: Visual Inspection

1. Note the documents shown when clicking first Compare button
2. Close the modal
3. Click second Compare button
4. **Compare**: Are the documents the same or different?

**Expected**: Each button should show a different pair of documents

### Option 4: Code-Level Test

Add the code from `inline_test_comparison_logic.js` to PredictionTab.tsx temporarily:

1. Open `PredictionTab.tsx`
2. Find the `identifyComparisonDocuments` function (around line 950)
3. Paste the test code right after the function closing brace `}`
4. Save the file
5. Refresh the browser
6. Check console for test results

The test will run automatically and show:
```
🧪 TESTING identifyComparisonDocuments Row-Specific Logic
Row 0: invoice1.pdf vs contract1.pdf
Row 1: contract1.pdf vs purchase_order.pdf
Row 2: purchase_order.pdf vs invoice1.pdf
✅ SUCCESS: All rows show DIFFERENT document pairs!
```

## Troubleshooting

### Issue: No console logs appear

**Cause**: ComparisonButton might not be calling onCompare with rowIndex

**Fix**: Check `ComparisonButton.tsx` line ~76:
```typescript
onCompare(evidenceString, fieldName, clonedItem, rowIndex);  // ← rowIndex must be included
```

### Issue: rowIndex is always undefined

**Cause**: DataTable not passing rowIndex to ComparisonButton

**Fix**: Check `DataTable.tsx` around line 123:
```typescript
<ComparisonButton
  key={buttonKey}
  fieldName={fieldName}
  item={item}
  rowIndex={rowIndex}   // ← Must be passed
  onCompare={onCompare}
/>
```

### Issue: Row-specific logic not triggered

**Symptoms**: No logs saying "Using rowIndex-based selection"

**Debug**: Add this temporary logging in `identifyComparisonDocuments`:
```typescript
console.log('🔍 Row-specific check:', {
  invoiceFile: invoiceFile?.name,
  contractFile: contractFile?.name,
  rowIndex: rowIndex,
  rowIndexType: typeof rowIndex,
  condition: (!invoiceFile || !contractFile) && rowIndex !== undefined && allFiles.length >= 2
});
```

### Issue: Still shows same documents

**Possible causes**:
1. Pre-computed matches exist and are the same for all rows
2. Modal is not remounting properly (key prop issue)
3. State updates are being batched/deduplicated

**Check**: Look for this log:
```
[handleCompareFiles] ✅ Using PRE-COMPUTED document matches
```

If you see it, the issue is in the pre-computed match logic, not the fallback.

## Quick Verification Checklist

- [ ] Console shows different `rowIndex` for each button (0, 1, 2...)
- [ ] Console shows "🔧 FIX: Row X - Using rowIndex-based selection" messages
- [ ] Console shows different `documentA` names for each row
- [ ] Console shows different `documentB` names for each row
- [ ] Modal displays different documents visually
- [ ] No JavaScript errors in console

## Expected Console Output Pattern

```
User clicks Row 0:
[ComparisonButton] Compare button clicked for FieldName, row 0!
[handleCompareFiles] 🔧 FIX: Processing row 0 with unique data
[handleCompareFiles] ⚠️ No pre-computed matches for row 0
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docA (offset 0): invoice.pdf
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docB (offset 1): contract.pdf
[handleCompareFiles] 🔧 FIX: Modal state set for row 0: {
  documentA: "invoice.pdf",
  documentB: "contract.pdf",
  rowIndex: 0
}

User clicks Row 1:
[ComparisonButton] Compare button clicked for FieldName, row 1!
[handleCompareFiles] 🔧 FIX: Processing row 1 with unique data
[handleCompareFiles] ⚠️ No pre-computed matches for row 1
[identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection for docA (offset 1): contract.pdf
[identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection for docB (offset 2): purchase.pdf
[handleCompareFiles] 🔧 FIX: Modal state set for row 1: {
  documentA: "contract.pdf",    ← DIFFERENT from row 0! ✅
  documentB: "purchase.pdf",    ← DIFFERENT from row 0! ✅
  rowIndex: 1
}
```

## Report Your Results

After testing, please report:

1. **Which test method you used** (Option 1, 2, 3, or 4)
2. **Test result** (All same / All different / Some different)
3. **Console log excerpt** (copy relevant logs)
4. **Number of files** in your analysis
5. **Number of rows** with comparison buttons

Example:
```
Test Method: Option 1 (Browser Console Test)
Result: ❌ All same
Files: 2 files (invoice.pdf, contract.pdf)
Rows: 3 rows with Compare buttons
Console: All rows logged documentA="invoice.pdf", documentB="contract.pdf"
```

This will help us identify the exact cause and apply the correct fix!
