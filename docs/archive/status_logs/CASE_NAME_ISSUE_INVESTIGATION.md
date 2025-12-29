# 🔍 Case Name Issue - Investigation & Fix

## User-Reported Issues

### Issue 1: Case Name Can't Be Edited After Selecting Files ❓
**Symptom**: Case Name input field becomes uneditable after selecting files from library

**Current Code Investigation**:
```typescript
<Input
  value={caseName}
  onChange={(_, data) => setCaseName(data.value)}
  disabled={isLoading}  // ← Only disabled during save operation
/>
```

**Finding**: There's **NO logic** that disables the Case Name field after file selection.

**Possible Causes**:
1. **Focus Loss**: Dialog might be stealing focus when FileSelectorDialog closes
2. **Event Bubbling**: Click events might be blocked by overlays
3. **State Issue**: caseName state might not be updating properly
4. **Browser Issue**: Input field might appear focused but not responding

**Need More Info**: 
- Does clicking directly in the Case Name field allow typing?
- Or does it appear "grayed out"?
- Does refreshing the page help?

---

### Issue 2: Case Name Gets Duplicated with Capitalization ❓
**Symptom**: "Saved case name would repeat user input by add a capitalized one and a hyphen before it"

**Example**:
- User types: `"My Test Case"`
- Sees displayed: `"MY-TEST-CASE My Test Case"` (??)

**Root Cause Analysis**:

The system has **TWO** fields:
1. **`case_id`** (unique identifier) - Auto-generated from `case_name`
2. **`case_name`** (display name) - What user types

```typescript
const generateCaseId = (name: string): string => {
  return name
    .trim()
    .toUpperCase()              // "my test case" → "MY TEST CASE"
    .replace(/[^A-Z0-9\s]/g, '') // Remove special chars
    .replace(/\s+/g, '-')        // "MY TEST CASE" → "MY-TEST-CASE"
    .substring(0, 50) || 'CASE-' + Date.now();
};
```

**What Gets Saved**:
```json
{
  "case_id": "MY-TEST-CASE",      // ← Generated
  "case_name": "My Test Case",    // ← User input (preserved!)
  "description": "...",
  ...
}
```

**The Problem**: 
If the UI is displaying `case_id` instead of (or alongside) `case_name`, users will see:
- `"MY-TEST-CASE"` (the ID)
- Instead of `"My Test Case"` (the name they typed)

---

## Investigation Questions

### Q1: Where do you see the "duplicated" name?
- [ ] In the Cases list/table?
- [ ] In the modal after saving?
- [ ] In the case details view?
- [ ] Somewhere else?

### Q2: Is it showing BOTH fields together?
Example: `"MY-TEST-CASE - My Test Case"` 

Or just the uppercase version: `"MY-TEST-CASE"`?

### Q3: Can you share a screenshot or exact text of what you see?

---

## Possible Solutions

### Solution A: Don't Display case_id in UI (Recommended)
**If**: Users only care about the friendly name

**Change**: Never show `case_id` in the UI, only use it internally for API calls

```typescript
// In cases list
{cases.map(c => (
  <div>{c.case_name}</div>  {/* NOT c.case_id */}
))}
```

### Solution B: Make case_id Same as case_name
**If**: You don't need uppercase/hyphenated IDs

**Change**: Use case_name as-is for case_id

```typescript
const generateCaseId = (name: string): string => {
  return name.trim() || 'CASE-' + Date.now();
  // No uppercase, no hyphenation
};
```

**Result**:
- User types: `"My Test Case"`
- `case_id`: `"My Test Case"` (same!)
- `case_name`: `"My Test Case"`

### Solution C: Let Users Edit case_id Separately
**If**: You need both a friendly name AND a unique ID

**Change**: Show both fields in the modal

```
Case ID:   [MY-TEST-CASE        ] (auto-generated, can edit)
Case Name: [My Test Case        ] (user input)
```

### Solution D: Use UUID for case_id
**If**: You want guaranteed unique IDs independent of names

**Change**: Generate random UUIDs

```typescript
const generateCaseId = (): string => {
  return crypto.randomUUID(); // "550e8400-e29b-41d4-a716-446655440000"
};
```

**Result**:
- `case_id`: `"550e8400-e29b-41d4-a716-446655440000"` (never shown to user)
- `case_name`: `"My Test Case"` (shown everywhere)

---

## Current Implementation (After Reverting)

✅ **Reverted** the Case ID input field I added (you don't need it)

**Current Behavior**:
1. User types Case Name: `"My Test Case"`
2. System auto-generates case_id: `"MY-TEST-CASE"`
3. Both get saved to backend
4. UI **should** display `case_name` only

**If UI is showing the wrong field**, we need to find where and fix it.

---

## Next Steps

1. **Please clarify**:
   - Can you edit Case Name initially?
   - Does it become locked after file selection?
   - Where do you see the "MY-TEST-CASE" version?

2. **I will**:
   - Search the UI code for where cases are displayed
   - Check if it's rendering `case_id` instead of `case_name`
   - Fix the display logic

3. **Quick Test**:
   - Try creating a case with name: `"test123"`
   - Check what gets displayed after saving
   - Report back what you see

---

## Code Status

✅ **Removed** Case ID input field (reverted to original)  
✅ **Kept** file sorting functionality in FileSelectorDialog  
✅ **Zero** compilation errors  

**Files Modified**:
- `CaseManagementModal.tsx` - Reverted Case ID field changes
- `FileSelectorDialog.tsx` - Kept sorting enhancements ✅

Ready for your clarification on the exact issue! 🔍
