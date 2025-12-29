# Debugging Party Grouping - Not Working Issue

**Date:** October 17, 2025  
**Status:** 🔍 DEBUGGING  
**Issue:** Parties still displaying in same row despite new component

---

## 🐛 Problem Report

User reports that after implementing `DataTableWithPartyGrouping`, all parties are still showing in the same row instead of being split into separate rows.

---

## 🔍 Debug Steps Added

### 1. Console Logging

I've added extensive console logging to help diagnose the issue. When you refresh the page and view the Analysis tab, you should see logs in the browser console:

```javascript
[DataTableWithPartyGrouping] Analyzing data for party grouping: {...}
[detectPartyBasedStructure] Checking keys: [...]
[detectPartyBasedStructure] Found numbered keys: [...]
[detectPartyBasedStructure] Extracted party numbers: [...]
[detectPartyBasedStructure] Has common patterns: true/false
[detectPartyBasedStructure] Final decision: {...}
```

### 2. What to Check in Console

**Open your browser's Developer Tools (F12) and look for:**

1. **Are the logs appearing?**
   - If NO logs → Component isn't being rendered at all
   - If logs appear → Continue to step 2

2. **What keys are detected?**
   ```
   [detectPartyBasedStructure] Checking keys: ["Field", "FileName1", "PageNumber1", "FileName2", "PageNumber2"]
   ```
   - Do you see numbered keys like `FileName1`, `FileName2`?
   - Or are they named differently (e.g., `File_Name_1`, `file1`, `party_1_filename`)?

3. **Are party numbers extracted?**
   ```
   [detectPartyBasedStructure] Extracted party numbers: [1, 2]
   ```
   - Should show `[1, 2]` or similar
   - If empty `[]` → Keys don't match the regex pattern

4. **Is hasCommonPatterns true?**
   ```
   [detectPartyBasedStructure] Has common patterns: false
   ```
   - If FALSE → Field names don't match expected patterns
   - Current patterns: `FileName`, `PageNumber`, `Value`, `Amount`, `Date`, `Party`, `Document`

5. **Final decision:**
   ```
   [detectPartyBasedStructure] Final decision: { isPartyBased: false, ... }
   ```
   - If `isPartyBased: false` → Detection failed
   - If `isPartyBased: true` but still showing in one row → Rendering issue

---

## 🎯 Possible Root Causes

### Cause 1: Field Names Don't Match Pattern

**Symptom:** `hasCommonPatterns: false` in logs

**Current regex pattern:**
```typescript
key.match(/^(FileName|PageNumber|Value|Amount|Date|Party|Document)/i)
```

**Your fields might be named:**
- `File1`, `File2` (missing "Name")
- `Page1`, `Page2` (missing "Number")
- `Vendor1`, `Supplier1` (not in pattern list)
- `file_name_1`, `file_name_2` (underscores, lowercase)

**Solution:** Add more patterns or make it more flexible.

---

### Cause 2: Numbers Not at End of Key

**Symptom:** `numberedKeys: []` (empty) in logs

**Current regex:**
```typescript
/\d+$/.test(key)  // Requires digits AT THE END
```

**Won't match:**
- `File1Name` (number in middle)
- `1FileName` (number at start)
- `File_1_Name` (number with trailing text)

**Solution:** Adjust regex or normalize field names before detection.

---

### Cause 3: Data Structure Issue

**Symptom:** Keys show Azure value containers, not actual field names

**Example of problematic structure:**
```javascript
{
  type: "object",
  valueObject: {
    "SomeField": {
      type: "string",
      valueString: "FileName1: invoice.pdf"  // Data is INSIDE the value
    }
  }
}
```

Instead of:
```javascript
{
  type: "object",
  valueObject: {
    "FileName1": "invoice.pdf",
    "FileName2": "contract.pdf"
  }
}
```

**Solution:** Extract from nested value containers.

---

### Cause 4: Only 1 Party Detected

**Symptom:** `partyNumbers: [1]` or `partyNumbers: [2]` (only one number)

**Code requirement:**
```typescript
isPartyBased = limitedPartyNumbers.length >= 2 && hasCommonPatterns;
```

Needs at least 2 parties!

**Your data might be:**
- All fields end with `1` only
- Missing the second party's fields
- Party numbers aren't consistent (one field has `1`, another has `3`, but missing `2`)

**Solution:** Ensure data has multiple party numbers OR change requirement to `>= 1`.

---

## 🔧 Quick Fixes to Try

### Fix 1: Expand Pattern Matching

If your fields are named differently, update the pattern:

```typescript
// Current (line ~55 in DataTableWithPartyGrouping.tsx)
const hasCommonPatterns = keys.some(key => 
  key.match(/^(FileName|PageNumber|Value|Amount|Date|Party|Document)/i)
);

// Try more flexible version:
const hasCommonPatterns = keys.some(key => 
  key.match(/^(File|Page|Value|Amount|Date|Party|Document|Vendor|Supplier|Contract|Invoice|Price|Total)/i)
);
```

### Fix 2: Allow Single Party (for testing)

If you just want to see if it works with 1 party:

```typescript
// Current (line ~61)
const isPartyBased = limitedPartyNumbers.length >= 2 && hasCommonPatterns;

// Temporary test version:
const isPartyBased = limitedPartyNumbers.length >= 1 && hasCommonPatterns;
```

### Fix 3: Check valueObject Nesting

The detection looks at:
```typescript
const valueObject = item.valueObject || item;
```

If your data has deeper nesting, you might need to adjust extraction.

---

## 📋 Testing Checklist

After adding debug logs, test with actual data:

1. ✅ Open browser Developer Tools (F12)
2. ✅ Go to Console tab
3. ✅ Navigate to Analysis tab in the app
4. ✅ Click on a field that should show party data
5. ✅ Look for `[DataTableWithPartyGrouping]` logs
6. ✅ Copy the logs and share them

**What to share:**
```
[DataTableWithPartyGrouping] Analyzing data: { ... }
[detectPartyBasedStructure] Checking keys: [ ... ]
[detectPartyBasedStructure] Found numbered keys: [ ... ]
[detectPartyBasedStructure] Extracted party numbers: [ ... ]
[detectPartyBasedStructure] Has common patterns: ...
[detectPartyBasedStructure] Final decision: { ... }
```

This will tell us exactly why detection is failing!

---

## 🎯 Example Expected Logs (Working Case)

```javascript
[DataTableWithPartyGrouping] Analyzing data for party grouping: {
  fieldName: "CrossDocumentInconsistencies",
  dataLength: 3,
  sampleItem: { type: "object", valueObject: {...} }
}

[detectPartyBasedStructure] Checking keys: [
  "Field",
  "FileName1",
  "PageNumber1", 
  "FileName2",
  "PageNumber2",
  "Discrepancy"
]

[detectPartyBasedStructure] Found numbered keys: [
  "FileName1",
  "PageNumber1",
  "FileName2", 
  "PageNumber2"
]

[detectPartyBasedStructure] Extracted party numbers: [1, 2]

[detectPartyBasedStructure] Has common patterns: true

[detectPartyBasedStructure] Final decision: {
  isPartyBased: true,
  partyCount: 2,
  hasCommonPatterns: true
}

[DataTableWithPartyGrouping] ✅ Party-based data detected! Enabling party grouping.
```

Then you should see the blue info banner and separate rows!

---

## 🚨 Next Steps

1. **Check console logs** - Share what you see
2. **Inspect actual data structure** - Copy one row's full object
3. **Identify naming pattern** - What are your field names actually called?
4. **Adjust detection** - Update regex patterns to match your data

Once you share the console output, I can provide a targeted fix!

---

## 📝 Files Modified (with Debug Logging)

- `DataTableWithPartyGrouping.tsx`
  - Added logging to `usePartyGrouping` memo
  - Added logging to `detectPartyBasedStructure` function
  - Shows: keys found, numbered keys, party numbers, pattern matching, final decision

---

**Status:** Waiting for console log output to diagnose issue  
**Action Required:** Open browser console, navigate to Analysis tab, copy logs
