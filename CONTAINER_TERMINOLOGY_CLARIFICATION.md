# 📦 Container Terminology Clarification

## 🔍 Two Different "Containers" - Explained

### Container Type 1: **Docker/Kubernetes Container** (Application Runtime)
**This is what gets destroyed on redeployment!**

A Docker/Kubernetes container is like a **lightweight virtual machine** that runs your Python/Node.js application:

```
┌─────────────────────────────────────────────────────────┐
│  Docker/Kubernetes Container (Pod)                      │
│  ┌───────────────────────────────────────────────────┐ │
│  │ Your Python Application                           │ │
│  │ - FastAPI backend                                 │ │
│  │ - case_service.py                                 │ │
│  │                                                    │ │
│  │ Local Filesystem (TEMPORARY):                     │ │
│  │ /app/                                             │ │
│  │   ├── main.py                                     │ │
│  │   ├── storage/  ← This directory is TEMPORARY!   │ │
│  │   │   └── cases/                                  │ │
│  │   │       ├── cases_index.json                    │ │
│  │   │       ├── CASE-001.json                       │ │
│  │   │       └── CASE-002.json                       │ │
│  └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**What happens on redeployment:**

```
OLD DEPLOYMENT:
Container A (Running)
  /app/storage/cases/
    ├── CASE-001.json  ← Your saved cases
    └── CASE-002.json

       ↓ CODE UPDATE / REDEPLOY ↓

Container A → DESTROYED (deleted completely) ❌
  /app/storage/cases/ → GONE! All files deleted!

       ↓ NEW CONTAINER STARTS ↓

NEW DEPLOYMENT:
Container B (Fresh Start)
  /app/storage/cases/
    └── (empty directory) ← No case files!
```

---

### Container Type 2: **Azure Storage Container** (Blob Storage)
**This is PERSISTENT storage - data survives redeployments!**

An Azure Storage Container is a **folder in Azure Blob Storage** that stores files permanently:

```
┌─────────────────────────────────────────────────────────┐
│  Azure Storage Account                                  │
│  ┌───────────────────────────────────────────────────┐ │
│  │ Blob Container: "input-files"                     │ │
│  │   ├── invoice.pdf                                 │ │
│  │   ├── contract.pdf                                │ │
│  │   └── document.pdf                                │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ Blob Container: "reference-files"                 │ │
│  │   └── template.pdf                                │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ Blob Container: "schemas"                         │ │
│  │   └── my-schema.json                              │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ Blob Container: "predictions"                     │ │
│  │   └── prediction-001.json                         │ │
│  └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**What happens on redeployment:**
- ✅ **Files persist** - They remain in Azure Storage
- ✅ **Accessible from any container** - New app container can access same files
- ✅ **Survives crashes/restarts** - Data is safe

---

## 🔑 Key Differences

| Aspect | Docker Container Filesystem | Azure Storage Container |
|--------|---------------------------|------------------------|
| **Location** | Inside the app container (`/app/storage/`) | Azure cloud (Blob Storage) |
| **Persistence** | ❌ Temporary - deleted on redeploy | ✅ Permanent - survives forever |
| **Access** | Only from that specific container | From anywhere (API, multiple apps) |
| **Lifetime** | Lives and dies with container | Independent of app deployments |
| **Purpose** | Temporary app files, logs | Long-term data storage |
| **Cost** | Free (part of container) | Paid (Azure Storage costs) |

---

## 📂 What "File-Based Storage" Means

When I said **"file-based storage"**, I meant:

### Current Implementation (File-Based):
```python
# case_service.py saves to LOCAL filesystem
def _save_case_to_file(self, case: AnalysisCase):
    # This path is INSIDE the Docker container
    case_file = self.storage_path / f"{case_id}.json"
    #           ↑
    #           This is: /app/storage/cases/CASE-001.json
    #           Located: INSIDE the Docker container
    #           Persistence: TEMPORARY (deleted on redeploy)
    
    with open(case_file, 'w') as f:
        json.dump(case_dict, f)
```

**Storage location:**
```
Docker Container Filesystem (Temporary):
/app/
  └── storage/
      └── cases/
          ├── cases_index.json
          └── CASE-001.json  ← Saved here (TEMPORARY)
```

**Problem:** This is **inside** the Docker container's filesystem, which is destroyed on every redeployment!

---

### Recommended: Database Storage (Cosmos DB)

Instead of saving to files, save to Cosmos DB (MongoDB):

```python
# Recommended: Save to Cosmos DB
def create_case(self, request: CaseCreateRequest):
    # Connect to Cosmos DB (MongoDB API)
    collection = self.db["analysis_cases"]
    
    # Insert into database
    collection.insert_one({
        "_id": request.case_id,
        "case_name": request.case_name,
        # ... other fields
    })
    #  ↑
    #  Saved to: Cosmos DB (cloud database)
    #  Persistence: PERMANENT (survives redeployments)
```

**Storage location:**
```
Azure Cosmos DB (Permanent):
Database: content-processing
  └── Collection: analysis_cases
      ├── { "_id": "CASE-001", "case_name": "Q4 Review", ... }
      └── { "_id": "CASE-002", "case_name": "Audit 2025", ... }
```

**Benefit:** Data is stored in Azure cloud, **completely separate** from your app container!

---

## 🏗️ Visual Architecture Comparison

### Current Architecture (Why Cases Disappear):

```
┌──────────────────────────────────────────────────────────┐
│  Azure Kubernetes Service (AKS)                          │
│                                                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Docker Container (Pod)                             │ │
│  │                                                     │ │
│  │  FastAPI App                                       │ │
│  │    ├── case_service.py                            │ │
│  │    └── /app/storage/cases/  ← CASES SAVED HERE   │ │
│  │         └── CASE-001.json   ← TEMPORARY!         │ │
│  └────────────────────────────────────────────────────┘ │
│         ↑                                                │
│         │ Redeployment destroys this container          │
│         │ All files in /app/storage/ are LOST!          │
└──────────────────────────────────────────────────────────┘

External Storage (Safe from redeployments):
┌──────────────────────────────────────────────────────────┐
│  Azure Storage Account                                   │
│    ├── input-files (container)     ← Files saved here   │
│    ├── reference-files (container)                       │
│    └── schemas (container)                               │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Azure Cosmos DB                                         │
│    ├── files metadata              ← Files metadata     │
│    ├── schemas metadata            ← Schemas metadata   │
│    └── [NO cases collection yet!]  ← Cases NOT here!   │
└──────────────────────────────────────────────────────────┘
```

---

### Recommended Architecture (Cases Persist):

```
┌──────────────────────────────────────────────────────────┐
│  Azure Kubernetes Service (AKS)                          │
│                                                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Docker Container (Pod) - STATELESS                 │ │
│  │                                                     │ │
│  │  FastAPI App                                       │ │
│  │    ├── case_service.py                            │ │
│  │    └── No local storage needed!                   │ │
│  └────────────────────────────────────────────────────┘ │
│         │                                                │
│         │ Calls Cosmos DB API                            │
│         ↓                                                │
└──────────────────────────────────────────────────────────┘

External Storage (Safe from redeployments):
┌──────────────────────────────────────────────────────────┐
│  Azure Storage Account (Blob Storage)                    │
│    ├── input-files          ← Files saved here          │
│    ├── reference-files                                   │
│    ├── schemas                                           │
│    └── predictions                                       │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Azure Cosmos DB (MongoDB API)                           │
│    ├── files (collection)        ← Files metadata       │
│    ├── schemas (collection)      ← Schemas metadata     │
│    ├── predictions (collection)  ← Predictions metadata  │
│    └── analysis_cases (NEW!)     ← Cases saved here ✅  │
└──────────────────────────────────────────────────────────┘
```

---

## 🎯 Why Redeployment Destroys Docker Containers

### What is a Docker Container?

Think of a Docker container like a **temporary workspace**:

1. **Created fresh** each time you deploy
2. Contains your code + dependencies
3. Has its own temporary filesystem
4. **Destroyed** when you redeploy or update

### Deployment Process:

```
Step 1: Build new Docker image
  ├── Copy code files
  ├── Install dependencies
  └── Create image: myapp:v2

Step 2: Deploy to Kubernetes
  ├── Stop old container (myapp:v1)
  ├── DELETE old container ❌ ← Everything inside is deleted!
  ├── Start new container (myapp:v2)
  └── Fresh filesystem (empty /app/storage/)

Step 3: Application starts
  └── /app/storage/cases/ is EMPTY!
```

**This is by design!** Containers are meant to be:
- **Stateless** - No permanent data inside
- **Disposable** - Can be destroyed and recreated anytime
- **Scalable** - Can run multiple copies simultaneously

### Why Your Files Persist (But Cases Don't)

**Files work** because they use **external storage**:
```python
# Files are uploaded to Azure Blob Storage (external)
blob_client.upload_blob(file_data)  # Saved to cloud ✅
```

**Cases fail** because they use **local storage**:
```python
# Cases are saved to local filesystem (inside container)
with open('/app/storage/cases/CASE-001.json', 'w') as f:  # Temporary ❌
    json.dump(case_data, f)
```

---

## 🔧 The Fix: Move Cases to Cosmos DB

Just like files, schemas, and predictions already do!

### Before (Current - Breaks on Redeploy):
```python
# Saves to container's local filesystem
case_file = Path("/app/storage/cases/CASE-001.json")
with open(case_file, 'w') as f:
    json.dump(case_data, f)
```

### After (Recommended - Survives Redeploy):
```python
# Saves to Cosmos DB (external cloud database)
from pymongo import MongoClient

client = MongoClient(cosmos_connection_string)
collection = client["ContentProcessor"]["analysis_cases"]
collection.insert_one(case_data)
```

---

## 📊 Summary

| Question | Answer |
|----------|--------|
| **What is "file-based storage"?** | Saving JSON files to the Docker container's local filesystem (`/app/storage/cases/`) |
| **Why does container get destroyed?** | Docker containers are temporary by design - they're recreated on every deployment |
| **Is this the Azure Storage container?** | No! Different "container" - this is the Docker/Kubernetes container (app runtime) |
| **Where are files actually stored?** | Azure Blob Storage (permanent) + Cosmos DB metadata (permanent) |
| **Where are cases stored?** | Currently: Docker container filesystem (TEMPORARY) ← This is the problem! |
| **What's the fix?** | Move cases to Cosmos DB, just like files/schemas/predictions |

---

## 🎯 Next Steps

Would you like me to implement the Cosmos DB storage for cases now? This will:
1. ✅ Make cases persist across redeployments
2. ✅ Use the same pattern as files/schemas (already working)
3. ✅ Enable multi-instance scaling (multiple app pods)
4. ✅ Provide better performance (database queries vs. file I/O)

Let me know and I'll proceed with the implementation!
