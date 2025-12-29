# Case Selection Auto-Population Debug Guide

## Problem
When selecting a case from the dropdown, the Start Analysis button should become enabled because:
1. Case selection should auto-populate input files
2. Case selection should auto-populate the schema
3. With schema + files selected, `canStartAnalysis` should be `true`

If the button remains disabled after case selection, there's a failure in this chain.

---

## Debugging Changes Applied

### 1. Enhanced Reason Display
**File:** `PredictionTab.tsx`

**What it does:**
- Shows exactly WHY the Start Analysis button is disabled
- Displays under the button when `!canStartAnalysis`

**What to look for:**
```
Cannot start analysis: No schema selected (open the Schema tab) · No input files selected (open the Files tab)
```

This tells you which part of the auto-population failed.

---

### 2. Case Auto-Population Logging
**File:** `PredictionTab.tsx` (useEffect lines ~210-340)

**Enhanced logs added:**
```javascript
// When case is selected:
[PredictionTab] 📁 Case selected, auto-populating files and schema: <case_id>

// Race condition detection:
[PredictionTab] ⚠️⚠️⚠️ RACE CONDITION DETECTED: Files not loaded yet!
[PredictionTab] ⚠️⚠️⚠️ RACE CONDITION DETECTED: Schemas not loaded yet!

// What the case expects:
[PredictionTab] 🔍 Case definition: {
  input_file_names: [...],
  reference_file_names: [...],
  schema_name: "..."
}

// What's available in Redux:
[PredictionTab] 🔍 Available files/schemas in Redux: {
  allInputFiles: [...],
  allReferenceFiles: [...],
  allSchemas: [...]
}

// Before dispatch:
[PredictionTab] ✅ Auto-populating (BEFORE dispatch): {
  inputFileIds: 2,
  referenceFileIds: 1,
  schemaId: "abc-123",
  foundSchema: true
}

// If nothing matched:
[PredictionTab] ⚠️ Could not find any input files matching case definition!
[PredictionTab] ⚠️ Could not find schema matching case definition!
[PredictionTab] ⚠️ Skipping setSelectedInputFiles - no matching files found
[PredictionTab] ⚠️ Skipping setActiveSchema - no matching schema found

// When dispatching:
[PredictionTab] 🚀 Dispatching setSelectedInputFiles with: [...]
[PredictionTab] 🚀 Dispatching setActiveSchema with: <schema_id>
```

---

### 3. Redux State Change Tracking
**File:** `PredictionTab.tsx`

**New useEffects added:**
```javascript
useEffect(() => {
  console.log('[PredictionTab] 🔄 Redux state change detected - selectedInputFileIds:', selectedInputFileIds);
}, [selectedInputFileIds]);

useEffect(() => {
  console.log('[PredictionTab] 🔄 Redux state change detected - activeSchemaId:', activeSchemaId);
}, [activeSchemaId]);
```

**What to look for:**
- After dispatching `setSelectedInputFiles`, you should see:
  ```
  [PredictionTab] 🔄 Redux state change detected - selectedInputFileIds: ["file-1", "file-2"]
  ```
- After dispatching `setActiveSchema`, you should see:
  ```
  [PredictionTab] 🔄 Redux state change detected - activeSchemaId: "schema-abc"
  ```

If these logs DON'T appear after the dispatches, Redux is not updating → **Redux bug**.

---

## Step-by-Step Reproduction

1. **Open the app** and navigate to Pro Mode
2. **Open browser console** (F12 → Console tab)
3. **Filter logs** by typing `[PredictionTab]` in the console filter
4. **Select a case** from the Case Management dropdown
5. **Watch the logs** unfold in this sequence:

### Expected Flow (Success)

```
[PredictionTab] 📁 Case selected, auto-populating files and schema: <case_id>
[PredictionTab] 🔍 Case definition: { input_file_names: [...], schema_name: "..." }
[PredictionTab] 🔍 Available files/schemas in Redux: { allInputFiles: [...], allSchemas: [...] }
[PredictionTab] ✅ Auto-populating (BEFORE dispatch): { inputFileIds: 2, schemaId: "abc", foundSchema: true }
[PredictionTab] 🚀 Dispatching setSelectedInputFiles with: [...]
[PredictionTab] 🚀 Dispatching setActiveSchema with: abc
[PredictionTab] 🔄 Redux state change detected - selectedInputFileIds: [...]
[PredictionTab] 🔄 Redux state change detected - activeSchemaId: abc
```

**Result:** Start Analysis button becomes enabled ✅

---

### Problem Flow 1: Race Condition (Files Not Loaded)

```
[PredictionTab] 📁 Case selected, auto-populating files and schema: <case_id>
[PredictionTab] ⚠️⚠️⚠️ RACE CONDITION DETECTED: Files not loaded yet!
[PredictionTab] 🔍 Available files/schemas in Redux: { allInputFiles: [], allSchemas: [...] }
[PredictionTab] ⚠️ Could not find any input files matching case definition!
[PredictionTab] ⚠️ Skipping setSelectedInputFiles - no matching files found
```

**Then later (when files load):**
```
[PredictionTab] 📁 Case selected, auto-populating files and schema: <case_id>
[PredictionTab] 🔍 Available files/schemas in Redux: { allInputFiles: [...], allSchemas: [...] }
[PredictionTab] ✅ Auto-populating (BEFORE dispatch): { inputFileIds: 2, schemaId: "abc" }
[PredictionTab] 🚀 Dispatching setSelectedInputFiles with: [...]
```

**Expected:** useEffect re-runs when files load → button becomes enabled ✅

**If button stays disabled:** useEffect did NOT re-run → **dependency array bug**

---

### Problem Flow 2: Name Mismatch (Files Loaded but Names Don't Match)

```
[PredictionTab] 📁 Case selected, auto-populating files and schema: <case_id>
[PredictionTab] 🔍 Case definition: { input_file_names: ["invoice.pdf", "contract.pdf"] }
[PredictionTab] 🔍 Available files/schemas in Redux: { 
  allInputFiles: [
    { id: "1", fileName: "123-invoice.pdf", name: "invoice.pdf" },
    { id: "2", fileName: "456-contract.pdf", name: "contract.pdf" }
  ]
}
[PredictionTab] ⚠️ Could not find any input files matching case definition!
```

**Problem:** File names in the case don't match `fileName` or `name` properties

**Fix:** Check the case data format vs. file object format

---

### Problem Flow 3: Redux Not Updating (Bug in proModeStore)

```
[PredictionTab] 🚀 Dispatching setSelectedInputFiles with: ["file-1", "file-2"]
[PredictionTab] 🚀 Dispatching setActiveSchema with: abc-123
```

**BUT NO FOLLOW-UP LOGS:**
```
❌ MISSING: [PredictionTab] 🔄 Redux state change detected - selectedInputFileIds: ...
❌ MISSING: [PredictionTab] 🔄 Redux state change detected - activeSchemaId: ...
```

**Problem:** Redux actions are being dispatched but state is NOT updating

**Fix:** Check `proModeStore.ts` → `analysisContextSlice` → ensure reducers are properly handling the actions

---

## Common Root Causes

### 1. **Files/Schemas Not Loaded (Race Condition)**
- **Symptom:** Race condition warnings in logs
- **Why:** Case selected before files/schemas finish loading
- **Fix:** Should auto-resolve when files/schemas load (useEffect re-runs)
- **If it doesn't:** Dependency array missing `allInputFiles`/`allSchemas`

### 2. **Name Mismatch (Case Data Format)**
- **Symptom:** "Could not find any input files matching case definition"
- **Why:** Case stores file names as "invoice.pdf" but files have "123-invoice.pdf"
- **Fix:** Update case creation to use consistent naming, or update matching logic

### 3. **Redux Actions Not Working**
- **Symptom:** Dispatches logged but no Redux state change logs
- **Why:** Bug in Redux reducer or action not exported properly
- **Fix:** Check `proModeStore.ts` and ensure actions are in `extraReducers`

### 4. **Group Mismatch**
- **Symptom:** Warning toast: "This case was created for group X. You are in group Y."
- **Why:** Case belongs to different group, files not available
- **Fix:** Switch to correct group or re-create case in current group

---

## Quick Diagnostic Checklist

After selecting a case, check these in console:

- [ ] `[PredictionTab] 📁 Case selected` — Case selection detected
- [ ] `[PredictionTab] 🔍 Available files/schemas` — Files/schemas present in Redux
- [ ] `[PredictionTab] 🚀 Dispatching setSelectedInputFiles` — Redux action dispatched
- [ ] `[PredictionTab] 🔄 Redux state change detected - selectedInputFileIds` — Redux updated
- [ ] `Cannot start analysis: ...` message under button (if disabled) — Shows exact reason

---

## Next Steps Based on Logs

### If you see race condition warnings:
✅ **This is expected!** Wait 1-2 seconds for files/schemas to load. The useEffect should re-run automatically.

### If files/schemas are loaded but no matches found:
🔍 **Compare the case definition vs. available files** in the logs. File names must match exactly.

### If dispatches happen but no Redux state changes:
🐛 **Redux bug** — Check `proModeStore.ts` reducers and ensure actions are properly handled.

### If button is still disabled after all looks good:
🔍 **Check the "Cannot start analysis" message** under the button for the exact reason.

---

## Files Modified

1. `src/ProModeComponents/PredictionTab.tsx`
   - Added `disableReasons` array computation
   - Added helper message rendering under Start Analysis button
   - Enhanced case auto-population logging (useEffect ~210-340)
   - Added Redux state change tracking (useEffects for selectedInputFileIds/activeSchemaId)

---

## Viewing the Logs

**Chrome/Edge:**
1. F12 → Console tab
2. Filter: `[PredictionTab]`
3. Select a case from dropdown
4. Watch logs unfold

**Look for:**
- ⚠️ warnings → Something failed
- ✅ success markers → Things working
- 🚀 dispatches → Redux actions sent
- 🔄 state changes → Redux updated

---

## Expected Timeline

When you select a case:

| Time | Event | Log |
|------|-------|-----|
| 0ms | Case selected | `📁 Case selected` |
| 1ms | Check files/schemas | `🔍 Available files/schemas in Redux` |
| 2ms | Match files | `✅ Auto-populating (BEFORE dispatch)` |
| 3ms | Dispatch Redux | `🚀 Dispatching setSelectedInputFiles` |
| 5ms | Redux updates | `🔄 Redux state change detected` |
| 10ms | Button re-renders | Button becomes enabled ✅ |

If Redux state changes don't happen within ~10ms of dispatches, there's a Redux bug.

---

## Testing the Fix

1. Refresh the page (clear any stale state)
2. Navigate to Pro Mode → Prediction tab
3. Select a case from the dropdown
4. Check console logs for the expected flow
5. Verify Start Analysis button becomes enabled
6. If disabled, check the helper message under the button

---

## Contact for Help

If after following this guide the issue persists:

1. Copy the full console log output (filtered by `[PredictionTab]`)
2. Include the "Cannot start analysis: ..." message from the UI
3. Note which flow pattern you're seeing (race condition / name mismatch / Redux bug)
4. Share the case definition (from logs: `🔍 Case definition`)
5. Share available files/schemas (from logs: `🔍 Available files/schemas in Redux`)
