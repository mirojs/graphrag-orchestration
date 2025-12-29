# Using Document-Pair Grouping for Your Use Case

## Current Situation ✅

Based on console logs, you have:
- **2 inconsistencies** (Payment Total Mismatch, Item Description Mismatch)
- **Same document pair** (invoice.pdf vs purchase_contract.pdf)
- **Each inconsistency has 1 document in Documents array**

Current UI shows 2 separate tables (grouped by category: PaymentTerms, Items).

## Solution: Use MetaArrayRenderer with Document-Pair View

### Option 1: Quick Toggle (Recommended)

Replace your current DataRenderer with MetaArrayRenderer to give users a toggle:

```tsx
import { MetaArrayRenderer } from './shared';

// Instead of:
// <DataRenderer fieldName="AllInconsistencies" fieldData={data} onCompare={handleCompare} />

// Use:
<MetaArrayRenderer
  fieldName="AllInconsistencies"
  data={allInconsistenciesData}
  onCompare={handleCompare}
  initialMode="document-pair"  // Start in document-pair grouping mode
/>
```

**Result:** Users can toggle between:
- **Category view:** See all PaymentTerms issues, all Items issues (current view)
- **Document-pair view:** See all issues for invoice.pdf vs purchase_contract.pdf together

---

### Option 2: Always Show Document-Pair Grouped

If you ALWAYS want document-pair grouping, use DocumentPairGroup directly:

```tsx
import { DocumentPairGroup } from './shared';

// Group all inconsistencies by document pair
const groupByDocumentPair = (inconsistencies: any[]) => {
  const groups = new Map<string, any[]>();
  
  inconsistencies.forEach(item => {
    const obj = item?.valueObject || item;
    const docs = obj?.Documents?.valueArray || obj?.Documents || [];
    const firstDoc = docs[0]?.valueObject || docs[0];
    
    const docA = firstDoc?.DocumentASourceDocument?.valueString || 
                 firstDoc?.DocumentASourceDocument || 'UnknownA';
    const docB = firstDoc?.DocumentBSourceDocument?.valueString || 
                 firstDoc?.DocumentBSourceDocument || 'UnknownB';
    const key = `${docA}|||${docB}`;
    
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
  });
  
  return Array.from(groups.values());
};

// In your render:
const inconsistenciesArray = allInconsistenciesData?.valueArray || [];
const groupedByDocPair = groupByDocumentPair(inconsistenciesArray);

return (
  <div>
    {groupedByDocPair.map((group, index) => (
      <DocumentPairGroup
        key={index}
        inconsistencies={group}
        onCompare={handleCompare}
      />
    ))}
  </div>
);
```

**Result:** Single card showing:
```
┌─────────────────────────────────────────────┐
│ 📄 invoice.pdf ⚡ purchase_contract.pdf     │
│ 2 issues | Severity: Critical              │
├─────────────────────────────────────────────┤
│ 1️⃣  Payment Total Mismatch                  │
│     $610.00 ≠ $29,900.00                   │
│                               [Compare]    │
│                                            │
│ 2️⃣  Item Description Mismatch               │
│     Consulting Services ≠ Vertical Lift    │
│                               [Compare]    │
└─────────────────────────────────────────────┘
```

---

### Option 3: Update DataRenderer Priority (Automatic)

Add document-pair detection as a higher priority in DataRenderer itself:

**File:** `ProModeComponents/shared/DataRenderer.tsx`

Add this check BEFORE the category grouping:

```tsx
// PRIORITY 0.5: Check if all inconsistencies share same document pair
// If yes, group by document pair instead of category
if (firstItemObj?.Category && fieldData.valueArray.length > 1) {
  // Check if all items have same document pair
  const allDocPairs = fieldData.valueArray.map((item: any) => {
    const obj = item?.valueObject || item;
    const docs = obj?.Documents?.valueArray || obj?.Documents || [];
    const firstDoc = docs[0]?.valueObject || docs[0];
    const docA = extractDisplayValue(firstDoc?.DocumentASourceDocument);
    const docB = extractDisplayValue(firstDoc?.DocumentBSourceDocument);
    return `${docA}|||${docB}`;
  });
  
  const uniqueDocPairs = new Set(allDocPairs);
  
  if (uniqueDocPairs.size === 1) {
    // All inconsistencies are for the same document pair!
    console.log(`[DataRenderer] 🎯 All inconsistencies for same document pair - using document-pair grouping`);
    
    return (
      <DocumentPairGroup
        inconsistencies={fieldData.valueArray}
        onCompare={onCompare}
      />
    );
  }
}

// Otherwise, fall through to category grouping...
```

This would automatically detect when all inconsistencies are for the same document pair and render them grouped together.

---

## Recommendation

**I recommend Option 1 (MetaArrayRenderer with toggle)** because:
- ✅ Gives users flexibility
- ✅ No code changes needed in DataRenderer
- ✅ Already built and tested
- ✅ Works for both scenarios:
  - Single document pair (your current case)
  - Multiple document pairs (future cases)

---

## Where to Make the Change

**File to modify:** Wherever you're currently using DataRenderer for AllInconsistencies

**Look for code like:**
```tsx
<DataRenderer
  fieldName="AllInconsistencies"
  fieldData={result?.AllInconsistencies}
  onCompare={handleCompare}
/>
```

**Replace with:**
```tsx
<MetaArrayRenderer
  fieldName="AllInconsistencies"
  data={result?.AllInconsistencies}
  onCompare={handleCompare}
  initialMode="document-pair"
/>
```

---

## Expected Result

With document-pair grouping, you'll see:

```
┌────────────────────────────────────────────────┐
│ 📄 invoice.pdf  ⚡  📄 purchase_contract.pdf   │
│ 2 issues  Critical                            │
├────────────────────────────────────────────────┤
│                                                │
│ 1️⃣  Payment Total Mismatch   [PaymentTerms]   │
│     Invoice shows $610.00 but contract...     │
│                                                │
│     ┌────────────────┐  ≠  ┌────────────────┐ │
│     │ Amount Due     │     │ Total Contract │ │
│     │ $610.00        │     │ $29,900.00     │ │
│     │ invoice.pdf p.1│     │ purchase...p.1 │ │
│     └────────────────┘     └────────────────┘ │
│                                    [Compare]  │
│                                                │
│ 2️⃣  Item Description Mismatch   [Items]       │
│     Invoice lists Consulting Services...      │
│                                                │
│     ┌────────────────┐  ≠  ┌────────────────┐ │
│     │ Services       │     │ Scope of Work  │ │
│     │ Consulting...  │     │ Vertical Lift..│ │
│     │ invoice.pdf p.1│     │ purchase...p.1 │ │
│     └────────────────┘     └────────────────┘ │
│                                    [Compare]  │
└────────────────────────────────────────────────┘

📑 Pages: invoice.pdf p.1 ⚡ purchase_contract.pdf p.1
Critical: 1  High: 0  Medium: 1
```

Instead of the current:
```
📋 PaymentTerms (1 inconsistency)
  [Table with 1 row]

📋 Items (1 inconsistency)
  [Table with 1 row]
```

---

## Summary

✅ **Your display logic is working perfectly!**
✅ **Console logs confirm each inconsistency has 1 document pair (as designed)**
✅ **You just need document-pair grouping instead of category grouping**
✅ **Solution already exists: MetaArrayRenderer or DocumentPairGroup**

Would you like me to find the exact file where you're using DataRenderer and make the change for you?
