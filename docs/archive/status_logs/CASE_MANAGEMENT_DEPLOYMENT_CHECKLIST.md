# Case Management 405 Error - Deployment Checklist

## Issue Summary
After deployment, the "Save Case" button returns:
```
405 (Method Not Allowed) from POST https://.../pro-mode/cases
```

## Root Cause Confirmed
The `case_management.py` router was using an **incompatible routing pattern**:
- ❌ OLD: Used `prefix="/pro-mode/cases"` with relative paths like `""`
- ✅ NEW: Uses NO prefix with full paths like `"/pro-mode/cases"`

This matches the pattern used by the working `proMode.py` router.

## Files Modified

### 1. `/app/routers/case_management.py`
**Changes Made:**
```python
# BEFORE (Incorrect):
router = APIRouter(
    prefix="/pro-mode/cases",  # ❌ Has prefix
    tags=["Case Management"]
)
@router.post("", ...)  # ❌ Relative path

# AFTER (Correct):
router = APIRouter(
    tags=["Case Management"]  # ✅ No prefix
)
@router.post("/pro-mode/cases", ...)  # ✅ Full path
```

**All Updated Endpoints:**
- `@router.post("/pro-mode/cases", ...)` - Create case
- `@router.get("/pro-mode/cases", ...)` - List cases
- `@router.get("/pro-mode/cases/{case_id}", ...)` - Get case
- `@router.put("/pro-mode/cases/{case_id}", ...)` - Update case
- `@router.delete("/pro-mode/cases/{case_id}", ...)` - Delete case
- `@router.post("/pro-mode/cases/{case_id}/analyze", ...)` - Start analysis
- `@router.get("/pro-mode/cases/{case_id}/history", ...)` - Get history
- `@router.post("/pro-mode/cases/{case_id}/duplicate", ...)` - Duplicate case

## Deployment Steps

### Step 1: Verify Local Changes
```bash
# Check that case_management.py has the correct pattern
grep -A 2 "router = APIRouter" /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/case_management.py

# Should show NO prefix (just tags)
```

### Step 2: Build Docker Image
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
conda deactivate
./docker-build.sh
```

### Step 3: Deploy to Azure Container Apps
The docker-build.sh script should handle deployment. Verify the deployment completes successfully.

### Step 4: Wait for Container Restart
Azure Container Apps need time to:
1. Pull the new image
2. Stop old containers
3. Start new containers
4. Pass health checks

**Wait 2-5 minutes** after deployment completes.

### Step 5: Verify Deployment

#### Test 1: Check Health Endpoint
```bash
curl -s https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/health
# Should return: {"message": "I'm alive!"}
```

#### Test 2: Check API Docs (if accessible)
Open browser: `https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/docs`

Look for "Case Management" endpoints in the API documentation.

#### Test 3: Test from Frontend
1. Navigate to the Analysis page
2. Fill in case details
3. Click "Save Case" button
4. **Expected**: Case saves successfully without 405 error
5. **Actual**: _(to be filled in after testing)_

## Verification Checklist

- [  ] Code changes committed to repository
- [ ] Docker image built successfully
- [ ] Deployment completed without errors
- [ ] Container health check passes
- [ ] Frontend "Save Case" button works
- [ ] Can create, list, and retrieve cases

## Troubleshooting

### If 405 Error Persists:

#### Check 1: Verify Container is Running New Code
```bash
# Get container logs to see startup messages
# (Azure Portal > Container Apps > Log Stream)
# Look for: "case_management router loaded" or similar
```

#### Check 2: Verify Router Registration
The main.py file must have:
```python
from app.routers import contentprocessor, schemavault, proMode, streaming, case_management
app.include_router(case_management.router)
```

#### Check 3: Check for Import Errors
Container logs should show if case_management.py failed to import:
```
ModuleNotFoundError: No module named 'app.models.case_model'
ModuleNotFoundError: No module named 'app.services.case_service'
```

If you see these errors, the case_management router is not loaded.

#### Check 4: Verify Dependencies Exist
```bash
# Check that required files exist in the image:
# - app/models/case_model.py
# - app/services/case_service.py
```

### If Case Service Errors Occur:

The case service uses file-based storage. Check:
1. Storage directory permissions
2. Disk space availability
3. Service initialization in logs

## Rollback Plan

If issues persist:
1. Revert `case_management.py` changes
2. Rebuild and redeploy
3. Investigate further before re-attempting fix

## Success Criteria

✅ POST to `/pro-mode/cases` returns 201 (Created) instead of 405
✅ Frontend can save, list, and manage cases
✅ No console errors related to case management API

## Notes

- The fix matches the exact pattern used by working endpoints in `proMode.py`
- No frontend changes needed - frontend already calls correct URLs
- The router IS registered in main.py - deployment just needs to pick up the changes
