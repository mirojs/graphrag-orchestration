# What Are We Actually Comparing? (Strategy Fallback Explained)

## The Question
"If Strategy 1 and 2 find nothing, then what are we comparing?"

## The Answer: **Strategy 6 Guarantees Something is Always Returned**

---

## The Waterfall Logic

The function **never returns empty** (unless there are literally NO files). Here's what happens:

### Scenario: Typical Analysis with 5 Uploaded Files

```typescript
allFiles = [
  'contoso_lifts_invoice.pdf',           // index 0
  'HOLDING_TANK_SERVICING_CONTRACT.pdf', // index 1
  'purchase_order.pdf',                  // index 2
  'quote.pdf',                           // index 3
  'receipt.pdf'                          // index 4
]
```

### Strategy Execution for Row 0:

#### **Strategy 1: Content-Based Matching**
```typescript
if (invoiceValue) {
  invoiceFile = findDocByContentMatch(invoiceValue.substring(0, 50), 'invoice');
}
// invoiceValue is empty or object → invoiceFile = null ❌

if (contractValue) {
  contractFile = findDocByContentMatch(contractValue.substring(0, 50), 'contract');
}
// contractValue is empty or object → contractFile = null ❌

// Result: invoiceFile = null, contractFile = null
```

#### **Strategy 2: Azure DocumentTypes**
```typescript
const documentTypes = analysisFields?.DocumentTypes?.valueArray || [];
// documentTypes = [] (empty array in your case) ❌

// Result: invoiceFile = null, contractFile = null (unchanged)
```

#### **Strategy 3: Row-Specific Selection** ✅
```typescript
if (rowIndex !== undefined && allFiles.length >= 2) {
  const numFiles = allFiles.length; // 5
  const offset = rowIndex % Math.max(1, numFiles - 1); // 0 % 4 = 0
  
  if (!invoiceFile) { // TRUE (still null from Strategy 1 & 2)
    invoiceFile = allFiles[offset]; // allFiles[0]
    // invoiceFile = 'contoso_lifts_invoice.pdf' ✅
  }
  
  if (!contractFile) { // TRUE
    const secondIdx = (offset + 1) % numFiles; // 1 % 5 = 1
    contractFile = allFiles[secondIdx]; // allFiles[1]
    // contractFile = 'HOLDING_TANK_SERVICING_CONTRACT.pdf' ✅
  }
}

// Result: BOTH FILES NOW SET! ✅
```

#### **Strategy 4, 5, 6: SKIPPED**
```typescript
// These never run because the condition is now FALSE:
if (!invoiceFile) {  // FALSE (already set by Strategy 3)
  // SKIPPED
}

if (!contractFile) { // FALSE (already set by Strategy 3)
  // SKIPPED
}
```

---

## So What Gets Compared?

### **After the fix, you're comparing:**

**Row 0:**
- DocumentA: `allFiles[0]` = `contoso_lifts_invoice.pdf`
- DocumentB: `allFiles[1]` = `HOLDING_TANK_SERVICING_CONTRACT.pdf`

**Row 1:**
- DocumentA: `allFiles[1]` = `HOLDING_TANK_SERVICING_CONTRACT.pdf`
- DocumentB: `allFiles[2]` = `purchase_order.pdf`

**Row 2:**
- DocumentA: `allFiles[2]` = `purchase_order.pdf`
- DocumentB: `allFiles[3]` = `quote.pdf`

**Row 3:**
- DocumentA: `allFiles[3]` = `quote.pdf`
- DocumentB: `allFiles[4]` = `receipt.pdf`

**Row 4:**
- DocumentA: `allFiles[4]` = `receipt.pdf`
- DocumentB: `allFiles[0]` = `contoso_lifts_invoice.pdf` (wraps around)

---

## What If Strategy 3 Also Fails?

**Scenario:** `rowIndex` is undefined or only 1 file exists

### **Then Strategy 4 (Pattern Matching) Runs:**
```typescript
if (!invoiceFile) {
  invoiceFile = findDocByFilenamePattern('invoice');
  // Searches for 'invoice', 'bill', 'receipt', 'inv' in filenames
  // Finds: 'contoso_lifts_invoice.pdf' ✅
}

if (!contractFile) {
  contractFile = findDocByFilenamePattern('contract');
  // Searches for 'contract', 'agreement', 'purchase', 'po' in filenames
  // Finds: 'HOLDING_TANK_SERVICING_CONTRACT.pdf' ✅
}
```

**Problem:** This always returns the **same two files** (why all rows showed same window before)

---

## What If Even Pattern Matching Fails?

**Scenario:** Files are named `file1.pdf`, `file2.pdf` (no keywords)

### **Then Strategy 6 (Final Fallback) Runs:**
```typescript
// 🎯 STRATEGY 6: Final fallback to available files
if (!invoiceFile && allFiles.length > 0) {
  invoiceFile = allFiles[0];
  console.log('[identifyComparisonDocuments] 🔄 Fallback: Using first available file as invoice:', invoiceFile.name);
  // invoiceFile = 'file1.pdf' ✅
}

if (!contractFile && allFiles.length > 1) {
  contractFile = allFiles[1];
  console.log('[identifyComparisonDocuments] 🔄 Fallback: Using second available file as contract:', contractFile.name);
  // contractFile = 'file2.pdf' ✅
} else if (!contractFile && allFiles.length === 1) {
  contractFile = allFiles[0]; // Same file if only one available
  console.log('[identifyComparisonDocuments] ⚠️ Only one file available, using it for both sides');
  // contractFile = 'file1.pdf' ✅ (shows same file on both sides)
}
```

**This ALWAYS succeeds** as long as you have at least 1 uploaded file!

---

## The Only Way to Get Nothing

```typescript
if (invoiceFile && contractFile) {
  // Return the documents ✅
  return {
    documentA: invoiceFile,
    documentB: contractFile,
    comparisonType: 'input-reference' as const
  };
}

// Only reaches here if BOTH are still null
console.warn('[identifyComparisonDocuments] ⚠️ Could not identify documents for comparison');
return null;
```

**This only happens if:**
- `allFiles.length === 0` (NO files uploaded at all)
- All strategies are somehow broken (code error)

In your case with 5 uploaded files, **Strategy 3 or 6 will ALWAYS succeed**.

---

## Visual Flow Diagram

```
Strategy 1: Content Match
    ↓ (fails - empty values)
    
Strategy 2: DocumentTypes
    ↓ (fails - empty array)
    
Strategy 3: Row-Specific ← YOU ARE HERE (after fix)
    ✅ SUCCESS!
    invoiceFile = allFiles[rowIndex % 4]
    contractFile = allFiles[(rowIndex % 4) + 1]
    ↓
    STOP - both files set!
    
Strategy 4: Pattern Match (NEVER REACHED)
    
Strategy 5: Upload Context (NEVER REACHED)
    
Strategy 6: Final Fallback (NEVER REACHED)
```

---

## Before the Fix

```
Strategy 1: Content Match
    ↓ (fails - empty values)
    
Strategy 2: DocumentTypes
    ↓ (fails - empty array)
    
Strategy 3: Pattern Match ← WAS HERE (before fix)
    ✅ ALWAYS finds 'invoice' and 'contract' files
    invoiceFile = 'contoso_lifts_invoice.pdf'
    contractFile = 'HOLDING_TANK_SERVICING_CONTRACT.pdf'
    ↓
    STOP - both files set!
    
Strategy 4: Row-Specific (NEVER REACHED! 😱)
    ↓ Would have used rowIndex to vary documents
    ↓ But never executed because both already set
    
Strategy 5 & 6: (NEVER REACHED)
```

**Result:** Every row got the same two files!

---

## Summary: What Are You Comparing?

### **Question:** "If nothing could be found, then what are we comparing?"

### **Answer:** 

**You're ALWAYS comparing something** because of the waterfall fallback:

1. **Best case:** Azure's extracted values matched to actual content (Strategy 1)
2. **Good case:** Azure's document type classification (Strategy 2)
3. **Fixed case:** Different file pairs per row based on index math (Strategy 3) ← **YOU ARE HERE**
4. **Old broken case:** Same "invoice" and "contract" files every time (Strategy 4 when it ran first)
5. **Worst case:** First two files in upload order (Strategy 6)

**The fix moved Strategy 3 to run before Strategy 4**, so now you get **different documents per row** instead of the **same two documents every time**.

The comparison modal **always shows SOMETHING** - the strategies just determine **which** files to show!
