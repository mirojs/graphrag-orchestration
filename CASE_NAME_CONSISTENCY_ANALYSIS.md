# Case Name Consistency Analysis

## 🔍 Current State

The codebase **IS CONSISTENT** across frontend and backend:

### Backend (Python) - Snake Case ✅
```python
# Models use snake_case
class AnalysisCase(BaseModel):
    case_id: str
    case_name: str  # ← Snake case
    description: Optional[str]
```

### Frontend (TypeScript) - Snake Case ✅
```typescript
// Interfaces use snake_case to match API
export interface AnalysisCase {
  case_id: string;
  case_name: string;  // ← Snake case
  description?: string;
}
```

### API Responses - Snake Case ✅
```json
{
  "case_id": "CASE-001",
  "case_name": "My Test Case",
  "description": "Test"
}
```

---

## ⚠️ Potential Sources of Confusion

### 1. **Local Variable Names** (NOT an Issue)

In React components, **local variables** use camelCase (TypeScript convention):

```typescript
// ✅ This is CORRECT - it's just a local variable
const [caseName, setCaseName] = useState('');

// But when accessing the object, we use snake_case
setCaseName(existingCase.case_name);  // ← Accessing snake_case property

// And when creating the request object
const request = {
  case_name: caseName  // ← Sending snake_case to API
};
```

This is **NOT** an inconsistency - it's normal JavaScript/TypeScript conventions:
- **Object properties** from API: `case_name` (snake_case)
- **Local variables**: `caseName` (camelCase)

### 2. **Old File-Based Storage** (If Not Migrated)

If you have old cases stored in files that haven't been migrated to Cosmos DB:

**File-based** (OLD):
```json
// /app/storage/cases/CASE-001.json
{
  "case_id": "CASE-001",
  "case_name": "My Case",
  ...
}
```

**Cosmos DB** (NEW):
```json
// In Cosmos DB collection
{
  "_id": "CASE-001",
  "case_id": "CASE-001",
  "case_name": "My Case",
  ...
}
```

**Solution**: Run the migration script:
```bash
python migrate_cases_to_cosmos.py
```

### 3. **Browser Cache**

Old API responses might be cached in your browser.

**Solution**: Hard refresh
- Chrome/Edge: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
- Firefox: `Ctrl+F5` (Windows/Linux) or `Cmd+Shift+R` (Mac)

---

## 🧪 How to Verify Consistency

### Test 1: Check API Response

```bash
# Make a direct API call
curl -X GET "http://your-api-url/pro-mode/cases" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Expected output:
{
  "total": 1,
  "cases": [
    {
      "case_id": "CASE-001",
      "case_name": "Test Case",  ← Snake case
      ...
    }
  ]
}
```

### Test 2: Check Cosmos DB

```bash
# Run the migration script in check mode
python migrate_cases_to_cosmos.py

# Look at the output - it should show case_name (snake_case)
```

### Test 3: Check Browser Console

1. Open browser DevTools (F12)
2. Go to Network tab
3. Reload the page
4. Click on the `/pro-mode/cases` request
5. Check the Response tab

Expected:
```json
{
  "case_name": "My Case"  ← Should be snake_case
}
```

---

## 🐛 If You're Seeing Inconsistencies

### Symptom: Some responses have `caseName` (camelCase)

**Possible Causes**:
1. ❌ Manual data entry directly to database with wrong field names
2. ❌ Custom serialization somewhere converting snake_case to camelCase
3. ❌ Middleware/proxy converting field names

**Debug Steps**:

#### Step 1: Check Raw Database Data
```python
from pymongo import MongoClient
import os
import certifi

connstr = os.getenv("COSMOS_CONNECTION_STRING")
client = MongoClient(connstr, tlsCAFile=certifi.where())
db = client["ContentProcessor"]
collection = db["analysis_cases"]

# Check field names
for doc in collection.find().limit(1):
    print(doc.keys())  # Should show: case_id, case_name (not caseName)
```

#### Step 2: Check API Middleware
```bash
# Search for any camelCase conversion
cd code/content-processing-solution-accelerator/src/ContentProcessorAPI
grep -r "alias_generator" .
grep -r "camelize" .
grep -r "camelCase" .
```

#### Step 3: Check FastAPI Response Model
```python
# In case_management.py, verify the response model
@router.get("/pro-mode/cases")
async def list_cases():
    # ...
    return CaseListResponse(cases=cases)  # ← Check this model
```

---

## ✅ Verification Checklist

After deployment, verify:

- [ ] API returns `case_name` (not `caseName`)
- [ ] Database contains `case_name` field
- [ ] Frontend correctly displays case names
- [ ] Creating new case works with `case_name`
- [ ] Updating case name works
- [ ] Case names persist after redeployment

---

## 📋 Field Name Reference

### All Case Fields (Official Names)

```python
class AnalysisCase:
    case_id: str                    # ✅ Snake case
    case_name: str                  # ✅ Snake case  
    description: Optional[str]      # ✅ Snake case
    input_file_names: List[str]     # ✅ Snake case
    reference_file_names: List[str] # ✅ Snake case
    schema_name: str                # ✅ Snake case
    analysis_history: List          # ✅ Snake case
    created_at: datetime            # ✅ Snake case
    updated_at: datetime            # ✅ Snake case
    created_by: str                 # ✅ Snake case
    last_run_at: Optional[datetime] # ✅ Snake case
```

### Frontend Interface (Matches Backend)

```typescript
interface AnalysisCase {
  case_id: string;                    // ✅ Snake case
  case_name: string;                  // ✅ Snake case
  description?: string;               // ✅ Snake case
  input_file_names: string[];         // ✅ Snake case
  reference_file_names: string[];     // ✅ Snake case
  schema_name: string;                // ✅ Snake case
  analysis_history: AnalysisRun[];    // ✅ Snake case
  created_at: string;                 // ✅ Snake case
  updated_at: string;                 // ✅ Snake case
  created_by: string;                 // ✅ Snake case
  last_run_at?: string;               // ✅ Snake case
}
```

---

## 🎯 Summary

### What IS Consistent ✅
- Database field names: `case_name`
- API request/response: `case_name`
- TypeScript interfaces: `case_name`
- Model definitions: `case_name`

### What Looks Different (But Is Normal) ✅
- React component variables: `caseName` (local variable, different from object property)
- This is **standard practice** in JavaScript/TypeScript

### If You See `caseName` in API Responses ❌
This would be a **real problem**. Follow the debug steps above.

---

## 🔧 Quick Fix Commands

### 1. Re-deploy with Fresh Code
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### 2. Check Database Consistency
```bash
python migrate_cases_to_cosmos.py  # Shows current data
```

### 3. Clear Browser Cache
- Hard refresh: `Ctrl+Shift+R`
- Or clear site data in DevTools → Application → Storage

---

## 📞 Still Seeing Issues?

If you're still seeing inconsistencies:

1. **Capture Evidence**:
   - Screenshot of Network tab showing API response
   - Screenshot of console showing the object
   - Copy/paste of the exact error message

2. **Check These Files**:
   - `/app/models/case_model.py` - Model definitions
   - `/app/services/case_service.py` - Database operations
   - `/app/routers/case_management.py` - API endpoints

3. **Verify Deployment**:
   - Confirm new code was deployed (check container logs)
   - Confirm Cosmos DB migration ran
   - Confirm no old file-based storage is being used

The system is designed to be 100% consistent with `case_name` (snake_case) throughout.
