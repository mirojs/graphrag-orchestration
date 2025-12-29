# ROUTING ISSUE DIAGNOSIS AND FIX

## Critical Routing Issues Identified ⚠️

Based on the analysis, I've identified several potential routing issues that could explain the deployment problems:

### Issue 1: Schema ID Cross-Mode Contamination ❌

**Problem**: Schema uploaded in one mode might be referenced by the other mode

**Scenario**:
```
1. User uploads schema via standard mode → stored in `{container}`
2. User switches to pro mode tab
3. Frontend sends schema ID to pro mode endpoint → looks in `{container}_pro` 
4. Schema not found → 404 error
```

**Evidence**: 
- Pro mode uses: `get_pro_mode_container_name(app_config.app_cosmos_container_schema)` (line 1832)
- Standard mode would use: `app_config.app_cosmos_container_schema` directly
- Complete storage isolation between modes

### Issue 2: Frontend Mode Detection Logic ❌

**Problem**: Frontend might not correctly determine which endpoints to call

**Potential Issues**:
```javascript
// ❌ WRONG: Frontend uses hardcoded endpoints
const endpoint = "/contentprocessor/analyzers/" + analyzerId;  // 404 - doesn't exist

// ✅ CORRECT: Frontend should use mode-specific endpoints  
const endpoint = mode === "pro" 
  ? "/pro-mode/content-analyzers/" + analyzerId
  : "/standard-mode/content-analyzers/" + analyzerId;  // But this doesn't exist either!
```

### Issue 3: Missing Standard Mode Analyzer Endpoints ❌

**Critical Discovery**: 
- ✅ Pro mode has complete analyzer endpoints: `/pro-mode/content-analyzers/{id}`
- ❌ Standard mode has NO analyzer endpoints in `contentprocessor.py`
- ❌ Only has: `/contentprocessor/submit` and `/contentprocessor/processed`

**Impact**: If frontend expects standard mode analyzer creation, it will fail completely.

### Issue 4: Payload Structure Mismatch ❌

**Problem**: Frontend might send wrong payload structure to pro mode endpoints

**Standard Mode Expected** (doesn't exist but frontend might try):
```json
{
  "Schema_Id": "uuid",
  "Metadata_Id": "uuid", 
  "files": [...]
}
```

**Pro Mode Expected** (actual):
```json
{
  "schemaId": "uuid",
  "selectedReferenceFiles": ["file1.pdf"],
  "analysisMode": "pro"
}
```

## Root Cause Analysis

### Most Likely Scenario:
1. **Frontend assumes both modes have analyzer endpoints**
2. **Standard mode analyzer endpoints don't exist**
3. **Frontend defaults to pro mode endpoints with wrong payload**
4. **Pro mode receives malformed requests**
5. **Deployment fails with various errors**

## Fix Implementation

### Option A: Complete Standard Mode Implementation
Add missing standard mode analyzer endpoints to `contentprocessor.py`:

```python
# contentprocessor.py - ADD THESE ENDPOINTS
@router.put("/contentprocessor/analyzers/{analyzer_id}")
async def create_standard_analyzer(analyzer_id: str, payload: dict):
    # Standard mode analyzer creation logic
    # Uses app_config.app_cosmos_container_schema (not _pro suffix)
    # Calls Azure API with mode: "standard"
    pass

@router.post("/contentprocessor/analyzers/{analyzer_id}:analyze") 
async def analyze_standard_content(analyzer_id: str, request: AnalyzeRequest):
    # Standard mode analysis logic
    # Different payload structure than pro mode
    pass
```

### Option B: Frontend Route Enforcement (RECOMMENDED)
Force frontend to use pro mode exclusively:

```javascript
// frontend - ENFORCE PRO MODE ONLY
const FORCE_PRO_MODE = true;

function getAnalyzerEndpoint(analyzerId, mode) {
  if (FORCE_PRO_MODE || mode === "pro") {
    return `/pro-mode/content-analyzers/${analyzerId}`;
  }
  throw new Error("Standard mode analyzers not supported - use pro mode");
}

function getAnalyzeEndpoint(analyzerId, mode) {
  if (FORCE_PRO_MODE || mode === "pro") {
    return `/pro-mode/content-analyzers/${analyzerId}:analyze`;
  }
  throw new Error("Standard mode analysis not supported - use pro mode");
}
```

### Option C: Backend Route Validation (IMMEDIATE FIX)
Add validation to prevent wrong route usage:

```python
# proMode.py - ADD VALIDATION
@router.put("/pro-mode/content-analyzers/{analyzer_id}")
async def create_or_replace_content_analyzer(analyzer_id: str, request: Request, app_config: AppConfiguration = Depends(get_app_config)):
    payload = await request.json()
    
    # CRITICAL: Validate this is actually a pro mode request
    if payload.get('analysisMode') != 'pro':
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid analysis mode: {payload.get('analysisMode')}. Pro mode endpoints require analysisMode='pro'"
        )
    
    # Existing logic continues...
```

## Immediate Action Plan

### 1. Backend Validation (Deploy Now) 🚨
```python
# Add to proMode.py - Line 2055 (after payload = await request.json())
# ROUTING ISSUE FIX: Validate pro mode payload structure
required_pro_fields = ['schemaId']
missing_fields = [field for field in required_pro_fields if field not in payload]
if missing_fields:
    print(f"[AnalyzerCreate] ❌ ROUTING ERROR: Missing pro mode fields: {missing_fields}")
    print(f"[AnalyzerCreate] ❌ Received payload keys: {list(payload.keys())}")
    print(f"[AnalyzerCreate] ❌ This suggests frontend sent standard mode payload to pro mode endpoint")
    raise HTTPException(
        status_code=422,
        detail={
            "error": "Pro mode payload validation failed",
            "missing_fields": missing_fields,
            "received_keys": list(payload.keys()),
            "expected_structure": {
                "schemaId": "required - UUID of uploaded schema",
                "selectedReferenceFiles": "optional - array of reference file names",
                "analysisMode": "optional - defaults to 'pro'"
            },
            "routing_hint": "Ensure frontend calls /pro-mode/ endpoints with correct payload structure"
        }
    )

# Validate schema ID exists in PRO MODE containers  
if 'schemaId' in payload:
    schema_id = payload['schemaId']
    # Add validation that schema exists in PRO mode container
    # This prevents cross-mode contamination
```

### 2. Logging Enhancement (Deploy Now) 🚨
```python
# Add comprehensive routing logs to identify the exact issue
print(f"[AnalyzerCreate] ===== ROUTING VALIDATION =====")
print(f"[AnalyzerCreate] Endpoint called: /pro-mode/content-analyzers/{analyzer_id}")
print(f"[AnalyzerCreate] Frontend payload structure: {type(payload)} with keys: {list(payload.keys())}")
print(f"[AnalyzerCreate] Expected pro mode structure: ['schemaId', 'selectedReferenceFiles', 'analysisMode']")
print(f"[AnalyzerCreate] Schema storage mode: PRO (isolated containers)")
print(f"[AnalyzerCreate] Target container: {get_pro_mode_container_name(app_config.app_cosmos_container_schema)}")
```

### 3. Frontend Audit (Immediate) 🔍
Search frontend code for:
- Hardcoded `/contentprocessor/` calls
- Mode detection logic
- Schema ID resolution
- Endpoint selection logic

### 4. Testing Protocol (Next Deploy) 🧪
1. **Test pro mode with correct payload** → Should work
2. **Test pro mode with standard payload** → Should fail gracefully with clear error
3. **Test invalid endpoint calls** → Should return 404 with helpful message
4. **Test cross-mode schema contamination** → Should be prevented

## Expected Resolution

After implementing these fixes, the deployment should:
- ✅ Clearly identify routing issues in logs
- ✅ Prevent cross-mode payload contamination  
- ✅ Provide actionable error messages
- ✅ Guide frontend to correct endpoint usage

The root cause is likely **frontend-backend routing miscommunication** rather than the `$defs` preservation issue we already fixed.
