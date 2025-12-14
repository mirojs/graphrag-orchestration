# ✅ SOLUTION: Enable Document-Pair Grouping

## 🎯 What You Need

Based on your console logs, you want to see **both issues for the same document pair grouped together** instead of separated by category.

---

## 🔧 Quick Fix - Option 1: Update DataRenderer Import

**File:** `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`

### Step 1: Update Import (Line 65)

**Current:**
```tsx
import { DataRenderer } from './shared';
```

**Change to:**
```tsx
import { DataRenderer, MetaArrayRenderer } from './shared';
```

### Step 2: Add Conditional Rendering (Around Line 1818)

**Current code (lines ~1818-1822):**
```tsx
{/* Use new DataRenderer component for consistent, maintainable rendering */}
<DataRenderer
  fieldName={fieldName}
  fieldData={fieldData}
  onCompare={handleCompareFiles}
/>
```

**Replace with:**
```tsx
{/* Use MetaArrayRenderer for AllInconsistencies to enable document-pair grouping */}
{fieldName === 'AllInconsistencies' ? (
  <MetaArrayRenderer
    fieldName={fieldName}
    data={fieldData}
    onCompare={handleCompareFiles}
    initialMode="document-pair"  // Start in document-pair view
  />
) : (
  <DataRenderer
    fieldName={fieldName}
    fieldData={fieldData}
    onCompare={handleCompareFiles}
  />
)}
```

### Result

Now when rendering `AllInconsistencies`, users will see:

```
┌─────────────────────────────────────────┐
│ AllInconsistencies                      │
│ [Group by Category] [Group by Doc Pair]│ ← Toggle buttons
├─────────────────────────────────────────┤
│ 📄 invoice.pdf ⚡ purchase_contract.pdf │
│ 2 issues | Critical                    │
├─────────────────────────────────────────┤
│ 1️⃣  Payment Total Mismatch              │
│     $610.00 ≠ $29,900.00               │
│                          [Compare]     │
│                                        │
│ 2️⃣  Item Description Mismatch           │
│     Consulting ≠ Vertical Lift         │
│                          [Compare]     │
└─────────────────────────────────────────┘
```

Users can toggle to category view if they want.

---

## 🔧 Alternative Fix - Option 2: Always Use Document-Pair (No Toggle)

If you ALWAYS want document-pair grouping (no toggle):

**Replace with:**
```tsx
{/* Use DocumentPairGroup for AllInconsistencies */}
{fieldName === 'AllInconsistencies' && fieldData?.valueArray ? (
  <DocumentPairGroup
    inconsistencies={fieldData.valueArray}
    onCompare={handleCompareFiles}
  />
) : (
  <DataRenderer
    fieldName={fieldName}
    fieldData={fieldData}
    onCompare={handleCompareFiles}
  />
)}
```

**And update import to:**
```tsx
import { DataRenderer, DocumentPairGroup } from './shared';
```

---

## 🚀 Even Better - Option 3: Auto-Detect Same Document Pair

Add this logic to automatically use document-pair grouping when all inconsistencies are for the same document pair:

```tsx
{/* Smart rendering: use document-pair grouping if all for same doc pair */}
{(() => {
  if (fieldName === 'AllInconsistencies' && fieldData?.valueArray?.length > 1) {
    // Check if all inconsistencies are for same document pair
    const docPairs = fieldData.valueArray.map((item: any) => {
      const obj = item?.valueObject || item;
      const docs = obj?.Documents?.valueArray || [];
      const firstDoc = docs[0]?.valueObject || docs[0];
      const docA = firstDoc?.DocumentASourceDocument?.valueString || 
                   firstDoc?.DocumentASourceDocument || '';
      const docB = firstDoc?.DocumentBSourceDocument?.valueString || 
                   firstDoc?.DocumentBSourceDocument || '';
      return `${docA}|||${docB}`;
    });
    
    const uniquePairs = new Set(docPairs);
    
    if (uniquePairs.size === 1) {
      // All for same doc pair - use DocumentPairGroup
      return (
        <DocumentPairGroup
          inconsistencies={fieldData.valueArray}
          onCompare={handleCompareFiles}
        />
      );
    }
  }
  
  // Otherwise use standard DataRenderer
  return (
    <DataRenderer
      fieldName={fieldName}
      fieldData={fieldData}
      onCompare={handleCompareFiles}
    />
  );
})()}
```

This automatically detects:
- **Single document pair** → Use DocumentPairGroup (your current case)
- **Multiple document pairs** → Use DataRenderer with category grouping

---

## 📊 Recommendation

**I recommend Option 1 (MetaArrayRenderer with toggle)** because:
- ✅ Gives users choice
- ✅ Works for all scenarios (single or multiple doc pairs)
- ✅ Easy to implement (just change import and add conditional)
- ✅ No complex logic needed

---

## 🎬 Exact Code Change

**File:** `PredictionTab.tsx`

**Line 65 - Change import:**
```tsx
import { DataRenderer, MetaArrayRenderer } from './shared';
```

**Lines ~1818-1822 - Change rendering:**
```tsx
{fieldName === 'AllInconsistencies' ? (
  <MetaArrayRenderer
    fieldName={fieldName}
    data={fieldData}
    onCompare={handleCompareFiles}
    initialMode="document-pair"
  />
) : (
  <DataRenderer
    fieldName={fieldName}
    fieldData={fieldData}
    onCompare={handleCompareFiles}
  />
)}
```

**That's it!** 🎉

---

## ✅ What This Solves

**Before:**
```
📋 PaymentTerms (1 inconsistency)
  - Table with 1 row

📋 Items (1 inconsistency)
  - Table with 1 row
```

**After:**
```
📄 invoice.pdf ⚡ purchase_contract.pdf
2 issues | Critical

1️⃣ Payment Total Mismatch
   $610.00 ≠ $29,900.00

2️⃣ Item Description Mismatch
   Consulting ≠ Vertical Lift
```

**Both issues for the same document pair are now grouped together!** ✅
