# Document Matching Strategies - Complete Guide

## Overview
The `identifyComparisonDocuments()` function uses **6 strategies** to find the correct pair of documents to display in the comparison modal. They execute in **waterfall order** - each strategy only runs if previous strategies haven't found both documents yet.

---

## Strategy Execution Order (Priority)

### **STRATEGY 1: Content-Based Matching** 🥇
**Priority:** HIGHEST (Most Reliable)  
**Trigger:** When Azure analysis provides `InvoiceValue` and `ContractValue` fields

**How it works:**
- Extracts values from Azure's analysis results (e.g., invoice amount, contract terms)
- Searches for these values in the actual document content (Azure markdown)
- Maps the matched content back to uploaded files

**Example:**
```typescript
// If Azure found:
InvoiceValue: "$29,900.00"
ContractValue: "$22,000 upon signing, $7,000 upon delivery"

// It searches document contents for these strings
// and matches them to the source files
```

**Console output:**
```
✅ Content match: Found '$29,900.00' in invoice, matched to file: contoso_lifts_invoice.pdf
```

**When it's used:**
- When Azure's AI extraction successfully identifies specific values
- Most accurate because it matches based on actual content, not just filenames

---

### **STRATEGY 2: DocumentTypes from Azure** 🥈
**Priority:** HIGH  
**Trigger:** When Azure provides `DocumentTypes` array in analysis results

**How it works:**
- Reads `DocumentTypes` field from Azure analysis
- Each document has metadata like:
  - `DocumentType`: "invoice" or "contract"
  - `DocumentTitle`: Full filename or title
- Matches documents by type and title

**Example:**
```typescript
// Azure returns:
DocumentTypes: [
  { DocumentType: "invoice", DocumentTitle: "Contoso Lifts Invoice" },
  { DocumentType: "contract", DocumentTitle: "Holding Tank Servicing Contract" }
]

// Code matches these to uploaded files by name/type
```

**Console output:**
```
📊 DocumentTypes available: [{type: "invoice", title: "Contoso..."}, ...]
✅ Type match: Found invoice via DocumentTypes: contoso_lifts_invoice.pdf
```

**When it's used:**
- When Azure successfully categorizes documents
- Reliable but depends on Azure's document classification

---

### **STRATEGY 3: Row-Specific Selection** 🔧⭐
**Priority:** MEDIUM-HIGH (Critical for fixing "same window" issue)  
**Trigger:** When `rowIndex` is provided and at least 2 files exist

**How it works:**
- Uses the **row number** to calculate which documents to show
- Formula: 
  - `offset = rowIndex % (numFiles - 1)`
  - `documentA = allFiles[offset]`
  - `documentB = allFiles[(offset + 1) % numFiles]`
- **Ensures each row shows DIFFERENT documents**

**Example with 5 files:**
```typescript
// Row 0: offset=0 → files[0], files[1]
// Row 1: offset=1 → files[1], files[2]
// Row 2: offset=2 → files[2], files[3]
// Row 3: offset=3 → files[3], files[4]
// Row 4: offset=0 → files[4], files[0] (wraps around)
```

**Console output:**
```
🔧 FIX: Row 0 - Using rowIndex-based selection for docA (offset 0): file1.pdf
🔧 FIX: Row 0 - Using rowIndex-based selection for docB (offset 1): file2.pdf
```

**Why this strategy was added:**
- **Original problem:** All comparison buttons showed the same two documents
- **Root cause:** Pattern matching (Strategy 4) always found the same "invoice" and "contract" files
- **Solution:** Use rowIndex to rotate through different file pairs

**Critical Note:** 
- ⚠️ This strategy **MUST run BEFORE Strategy 4** (pattern matching)
- If pattern matching runs first, it sets both documents and this strategy never executes
- This is why the fix involved reordering the strategies!

---

### **STRATEGY 4: Filename Pattern Matching** 🔍
**Priority:** MEDIUM (Fallback only)  
**Trigger:** When previous strategies didn't find both documents

**How it works:**
- Searches filenames for keywords:
  - **Invoice patterns:** "invoice", "bill", "receipt", "inv"
  - **Contract patterns:** "contract", "agreement", "purchase", "po"
- Returns the **first file** that matches each pattern

**Example:**
```typescript
// Uploaded files:
// 1. contoso_lifts_invoice.pdf  ✅ matches "invoice"
// 2. HOLDING_TANK_SERVICING_CONTRACT.pdf  ✅ matches "contract"
// 3. quote.pdf
// 4. receipt.pdf  ✅ matches "receipt" (invoice pattern)

// Always finds: contoso_lifts_invoice.pdf and HOLDING_TANK_SERVICING_CONTRACT.pdf
// (first matches for each type)
```

**Console output:**
```
⚠️ Pattern match: Found invoice by filename pattern 'invoice': contoso_lifts_invoice.pdf
⚠️ Pattern match: Found contract by filename pattern 'contract': HOLDING_TANK_SERVICING_CONTRACT.pdf
```

**Limitations:**
- **Always returns the same files** if filenames contain patterns
- This was causing the "same window" bug before Strategy 3 was moved ahead
- Should only be used as a fallback when row-specific selection isn't available

---

### **STRATEGY 5: Upload Context** 📁
**Priority:** LOW  
**Trigger:** When no documents found yet, but files are uploaded

**How it works:**
- Uses the upload context to differentiate:
  - **Input files** → Assumed to be invoices (documents to analyze)
  - **Reference files** → Assumed to be contracts (documents to compare against)
- Takes first file from each category

**Example:**
```typescript
// If user uploaded:
// Input files: [invoice1.pdf, invoice2.pdf]
// Reference files: [contract1.pdf]

// Strategy 5 selects:
// documentA = invoice1.pdf (first input)
// documentB = contract1.pdf (first reference)
```

**Console output:**
```
📁 Context: Using first input file as invoice: invoice1.pdf
📁 Context: Using first reference file as contract: contract1.pdf
```

**When it's used:**
- When user separates files into "input" vs "reference" categories
- Rare in current implementation (most uploads are all "input" files)

---

### **STRATEGY 6: Final Fallback** 🔄
**Priority:** LOWEST (Last resort)  
**Trigger:** When NO other strategy found documents

**How it works:**
- Simply takes:
  - `documentA = allFiles[0]` (first uploaded file)
  - `documentB = allFiles[1]` (second uploaded file)
- If only 1 file exists, uses it for both sides

**Example:**
```typescript
// With any uploaded files, regardless of names:
// allFiles = [fileA.pdf, fileB.pdf, fileC.pdf]

// Strategy 6 selects:
// documentA = fileA.pdf
// documentB = fileB.pdf
```

**Console output:**
```
🔄 Fallback: Using first available file as invoice: fileA.pdf
🔄 Fallback: Using second available file as contract: fileB.pdf
```

**When it's used:**
- When all intelligent matching fails
- When files have generic names with no patterns
- Guarantees a comparison modal can always open

---

## Current Execution Flow (After Fix)

### For a typical analysis with 5 files:

1. **Strategy 1** tries content matching
   - ❌ Fails (content matching is complex, often returns null)

2. **Strategy 2** tries Azure DocumentTypes
   - ❌ Fails (DocumentTypes array is empty in current setup)

3. **Strategy 3** uses row-specific selection ✅
   - ✅ **SUCCESS!** Sets different documents based on rowIndex
   - Row 0 → files[0], files[1]
   - Row 1 → files[1], files[2]
   - etc.

4. **Strategy 4** pattern matching
   - ⏭️ **SKIPPED** because both documents already set by Strategy 3

5. **Strategy 5** upload context
   - ⏭️ **SKIPPED** because both documents already set

6. **Strategy 6** final fallback
   - ⏭️ **SKIPPED** because both documents already set

**Result:** Each row shows different documents! 🎉

---

## Before the Fix (BROKEN)

1. **Strategy 1** tries content matching ❌
2. **Strategy 2** tries DocumentTypes ❌
3. **Strategy 3** pattern matching ✅ (was in this position before)
   - Always found: `contoso_lifts_invoice.pdf` and `HOLDING_TANK_SERVICING_CONTRACT.pdf`
4. **Strategy 4** row-specific selection
   - ⏭️ **NEVER RAN** because condition `if (!invoiceFile || !contractFile)` was FALSE

**Result:** All rows showed same documents! ❌

---

## Key Takeaways

### Why Order Matters:
- Strategies execute in **waterfall sequence**
- Each strategy only runs if `!invoiceFile || !contractFile` is TRUE
- Once both documents are set, remaining strategies are skipped
- **Moving Strategy 3 before Strategy 4 fixed the bug!**

### Best Practices:
1. **Most specific strategies first** (content, types, row-specific)
2. **Generic strategies last** (pattern matching, fallback)
3. **Ensure fix strategies run before problematic ones**

### Console Log Prefixes:
- `✅` = Successful match
- `🔧 FIX` = Row-specific selection (the fix)
- `⚠️` = Pattern matching (fallback)
- `📊` = DocumentTypes metadata
- `📁` = Upload context
- `🔄` = Final fallback

---

## Testing the Current Implementation

### Expected console logs after fix:
```
[identifyComparisonDocuments] 📊 DocumentTypes available: []
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docA (offset 0): file1.pdf
[identifyComparisonDocuments] 🔧 FIX: Row 0 - Using rowIndex-based selection for docB (offset 1): file2.pdf
[identifyComparisonDocuments] ✅ SUCCESS - Selected documents for comparison: {documentA: 'file1.pdf', documentB: 'file2.pdf', rowIndex: 0}
```

### Bad console logs (if still broken):
```
[identifyComparisonDocuments] 📊 DocumentTypes available: []
[identifyComparisonDocuments] ⚠️ Pattern match: Found invoice by filename pattern 'invoice': contoso_lifts_invoice.pdf
[identifyComparisonDocuments] ⚠️ Pattern match: Found contract by filename pattern 'contract': HOLDING_TANK_SERVICING_CONTRACT.pdf
[identifyComparisonDocuments] ✅ SUCCESS - Selected documents for comparison: {documentA: 'contoso_lifts_invoice.pdf', documentB: 'HOLDING_TANK_SERVICING_CONTRACT.pdf', rowIndex: 0}
```

If you see `⚠️ Pattern match` before `🔧 FIX`, the strategies are still in the wrong order!
