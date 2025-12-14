# 🚨 CASE NAMES DISAPPEARING AFTER REFRESH - QUICK FIX GUIDE

## Problem
After refreshing the page, case names disappear from the dropdown list.

## Root Cause
The cases are likely still stored in **file-based storage** inside the Docker container, which gets destroyed on every deployment/restart.

---

## ✅ SOLUTION: 3-Step Fix

### Step 1: Diagnose the Issue

Run the diagnostic script to see where cases are stored:

```bash
# If inside container
python /app/diagnose_case_storage.py

# Or from project root
python diagnose_case_storage.py
```

**Expected Output:**
```
⚠️  ISSUE IDENTIFIED:
   • Old file-based cases exist
   • No cases in Cosmos DB
   • Cases disappear on refresh because files are in ephemeral container

✅ SOLUTION:
   Run migration script: python migrate_cases_to_cosmos.py
```

---

### Step 2: Verify Updated Code is Deployed

The updated `case_service.py` should use Cosmos DB, not file storage.

**Check deployment:**
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

**Verify the build completed successfully** (should show "Successfully tagged..." at the end)

---

### Step 3: Migrate Existing Cases (If Any)

If you had cases before, migrate them to Cosmos DB:

```bash
# Inside container or with COSMOS_CONNECTION_STRING set
python migrate_cases_to_cosmos.py

# This will:
# 1. Read cases from /app/storage/cases/*.json
# 2. Insert them into Cosmos DB
# 3. Preserve all data (names, files, schemas, history)
```

---

## 🔍 Quick Verification

After the fix, verify cases persist:

### Test 1: Create a Test Case
1. Open the app in browser
2. Go to Analysis tab
3. Create a new case (e.g., "Test-Refresh")
4. Note the case appears in dropdown ✅

### Test 2: Refresh Page
1. Press `F5` or `Ctrl+R` to refresh
2. **Case should still be in dropdown** ✅
3. If case disappeared ❌ → Cases not in Cosmos DB yet

### Test 3: Restart Container (Ultimate Test)
1. Restart the Docker container:
   ```bash
   kubectl rollout restart deployment/your-app-name
   # Or docker restart your-container
   ```
2. Wait for container to start
3. Open app in browser
4. **Cases should still be there** ✅

---

## 🐛 Troubleshooting

### Issue: Diagnostic script shows "Code is using OLD file-based storage"

**Fix:**
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
# Wait for build to complete
# Then redeploy the container
```

### Issue: "COSMOS_CONNECTION_STRING not set"

**Fix:**
```bash
# Set environment variable
export COSMOS_CONNECTION_STRING="mongodb://your-cosmos-db..."
export COSMOS_DATABASE_NAME="ContentProcessor"

# Or add to Kubernetes deployment:
kubectl set env deployment/your-app \
  COSMOS_CONNECTION_STRING="mongodb://..." \
  COSMOS_DATABASE_NAME="ContentProcessor"
```

### Issue: Migration script shows "No cases found"

**Explanation:**
- Either no cases existed (normal for fresh install)
- Or cases already migrated
- Or cases in different location

**Check manually:**
```bash
# Check file-based storage
ls -la /app/storage/cases/

# Check Cosmos DB
python -c "
from pymongo import MongoClient
import certifi
import os

connstr = os.getenv('COSMOS_CONNECTION_STRING')
client = MongoClient(connstr, tlsCAFile=certifi.where())
db = client['ContentProcessor']
cases = list(db['analysis_cases'].find({}, {'case_id': 1, 'case_name': 1}))
print(f'Cases in DB: {len(cases)}')
for case in cases:
    print(f\"  - {case['case_id']}: {case['case_name']}\")
"
```

### Issue: Cases appear but disappear after refresh

**This means:**
- ❌ Old code still running (file-based storage)
- ❌ OR Cosmos DB connection not working

**Fix:**
1. Verify deployment: `docker ps` (check image timestamp)
2. Check logs: `kubectl logs <pod-name>` or `docker logs <container>`
3. Look for errors about Cosmos DB connection
4. Verify environment variables are set in container

---

## 📋 Checklist for Complete Fix

After following all steps, verify:

- [ ] Diagnostic script shows: "Code is using NEW Cosmos DB storage"
- [ ] Environment variable `COSMOS_CONNECTION_STRING` is set
- [ ] Can create a new case
- [ ] Case appears in dropdown immediately
- [ ] **After page refresh, case still appears** ← KEY TEST
- [ ] After container restart, case still appears ← ULTIMATE TEST

---

## 🎯 Why This Happens

### Before Fix (File-Based Storage)
```
[Browser] → [API] → [File System: /app/storage/cases/CASE-001.json]
                            ↓
                     [Container destroyed on restart]
                            ↓
                     [Files LOST! 💥]
```

### After Fix (Cosmos DB Storage)
```
[Browser] → [API] → [Cosmos DB: analysis_cases collection]
                            ↓
                     [Permanent cloud storage ✅]
                            ↓
                     [Survives ALL restarts! 🎉]
```

---

## 🚀 Expected Behavior After Fix

1. **Create case** → Case saved to Cosmos DB
2. **Refresh page** → Case loads from Cosmos DB ✅
3. **Redeploy app** → Case loads from Cosmos DB ✅
4. **Restart container** → Case loads from Cosmos DB ✅
5. **Months later** → Case loads from Cosmos DB ✅

**Cases now persist FOREVER** (or until manually deleted).

---

## 📞 Still Not Working?

Run this complete diagnostic:

```bash
# 1. Check diagnostic
python diagnose_case_storage.py

# 2. Check case service code
grep -A 5 "class CaseManagementService" ./code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/services/case_service.py

# Should show:
# def __init__(self, cosmos_connstr: str, database_name: str):
#     self.client = MongoClient(...)  ← NEW CODE

# If you see:
# def __init__(self, storage_path: str):
#     self.storage_path = Path(...)  ← OLD CODE
# Then the new code is NOT deployed!

# 3. Check container environment
kubectl exec -it <pod-name> -- env | grep COSMOS

# 4. Check API logs
kubectl logs <pod-name> | grep -i "case\|cosmos"

# 5. Test API directly
curl -X GET "http://your-api/pro-mode/cases" -H "Authorization: Bearer $TOKEN"
```

Share the output and I can help debug further!

---

## 🎉 Success Indicators

When working correctly, you should see:

1. **In logs (container startup):**
   ```
   [CaseService] Initializing Cosmos DB connection
   [CaseService] Connected to database: ContentProcessor
   [CaseService] Collection: analysis_cases
   ```

2. **In browser (Network tab):**
   ```
   GET /pro-mode/cases
   Status: 200 OK
   Response: { "total": 3, "cases": [...] }
   ```

3. **In Cosmos DB (Data Explorer):**
   ```
   Database: ContentProcessor
   Collection: analysis_cases
   Documents: [Shows your cases]
   ```

---

**Good luck! The fix should take ~5 minutes once the correct code is deployed.**
