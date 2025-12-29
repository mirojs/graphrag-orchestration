# Party-Based Data Grouping - Multi-Row Display with Single Compare Button ✅

**Date:** October 17, 2025  
**Status:** ✅ COMPLETE  
**Component:** DataTableWithPartyGrouping.tsx

---

## 🎯 Problem

Analysis results from the API now include direct file names and page numbers for each party, resulting in very wide rows with data like:

```
| Field | FileName1 | PageNumber1 | FileName2 | PageNumber2 | Actions |
|-------|-----------|-------------|-----------|-------------|---------|
| Value | file1.pdf | 5           | file2.pdf | 3           | Compare |
```

**Issues:**
- ❌ Rows are extremely wide - requires horizontal scrolling
- ❌ Hard to read with all parties crammed into one line
- ❌ In some cases, two Compare buttons appeared (one per party)
- ❌ Inconsistent display when parties have different amounts of data

---

## ✅ Solution

Created a new `DataTableWithPartyGrouping` component that:

1. **Detects party-numbered fields** (FileName1, FileName2, etc.)
2. **Splits parties into separate rows** for better readability
3. **Shows only ONE Compare button** at the end of the party group
4. **Maintains visual grouping** with styling to show rows belong together

### Visual Transformation

**Before (Wide Single Row):**
```
┌────────────────────────────────────────────────────────────────────────────────┐
│ Field      │ FileName1   │ PageNumber1 │ FileName2   │ PageNumber2 │ Compare  │
├────────────────────────────────────────────────────────────────────────────────┤
│ TotalPrice │ invoice.pdf │ 5           │ contract.pdf│ 3           │ [Button] │
└────────────────────────────────────────────────────────────────────────────────┘
         Requires horizontal scroll →→→→→→→→→→→→→→
```

**After (Multiple Rows, One Button):**
```
┌──────────────────────────────────────────────────────┐
│ Party │ FileName     │ PageNumber │ Actions          │
├──────────────────────────────────────────────────────┤
│   1   │ invoice.pdf  │ 5          │                  │  ← Light gray bg
├──────────────────────────────────────────────────────┤
│   2   │ contract.pdf │ 3          │ [Compare]        │  ← Thicker border
└──────────────────────────────────────────────────────┘
         No horizontal scroll needed! ✅
```

---

## 🔧 Implementation Details

### Component: DataTableWithPartyGrouping.tsx

**Location:** `src/ProModeComponents/shared/DataTableWithPartyGrouping.tsx`

#### Key Features

1. **Automatic Party Detection**
   ```typescript
   const detectPartyBasedStructure = (item: any): { isPartyBased: boolean; parties: number[] } => {
     // Looks for numbered field suffixes (FileName1, FileName2, etc.)
     // Returns list of party numbers found
   }
   ```

2. **Party Data Extraction**
   ```typescript
   const extractPartyData = (item: any, partyNumber: number): Record<string, any> => {
     // Extracts fields ending with specific party number
     // Also includes common fields without numbers
   }
   ```

3. **Row Preparation**
   - Converts single row with multiple parties into multiple rows
   - Each party gets its own row
   - Tracks which row is last in group for styling

4. **Visual Grouping**
   - Light gray background on non-last rows
   - Thicker border after last row in group
   - Empty action cell on non-last rows
   - Compare button only on last row

---

## 📋 How It Works

### Step 1: Detection

When data comes in, the component checks for party-numbered fields:

```typescript
{
  valueObject: {
    "Field": "TotalPrice",
    "FileName1": "invoice.pdf",
    "PageNumber1": "5",
    "FileName2": "contract.pdf",
    "PageNumber2": "3",
    "Discrepancy": "Values differ"
  }
}
```

Detects: `isPartyBased = true`, `parties = [1, 2]`

### Step 2: Row Splitting

Creates separate rows for each party:

```typescript
[
  {
    partyNumber: 1,
    displayData: {
      "Field": "TotalPrice",
      "FileName": "invoice.pdf",      // Number removed
      "PageNumber": "5",               // Number removed
      "Discrepancy": "Values differ"   // Shared field
    },
    isLastInGroup: false
  },
  {
    partyNumber: 2,
    displayData: {
      "Field": "TotalPrice",
      "FileName": "contract.pdf",
      "PageNumber": "3",
      "Discrepancy": "Values differ"
    },
    isLastInGroup: true  // Compare button shows here
  }
]
```

### Step 3: Rendering

- Adds "Party" column showing party number
- Renders each party in its own row
- Only shows Compare button on last row of group
- Applies visual styling to group rows together

---

## 🎨 Visual Design

### Row Styling

**Non-Last Rows (Within Group):**
```css
background-color: #fafafa;  /* Light gray */
border-bottom: 1px solid #e0e0e0;  /* Thin border */
```

**Last Row in Group:**
```css
background-color: transparent;  /* White */
border-bottom: 2px solid #1976d2;  /* Thick border */
```

### Party Column
- **Width:** 80px fixed
- **Alignment:** Center
- **Font:** Bold, blue (#1976d2)
- **Content:** Party number (1, 2, 3, etc.)

### Actions Column
- **Width:** 100px fixed  
- **Alignment:** Center
- **Content:** Compare button (only on last row of group)
- **Empty Cells:** Light gray background (#f5f5f5)

---

## 📊 Comparison Behavior

### Single Compare Button Strategy

**Why only one button?**
- All parties are related to the same inconsistency/field
- Compare button passes the ORIGINAL item with ALL party data
- Backend/comparison logic can access all parties' file/page info
- Cleaner UI - no redundant buttons

**Data Passed to onCompare:**
```typescript
onCompare(
  evidence,          // Formatted evidence string
  fieldName,         // Field name for context
  originalItem,      // Full object with ALL party data
  rowIndex           // Original row index
)
```

The `originalItem` contains:
```typescript
{
  valueObject: {
    "FileName1": "invoice.pdf",
    "PageNumber1": "5",
    "FileName2": "contract.pdf",
    "PageNumber2": "3",
    // ... all other fields
  }
}
```

So the comparison logic has access to all parties' information!

---

## 🔍 Edge Cases Handled

### Case 1: Mixed Data (Some Party-Based, Some Not)

```typescript
data = [
  { FileName1: "a.pdf", FileName2: "b.pdf" },  // Party-based ✓
  { FileName: "c.pdf" },                        // Not party-based ✓
  { FileName1: "d.pdf", FileName2: "e.pdf" }   // Party-based ✓
]
```

**Result:** Each row is independently detected and rendered appropriately

### Case 2: Unequal Party Numbers

```typescript
{
  FileName1: "a.pdf",
  FileName3: "b.pdf",  // Party 2 missing
  FileName5: "c.pdf"
}
```

**Result:** Displays parties 1, 3, and 5 (skips missing)

### Case 3: No Party Data

```typescript
{
  FileName: "a.pdf",  // No number
  PageNumber: "5"
}
```

**Result:** Falls back to regular table display (no party grouping)

### Case 4: Shared Fields

```typescript
{
  FieldName: "TotalPrice",    // No number - shared
  Discrepancy: "Different",   // No number - shared
  FileName1: "a.pdf",         // Party 1
  FileName2: "b.pdf"          // Party 2
}
```

**Result:** Shared fields appear in ALL party rows

---

## 🚀 Integration

### Updated Components

1. **DataRenderer.tsx**
   - Now imports `DataTableWithPartyGrouping`
   - Uses it instead of regular `DataTable`
   - Automatic detection - no configuration needed

2. **shared/index.ts**
   - Exports new component
   - Exports type definition

### Backward Compatibility

✅ **Fully backward compatible!**

The new component automatically detects party-based data:
- **If detected:** Uses party grouping
- **If not detected:** Renders exactly like old DataTable

No breaking changes to existing code!

---

## 💡 Benefits

### For Users

1. **Easier to Read**
   - Each party's data on its own row
   - No horizontal scrolling needed
   - Clear party identification

2. **Better Comparison**
   - Single button per group (less confusion)
   - Visual grouping shows related parties
   - Clear which parties are being compared

3. **More Information Visible**
   - Can see more fields without scrolling
   - Party column makes relationships clear
   - Grouped rows show data belongs together

### For Developers

1. **Automatic**
   - No configuration needed
   - Detection is automatic
   - Falls back gracefully

2. **Maintainable**
   - Single component handles both cases
   - Clear separation of concerns
   - Well-documented logic

3. **Extensible**
   - Easy to add more party patterns
   - Can customize detection logic
   - Styling can be themed

---

## 🧪 Testing Scenarios

### Test 1: Standard Party-Based Data
```typescript
Input:
{
  valueObject: {
    "Field": "Amount",
    "FileName1": "doc1.pdf",
    "PageNumber1": "3",
    "FileName2": "doc2.pdf",
    "PageNumber2": "5"
  }
}

Expected Output:
- 2 rows displayed
- Party column shows 1 and 2
- Compare button only on row 2
- Light gray background on row 1
- Thick border after row 2
```

### Test 2: Three Parties
```typescript
Input:
{
  valueObject: {
    "FileName1": "a.pdf",
    "FileName2": "b.pdf",
    "FileName3": "c.pdf"
  }
}

Expected Output:
- 3 rows displayed
- Compare button only on row 3
- Rows 1-2 have light background
- Row 3 has white background with thick border
```

### Test 3: Non-Party Data
```typescript
Input:
{
  valueObject: {
    "Field": "Amount",
    "FileName": "doc.pdf",
    "PageNumber": "3"
  }
}

Expected Output:
- 1 row displayed (normal table)
- No Party column
- Compare button shows normally
- Regular table styling
```

### Test 4: Mixed Shared and Party Fields
```typescript
Input:
{
  valueObject: {
    "FieldName": "Price",     // Shared
    "Discrepancy": "Differ",  // Shared
    "FileName1": "a.pdf",     // Party 1
    "FileName2": "b.pdf"      // Party 2
  }
}

Expected Output:
- 2 rows displayed
- "FieldName" and "Discrepancy" appear in BOTH rows
- "FileName" appears in each row with respective values
```

---

## 📖 Code Examples

### Usage in DataRenderer

```typescript
// Automatically used when rendering structured data
<DataRenderer
  fieldName="CrossDocumentInconsistencies"
  fieldData={inconsistencyData}
  onCompare={handleCompareFiles}
/>
```

### Direct Usage

```typescript
import { DataTableWithPartyGrouping } from './shared';

<DataTableWithPartyGrouping
  fieldName="PaymentTerms"
  data={tableData}
  onCompare={(evidence, field, item, rowIndex) => {
    // item contains full data for all parties
    console.log('Comparing:', item);
  }}
/>
```

---

## 🎯 Detection Patterns

The component looks for these patterns to identify party-based data:

### Field Name Patterns
- `FileName1`, `FileName2`, etc.
- `PageNumber1`, `PageNumber2`, etc.
- `Value1`, `Value2`, etc.
- `Amount1`, `Amount2`, etc.
- `Date1`, `Date2`, etc.
- `Party1`, `Party2`, etc.
- `Document1`, `Document2`, etc.

### Detection Rules
1. **Multiple numbered fields** - At least 2 fields with numbers
2. **Sequential or non-sequential** - Works with 1,2,3 or 1,3,5
3. **Common prefixes** - Fields share base name (FileName, PageNumber, etc.)
4. **Minimum 2 parties** - Needs at least 2 to be considered party-based

---

## 🔄 Future Enhancements

### Potential Improvements

1. **Collapsible Groups**
   - Add collapse/expand for party groups
   - Useful when many parties

2. **Party Labels**
   - Instead of numbers, show "Invoice", "Contract", etc.
   - Could be detected from FileName or explicit Party field

3. **Highlight Differences**
   - Visually highlight cells that differ between parties
   - Help users spot inconsistencies faster

4. **Custom Party Column**
   - Allow custom party identifiers
   - Support non-numeric party IDs

5. **Nested Parties**
   - Support sub-parties (Party1Sub1, Party1Sub2)
   - Hierarchical grouping

---

## ✅ Verification

- **TypeScript:** No errors ✅
- **Backward Compatible:** Yes ✅
- **Automatic Detection:** Yes ✅
- **Single Compare Button:** Yes ✅
- **Visual Grouping:** Yes ✅
- **Horizontal Scroll Reduced:** Yes ✅

---

## 🎉 Summary

**Problem:** Wide rows with party data requiring horizontal scrolling and duplicate compare buttons  
**Solution:** Automatic party detection with multi-row display and single compare button  
**Result:** Clean, readable table with better UX and no redundant controls ✅

**Key Features:**
- 🔍 Automatic party detection
- 📊 Multi-row display per inconsistency
- 🔘 Single compare button per group
- 🎨 Visual grouping with styling
- ↔️ No horizontal scrolling needed
- ♻️ Fully backward compatible

---

**Implementation Complete:** October 17, 2025  
**Component:** DataTableWithPartyGrouping.tsx  
**Auto-enabled:** Via DataRenderer  
**Impact:** All tables with party-numbered fields
