# 🔍 Case Persistence Issue - Side-by-Side Cosmos DB Analysis

## 📊 Executive Summary

**Problem**: Cases disappear from the dropdown after page refresh, despite Cosmos DB implementation
**Root Cause**: Case service singleton is NOT properly initialized with Cosmos DB connection
**Solution**: Fix singleton initialization to match working Schema pattern exactly

---

## 🆚 Side-by-Side Comparison: Schema Service (✅ Working) vs Case Service (❌ Broken)

### 1. Service Initialization Pattern

#### ✅ **Schema Service** (Working - in `proMode.py`)
```python
def get_mongo_client_safe(app_config: AppConfiguration) -> tuple[MongoClient | None, Exception | None]:
    """Safely get MongoDB client with proper error handling."""
    try:
        if not app_config.app_cosmos_connstr:
            return None, Exception("Cosmos DB connection string not configured")
        
        client = MongoClient(app_config.app_cosmos_connstr, tlsCAFile=certifi.where())
        client.admin.command('ping')  # Test connection
        return client, None
    except Exception as e:
        return None, e
```

**Direct Access Pattern in Endpoints**:
```python
@router.get("/pro-mode/schemas")
async def get_pro_schemas(app_config: AppConfiguration = Depends(get_app_config)):
    client, error = get_mongo_client_safe(app_config)
    if error:
        raise error
    
    try:
        db = client[app_config.app_cosmos_database]
        pro_container_name = get_pro_mode_container_name(app_config.app_cosmos_container_schema)
        collection = db[pro_container_name]
        
        schemas = list(collection.find({}, projection))
        return schemas
    finally:
        if client:
            client.close()
```

**Key Points**:
- ✅ Gets fresh client for each request
- ✅ Properly passes AppConfiguration
- ✅ Tests connection with ping
- ✅ Closes client after use
- ✅ **NO SINGLETON** - creates new client each time

---

#### ❌ **Case Service** (Broken - in `case_service.py`)
```python
_case_service_instance: Optional[CaseManagementService] = None

def get_case_service(
    cosmos_connstr: Optional[str] = None, 
    database_name: Optional[str] = None,
    container_name: str = "cases"
) -> CaseManagementService:
    """Get singleton instance of case management service."""
    global _case_service_instance
    
    if _case_service_instance is None:
        if not cosmos_connstr or not database_name:
            from app.appsettings import get_app_config
            app_config = get_app_config()
            cosmos_connstr = app_config.app_cosmos_connstr
            database_name = app_config.app_cosmos_database
        
        _case_service_instance = CaseManagementService(
            cosmos_connstr, 
            database_name,
            container_name
        )
    
    return _case_service_instance
```

**Endpoint Usage**:
```python
@router.get("/pro-mode/cases")
async def list_cases(
    search: Optional[str] = Query(None),
    app_config: AppConfiguration = Depends(get_app_config)  # ⚠️ PASSED BUT NOT USED!
):
    case_service = get_case_service()  # ⚠️ No args = uses cached instance!
    cases = await case_service.list_cases(search=search)
    return cases
```

**Key Problems**:
- ❌ Uses singleton pattern (BAD for Cosmos DB)
- ❌ `app_config` injected but NEVER passed to `get_case_service()`
- ❌ Falls back to stale config from first initialization
- ❌ Connection might be closed or using wrong credentials
- ❌ No connection health check

---

### 2. Cosmos DB Connection Lifecycle

#### ✅ **Schema Service Pattern**
```
Request 1:
┌──────────────────────────────────────────┐
│ User hits /pro-mode/schemas              │
├──────────────────────────────────────────┤
│ 1. Inject fresh AppConfiguration         │
│ 2. Create NEW MongoClient                │
│ 3. Ping to test connection               │
│ 4. Query schemas                         │
│ 5. Close client in finally block         │
└──────────────────────────────────────────┘

Request 2 (after app restart):
┌──────────────────────────────────────────┐
│ User hits /pro-mode/schemas              │
├──────────────────────────────────────────┤
│ 1. Inject FRESH AppConfiguration         │ ✅
│ 2. Create NEW MongoClient                │ ✅
│ 3. Ping to test connection               │ ✅
│ 4. Query schemas                         │ ✅
│ 5. Close client in finally block         │ ✅
└──────────────────────────────────────────┘
```

---

#### ❌ **Case Service Pattern (BROKEN)**
```
Request 1:
┌──────────────────────────────────────────┐
│ User hits /pro-mode/cases                │
├──────────────────────────────────────────┤
│ 1. Inject AppConfiguration (IGNORED)     │ ❌
│ 2. Call get_case_service() with NO args │
│ 3. Check singleton: None                 │
│ 4. Load config from get_app_config()     │
│ 5. Create CaseManagementService          │
│ 6. Store in global _case_service_instance│
│ 7. Query cases (works this time)         │
└──────────────────────────────────────────┘

Request 2 (after page refresh):
┌──────────────────────────────────────────┐
│ User hits /pro-mode/cases                │
├──────────────────────────────────────────┤
│ 1. Inject AppConfiguration (IGNORED)     │ ❌
│ 2. Call get_case_service() with NO args │
│ 3. Check singleton: EXISTS               │
│ 4. Return CACHED instance                │ ❌
│ 5. Use STALE MongoClient                 │ ❌
│ 6. Query fails or returns empty          │ ❌
└──────────────────────────────────────────┘
```

---

### 3. Container Name Pattern

#### ✅ **Schema Service**
```python
def get_pro_mode_container_name(base_container_name: str) -> str:
    """Generate isolated container name for pro mode."""
    return f"{base_container_name}_pro"

# Usage in proMode.py
pro_container_name = get_pro_mode_container_name(app_config.app_cosmos_container_schema)
# Result: "documentIntelligenceSchema_pro"
```

#### ✅ **Case Service** (This part is actually correct!)
```python
def get_pro_mode_container_name(base_container_name: str) -> str:
    """Generate isolated container name for pro mode (same pattern as schemas)."""
    return f"{base_container_name}_pro"

# Usage in case_service.py
pro_container_name = get_pro_mode_container_name(container_name)
# Result: "cases_pro"
```

**Both use the same pattern** ✅

---

### 4. Data Retrieval Pattern

#### ✅ **Schema Service**
```python
# Optimized projection
projection = {
    "id": 1, "name": 1, "displayName": 1, "description": 1, 
    "fields": 1, "fieldCount": 1, "createdAt": 1, 
    "blobUrl": 1, "_id": 0
}

schemas = list(collection.find({}, projection))

# Normalize displayName
for schema in schemas:
    display_name = schema.get("displayName") or schema.get("ClassName")
    if display_name in ["Updated Schema", None, ""]:
        schema["displayName"] = schema.get("name", "Unnamed Schema")

return safe_json_response(schemas)
```

#### ✅ **Case Service** (This part is also correct!)
```python
# Optimized projection
projection = {
    "id": 1, "case_id": 1, "case_name": 1, "description": 1,
    "input_file_names": 1, "reference_file_names": 1, "schema_name": 1,
    "created_at": 1, "updated_at": 1, "_id": 0
}

cursor = collection.find(query, projection).sort(sort_by, sort_order)

cases = []
for doc in cursor:
    try:
        cases.append(self._convert_to_case(doc))
    except Exception as e:
        print(f"Error converting case: {e}")

return cases
```

**Both use optimized projections correctly** ✅

---

## 🎯 Root Cause Summary

| Aspect | Schema Service | Case Service | Status |
|--------|---------------|--------------|--------|
| Connection Pattern | Fresh client per request | Singleton (stale connection) | ❌ BROKEN |
| AppConfig Injection | Used directly in endpoint | Injected but ignored | ❌ BROKEN |
| Client Lifecycle | Opens & closes per request | Never refreshed | ❌ BROKEN |
| Connection Testing | Pings before use | No health check | ❌ BROKEN |
| Container Naming | `{base}_pro` pattern | `{base}_pro` pattern | ✅ CORRECT |
| Data Projection | Optimized fields | Optimized fields | ✅ CORRECT |
| Field Conversion | Proper datetime handling | Proper datetime handling | ✅ CORRECT |

---

## 💡 The Fix

### Option 1: Remove Singleton Pattern (RECOMMENDED - Match Schema Service)

Change `case_service.py` to NOT use singleton:

```python
def get_case_service(app_config: AppConfiguration) -> CaseManagementService:
    """
    Get case service instance (NO SINGLETON - fresh per request like schemas).
    
    Args:
        app_config: Application configuration with Cosmos DB connection
        
    Returns:
        CaseManagementService instance
    """
    return CaseManagementService(
        cosmos_connstr=app_config.app_cosmos_connstr,
        database_name=app_config.app_cosmos_database,
        container_name="cases"
    )
```

Update endpoints to pass `app_config`:

```python
@router.get("/pro-mode/cases")
async def list_cases(
    search: Optional[str] = Query(None),
    app_config: AppConfiguration = Depends(get_app_config)
):
    case_service = get_case_service(app_config)  # ✅ Pass config!
    cases = await case_service.list_cases(search=search)
    return cases
```

---

### Option 2: Fix Singleton to Always Use Fresh Config

Keep singleton but update it on every request:

```python
def get_case_service(app_config: AppConfiguration) -> CaseManagementService:
    """Get or refresh case service with latest config."""
    global _case_service_instance
    
    # Always recreate to ensure fresh connection (like schemas do)
    _case_service_instance = CaseManagementService(
        cosmos_connstr=app_config.app_cosmos_connstr,
        database_name=app_config.app_cosmos_database,
        container_name="cases"
    )
    
    return _case_service_instance
```

**But Option 1 is better because:**
- ✅ Matches proven working schema pattern
- ✅ No global state
- ✅ Thread-safe
- ✅ Easier to test
- ✅ No stale connections

---

## 📋 Implementation Checklist

### Step 1: Update `case_service.py`
- [ ] Remove global `_case_service_instance` variable
- [ ] Update `get_case_service()` to require `app_config` parameter
- [ ] Remove singleton logic
- [ ] Return fresh instance every time

### Step 2: Update `case_management.py`
- [ ] Pass `app_config` to `get_case_service()` in all endpoints:
  - `/pro-mode/cases` (GET, POST)
  - `/pro-mode/cases/{case_id}` (GET, PUT, DELETE)
  - `/pro-mode/cases/{case_id}/analyze`
  - `/pro-mode/cases/{case_id}/history`
  - `/pro-mode/cases/{case_id}/duplicate`

### Step 3: Test
- [ ] Create a case
- [ ] Refresh page
- [ ] Verify cases still appear in dropdown
- [ ] Check console logs for Cosmos DB connection messages
- [ ] Verify data persists after app restart

---

## 🚀 Expected Outcome

After fixing:

```
User Creates Case:
┌─────────────────────────────────────────┐
│ POST /pro-mode/cases                    │
│ → Fresh MongoClient                     │
│ → Insert into cases_pro collection      │
│ → Close client                          │
│ → ✅ Case saved to Cosmos DB            │
└─────────────────────────────────────────┘

User Refreshes Page:
┌─────────────────────────────────────────┐
│ GET /pro-mode/cases                     │
│ → Fresh MongoClient                     │
│ → Query cases_pro collection            │
│ → ✅ Cases retrieved from Cosmos DB     │
│ → ✅ Dropdown populated                 │
│ → Close client                          │
└─────────────────────────────────────────┘

Container Restarts:
┌─────────────────────────────────────────┐
│ GET /pro-mode/cases                     │
│ → Fresh MongoClient (new container)     │
│ → Query cases_pro collection            │
│ → ✅ Cases still in Cosmos DB           │
│ → ✅ Dropdown populated                 │
│ → Close client                          │
└─────────────────────────────────────────┘
```

---

## 📝 Why Schema Upload Works But Cases Don't

**Schema Upload Endpoint (`/pro-mode/schemas`)**:
```python
async def get_pro_schemas(app_config: AppConfiguration = Depends(get_app_config)):
    client, error = get_mongo_client_safe(app_config)  # ✅ Fresh client
    try:
        collection = db[pro_container_name]
        schemas = list(collection.find({}, projection))
        return schemas
    finally:
        client.close()  # ✅ Clean cleanup
```

**Case Management Endpoint (`/pro-mode/cases`)**:
```python
async def list_cases(app_config: AppConfiguration = Depends(get_app_config)):
    case_service = get_case_service()  # ❌ No config passed!
    # Uses STALE singleton with potentially closed/wrong connection
    cases = await case_service.list_cases(search=search)
    return cases
```

The difference is **crystal clear**: Schemas create fresh connections, Cases reuse stale ones!

---

## 🎓 Lesson Learned

**Singleton Pattern is DANGEROUS for Database Connections**

- ✅ **Good for**: Stateless utilities, configuration, loggers
- ❌ **Bad for**: Database connections, API clients, anything with state

**Best Practice**: Follow the proven working pattern (Schema Service) exactly!
