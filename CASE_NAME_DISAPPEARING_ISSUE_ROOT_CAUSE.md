# 🔍 Case Name Disappearing After Redeployment - Root Cause Analysis

## 🚨 Problem Statement

**Issue**: Case names disappear from the dropdown list after redeploying the application, even though the data should be persistent in Cosmos DB.

**Expected**: Cases should remain in Cosmos DB and be available after redeployment.

**Actual**: Cases disappear after redeployment.

---

## 🎯 Root Cause Identified

The issue is **NOT actually using Cosmos DB for case storage** despite what the documentation suggests!

### Current Implementation (File-Based Storage)

Looking at `/app/services/case_service.py`, the service is using **local filesystem storage**:

```python
class CaseManagementService:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            # Default to a 'cases' directory in the project root
            storage_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "storage",
                "cases"  # ← LOCAL FILESYSTEM!
            )
        
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Index file for quick lookups
        self.index_file = self.storage_path / "cases_index.json"
```

### Storage Location

Cases are stored in:
```
/app/storage/cases/
├── cases_index.json          # Index file with case metadata
├── CASE-001.json            # Individual case files
├── CASE-002.json
└── Q4-CONTRACT-REVIEW.json
```

---

## 💥 Why Cases Disappear on Redeployment

### Container/Pod Filesystem Behavior

When you redeploy an application in Azure/Kubernetes:

1. **Old container is destroyed** → All local filesystem data is lost
2. **New container is created** → Starts with a fresh filesystem
3. **`/app/storage/cases/` directory is empty** → No case files exist
4. **API returns empty array** → Dropdown shows no cases

### The Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ USER CREATES CASE                                            │
├─────────────────────────────────────────────────────────────┤
│ 1. POST /pro-mode/cases                                     │
│ 2. CaseManagementService.create_case()                      │
│ 3. Saved to: /app/storage/cases/MY-CASE.json               │
│ 4. Saved to: /app/storage/cases/cases_index.json           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ CONTAINER RESTART (Deployment/Update)                       │
├─────────────────────────────────────────────────────────────┤
│ ❌ Old container destroyed                                   │
│ ❌ /app/storage/ directory DELETED                           │
│ ✅ New container starts                                      │
│ ✅ /app/storage/cases/ is EMPTY                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ USER OPENS APP AFTER REDEPLOYMENT                           │
├─────────────────────────────────────────────────────────────┤
│ 1. GET /pro-mode/cases                                      │
│ 2. CaseManagementService.list_cases()                       │
│ 3. Reads from: /app/storage/cases/cases_index.json         │
│ 4. Index file is EMPTY or missing                          │
│ 5. Returns: { total: 0, cases: [] }                        │
│ 6. UI shows: "No cases available"                          │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Solution Options

### Option 1: Implement Cosmos DB Storage (Recommended)

**Change the service to use Cosmos DB instead of files**

#### Implementation Steps:

1. **Update `case_service.py` to use MongoDB API**:

```python
from pymongo import MongoClient
import certifi

class CaseManagementService:
    def __init__(self, cosmos_connstr: str, database_name: str):
        """Initialize with Cosmos DB connection."""
        self.client = MongoClient(cosmos_connstr, tlsCAFile=certifi.where())
        self.db = self.client[database_name]
        self.collection = self.db["analysis_cases"]
        
        # Create indexes
        self.collection.create_index("case_id", unique=True)
        self.collection.create_index("case_name")
        self.collection.create_index("created_at")
        self.collection.create_index("updated_at")
    
    async def create_case(self, request: CaseCreateRequest, user_id: str) -> AnalysisCase:
        """Create case in Cosmos DB."""
        now = datetime.utcnow()
        case_dict = {
            "_id": request.case_id,
            "case_id": request.case_id,
            "case_name": request.case_name,
            "description": request.description,
            "input_file_names": request.input_file_names,
            "reference_file_names": request.reference_file_names,
            "schema_name": request.schema_name,
            "analysis_history": [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "created_by": user_id,
            "last_run_at": None
        }
        
        result = self.collection.insert_one(case_dict)
        return AnalysisCase(**case_dict)
    
    async def list_cases(self, search: Optional[str] = None, 
                        sort_by: str = "updated_at", 
                        sort_desc: bool = True) -> List[AnalysisCase]:
        """List cases from Cosmos DB."""
        query = {}
        if search:
            query = {
                "$or": [
                    {"case_id": {"$regex": search, "$options": "i"}},
                    {"case_name": {"$regex": search, "$options": "i"}}
                ]
            }
        
        sort_order = -1 if sort_desc else 1
        cursor = self.collection.find(query).sort(sort_by, sort_order)
        
        cases = []
        for doc in cursor:
            cases.append(AnalysisCase(**doc))
        
        return cases
    
    async def get_case(self, case_id: str) -> Optional[AnalysisCase]:
        """Get case from Cosmos DB."""
        doc = self.collection.find_one({"case_id": case_id})
        if doc:
            return AnalysisCase(**doc)
        return None
    
    async def update_case(self, case_id: str, request: CaseUpdateRequest) -> Optional[AnalysisCase]:
        """Update case in Cosmos DB."""
        update_dict = {k: v for k, v in request.model_dump().items() if v is not None}
        update_dict["updated_at"] = datetime.utcnow().isoformat()
        
        result = self.collection.find_one_and_update(
            {"case_id": case_id},
            {"$set": update_dict},
            return_document=True
        )
        
        if result:
            return AnalysisCase(**result)
        return None
    
    async def delete_case(self, case_id: str) -> bool:
        """Delete case from Cosmos DB."""
        result = self.collection.delete_one({"case_id": case_id})
        return result.deleted_count > 0
```

2. **Update service initialization in `case_management.py`**:

```python
from app.appsettings import get_app_config

def get_case_service() -> CaseManagementService:
    """Get case service with Cosmos DB connection."""
    app_config = get_app_config()
    return CaseManagementService(
        cosmos_connstr=app_config.app_cosmos_connstr,
        database_name=app_config.app_cosmos_database
    )
```

---

### Option 2: Use Persistent Volume (Alternative)

**Mount a persistent volume to `/app/storage/cases/`**

This keeps the file-based approach but adds persistence:

```yaml
# In Kubernetes deployment
volumes:
  - name: case-storage
    azureFile:
      secretName: azure-storage-secret
      shareName: case-files
      readOnly: false

volumeMounts:
  - name: case-storage
    mountPath: /app/storage/cases
```

**Pros**: Minimal code changes
**Cons**: 
- Requires Azure File Share setup
- Not ideal for distributed/scaled deployments
- Slower than database access

---

### Option 3: Hybrid Approach

**Store cases in Cosmos DB, cache in Redis**

Best for high-performance scenarios with many concurrent users.

---

## 🎯 Recommended Fix: Option 1 (Cosmos DB)

### Why Cosmos DB?

1. ✅ **Persistent** - Survives deployments/restarts
2. ✅ **Scalable** - Works with multiple app instances
3. ✅ **Fast** - Indexed queries
4. ✅ **Consistent** - Single source of truth
5. ✅ **Already available** - You're already using it for files/schemas

### Implementation Priority

**HIGH PRIORITY** - This affects data persistence and user experience

---

## 📋 Migration Plan

If you implement Cosmos DB storage, you'll need to:

1. **Migrate existing cases** (if any are currently saved):
   ```python
   # One-time migration script
   import os
   import json
   from pymongo import MongoClient
   
   def migrate_cases_to_cosmos():
       storage_path = "/app/storage/cases"
       client = MongoClient(cosmos_connstr, tlsCAFile=certifi.where())
       collection = client[database_name]["analysis_cases"]
       
       # Read all existing case files
       for filename in os.listdir(storage_path):
           if filename.endswith('.json') and filename != 'cases_index.json':
               with open(os.path.join(storage_path, filename), 'r') as f:
                   case_data = json.load(f)
                   collection.insert_one(case_data)
       
       print(f"Migrated {collection.count_documents({})} cases to Cosmos DB")
   ```

2. **Update service initialization**
3. **Test with new cases**
4. **Deploy**

---

## 🔍 How to Verify Current State

### Check if cases exist in filesystem:

```bash
# SSH into container
kubectl exec -it <pod-name> -- /bin/bash

# Check storage directory
ls -la /app/storage/cases/

# View index file
cat /app/storage/cases/cases_index.json
```

### Check Cosmos DB:

```python
from pymongo import MongoClient
import certifi

client = MongoClient(connection_string, tlsCAFile=certifi.where())
db = client[database_name]
collection = db["analysis_cases"]

# Check if collection exists
print("Collections:", db.list_collection_names())

# Check case count
print("Case count:", collection.count_documents({}))

# List all cases
for case in collection.find():
    print(case["case_name"])
```

---

## 📊 Comparison: Current vs. Recommended

| Aspect | Current (Files) | Recommended (Cosmos DB) |
|--------|----------------|------------------------|
| **Persistence** | ❌ Lost on redeploy | ✅ Survives restarts |
| **Scalability** | ❌ Single instance only | ✅ Multi-instance ready |
| **Performance** | ⚠️ Filesystem I/O | ✅ Indexed queries |
| **Backup** | ❌ Manual | ✅ Automatic |
| **Search** | ⚠️ Load all files | ✅ Database queries |
| **Concurrency** | ❌ File locking issues | ✅ Transaction support |

---

## 🎯 Summary

**Root Cause**: Cases are stored in container's local filesystem (`/app/storage/cases/`), which is **ephemeral** and gets deleted on every redeployment.

**Fix**: Implement Cosmos DB storage using MongoDB API (same pattern as files/schemas/predictions).

**Impact**: After implementation, cases will persist across deployments just like files and schemas do.

---

## Next Steps

Would you like me to:
1. ✅ Implement the Cosmos DB storage for cases?
2. 📝 Create a migration script for existing cases?
3. 🧪 Add tests for the new implementation?

Let me know and I'll proceed with the implementation!
