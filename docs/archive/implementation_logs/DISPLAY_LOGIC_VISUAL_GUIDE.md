# Display Logic Flow - Visual Guide

## 🎯 The Core Question: "Why Single Row Instead of Multiple?"

### Understanding the Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      DataRenderer                           │
│  (Smart Router - Detects Format & Delegates)               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
            ┌─────────────┴─────────────┐
            │                           │
    ┌───────▼────────┐        ┌────────▼────────┐
    │ Has Category?  │        │ Has Documents   │
    │     field      │        │     array?      │
    └───────┬────────┘        └────────┬────────┘
            │ YES                      │ YES
            ▼                          ▼
    ┌───────────────┐          ┌──────────────┐
    │  META-ARRAY   │          │   DOCUMENTS  │
    │   Rendering   │          │    ARRAY     │
    └───────┬───────┘          └──────┬───────┘
            │                         │
            └────────┬────────────────┘
                     ▼
         ┌────────────────────────┐
         │ DocumentsComparisonTable│
         │  (Renders N rows for   │
         │   N items in Documents │
         │        array)          │
         └────────────────────────┘
```

---

## 📊 Key Rendering Rule

```
╔═══════════════════════════════════════════════════════════════╗
║  ROWS = documentsArray.length                                 ║
║                                                               ║
║  • Documents array with 1 item  →  1 table row               ║
║  • Documents array with 2 items →  2 table rows              ║
║  • Documents array with N items →  N table rows              ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 🔍 Three Common Scenarios

### Scenario A: Multiple Inconsistencies (Each with 1 Document Pair)

**Data Structure:**
```json
{
  "AllInconsistencies": [
    {
      "Category": "PaymentTerms",
      "InconsistencyType": "Due Date Mismatch",
      "Documents": [
        { "Invoice1 vs Contract1" }  ← 1 document pair
      ]
    },
    {
      "Category": "PaymentTerms", 
      "InconsistencyType": "Payment Method",
      "Documents": [
        { "Invoice1 vs Contract1" }  ← 1 document pair
      ]
    },
    {
      "Category": "Items",
      "InconsistencyType": "Price Mismatch", 
      "Documents": [
        { "Invoice1 vs Contract1" }  ← 1 document pair
      ]
    }
  ]
}
```

**How It Renders:**
```
╔════════════════════════════════════════════════╗
║ 📋 PaymentTerms (2 inconsistencies)           ║
╠════════════════════════════════════════════════╣
║ ┌────────────────────────────────────────┐   ║
║ │ Due Date Mismatch                      │   ║
║ ├─────────────────────────────────────────┤   ║
║ │ Row 1: Invoice1 vs Contract1  [Compare]│   ║ ← Table 1 (1 row)
║ └────────────────────────────────────────┘   ║
║                                              ║
║ ┌────────────────────────────────────────┐   ║
║ │ Payment Method Mismatch                │   ║
║ ├─────────────────────────────────────────┤   ║
║ │ Row 1: Invoice1 vs Contract1  [Compare]│   ║ ← Table 2 (1 row)
║ └────────────────────────────────────────┘   ║
╚════════════════════════════════════════════════╝

╔════════════════════════════════════════════════╗
║ 📋 Items (1 inconsistency)                    ║
╠════════════════════════════════════════════════╣
║ ┌────────────────────────────────────────┐   ║
║ │ Price Mismatch                         │   ║
║ ├─────────────────────────────────────────┤   ║
║ │ Row 1: Invoice1 vs Contract1  [Compare]│   ║ ← Table 3 (1 row)
║ └────────────────────────────────────────┘   ║
╚════════════════════════════════════════════════╝
```

**Console Logs:**
```
[DocumentsComparisonTable] ✅ Extracted Azure array with 1 document(s)  ← For each table
[DocumentsComparisonTable] ✅ Extracted Azure array with 1 document(s)
[DocumentsComparisonTable] ✅ Extracted Azure array with 1 document(s)
```

**Is this correct?** ✅ YES - Each inconsistency is separate

**User expectation mismatch?** If user wants all issues for Invoice1 vs Contract1 grouped:
```
Solution: Use DocumentPairGroup component
```

---

### Scenario B: Single Inconsistency (Multiple Document Pairs)

**Data Structure:**
```json
{
  "AllInconsistencies": [
    {
      "Category": "PaymentTerms",
      "InconsistencyType": "Due Date Mismatch",
      "Documents": [
        { "Invoice1 vs Contract1" },  ← Document pair 1
        { "Invoice2 vs Contract2" },  ← Document pair 2
        { "Invoice3 vs Contract3" }   ← Document pair 3
      ]
    }
  ]
}
```

**How It Renders:**
```
╔════════════════════════════════════════════════╗
║ 📋 PaymentTerms (1 inconsistency)             ║
╠════════════════════════════════════════════════╣
║ ┌────────────────────────────────────────┐   ║
║ │ Due Date Mismatch                      │   ║
║ ├─────────────────────────────────────────┤   ║
║ │ Row 1: Invoice1 vs Contract1  [Compare]│   ║ ← Row 1
║ ├─────────────────────────────────────────┤   ║
║ │ Row 2: Invoice2 vs Contract2  [Compare]│   ║ ← Row 2
║ ├─────────────────────────────────────────┤   ║
║ │ Row 3: Invoice3 vs Contract3  [Compare]│   ║ ← Row 3
║ └────────────────────────────────────────┘   ║
╚════════════════════════════════════════════════╝
```

**Console Logs:**
```
[DocumentsComparisonTable] ✅ Extracted Azure array with 3 document(s)
```

**Is this correct?** ✅ YES - Multiple rows in single table

**This shows multiple rows!**

---

### Scenario C: Data Extraction Failed

**Data Structure:**
```json
{
  "AllInconsistencies": [
    {
      "Category": "PaymentTerms",
      "InconsistencyType": "Due Date Mismatch",
      "Documents": "Invoice1 vs Contract1"  ← WRONG: String instead of array
    }
  ]
}
```

**Console Logs:**
```
[DocumentsComparisonTable] ⚠️ Documents field exists but not in expected format
```

**How It Renders:**
```
╔════════════════════════════════════════════════╗
║ 📋 PaymentTerms (1 inconsistency)             ║
╠════════════════════════════════════════════════╣
║ ┌────────────────────────────────────────┐   ║
║ │ Due Date Mismatch                      │   ║
║ ├─────────────────────────────────────────┤   ║
║ │ ℹ️ No documents to display              │   ║ ← Empty/fallback
║ └────────────────────────────────────────┘   ║
╚════════════════════════════════════════════════╝
```

**Is this correct?** ❌ NO - Data structure issue

---

## 🔧 Diagnostic Decision Tree

```
┌─────────────────────────────────────────┐
│ User sees single row instead of 2+     │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ Check Console Logs                      │
│ Look for [DocumentsComparisonTable]     │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┴──────────┐
        │                    │
        ▼                    ▼
┌───────────────┐    ┌──────────────────┐
│ "Extracted    │    │ "⚠️ No Documents"│
│  array with   │    │ OR "not in       │
│  1 document(s)"│   │  expected format"│
└───────┬───────┘    └─────────┬────────┘
        │                      │
        ▼                      ▼
   SCENARIO A            SCENARIO C
   (Most likely)         (Data issue)
        │                      │
        │                      │
        ▼                      ▼
┌──────────────┐      ┌────────────────┐
│ Each         │      │ Fix data       │
│ inconsistency│      │ structure:     │
│ has only 1   │      │ Documents      │
│ doc pair.    │      │ must be array  │
│              │      └────────────────┘
│ This is      │
│ CORRECT!     │
│              │
│ User wants:  │
│ Group by     │
│ doc pair?    │
└──────┬───────┘
       │
       ▼
┌──────────────────────┐
│ Use:                 │
│ • DocumentPairGroup  │
│   OR                 │
│ • MetaArrayRenderer  │
│   (doc-pair mode)    │
└──────────────────────┘
```

---

## 🎨 Visual Comparison: Current vs Alternative UIs

### Current UI (Category Grouping)
```
┌─────────────────────────────────────────────┐
│ 📋 PaymentTerms (3 inconsistencies)        │
├─────────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐   │
│ │ Issue #1: Due Date                  │   │
│ │ • Invoice1 vs Contract1             │   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─────────────────────────────────────┐   │
│ │ Issue #2: Payment Method            │   │
│ │ • Invoice1 vs Contract1             │   │
│ └─────────────────────────────────────┘   │
│                                           │
│ ┌─────────────────────────────────────┐   │
│ │ Issue #3: Late Fee                  │   │
│ │ • Invoice1 vs Contract1             │   │
│ └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```
**Good for:** Understanding issues by category

---

### Alternative UI - DocumentPairGroup (Document Pair Grouping)
```
┌─────────────────────────────────────────────┐
│ 📄 Invoice1.pdf ⚡ Contract1.pdf           │
│ 3 issues | Severity: Critical             │
├─────────────────────────────────────────────┤
│ 1️⃣  Due Date Mismatch                      │
│     30 days ≠ 45 days                      │
│                               [Compare]    │
│                                            │
│ 2️⃣  Payment Method Mismatch                │
│     Wire Transfer ≠ ACH                    │
│                               [Compare]    │
│                                            │
│ 3️⃣  Late Fee Discrepancy                   │
│     2% ≠ 3%                                │
│                               [Compare]    │
└─────────────────────────────────────────────┘
```
**Good for:** Understanding all issues for specific document pair

---

## 📝 Quick Reference Table

| Symptom | Console Log | Diagnosis | Solution |
|---------|-------------|-----------|----------|
| **Seeing 1 row per table** | `Extracted array with 1 document(s)` (repeated) | Multiple inconsistencies, each with 1 doc pair | ✅ CORRECT - Use DocumentPairGroup if want grouping |
| **Seeing multiple rows** | `Extracted array with N document(s)` where N > 1 | Single inconsistency with multiple doc pairs | ✅ CORRECT - Working as expected |
| **Seeing no rows** | `⚠️ No Documents field found` | Missing Documents field | ❌ Schema/API issue |
| **Seeing no rows** | `⚠️ Documents field exists but not in expected format` | Documents is not an array | ❌ Data structure issue |
| **Seeing fallback** | No DocumentsComparisonTable logs | Not detected as Documents array format | ⚠️ Check data format |

---

## 🚀 How to Test

### Test 1: Verify Multiple Rows Work
```typescript
// Paste this in browser console when on the page:
const testData = {
  type: 'array',
  valueArray: [{
    valueObject: {
      Category: 'TestCategory',
      InconsistencyType: 'Test Issue',
      Documents: {
        type: 'array',
        valueArray: [
          { valueObject: { DocumentASourceDocument: 'Invoice1.pdf', DocumentAValue: 'Value1' } },
          { valueObject: { DocumentASourceDocument: 'Invoice2.pdf', DocumentAValue: 'Value2' } }
        ]
      }
    }
  }]
};

// Render it
<DocumentsComparisonTable 
  fieldName="Test" 
  inconsistency={testData.valueArray[0]} 
  onCompare={() => {}} 
/>
```
**Expected:** Table with 2 rows ✅

### Test 2: Check Console Logs
```javascript
// In browser console:
// 1. Filter logs
console.log('Filtering for DocumentsComparisonTable logs...');

// 2. Look for this pattern:
// [DocumentsComparisonTable] ✅ Extracted Azure array with X document(s)

// 3. X = number of rows that should render
```

---

## ✅ Conclusion

**The display logic is working correctly!** 

The question is: **What is the actual data structure?**

**To determine:**
1. Check console logs for `documentsArray.length`
2. If length = 1 repeatedly → You have multiple inconsistencies with 1 doc pair each (CORRECT)
3. If you want them grouped → Use `DocumentPairGroup` or `MetaArrayRenderer`

**Next Step:** Share console log showing the `documentsArray.length` value! 🔍
