# Case-Analyzer Association Implementation Plan

## Overview

Implement analyzer reuse for case-based analyses while keeping Quick Query as one-time-use temporary analyzers.

---

## Architecture Decision

### Current Flow (All Analyses)
```
Frontend generates unique ID → PUT create analyzer → POST analyze → Results
Each analysis creates a new analyzer (costly)
```

### New Flow

**Quick Query (No Change)**:
```
Frontend generates `quick-query-{timestamp}` → PUT create analyzer → POST analyze → Immediate cleanup ✅
```

**Case-Based Analysis (NEW)**:
```
1. Check if case has analyzer_id
   ├─ YES → Reuse existing analyzer (skip PUT)
   └─ NO → Create new analyzer → Save analyzer_id to case
2. POST analyze with existing/new analyzer
3. Store results as case-{id}/result.json
4. Update last_analyzed_at timestamp
```

---

## Implementation Steps

### Step 1: Database Schema (Cosmos DB - cases_pro collection)

Add fields to case documents:

```json
{
  "id": "case-123",
  "name": "Invoice Analysis Project",
  "caseNumber": "2025-001",
  
  // NEW FIELDS for analyzer association
  "analyzer_id": "analyzer-1730304523-abc123",  // Associated analyzer
  "analyzer_created_at": "2025-01-15T10:30:00Z",  // When analyzer was created
  "last_analyzed_at": "2025-01-15T14:45:00Z",  // Last analysis run
  
  // Existing fields
  "inputFiles": [...],
  "selectedSchema": {...},
  "createdAt": "2025-01-15T09:00:00Z"
}
```

### Step 2: Backend API Changes

#### 2.1 Update ContentAnalyzerRequest Model

**File**: `proMode.py` (Line ~3240)

**Status**: ✅ ALREADY DONE

```python
class ContentAnalyzerRequest(BaseModel):
    analyzerId: str
    analysisMode: str = "pro"
    baseAnalyzerId: str = "prebuilt-documentAnalyzer"
    schema_config: Optional[ProSchema] = None
    inputFiles: List[str] = []
    referenceFiles: List[str] = []
    
    # Case-analyzer association (NEW)
    case_id: Optional[str] = None  # ✅ Added
    
    pages: Optional[str] = None
    locale: Optional[str] = None
    outputFormat: Optional[str] = "json"
    includeTextDetails: Optional[bool] = True
```

#### 2.2 Add Case-Analyzer Helper Functions

**File**: `proMode.py` (Add near top, after imports ~Line 400)

```python
def get_cases_collection():
    """Get Cosmos DB collection for case management"""
    try:
        cfg: AppConfiguration = get_app_config()
        if not getattr(cfg, "app_cosmos_connstr", None):
            logger.warning("Cosmos connection string not configured")
            return None
        client = MongoClient(cfg.app_cosmos_connstr, tlsCAFile=certifi.where())
        db = client[cfg.app_cosmos_database]
        collection = db["cases_pro"]
        return collection
    except Exception as e:
        logger.error(f"Failed to get cases collection: {e}")
        return None


async def get_or_create_case_analyzer(
    case_id: str,
    group_id: str,
    create_analyzer_func,  # Function to call if analyzer needs to be created
    **create_params
) -> Dict[str, Any]:
    """
    Get existing analyzer for case or create new one.
    
    Returns:
        {
            "analyzer_id": "analyzer-xxx",
            "is_new": bool,  # True if just created
            "reused": bool  # True if reused from case
        }
    """
    cases_collection = get_cases_collection()
    if not cases_collection:
        # Fallback: create new analyzer (no case association)
        analyzer_id = await create_analyzer_func(**create_params)
        return {"analyzer_id": analyzer_id, "is_new": True, "reused": False}
    
    try:
        # Find case document
        case = cases_collection.find_one({"id": case_id, "group_id": group_id})
        
        if not case:
            logger.warning(f"[CaseAnalyzer] Case not found: {case_id}")
            # Create analyzer without case association
            analyzer_id = await create_analyzer_func(**create_params)
            return {"analyzer_id": analyzer_id, "is_new": True, "reused": False}
        
        # Check if case already has an analyzer
        existing_analyzer_id = case.get("analyzer_id")
        
        if existing_analyzer_id:
            # Reuse existing analyzer
            logger.info(f"[CaseAnalyzer] ♻️ Reusing existing analyzer for case {case_id}: {existing_analyzer_id}")
            
            # Update last_analyzed_at timestamp
            cases_collection.update_one(
                {"id": case_id, "group_id": group_id},
                {
                    "$set": {
                        "last_analyzed_at": datetime.utcnow()
                    }
                }
            )
            
            return {
                "analyzer_id": existing_analyzer_id,
                "is_new": False,
                "reused": True
            }
        
        else:
            # Create new analyzer and save to case
            logger.info(f"[CaseAnalyzer] 🆕 Creating new analyzer for case {case_id}")
            analyzer_id = await create_analyzer_func(**create_params)
            
            # Save analyzer_id to case document
            cases_collection.update_one(
                {"id": case_id, "group_id": group_id},
                {
                    "$set": {
                        "analyzer_id": analyzer_id,
                        "analyzer_created_at": datetime.utcnow(),
                        "last_analyzed_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"[CaseAnalyzer] ✅ Associated analyzer {analyzer_id} with case {case_id}")
            
            return {
                "analyzer_id": analyzer_id,
                "is_new": True,
                "reused": False
            }
            
    except Exception as e:
        logger.error(f"[CaseAnalyzer] Error in case-analyzer association: {e}")
        # Fallback: create analyzer without case association
        analyzer_id = await create_analyzer_func(**create_params)
        return {"analyzer_id": analyzer_id, "is_new": True, "reused": False}
```

#### 2.3 Modify Background Polling to Use Case-Based Blob Paths

**File**: `proMode.py` (Line ~320, in `poll_azure_analysis_status_background`)

```python
# In the success path where we save to blob storage
if status_value == "succeeded":
    try:
        import json
        
        cfg: AppConfiguration = get_app_config()
        result_json = json.dumps(result.get("result", {}), ensure_ascii=False, indent=2)
        group_container = get_group_container_name(group_id)
        storage_helper = StorageBlobHelper(cfg.app_storage_blob_url, group_container)
        
        # NEW: Determine blob path based on case_id
        # (We need to pass case_id to background function - see Step 2.4)
        if case_id:
            # Case-based analysis: use predictable path
            blob_name = get_resource_blob_path("analysis_result", f"case-{case_id}/result.json")
            logger.info(f"[BackendPolling] 📁 Using case-based path: {blob_name}")
        else:
            # Regular/Quick Query: use operation_id
            blob_name = get_resource_blob_path("analysis_result", f"{operation_id}.json")
            logger.info(f"[BackendPolling] 📁 Using operation-based path: {blob_name}")
        
        storage_helper.upload_blob(
            blob_name=blob_name,
            file_stream=result_json.encode('utf-8')
        )
        
        blob_url = f"{normalize_storage_url(cfg.app_storage_blob_url)}/{group_container}/{blob_name}"
        
        # Update Cosmos status doc with blob URL
        status_collection.update_one(
            {"operation_id": operation_id, "group_id": group_id},
            {
                "$set": {
                    "result_blob_url": blob_url,
                    "case_id": case_id if case_id else None,  # Track case association
                    "last_updated": datetime.utcnow()
                }
            }
        )
        
        print(f"[BackendPolling] 💾 Saved to blob: {group_container}/{blob_name}", flush=True)
        
        # Quick Query cleanup (existing code)
        if analyzer_id.startswith("quick-query-"):
            await cleanup_quick_query_resources(...)
            
    except Exception as blob_error:
        ...
```

#### 2.4 Update Background Polling Function Signature

**File**: `proMode.py` (Line ~216)

**Current**:
```python
async def poll_azure_analysis_status_background(
    operation_location: str,
    credential,
    group_id: str,
    analyzer_id: str,
    max_polls: int = 120
):
```

**New**:
```python
async def poll_azure_analysis_status_background(
    operation_location: str,
    credential,
    group_id: str,
    analyzer_id: str,
    case_id: Optional[str] = None,  # NEW: for case-based blob paths
    max_polls: int = 120
):
    """
    Background task that polls Azure for analysis status and writes to Cosmos DB.
    
    Args:
        operation_location: The Azure operation-location URL to poll
        credential: Azure credential for authentication
        group_id: Group ID for partition key and resource isolation
        analyzer_id: Analyzer ID (used to detect Quick Query for cleanup)
        case_id: Case ID (if case-based analysis, for predictable blob paths)
        max_polls: Maximum number of polls before giving up
    """
```

#### 2.5 Update analyze_content Endpoint Call to Background Task

**File**: `proMode.py` (Line ~7437, where background_tasks.add_task is called)

**Current**:
```python
background_tasks.add_task(
    poll_azure_analysis_status_background,
    operation_location,
    credential,
    group_id,
    analyzer_id
)
```

**New**:
```python
# Extract case_id from request
case_id = getattr(request, 'case_id', None)

background_tasks.add_task(
    poll_azure_analysis_status_background,
    operation_location,
    credential,
    group_id,
    analyzer_id,
    case_id  # Pass case_id for blob path determination
)
```

---

### Step 3: Frontend Changes

#### 3.1 Update Analysis Request Interface

**File**: `proModeApiService.ts`

```typescript
export interface StartAnalysisOrchestratedParams {
  analyzerId: string;
  schemaId: string;
  inputFileIds: string[];
  referenceFileIds?: string[];
  schema?: any;
  caseId?: string;  // NEW: Associate with case
  configuration?: any;
  pages?: string;
  locale?: string;
  outputFormat?: string;
  includeTextDetails?: boolean;
  analysisType?: 'comprehensive' | 'quickQuery';
}
```

#### 3.2 Pass case_id in Analysis Request

**File**: `PredictionTab.tsx` (in `handleStartAnalysis` function)

```typescript
const handleStartAnalysis = async () => {
  // ... validation ...
  
  // Get current case ID if a case is selected
  const currentCase = selectedCase || cases.find(c => c.id === selectedCaseId);
  const caseId = currentCase?.id;
  
  const result = await dispatch(startAnalysisOrchestratedAsync({
    analyzerId,
    schemaId: selectedSchema.id,
    inputFileIds: selectedInputFiles.map(f => f.id),
    referenceFileIds: selectedReferenceFiles.map(f => f.id),
    schema: schemaConfig,
    caseId,  // NEW: Pass case ID
    configuration: { mode: 'pro' },
    locale: 'en-US',
    outputFormat: 'json',
    includeTextDetails: true,
    analysisType: 'comprehensive'
  })).unwrap();
};
```

#### 3.3 Pass case_id to Backend API

**File**: `proModeApiService.ts` (in `startAnalysisOrchestrated` function)

```typescript
export const startAnalysisOrchestrated = async (request: StartAnalysisOrchestratedRequest) => {
  // ... existing code ...
  
  const analyzePayload = {
    analyzerId: request.analyzerId,
    analysisMode: 'pro',
    baseAnalyzerId: 'prebuilt-documentAnalyzer',
    schema_config: schemaForAnalyze,
    inputFiles: [...],
    referenceFiles: [...],
    caseId: request.caseId,  // NEW: Pass to backend
    pages: request.pages,
    locale: request.locale,
    outputFormat: request.outputFormat,
    includeTextDetails: request.includeTextDetails
  };
  
  // POST to analyze endpoint
  const analyzeResponse = await httpUtility.post(analyzeEndpoint, analyzePayload);
  // ...
};
```

---

## Testing Plan

### Test Case 1: First Analysis for a Case
1. Create new case
2. Select files and schema
3. Click "Start Analysis"
4. **Expected**:
   - New analyzer created
   - `analyzer_id` saved to case document
   - Results stored as `case-{id}/result.json`
   - `analyzer_created_at` and `last_analyzed_at` timestamps set

### Test Case 2: Re-analysis of Same Case
1. Use existing case (from Test Case 1)
2. Click "Start Analysis" again
3. **Expected**:
   - Existing analyzer reused (no PUT request)
   - Results overwrite `case-{id}/result.json`
   - `last_analyzed_at` timestamp updated
   - `analyzer_created_at` unchanged

### Test Case 3: Quick Query (No Case)
1. Don't select a case
2. Use Quick Query
3. **Expected**:
   - Temporary analyzer created (`quick-query-{timestamp}`)
   - Results stored as `{operation_id}.json`
   - Analyzer and blob deleted after completion
   - No case association

### Test Case 4: Analysis Without Case Selection
1. Don't select a case
2. Use "Start Analysis" button
3. **Expected**:
   - Regular flow (no case association)
   - Results stored as `{operation_id}.json`
   - No analyzer reuse

---

## Migration Considerations

### Existing Cases
- Cases created before this feature won't have `analyzer_id`
- First analysis will create and associate analyzer
- Subsequent analyses will reuse the analyzer

### Backward Compatibility
- If `case_id` is not provided → fallback to old behavior
- If case not found → create analyzer without association
- No breaking changes to existing API contracts

---

## Monitoring & Logging

Add diagnostic logging:

```python
logger.info(f"[CaseAnalyzer] Analysis request - case_id: {case_id}, analyzer_id: {analyzer_id}")
logger.info(f"[CaseAnalyzer] ♻️ Reused analyzer: {existing_analyzer_id}")
logger.info(f"[CaseAnalyzer] 🆕 Created new analyzer: {new_analyzer_id}")
logger.info(f"[CaseAnalyzer] 📁 Blob path: {blob_path}")
```

---

## Benefits Summary

1. **Cost Savings**: Reuse analyzers for same case (avoid repeated PUT requests to Azure AI)
2. **Faster Analysis**: Skip analyzer creation step on re-runs
3. **Predictable Storage**: `case-{id}/result.json` instead of random operation IDs
4. **Easy Cleanup**: Delete case → delete associated analyzer and results
5. **Better UX**: Clear file organization, easy result comparison across runs

---

## Next Steps

1. Review this plan
2. Implement Step 2.2 (helper functions)
3. Implement Step 2.3-2.5 (blob path logic)
4. Implement Step 3 (frontend changes)
5. Test with all 4 test cases
6. Deploy and monitor

Ready to proceed?
