# Case Names Disappearing After Page Refresh - Root Cause & Fix

## 🔴 Problem

After refreshing the browser page, case names disappear from the dropdown list in the Analysis tab.

---

## 🔍 Root Cause Analysis

### Why This Happens

1. **Redux State is NOT Persisted**
   - Redux store resets on every page refresh (no redux-persist)
   - Cases must be fetched from the backend API on every page load
   
2. **Backend Uses Cosmos DB Now**
   - Updated code reads from Cosmos DB `analysis_cases` collection
   - Old cases might still be in file-based storage (`/app/storage/cases/`)
   
3. **Data Migration Required**
   - If cases were created before the Cosmos DB migration
   - They exist in files but NOT in Cosmos DB
   - New code can't find them → dropdown appears empty

### Flow Diagram

```
Page Refresh
    ↓
Redux Store Resets (no data)
    ↓
Component Mounts
    ↓
dispatch(fetchCases())
    ↓
API Call: GET /pro-mode/cases
    ↓
Backend: case_service.list_cases()
    ↓
Reads from: Cosmos DB collection "analysis_cases"
    ↓
If empty → Returns []
    ↓
Redux: state.cases = [] 
    ↓
Dropdown: Shows "No cases found"
```

---

## ✅ Solution

### Step 1: Diagnose the Issue

Run the diagnostic script to check where your cases are:

```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939

# Set environment variables (if not already set)
export COSMOS_CONNECTION_STRING='your-connection-string'
export COSMOS_DATABASE_NAME='ContentProcessor'

# Run diagnostic
python check_case_storage.py
```

**What to look for:**
- ✅ Cases in OLD file storage → Need migration
- ✅ Cases in Cosmos DB → Check frontend
- ❌ No cases anywhere → Create test case

---

### Step 2: Fix Based on Diagnosis

#### Scenario A: Cases in Files, NOT in Cosmos DB

**Problem**: Cases stored in `/app/storage/cases/*.json` but Cosmos DB is empty

**Fix**: Run migration script

```bash
# Dry run first (check what will be migrated)
python migrate_cases_to_cosmos.py --dry-run

# Actually migrate
python migrate_cases_to_cosmos.py

# Verify
python check_case_storage.py
```

#### Scenario B: Cases in Cosmos DB, Still Disappearing

**Problem**: Database has cases but API not returning them

**Debug Steps**:

1. **Check Backend Logs**
   ```bash
   # In container
   kubectl logs <pod-name> | grep -i case
   
   # Look for:
   # - "[CaseService] Listing cases"
   # - "[CaseService] Found X cases"
   ```

2. **Check API Directly**
   ```bash
   curl -X GET "http://your-api-url/pro-mode/cases" \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

3. **Check Browser Console**
   - Open DevTools (F12)
   - Network tab
   - Refresh page
   - Find `/pro-mode/cases` request
   - Check response

**Possible Fixes**:

- **Empty response**: Cosmos DB connection issue
  ```bash
  # Check environment variables in container
  kubectl exec -it <pod-name> -- printenv | grep COSMOS
  ```

- **401/403 error**: Authentication issue
  ```bash
  # Check if token is being sent
  # Look in Network tab → Headers → Authorization
  ```

- **500 error**: Backend crash
  ```bash
  # Check backend logs for stack trace
  kubectl logs <pod-name> --tail=100
  ```

#### Scenario C: No Cases Exist

**Problem**: Fresh installation or all cases were deleted

**Fix**: Create a test case

1. Open the app
2. Go to Analysis tab
3. Click "New Case" or "Create Case"
4. Fill in:
   - Case ID: `TEST-001`
   - Case Name: `Test Case`
   - Select input files
   - Select schema
5. Save
6. Refresh page
7. Case should still appear

If it DOESN'T appear after refresh:
```bash
# Check if it was saved
python check_case_storage.py
```

---

### Step 3: Verify the Fix

After fixing, verify persistence:

1. **Create Test Case**
   ```
   Case ID: PERSIST-TEST-001
   Case Name: Persistence Test
   ```

2. **Note the Case ID**

3. **Refresh Browser** (Ctrl+R or Cmd+R)

4. **Check Dropdown**
   - ✅ Should show "Persistence Test"
   - ❌ If empty → Issue not fixed

5. **Check Database**
   ```bash
   python check_case_storage.py
   ```

6. **Redeploy App**
   ```bash
   # Trigger a full pod restart
   kubectl rollout restart deployment/<deployment-name>
   ```

7. **Check Again**
   - ✅ Case still appears → FIXED!
   - ❌ Case disappeared → Issue remains

---

## 🔧 Common Issues & Fixes

### Issue 1: Migration Script Fails

**Error**: `Cannot connect to Cosmos DB`

**Fix**:
```bash
# Check connection string format
echo $COSMOS_CONNECTION_STRING
# Should be: mongodb://accountname:key@accountname.mongo.cosmos.azure.com:10255/?ssl=true

# Test connection
python -c "
from pymongo import MongoClient
import certifi
import os
connstr = os.getenv('COSMOS_CONNECTION_STRING')
client = MongoClient(connstr, tlsCAFile=certifi.where())
print(client.server_info())
"
```

### Issue 2: Cases Saved to Files Instead of Cosmos DB

**Symptom**: New cases appear but disappear after refresh

**Diagnosis**: Backend using old file-based code

**Fix**:
```bash
# Verify the updated code is deployed
kubectl exec -it <pod-name> -- grep -A 5 "def __init__" /app/app/services/case_service.py

# Should show:
#   def __init__(self, cosmos_connstr: str, database_name: str):
#
# NOT:
#   def __init__(self, storage_path: Path):
```

If old code is running:
```bash
# Rebuild and redeploy
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### Issue 3: Frontend Not Fetching Cases

**Symptom**: Backend has cases but UI shows empty dropdown

**Debug**:
1. Open Browser DevTools (F12)
2. Console tab
3. Refresh page
4. Look for:
   ```
   [caseManagementService] Fetching cases from: /pro-mode/cases
   [caseManagementService] Fetch cases response: ...
   ```

**If no logs appear**:
- Component not mounting
- Redux dispatch not happening
- Check React component tree

**If error appears**:
- Check error message
- Usually authentication or network issue

### Issue 4: Authentication Errors

**Error**: `401 Unauthorized` or `403 Forbidden`

**Fix**:
```typescript
// Check if httpUtility is being used
// In caseManagementService.ts, verify:
import httpUtility from '../Services/httpUtility';

// NOT:
// import axios from 'axios';
```

---

## 📊 Monitoring & Verification

### Backend Monitoring

Add logging to verify cases are being saved:

```bash
# Watch backend logs
kubectl logs -f <pod-name> | grep -i "case"

# Should see:
# [CaseService] Creating case: CASE-001
# [CaseService] Case created successfully: CASE-001
# [CaseService] Listing cases (search=None, sort=updated_at)
# [CaseService] Found 1 cases
```

### Frontend Monitoring

Add console logs in CaseSelector component:

```typescript
useEffect(() => {
  console.log('[CaseSelector] Fetching cases on mount...');
  dispatch(fetchCases({}));
}, [dispatch]);

// After fetchCases completes
useEffect(() => {
  console.log('[CaseSelector] Cases loaded:', allCases.length);
  console.log('[CaseSelector] Cases:', allCases);
}, [allCases]);
```

### Database Monitoring

Check Cosmos DB directly:

```bash
python -c "
from pymongo import MongoClient
import certifi
import os

connstr = os.getenv('COSMOS_CONNECTION_STRING')
client = MongoClient(connstr, tlsCAFile=certifi.where())
db = client['ContentProcessor']
collection = db['analysis_cases']

print('Total cases:', collection.count_documents({}))
for doc in collection.find({}, {'case_id': 1, 'case_name': 1}):
    print(f\"  - {doc['case_id']}: {doc['case_name']}\")
"
```

---

## 🎯 Quick Checklist

Before troubleshooting, verify:

- [ ] COSMOS_CONNECTION_STRING environment variable is set
- [ ] Backend code updated to use Cosmos DB (not files)
- [ ] Backend deployed and running
- [ ] Migration script completed (if you had old cases)
- [ ] Browser cache cleared (Ctrl+Shift+R)
- [ ] No console errors in browser DevTools
- [ ] API endpoint responding (check Network tab)

---

## 🚀 Expected Behavior After Fix

1. **Create Case**
   - Click "New Case"
   - Fill in details
   - Save

2. **Case Appears in Dropdown**
   - Immediately shows in dropdown
   - Can be selected

3. **Refresh Page**
   - Page reloads
   - Dropdown loads
   - **Case still appears** ✅

4. **Redeploy App**
   - Pod restarts
   - Page reloads
   - **Case STILL appears** ✅

5. **Check Database**
   ```bash
   python check_case_storage.py
   # Shows case in Cosmos DB ✅
   ```

---

## 📞 Still Not Working?

If cases still disappear after following all steps:

1. **Capture Evidence**
   - Screenshot of dropdown (before and after refresh)
   - Screenshot of Network tab showing API response
   - Copy of backend logs
   - Output of `check_case_storage.py`

2. **Check These Files**
   - `/app/services/case_service.py` - Should use Cosmos DB
   - `/app/routers/case_management.py` - Should call case_service
   - Frontend: `CaseSelector.tsx` - Should dispatch fetchCases()
   - Frontend: `casesSlice.ts` - Should handle fetchCases response

3. **Verify End-to-End**
   ```bash
   # 1. Create case via API
   curl -X POST "http://api-url/pro-mode/cases" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer TOKEN" \
     -d '{
       "case_id": "TEST-001",
       "case_name": "Test",
       "input_file_names": ["test.pdf"],
       "reference_file_names": [],
       "schema_name": "TestSchema"
     }'
   
   # 2. Check database
   python check_case_storage.py
   
   # 3. Fetch via API
   curl "http://api-url/pro-mode/cases"
   
   # 4. If all work but UI doesn't → Frontend issue
   # 5. If API fails → Backend issue
   ```

---

## 📚 Related Documentation

- `CASE_COSMOS_DB_MIGRATION_COMPLETE.md` - Full migration guide
- `CASE_STORAGE_MIGRATION_SUMMARY.md` - Overview and deployment
- `CASE_NAME_CONSISTENCY_ANALYSIS.md` - Field naming analysis
- `migrate_cases_to_cosmos.py` - Migration script
- `check_case_storage.py` - Diagnostic script
- `test_case_cosmos_storage.py` - Test suite

---

**The root cause is always one of these:**
1. Cases not in Cosmos DB (need migration)
2. Backend not connecting to Cosmos DB (config issue)
3. Frontend not fetching cases (component/Redux issue)

Run the diagnostic script first to identify which one!
