# No Backend Logs - Diagnostic Steps

**Issue:** Request appears to timeout but NO logs appear in backend container  
**Implication:** Request never reaches the backend code

---

## Changes Made for Diagnosis

### 1. Added Startup Logging
```python
# When proMode.py module loads (on server startup)
print("🔧 proMode.py router loaded - /pro-mode/ai-enhancement/orchestrated endpoint registered")
```

**When to see this:** Immediately when backend container starts  
**If you DON'T see this:** The module isn't loading (Python error?)

### 2. Added Endpoint Hit Logging
```python
@router.post("/pro-mode/ai-enhancement/orchestrated", ...)
async def orchestrated_ai_enhancement(...):
    print("=" * 80)
    print("🚨 ENDPOINT HIT: /pro-mode/ai-enhancement/orchestrated")
    print("=" * 80)
```

**When to see this:** The moment ANY request hits this endpoint  
**If you DON'T see this:** Request isn't reaching FastAPI router

---

## Diagnostic Steps

### Step 1: Rebuild Backend
```bash
cd code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### Step 2: Check Startup Logs
Look for this line when container starts:
```
🔧 proMode.py router loaded - /pro-mode/ai-enhancement/orchestrated endpoint registered
```

**If you see it:** ✅ Route is registered  
**If you DON'T:** ❌ Module loading issue (check for Python errors)

### Step 3: Test the Endpoint
Click "AI Schema Update" button in frontend

### Step 4: Check Runtime Logs
Look for this:
```
================================================================================
🚨 ENDPOINT HIT: /pro-mode/ai-enhancement/orchestrated
================================================================================
```

**If you see it:** ✅ Request reached backend  
**If you DON'T:** ❌ Request blocked before reaching code

---

## Possible Causes If No Logs

### Cause 1: Frontend Not Sending Request
**Check:** Browser DevTools → Network tab  
**Look for:** Request to `/pro-mode/ai-enhancement/orchestrated`  
**Status codes:**
- No request at all → Frontend isn't calling it
- 404 → Route not registered or wrong URL
- 401/403 → Authentication blocking
- 502/503 → Backend container down
- 504 → Gateway timeout (request never reached backend)

### Cause 2: Wrong API Base URL
**Frontend might be calling:**
- Wrong hostname (not pointing to your backend)
- Wrong path (typo in URL)
- Old cached deployment

**How to check:**
```typescript
// In browser console
console.log(window.location.origin);  // Current frontend URL
// API should be: origin.replace('-web.', '-api.')
```

### Cause 3: Authentication Middleware Blocking
**Check if request has:**
- Missing auth token
- Invalid token
- Token validation failing before reaching endpoint

### Cause 4: Container Not Running
**Check:**
```bash
# List running containers
az containerapp show \
  --name <your-api-container> \
  --resource-group <your-rg> \
  --query "properties.runningStatus"
```

### Cause 5: Old Deployment Still Running
**Possible:** docker-build.sh completed but old code still running

**Solution:** Force restart:
```bash
az containerapp revision restart \
  --name <container-app-name> \
  --resource-group <resource-group> \
  --revision <revision-name>
```

---

## What to Check in Browser DevTools

### Network Tab
1. Click "AI Schema Update" button
2. Look for request to `/pro-mode/ai-enhancement/orchestrated`
3. Check:
   - **Request URL:** Does it point to correct API hostname?
   - **Request Method:** POST?
   - **Status Code:** What status?
   - **Request Payload:** Does it have schema_blob_url?
   - **Response:** What error message?
   - **Timing:** How long did it wait?

### Console Tab
Look for:
```
[IntelligentSchemaEnhancerService] Calling orchestrated backend with minimal payload (no schema_data): {...}
```

This confirms frontend IS trying to call the API.

---

## Next Steps

### 1. Rebuild with diagnostic logging
```bash
cd code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### 2. Check container startup logs
Should see: `🔧 proMode.py router loaded...`

### 3. Test and monitor logs
- Click "AI Schema Update"
- Watch container logs for: `🚨 ENDPOINT HIT...`

### 4. Share findings
Please share:
- Do you see the startup log?
- Do you see the endpoint hit log?
- What's in browser Network tab for the request?

---

## Expected vs Actual

### Expected (Working)
```
# On container startup
🔧 proMode.py router loaded - /pro-mode/ai-enhancement/orchestrated endpoint registered

# When button clicked
================================================================================
🚨 ENDPOINT HIT: /pro-mode/ai-enhancement/orchestrated
================================================================================
🤖 Starting orchestrated AI enhancement for schema: [name]
...
```

### Actual (Current Issue)
```
# On container startup
??? (unknown - need to check)

# When button clicked
(nothing - no logs at all)
```

**This tells us the request isn't reaching the FastAPI application code.**

---

## Summary

Added two diagnostic logs:
1. **Startup log** - Confirms route is registered
2. **Endpoint hit log** - Confirms request reaches code

These will help us determine:
- Is the backend running the new code?
- Is the route properly registered?
- Is the request reaching FastAPI?
- Where exactly is the request getting blocked?

**Next:** Rebuild, test, and share what logs you see (or don't see).
