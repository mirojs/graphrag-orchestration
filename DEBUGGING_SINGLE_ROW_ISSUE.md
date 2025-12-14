# Debugging Guide: Comparison Pairs Single-Row Display Issue

## Issue Report
**User:** "I still saw the comparison pair were in a single row instead of 2. Please check it."

## Expected Behavior
When an inconsistency has a `Documents` array with multiple document pairs, each pair should render as a **separate row** in the table.

**Example:**
```
Documents array: [
  { DocumentA: "Invoice1.pdf", DocumentB: "Contract1.pdf", ... },
  { DocumentA: "Invoice2.pdf", DocumentB: "Contract2.pdf", ... }
]
```

**Should render as:**
```
Row 1: Invoice1.pdf vs Contract1.pdf [Compare button]
Row 2: Invoice2.pdf vs Contract2.pdf [Compare button]
```

## Actual Behavior (Reported)
All document pairs showing in a **single row** instead of multiple rows.

## Investigation Steps

### 1. Added Debug Logging

**File:** `ProModeComponents/shared/DocumentsComparisonTable.tsx`

**Added comprehensive logging:**
```typescript
const documentsArray = React.useMemo(() => {
  const obj = inconsistency?.valueObject || inconsistency;
  
  console.log(`[DocumentsComparisonTable] 🔍 Extracting Documents array for ${fieldName}`);
  console.log(`[DocumentsComparisonTable] Full inconsistency object:`, inconsistency);
  console.log(`[DocumentsComparisonTable] obj.Documents:`, obj?.Documents);
  
  if (!obj?.Documents) {
    console.log(`[DocumentsComparisonTable] ⚠️ No Documents field found`);
    return [];
  }
  
  // Handle Azure array structure
  if (obj.Documents.type === 'array' && (obj.Documents as any).valueArray) {
    const array = (obj.Documents as any).valueArray;
    console.log(`[DocumentsComparisonTable] ✅ Extracted Azure array with ${array.length} document(s)`);
    console.log(`[DocumentsComparisonTable] Documents array:`, array);
    return array;
  }
  
  // Handle direct array (fallback)
  if (Array.isArray(obj.Documents)) {
    console.log(`[DocumentsComparisonTable] ✅ Extracted direct array with ${obj.Documents.length} document(s)`);
    console.log(`[DocumentsComparisonTable] Documents array:`, obj.Documents);
    return obj.Documents;
  }
  
  console.log(`[DocumentsComparisonTable] ⚠️ Documents field exists but not in expected format`);
  return [];
}, [inconsistency, fieldName]);
```

### 2. Console Log Analysis

When you run the application and view inconsistencies, check the browser console for these log messages:

#### Scenario A: Working Correctly (Multiple Rows)
```
[DocumentsComparisonTable] 🔍 Extracting Documents array for PaymentTerms 1
[DocumentsComparisonTable] ✅ Extracted Azure array with 2 document(s)
[DocumentsComparisonTable] Documents array: [
  {
    valueObject: {
      DocumentASourceDocument: "Invoice1.pdf",
      DocumentBSourceDocument: "Contract1.pdf",
      ...
    }
  },
  {
    valueObject: {
      DocumentASourceDocument: "Invoice2.pdf",
      DocumentBSourceDocument: "Contract2.pdf",
      ...
    }
  }
]
```
**Result:** Should render 2 rows (one per document pair)

#### Scenario B: Single Row Issue - Documents Array Has 1 Item
```
[DocumentsComparisonTable] 🔍 Extracting Documents array for PaymentTerms 1
[DocumentsComparisonTable] ✅ Extracted Azure array with 1 document(s)
[DocumentsComparisonTable] Documents array: [
  {
    valueObject: {
      DocumentASourceDocument: "Invoice1.pdf",
      DocumentBSourceDocument: "Contract1.pdf",
      ...
    }
  }
]
```
**Result:** Only 1 row renders (correct behavior if only 1 document pair)

#### Scenario C: Single Row Issue - Documents Not Extracted
```
[DocumentsComparisonTable] 🔍 Extracting Documents array for PaymentTerms 1
[DocumentsComparisonTable] ⚠️ Documents field exists but not in expected format
[DocumentsComparisonTable] Documents array: []
```
**Result:** No rows render, or fallback rendering

### 3. Possible Root Causes

#### Cause 1: Schema Generated Single Document Pair
**Symptom:** Each inconsistency only has 1 item in Documents array

**Diagnosis:**
```javascript
console.log(documentsArray.length); // Shows: 1
```

**Explanation:** This is actually **correct behavior** if:
- You're comparing only 1 invoice vs 1 contract
- Each inconsistency represents a single comparison
- Multiple inconsistencies exist, but each has its own single document pair

**Example:**
```json
{
  "AllInconsistencies": [
    {
      "Category": "PaymentTerms",
      "InconsistencyType": "Payment Due Date Mismatch",
      "Documents": [
        { 
          "DocumentASourceDocument": "Invoice1.pdf",
          "DocumentBSourceDocument": "Contract1.pdf"
        }
      ]
    },
    {
      "Category": "Items",
      "InconsistencyType": "Item Price Mismatch",
      "Documents": [
        { 
          "DocumentASourceDocument": "Invoice1.pdf",
          "DocumentBSourceDocument": "Contract1.pdf"
        }
      ]
    }
  ]
}
```
Each inconsistency gets its own card/section, each with a table showing 1 row.

#### Cause 2: Documents Array Structure Incorrect
**Symptom:** Multiple document pairs exist but not extracted correctly

**Diagnosis:**
```javascript
console.log(obj?.Documents); // Shows unexpected structure
```

**Possible issues:**
- Documents field is not an array
- Documents field is nested incorrectly
- Azure field structure not recognized

**Solution:** Check actual API response structure

#### Cause 3: Multiple Inconsistencies vs Multiple Document Pairs Confusion
**Important distinction:**

**SCENARIO A: Multiple inconsistencies, each with 1 document pair**
```json
[
  {
    "InconsistencyType": "Payment Terms",
    "Documents": [{ "Invoice1 vs Contract1" }]  ← 1 document pair
  },
  {
    "InconsistencyType": "Item Price",
    "Documents": [{ "Invoice1 vs Contract1" }]  ← 1 document pair
  }
]
```
**UI:** 2 separate cards/sections, each showing 1 row ✅ CORRECT

**SCENARIO B: Single inconsistency with 2 document pairs**
```json
[
  {
    "InconsistencyType": "Payment Terms",
    "Documents": [
      { "Invoice1 vs Contract1" },  ← document pair 1
      { "Invoice2 vs Contract2" }   ← document pair 2
    ]
  }
]
```
**UI:** 1 card/section showing 2 rows ✅ CORRECT

**User may be seeing Scenario A but expecting Scenario B**

---

## Debugging Workflow

### Step 1: Check Console Logs
1. Open browser DevTools (F12)
2. Go to Console tab
3. Look for `[DocumentsComparisonTable]` log messages
4. Note the `documentsArray.length` value

### Step 2: Inspect Actual Data
Add this to your component:
```typescript
console.log('Full AllInconsistencies:', allInconsistencies);
allInconsistencies.forEach((item, index) => {
  console.log(`Inconsistency ${index}:`, item);
  const docs = item?.Documents || item?.valueObject?.Documents;
  console.log(`  Documents count:`, docs?.length || docs?.valueArray?.length || 0);
});
```

### Step 3: Verify Schema Output
Check what the AI actually generated:
```typescript
// In your API response handler
const response = await analyzeDocument(schema);
console.log('Raw API Response:', JSON.stringify(response, null, 2));
```

### Step 4: Test with Sample Data
Create a test with known data:
```typescript
const testData = {
  type: 'array',
  valueArray: [
    {
      valueObject: {
        Category: 'PaymentTerms',
        InconsistencyType: 'Payment Due Date Mismatch',
        Documents: {
          type: 'array',
          valueArray: [
            {
              valueObject: {
                DocumentASourceDocument: 'Invoice1.pdf',
                DocumentBSourceDocument: 'Contract1.pdf',
                DocumentAValue: '30 days',
                DocumentBValue: '45 days'
              }
            },
            {
              valueObject: {
                DocumentASourceDocument: 'Invoice2.pdf',
                DocumentBSourceDocument: 'Contract2.pdf',
                DocumentAValue: '60 days',
                DocumentBValue: '90 days'
              }
            }
          ]
        }
      }
    }
  ]
};

<DocumentsComparisonTable
  fieldName="Test"
  inconsistency={testData.valueArray[0]}
  onCompare={handleCompare}
/>
```

**Expected:** Should render table with 2 rows

---

## Common Misunderstandings

### Misunderstanding 1: "Multiple comparisons in single row"
**What user might see:**
```
┌──────────────────────────────────────────────────────────────┐
│ Payment Terms Mismatch                                       │
├──────────────────────────────────────────────────────────────┤
│ Doc # | Invoice Field | Invoice Value | Contract Field | ... │
├──────────────────────────────────────────────────────────────┤
│   1   | Payment Terms | 30 days       | Payment Terms  | ... │
└──────────────────────────────────────────────────────────────┘
```
**User expects:** Row 2 with Invoice2 vs Contract2

**Reality:** This inconsistency only involves 1 document pair (Invoice1 vs Contract1). If there's an issue with Invoice2 vs Contract2, it would be a **separate inconsistency** with its own card/section.

### Misunderstanding 2: Category grouping
When viewing by category (meta-array), all PaymentTerms issues are grouped together, but each issue still has its own table showing its specific document pair(s).

**UI Structure:**
```
📋 PaymentTerms (3 inconsistencies)
  ├─ Payment Due Date Mismatch
  │  └─ Table: 1 row (Invoice1 vs Contract1)
  ├─ Payment Method Mismatch  
  │  └─ Table: 1 row (Invoice1 vs Contract1)
  └─ Late Fee Discrepancy
     └─ Table: 1 row (Invoice1 vs Contract1)
```

**This is correct!** Each mismatch is a separate issue with its own comparison.

### Misunderstanding 3: Old party detection behavior
User may remember the old party detection (FileName1, PageNumber1, FileName2, PageNumber2) where all parties showed in a single row. That was a **bug** we fixed. New behavior is **correct** - each document pair gets its own row.

---

## Solutions

### Solution 1: If AI Generated Single Document Pairs
**Problem:** AI is creating separate inconsistencies for each comparison instead of grouping multiple document pairs under one inconsistency.

**Schema currently says:**
```json
{
  "Documents": {
    "description": "Array of document comparison pairs involved in this inconsistency. If comparing multiple document pairs, create multiple items in this array."
  }
}
```

**If you want multiple document pairs in one inconsistency:**
Make the schema guidance more explicit:
```json
{
  "Documents": {
    "description": "IMPORTANT: If the SAME TYPE of inconsistency (e.g., Payment Terms Mismatch) exists across MULTIPLE document pairs (Invoice1 vs Contract1 AND Invoice2 vs Contract2), include ALL pairs in this array. Each item in this array represents one invoice-contract comparison showing the same type of mismatch. Example: If both Invoice1 and Invoice2 have payment term mismatches with their respective contracts, add both comparisons here."
  }
}
```

### Solution 2: Use DocumentPairGroup Component
If you have multiple inconsistencies for the same document pair and want to group them visually:

```typescript
import { DocumentPairGroup } from './shared';

// Group all issues for Invoice1 vs Contract1
const invoice1Contract1Issues = allInconsistencies.filter(item => {
  const docs = extractDocumentsArray(item);
  const firstDoc = docs[0]?.valueObject || docs[0];
  return firstDoc.DocumentASourceDocument === 'Invoice1.pdf' &&
         firstDoc.DocumentBSourceDocument === 'Contract1.pdf';
});

<DocumentPairGroup
  inconsistencies={invoice1Contract1Issues}
  onCompare={handleCompare}
/>
```

### Solution 3: Use MetaArrayRenderer Toggle
Allow users to switch between category view and document-pair view:

```typescript
import { MetaArrayRenderer } from './shared';

<MetaArrayRenderer
  fieldName="AllInconsistencies"
  data={allInconsistencies}
  onCompare={handleCompare}
  initialMode="document-pair"  // Start in document-pair grouping mode
/>
```

---

## Next Actions

### For User:
1. **Open browser console** and share the log output from `[DocumentsComparisonTable]`
2. **Share screenshot** of what you're seeing vs what you expect
3. **Share sample data** (JSON) of the AllInconsistencies array structure
4. **Clarify expectation:** 
   - Do you want multiple inconsistencies for the same doc pair grouped together?
   - Or do you want a single inconsistency with multiple doc pairs in its Documents array?

### For Developer:
1. Review console logs to see `documentsArray.length`
2. Inspect actual API response structure
3. Determine if this is:
   - Schema guidance issue (AI not grouping document pairs correctly)
   - UI expectation mismatch (behavior is correct, user expects different grouping)
   - Data extraction bug (Documents array not parsed correctly)
4. Test with sample data to verify rendering logic works

---

## Testing Checklist

- [ ] Single inconsistency with 1 document pair → Renders 1 row ✅
- [ ] Single inconsistency with 2 document pairs → Renders 2 rows ✅
- [ ] Multiple inconsistencies (each with 1 doc pair) → Multiple sections, each with 1 row ✅
- [ ] Console logs show correct documentsArray.length
- [ ] Azure array structure (valueArray) extracted correctly
- [ ] Direct array structure extracted correctly
- [ ] Empty Documents array → Shows "No documents to display" message

---

## Summary

**Most likely scenario:** User has multiple inconsistencies (each with 1 document pair) and expects them to be in a single table with multiple rows. This is an **expectation mismatch**, not a bug.

**Solution:** Use `DocumentPairGroup` or `MetaArrayRenderer` with document-pair mode to group multiple inconsistencies for the same document pair visually.

**Next step:** Get actual console logs and data structure to confirm diagnosis.
