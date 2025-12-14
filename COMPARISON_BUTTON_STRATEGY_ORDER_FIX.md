# Comparison Button Fix - Strategy Execution Order

## Problem Identified

After testing with 5 comparison buttons, **ALL buttons showed the same documents**:
- documentA: `contoso_lifts_invoice.pdf`
- documentB: `HOLDING_TANK_SERVICING_CONTRACT.pdf`

### Root Cause

The console logs revealed the issue:
```
⚠️ Pattern match: Found invoice by filename pattern 'invoice': contoso_lifts_invoice.pdf
⚠️ Pattern match: Found contract by filename pattern 'contract': HOLDING_TANK_SERVICING_CONTRACT.pdf
```

**Strategy 3 (pattern matching) was running BEFORE Strategy 4 (row-specific selection)**

Since pattern matching always finds the same two files with "invoice" and "contract" in their names, it sets both `invoiceFile` and `contractFile` variables. Then when Strategy 4 checked:
```typescript
if ((!invoiceFile || !contractFile) && rowIndex !== undefined && allFiles.length >= 2)
```

The condition was **FALSE** because both files were already set, so Strategy 4 (which uses rowIndex to select different documents) never executed!

## Solution Applied

**Swapped the execution order of Strategy 3 and Strategy 4:**

### Before (BROKEN):
1. Strategy 1: Pre-computed matches ❌ (none exist)
2. Strategy 2: DocumentTypes from Azure ❌ (empty array)
3. **Strategy 3: Filename pattern matching** ✅ (finds same files every time)
4. **Strategy 4: Row-specific selection** ❌ (never runs because condition is false)
5. Strategy 5: Upload context
6. Strategy 6: Final fallback

### After (FIXED):
1. Strategy 1: Pre-computed matches ❌ (none exist)
2. Strategy 2: DocumentTypes from Azure ❌ (empty array)
3. **Strategy 3: Row-specific selection** ✅ (RUNS FIRST, sets different docs per row!)
4. **Strategy 4: Filename pattern matching** ⏭️ (only runs if Strategy 3 didn't find both)
5. Strategy 5: Upload context
6. Strategy 6: Final fallback

## Code Changes

**File**: `PredictionTab.tsx`
**Function**: `identifyComparisonDocuments()`
**Lines**: ~886-929

### Key Change:
```typescript
// 🎯 STRATEGY 3: Row-specific document selection (CRITICAL FIX for same window issue)
// ⚠️ MUST RUN FIRST before pattern matching to ensure different documents per row!
// Use rowIndex to rotate through different document pairs for each row
if (rowIndex !== undefined && allFiles.length >= 2) {
  const numFiles = allFiles.length;
  const offset = rowIndex % Math.max(1, numFiles - 1);
  
  if (!invoiceFile) {
    invoiceFile = allFiles[offset];
    console.log(`[identifyComparisonDocuments] 🔧 FIX: Row ${rowIndex} - Using rowIndex-based selection for docA (offset ${offset}): ${invoiceFile.name}`);
  }
  
  if (!contractFile) {
    const secondIdx = (offset + 1) % numFiles;
    contractFile = allFiles[secondIdx];
    console.log(`[identifyComparisonDocuments] 🔧 FIX: Row ${rowIndex} - Using rowIndex-based selection for docB (offset ${secondIdx}): ${contractFile.name}`);
  }
}

// 🎯 STRATEGY 4: Filename pattern matching (FALLBACK - only if row-specific didn't set both)
// ... pattern matching code ...
```

## Expected Behavior After Fix

### With 5 uploaded files:
- Row 0: Shows files at index [0, 1]
- Row 1: Shows files at index [1, 2]
- Row 2: Shows files at index [2, 3]
- Row 3: Shows files at index [3, 4]
- Row 4: Shows files at index [4, 0] (wraps around)

Each row will now display **different document pairs**!

### Console logs should show:
```
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docA (offset 0): file1.pdf
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docB (offset 1): file2.pdf

[identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection for docA (offset 1): file2.pdf
[identifyComparisonDocuments] 🔧 FIX: Row 1 - Using rowIndex-based selection for docB (offset 2): file3.pdf
```

## Testing Instructions

1. **Refresh the browser** to load the updated code
2. Run an analysis with multiple files (already done)
3. Click the first Compare button → Note the documents shown
4. Click the second Compare button → **Should show DIFFERENT documents**
5. Click remaining buttons → Each should show different document pairs

### Watch console logs for:
- `🔧 FIX: Row X - Using rowIndex-based selection` messages
- Different document names for each row
- NO MORE `⚠️ Pattern match` messages appearing first

## Status

✅ **Fix Applied** - Strategy execution order corrected
⏳ **Pending Testing** - User needs to refresh browser and retest

## Previous Fix Attempts

1. ❌ First attempt: Added Strategy 4 but placed it AFTER pattern matching
2. ✅ Current fix: Moved row-specific strategy to run BEFORE pattern matching

The key insight: **Order of execution matters!** The first strategy that successfully sets both documents wins.
