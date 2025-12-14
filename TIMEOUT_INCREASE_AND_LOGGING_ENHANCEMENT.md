# Timeout Increase and Enhanced Logging

**Date:** 2025-10-05  
**Issue:** Backend reached but analysis results polling timed out after 150 seconds  
**Changes:** Increased timeout + added diagnostic logging

---

## Problem Analysis

### What We Know ✅
1. ✅ Request reached backend (not blocked by gateway)
2. ✅ Backend downloaded schema from blob
3. ✅ Minimal payload working (~500 bytes)
4. ❌ Analysis results polling timed out at 150 seconds

### Error Message
```
[IntelligentSchemaEnhancerService] Orchestrated AI enhancement failed: 
Error: AI enhancement analysis timed out - please try again 
(Analysis did not complete within 150 seconds)
```

### What This Means
- Backend IS working (message came from backend, not gateway)
- Azure Content Understanding analysis is taking longer than expected
- Need to determine WHERE the delay is occurring

---

## Changes Applied

### 1. Increased Polling Timeout

**Before:**
```python
max_polls = 30  # 30 attempts
poll_interval = 5  # 5 seconds
# Total: 30 × 5 = 150 seconds (2.5 minutes)
```

**After:**
```python
max_polls = 50  # 50 attempts (increased from 30)
poll_interval = 5  # 5 seconds
# Total: 50 × 5 = 250 seconds (4.17 minutes)
# Combined with analyzer ready wait: ~5 minutes total
```

**Rationale:**
- Previous 150s was too aggressive
- Azure might need 2-3 minutes for complex schema analysis
- New 250s timeout gives more breathing room
- Still fits within gateway timeout (~5 minutes)

### 2. Enhanced Diagnostic Logging

**Added HTTP Status Logging:**
```python
print(f"📊 Poll {poll_attempt + 1}/{max_polls}: HTTP Status = {results_response.status_code}")
```

**Added Non-200 Response Handling:**
```python
else:
    # Non-200 response - log details
    print(f"⚠️ Poll {poll_attempt + 1}/{max_polls}: Got HTTP {results_response.status_code}")
    try:
        error_data = results_response.json()
        print(f"   Error response: {error_data}")
    except:
        print(f"   Response text: {results_response.text[:200]}")
```

**Why This Helps:**
- Can see if Azure is returning 202 (still processing) vs 200 (done)
- Can detect errors early (404, 500, etc.)
- Can identify if operation_location URL is wrong

---

## Next Testing Steps

### 1. Rebuild Backend
```bash
cd code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### 2. Monitor Logs During Next Test
Look for this sequence:
```
🤖 Starting orchestrated AI enhancement for schema: [name]
📥 Downloading schema from blob storage...
✅ Downloaded schema: [size] bytes
🧠 Step 1: Generating enhancement schema from user intent
📤 Step 2: Uploading meta-schema to blob
✅ Meta-schema uploaded successfully: [url]
🔧 Step 3: Creating custom analyzer
⏳ Polling for analyzer status...
📊 Poll 1/12: Analyzer status = notStarted
📊 Poll 2/12: Analyzer status = running
📊 Poll 3/12: Analyzer status = ready
✅ Analyzer is ready: [analyzer_id]
🚀 Starting analysis with custom analyzer
✅ Analysis started, operation location: [url]
⏱️ Step 4: Polling for analysis results
🔗 Operation location: [full_url]
📊 Poll 1/50: HTTP Status = 202    <-- Should see this
📊 Poll 1/50: Analysis status = running
📊 Poll 2/50: HTTP Status = 202
📊 Poll 2/50: Analysis status = running
...
📊 Poll N/50: HTTP Status = 200    <-- Eventually this
📊 Poll N/50: Analysis status = succeeded
✅ Step 4: Analysis completed successfully
```

### 3. Key Diagnostic Questions

**If you see HTTP 404:**
- operation_location URL is wrong
- Check if it matches pattern from successful tests

**If you see HTTP 202 for all 50 polls:**
- Azure is genuinely taking >250 seconds
- May need async job pattern instead of polling

**If you see HTTP 500:**
- Azure service error
- Check if meta-schema format is correct

**If status stays "running" forever:**
- Analysis might be stuck
- Check schema size/complexity

---

## Expected Timeline (Normal Case)

```
T+0s:     Frontend sends request (~500 bytes)
T+0.5s:   Backend downloads schema from blob
T+2s:     Backend generates meta-schema
T+4s:     Backend uploads meta-schema
T+6s:     Backend creates analyzer
T+8s:     Analyzer status = notStarted
T+15s:    Analyzer status = running
T+25s:    Analyzer status = ready ✅
T+28s:    Backend starts analysis (POST :analyze)
T+30s:    Poll 1: HTTP 202, status = running
T+35s:    Poll 2: HTTP 202, status = running
T+40s:    Poll 3: HTTP 202, status = running
...
T+90s:    Poll 13: HTTP 200, status = succeeded ✅
T+92s:    Backend downloads results
T+95s:    Backend parses enhanced schema
T+98s:    Response sent to frontend
```

**Total:** 90-120 seconds typical  
**Max allowed:** 250 seconds (new timeout)

---

## Troubleshooting

### If Still Times Out After 250s

**Option 1: Async Job Pattern**
- Return 202 immediately to frontend
- Poll in background
- Frontend polls backend for results
- Eliminates gateway timeout risk

**Option 2: Investigate Azure Delay**
- Check if schema is too large
- Check if meta-schema has errors
- Try simpler enhancement prompt
- Contact Azure support

### If Different Error Appears

Check backend logs for:
- Blob download errors
- Meta-schema generation errors
- Analyzer creation errors
- Any exception traces

---

## Summary

**Changes:**
1. Timeout: 150s → 250s (67% increase)
2. Logging: Added HTTP status codes and error details
3. Error handling: Better diagnostics for non-200 responses

**Next:**
1. Rebuild backend with new timeout
2. Test again with "AI Schema Update" button
3. Monitor logs for detailed progress
4. Share logs if still times out

**Goal:** Determine if Azure needs more time, or if there's a different issue blocking completion.
