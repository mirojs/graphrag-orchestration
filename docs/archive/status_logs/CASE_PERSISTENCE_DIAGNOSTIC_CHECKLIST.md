# 🔍 Case Persistence - Post-Deployment Diagnostic Checklist

## After Deployment, Check These in Browser Developer Tools

### 1. Browser Console Logs (Expected Output)

When you refresh the Pro Mode page, you should see this sequence:

```
[ProModePage] useEffect - component mounted
[ProModePage] Loading cases for case management dropdown
[fetchCases] Starting fetch with search: undefined
[caseManagementService] Fetching cases from: /pro-mode/cases
[caseManagementService] Fetch cases response: {data: {total: X, cases: [...]}}
[caseManagementService] Response data type: object
[caseManagementService] Response data: {"total":X,"cases":[...]}
[caseManagementService] Standard cases array with X cases
[fetchCases] Fetch result: {cases: Array(X)}
[fetchCases] Cases count: X
[fetchCases] Returning X cases
```

**If you see this, cases ARE being loaded!** ✅

---

### 2. Network Tab Check

#### Expected Request:
- **URL**: `/pro-mode/cases`
- **Method**: GET
- **Status**: 200 OK
- **Timing**: Should happen within 1-2 seconds of page load

#### Expected Response:
```json
{
  "total": 2,
  "cases": [
    {
      "case_id": "your-case-id",
      "case_name": "Your Case Name",
      "description": "...",
      "schema_name": "...",
      "input_file_names": [...],
      "reference_file_names": [...],
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

**If you see this response, the backend is working!** ✅

---

### 3. Redux DevTools Check

Open Redux DevTools and check:

#### Action Dispatched:
```
cases/fetchAll/pending
cases/fetchAll/fulfilled
```

#### State After Fetch:
```json
{
  "cases": {
    "cases": [
      {
        "case_id": "...",
        "case_name": "...",
        ...
      }
    ],
    "loading": false,
    "error": null
  }
}
```

**If the `cases` array is populated, Redux state is correct!** ✅

---

### 4. UI Dropdown Check

Navigate to **Prediction Tab** → Check **Case Selector Dropdown**

#### Expected Behavior:
- Dropdown should show: "Select a case..."
- Click dropdown → Should show list of cases
- Each case should display `case_name`
- Selecting a case should populate the form

**If dropdown shows cases, the UI is working!** ✅

---

## 🚨 Troubleshooting If Cases Still Disappear

### Scenario 1: No API Call in Network Tab

**Problem**: `/pro-mode/cases` request never happens after page refresh

**Possible Causes**:
1. ProModePage component not mounting
2. useEffect not running (check dependencies)
3. dispatch function undefined

**Debug**:
```javascript
// Check in console:
console.log('[ProModePage] dispatch:', typeof dispatch);
console.log('[ProModePage] fetchCases:', typeof fetchCases);
```

**Fix**: Ensure ProModePage is properly wrapped with Redux Provider

---

### Scenario 2: API Call Fails (4xx/5xx Error)

**Problem**: Network tab shows error response

**Possible Causes**:
1. Backend not deployed correctly
2. Authentication issue
3. Cosmos DB connection issue

**Debug**:
- Check response error message in Network tab
- Check backend logs for errors
- Verify Cosmos DB connection string

**Fix**: Check backend deployment and configuration

---

### Scenario 3: API Returns Empty Cases

**Problem**: Response is `{"total": 0, "cases": []}`

**Possible Causes**:
1. No cases created yet
2. Cases exist but query is filtering them out
3. Wrong Cosmos DB container name

**Debug**:
```python
# Check backend logs for:
[CaseManagementService] Listing cases...
[CaseManagementService] Found X cases
```

**Fix**: 
- Create a test case
- Check Cosmos DB container name (should be `cases_pro`)
- Verify cases collection in Azure portal

---

### Scenario 4: Redux State Not Updated

**Problem**: Network shows success, but Redux state is empty

**Possible Causes**:
1. Reducer not updating state correctly
2. Response format mismatch
3. Type casting issue

**Debug**:
```javascript
// Check console logs:
[caseManagementService] Standard cases array with X cases
[fetchCases] Returning X cases
```

If logs show cases but Redux state is empty, there's a reducer issue.

**Fix**: Check `fetchCases.fulfilled` reducer in `casesSlice.ts`

---

### Scenario 5: Dropdown Still Empty

**Problem**: Redux state has cases, but dropdown is empty

**Possible Causes**:
1. Case field names mismatch (case_id vs id)
2. Selector filtering out all cases
3. Dropdown disabled (loading stuck)

**Debug**:
```javascript
// In CaseSelector component, check:
console.log('[CaseSelector] allCases:', allCases);
console.log('[CaseSelector] filteredCases:', filteredCases);
console.log('[CaseSelector] loading:', loading);
```

**Fix**: 
- Ensure backend returns `case_id` and `case_name`
- Check selector logic in `casesSlice.ts`
- Verify `loading` flag is set to `false` after fetch

---

## 📝 Comparison: Schemas vs Cases (Both Should Work Identically)

| Aspect | Schemas | Cases | Expected |
|--------|---------|-------|----------|
| **API Endpoint** | `/pro-mode/schemas` | `/pro-mode/cases` | Both 200 OK |
| **Response Format** | `{schemas: [...]}` or `{data: [...]}` | `{cases: [...]}` | Both valid |
| **Redux Action** | `fetchSchemas` | `fetchCases` | Both dispatch |
| **Page Load Timing** | On mount | On mount ✅ FIXED | Both immediate |
| **State Location** | `proModeStore` | `casesSlice` | Different but both work |
| **Dropdown Population** | Works ✅ | Should work ✅ | Both persist |

---

## ✅ Success Criteria

After deployment, you should be able to:

1. ✅ Refresh Pro Mode page
2. ✅ See console logs showing case fetch
3. ✅ See Network request to `/pro-mode/cases` with 200 status
4. ✅ See Redux state populated with cases
5. ✅ Navigate to Prediction tab
6. ✅ Open Case Selector dropdown
7. ✅ See list of cases in dropdown
8. ✅ Select a case and see it persist
9. ✅ Refresh page again
10. ✅ Cases still appear in dropdown ✨

---

## 🔧 Files Modified in This Fix

1. **ProModePage/index.tsx** (Line 10, 126, 140-144)
   - Added `useDispatch` import
   - Added `fetchCases` import
   - Added case loading in useEffect

2. **caseManagementService.ts** (Lines 22-57)
   - Added robust response format handling
   - Added detailed console logging
   - Added fallback for unexpected formats

3. **casesSlice.ts** (Lines 107-136)
   - Added detailed console logging
   - Added defensive checks for array
   - Added graceful error handling for server errors

---

## 🎯 Root Cause Summary

**The issue was NEVER about backend storage or API!**

It was a **React component lifecycle** issue:
- ProModePage default tab is 'files'
- PredictionTab (with CaseSelector) only mounts when tab is selected
- CaseSelector's useEffect only runs when component mounts
- Therefore, cases were never loaded on page refresh!

**The fix**: Load cases at ProModePage level (just like schemas), not at CaseSelector level.

---

## 📞 If Issues Persist

If cases still disappear after this deployment, capture:

1. Full browser console output (from page load to dropdown check)
2. Network tab screenshot (showing `/pro-mode/cases` request/response)
3. Redux DevTools state screenshot (showing `cases` state)
4. Any error messages in backend logs

This will help identify the exact failure point in the data flow pipeline.

---

**Expected Result**: Cases should now persist through page refresh, just like schemas! 🎉
