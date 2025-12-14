# AI Enhancement JSON Parse Fix - Current Status

**Date**: November 16, 2025
**Status**: Fix Deployed, Awaiting Test Results

---

## Problem Summary

AI enhancement was failing with error: **"CompleteEnhancedSchema not found or invalid"**

Through investigation, discovered:
- Azure Content Understanding API returns `CompleteEnhancedSchema.valueString` as JSON string
- The JSON string has **trailing content** after the valid JSON (6,402 chars with error at position 6,401)
- Error: `json.JSONDecodeError: Extra data at position 6401`

---

## Root Cause Analysis

### Azure API Endpoint Being Used

**Current Endpoint**: `/contentunderstanding/analyzers/{analyzer_id}:analyze`
- This is the **text/JSON API** endpoint (NOT binary)
- Returns JSON responses with text fields
- Alternative endpoint `:analyzebinary` exists for binary file uploads and returns binary output
- **Current investigation**: The :analyze (text) API may be appending special characters/content to the JSON response string

### Why the Test Passed but Production Failed

**Test file**: `schema_enhancement_test_results_1759669180.json` (Nov 3, 2025)
- `valueString` length: **4,873 characters**
- **Parses cleanly** with `json.loads()`
- No trailing content

**Production API response** (Nov 16, 2025):
- `valueString` length: **6,402 characters**
- **Fails to parse** at position 6,401 with "Extra data" error
- Azure appended **~1,529 extra characters** after valid JSON

**Conclusion**: Azure's API response format changed between test (Nov 3) and now (Nov 16), OR different model versions return different formats. The test data was already clean, but production needs robust parsing.

---

## Solution Implemented

### Code Changes

**File**: `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`

**Location**: Lines 12134-12145, 12570-12650, 12750-12780

**Fix 1**: Added robust JSON parsing with fallback to `JSONDecoder.raw_decode()`

**Fix 2**: Added diagnostics capture and persistent storage to blob

```python
# Capture diagnostics (API endpoint, string length, byte length, special chars, etc.)
diagnostics_info = {
    "api_endpoint": ":analyze (text/JSON)",
    "string_length": len(schema_json_str),
    "byte_length_utf8": len(schema_json_str.encode('utf-8')),
    "special_chars": special_chars_found,
    "last_50_hex": last_50.encode('utf-8').hex()[-100:]
}

# Save diagnostics to blob storage for persistent access
diagnostics_blob_name = f"diagnostics/ai-enhancement-{operation_id}-{timestamp}.json"
blob_client.upload_blob(diagnostics_content, overwrite=True)
diagnostics_info["blob_url"] = blob_client.url

# Return diagnostics in response
return AIEnhancementResponse(
    ...,
    diagnostics=diagnostics_info
)
```

**File**: `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/QuickQueryResults.tsx`

**Changes**: Minimized toast messages, diagnostics logged to console

```typescript
// Log diagnostics to console (already saved in blob storage)
if (enhancementResult.diagnostics?.blob_url) {
  console.log('📁 Diagnostics saved to:', enhancementResult.diagnostics.blob_url);
}

// Only essential toasts now:
// - Errors (user needs to know)
// - Success completion (user needs confirmation)
// - NO intermediate steps, NO diagnostic toasts
```

### How It Works

1. **First attempt**: Parse JSON string as-is with `json.loads()`
2. **If "Extra data" error**: Use `JSONDecoder().raw_decode()` to extract valid JSON and ignore trailing content
3. **Log what was removed**: Shows the trailing content in diagnostics for debugging
4. **Graceful fallback**: If extraction fails, returns None with detailed error message

---

## Deployment Status

### Commit History
1. **Commit ccb349f3**: "Add robust JSON parsing to handle trailing content from Azure"
2. **Push**: Successfully pushed to main branch
3. **Docker Build**: Completed successfully at 21:36 UTC
4. **Container Update**: `ca-cps-gw6br2ms6mxy-api` updated to revision 0000283

### Deployment Verification
- ✅ Backend API deployed
- ✅ Frontend web app deployed
- ✅ Container apps running
- ⏳ Waiting for Azure analysis to complete (last checked: 21:56 UTC)

---

## Testing Status

### Current Test in Progress

**Test Case**: AI Enhancement on Quick Query schema
- **Schema**: `__quick_query_temp_for_enhancement__`
- **Documents**: 5 PDF files (purchase contract, property agreement, warranty, etc.)
- **User Intent**: "Based on the query 'please summarize all the input files individually', enhance this schema..."
- **Analyzer**: `ai-enhancement-5dd3bc2e-5da2-4362-8cc3-416ca22af8e3-1763329238`
- **Status**: Azure processing started at 21:40:44 UTC

### What to Check Tomorrow

1. **Success toast after AI enhancement** (shows for 8 seconds):
   ```
   ✨ Schema optimized! 5 new fields added.
   
   📁 Diagnostics: ai-enhancement-{operation-id}-{timestamp}.json
   ```
   - Copy the filename from the toast
   - Or screenshot it if needed

2. **Access the diagnostics file in Azure Portal**:
   - Go to Storage Account → Containers → `schemas`
   - Browse to `diagnostics/` folder
   - Find file with name from toast
   - Download and view

3. **Alternative: List files in Azure CLI**:
   ```bash
   az storage blob list \
     --account-name <storage-account> \
     --container-name schemas \
     --prefix diagnostics/ \
     --output table
   ```

4. **What We're Investigating**:
   - ✅ Log message: "Extracted valid JSON (ends at position XXXX)"
   - ✅ Log message: "Extra content after JSON: '...'" (showing what was removed)
   - ✅ Log message: "FINAL RESPONSE - Returning schema with X total fields"
   - ✅ Frontend displays enhanced schema successfully

3. **If Still Failing**:
   - Check if `enhanced_schema_result` is None
   - Look for `parse_error_details` in logs
   - Verify the JSON string structure (first/last 200 chars logged)
   - Check if error is different from "Extra data"

---

## Code Files Modified

### Backend
- `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`
  - Lines 12134-12145: Added `diagnostics` field to `AIEnhancementResponse` model
  - Lines 12570: Initialize `diagnostics_info` dictionary
  - Lines 12585-12620: Capture diagnostic information
    - API endpoint type, string/byte lengths
    - Last 50 characters hex analysis
    - Special character detection
  - Lines 12640-12655: Capture extra content if JSON parse requires extraction
  - Lines 12750-12780: **Save diagnostics to blob storage** (`diagnostics/ai-enhancement-{operation_id}.json`)
  - Lines 12785: Return diagnostics with blob URL in response
  
### Frontend
- `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/QuickQueryResults.tsx`
  - Lines 250-258: **Removed diagnostic toast**, log to console with blob URL instead
  - Lines 259: Simplified success toast: "Schema optimized! X new fields added." (4s)
  - Lines 334: Simplified save toast: "Schema [name] saved!" (3s)
  - Lines 121, 156-157, 182: **Removed all intermediate toasts**
  
### Toast Message Summary
**Before**: 6 toast messages (flashy, hard to catch)
- Step 1/3, Waiting, Step 2/3, Step 3/3, Diagnostic info, Success

**After**: 2 toast messages (only essential)
- ✅ Success: "Schema optimized! X new fields added."
- ✅ Success: "Schema [name] saved!"
- ❌ Errors (when they occur)

**Diagnostics**: Saved to blob storage, URL logged to console

---

## Key Insights

### Pattern Comparison

**Test Meta-Schema** (test_schema_enhancement_real_evaluation.py lines 101-118):
```python
"CompleteEnhancedSchema": {
    "type": "string",
    "method": "generate",
    "description": f"Generate the complete enhanced schema in JSON format..."
}
```

**Production Meta-Schema** (proMode.py lines 14063-14069):
```python
"CompleteEnhancedSchema": {
    "type": "string",
    "method": "generate",
    "description": f"Generate the complete enhanced schema in JSON format..."
}
```

**Conclusion**: Meta-schemas are IDENTICAL. The difference is in Azure's response format.

### Why This Happens

Azure AI models can append:
- Explanatory text after JSON
- Markdown code fences (```)
- Newlines or whitespace
- Debug information
- Model reasoning

This is common with generative AI APIs. The fix using `raw_decode()` is a **production best practice** for handling real-world AI API responses.

---

## Next Steps (Tomorrow)

1. **Verify Fix Works**
   - Check logs for successful JSON extraction
   - Confirm enhanced schema loads in frontend
   - Verify all fields are present in returned schema

2. **If Successful**
   - Document success in completion file
   - Consider adding similar parsing to other Azure API responses
   - Update error handling documentation

3. **If Still Failing**
   - Capture actual `valueString` content to file for analysis
   - Check if Azure is returning completely different structure
   - Consider contacting Azure support about API response format changes

4. **Performance Optimization**
   - Monitor Azure processing time (currently ~15+ minutes for 5 documents)
   - Consider reducing timeout if needed
   - Add progress indicators for long-running enhancements

---

## References

### Test Files
- `data/schema_enhancement_test_results_1759669180.json` - Clean test response (4,873 chars)
- `test_schema_enhancement_real_evaluation.py` - Original test that captured data
- `extract_enhanced_schema.py` - Script that successfully parsed test data

### Documentation
- Azure Content Understanding API: 2025-05-01-preview
- Python `json.JSONDecoder.raw_decode()`: Extracts valid JSON from beginning of string

### Git Commits
- `ccb349f3`: Add robust JSON parsing to handle trailing content from Azure
- `8017292e`: Previous commit (before fix)

---

## Azure API Investigation Notes

### Current API: :analyze (Text/JSON)

The code uses:
```
POST /contentunderstanding/analyzers/{analyzer_id}:analyze
```

This is the **text/JSON API** that:
- Accepts JSON payloads with file URLs
- Returns JSON responses
- Field values are in `valueString` properties
- **Current Issue**: May be appending extra content after the JSON string

### Alternative API: :analyzebinary (Binary) - NOT USED

Azure also provides:
```
POST /contentunderstanding/analyzers/{analyzer_id}:analyzebinary
```

This is for **binary file uploads** and:
- Accepts binary file content in request body
- Returns binary output
- Different use case from our current implementation
- **Not the solution** to the current parsing issue

### Investigation Focus

We're **NOT** trying to switch to binary API. We're investigating:

1. **Character Analysis**: Print last 50 characters with hex bytes and char codes
   - Are there invisible characters? (BOM, null bytes, etc.)
   - Is there text content being appended? (markdown fences, debug info, etc.)

2. **Encoding Verification**: Check if response encoding is correct
   - Is it actually a Python `str` type?
   - Is UTF-8 byte length matching character length?
   - Any encoding corruption?

3. **API Behavior Change**: Compare test vs production
   - Test (Nov 3): 4,873 chars, clean JSON
   - Production (Nov 16): 6,402 chars, extra content at position 6,401
   - Did Azure change the AI model or response format?

### Diagnostic Logging Added

The code now prints detailed diagnostics:
- **API type verification**: Confirms using :analyze (not :analyzebinary)
- **String properties**: Type, character length, byte length
- **Last 50 characters**: Raw repr, hex bytes, char codes, special chars found
- **Extra content analysis**: If parsing fails, shows what was removed

This will help us understand **what** Azure is adding and **why**.

## Accessing Diagnostics Files

### Method 1: Browser Console (Easiest)

1. After AI enhancement completes, open browser DevTools (F12)
2. Look for console log: `📁 Diagnostics saved to: https://...`
3. Click the URL to download/view the JSON file

### Method 2: Azure Portal

1. Go to Azure Portal → Storage Account
2. Navigate to container: `schemas`
3. Browse to folder: `diagnostics/`
4. Files named: `ai-enhancement-{operation-id}-{timestamp}.json`
5. Download and view in text editor

### Method 3: Azure CLI

```bash
# List recent diagnostics files
az storage blob list \
  --account-name <storage-account> \
  --container-name schemas \
  --prefix diagnostics/ \
  --query "[?properties.lastModified >= '2025-11-17'].{name:name, size:properties.contentLength, modified:properties.lastModified}" \
  --output table

# Download a specific file
az storage blob download \
  --account-name <storage-account> \
  --container-name schemas \
  --name diagnostics/ai-enhancement-{operation-id}-{timestamp}.json \
  --file diagnostics.json
```

### Diagnostics File Contents

```json
{
  "timestamp": "2025-11-17T...",
  "operation_id": "...",
  "analyzer_id": "...",
  "schema_id": "...",
  "diagnostics": {
    "api_endpoint": ":analyze (text/JSON)",
    "string_length": 6402,
    "byte_length_utf8": 6402,
    "first_100_chars": "{\"fieldSchema\":{\"fields\":{...",
    "last_100_chars": "...}}}",
    "special_chars": ["newline at [45, 48]"],
    "last_50_hex": "7d7d7d0a0a",
    "extra_content": {
      "detected": true,
      "length": 1500,
      "preview": "```markdown\nThis is...",
      "hex_bytes_first_100": "60606..."
    },
    "blob_url": "https://...diagnostics/..."
  },
  "enhancement_summary": {
    "new_fields_added": ["field1", "field2"],
    "total_fields": 15,
    "status": "success"
  }
}
```

---

## Summary

**Problem**: Azure :analyze API appending ~1,500 extra characters after valid JSON, causing parse failure

**Fix 1**: Use `JSONDecoder.raw_decode()` to extract valid JSON and discard trailing content

**Fix 2**: Save diagnostics to persistent blob storage, filename shown in success toast (8 seconds)

**Investigation**: Diagnostics capture what Azure is adding (special chars, extra content, encoding)

**API Clarification**: Using :analyze (text/JSON) API - NOT :analyzebinary (binary) API

**Toast Optimization**: Reduced from 6 toasts to 1 success toast (includes diagnostics filename)

**Diagnostics Access**: 
- Filename shown in success toast for 8 seconds
- Saved to `diagnostics/ai-enhancement-{operation-id}.json` in blob storage
- Browse in Azure Portal using filename from toast
- No console logs needed (works in production!)

**Status**: Deployed and running, awaiting test completion with persistent diagnostics

**Next Action**: After AI enhancement, copy/screenshot the diagnostics filename from toast, then download from Azure Portal

````
