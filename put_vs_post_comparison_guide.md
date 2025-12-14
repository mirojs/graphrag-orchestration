# PUT vs POST Request Detailed Comparison Guide

## Request Overview
- **PUT**: `/pro-mode/content-analyzers/{analyzer_id}` (Working - 200)
- **POST**: `/pro-mode/content-analyzers/{analyzer_id}:analyze` (Failing - 500)

## Key Comparison Points

### 1. Authentication Headers
**PUT Request Headers:**
```
Content-Type: application/json
Authorization: Bearer {managed_identity_token}
```

**POST Request Headers:**
```
Content-Type: application/json  
Authorization: Bearer {managed_identity_token}
```

*Check: Both should now use managed identity after our fix*

### 2. Request Payload Structure
**PUT Request Body (Analyzer Creation):**
```json
{
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "schemaId": "schema_xxx",
  "fieldSchema": {
    "fields": [...]
  }
}
```

**POST Request Body (Content Analysis):**
```json
{
  "inputFiles": ["blob1", "blob2"],
  "referenceFiles": ["ref1", "ref2", "ref3", "ref4"],
  "schema": {...}
}
```

### 3. Azure API Endpoints Called
**PUT calls:**
```
PUT {endpoint}/contentunderstanding/analyzers/{analyzer_id}?api-version=2025-05-01-preview
```

**POST calls:**
```
POST {endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze?api-version=2025-05-01-preview
```

## Investigation Steps

### Step 1: Check Browser Network Tab
1. Open browser Developer Tools (F12)
2. Go to Network tab
3. Run both PUT and POST requests
4. Compare:
   - Request headers
   - Request payload
   - Response headers
   - Response body

### Step 2: Backend Log Comparison
Look for these specific log messages:

**PUT Request Logs:**
```
[AnalyzerCreate] ===== FORCING MANAGED IDENTITY AUTHENTICATION =====
[AnalyzerCreate] ✅ FORCED Credential type: ManagedIdentityCredential
```

**POST Request Logs:**
```
[AnalyzeContent] ===== FORCING MANAGED IDENTITY AUTHENTICATION =====
[AnalyzeContent] ✅ FORCED Credential type: ManagedIdentityCredential
[AnalyzeContent] ✅ SUCCESS MARKER B: About to make Azure API call
[AnalyzeContent] ✅ SUCCESS MARKER C: Azure API response received!
```

### Step 3: Key Questions to Answer
1. Do you see both authentication logging messages?
2. Do you see SUCCESS MARKER B in the POST logs?
3. What's the exact difference in request payloads?
4. Are the Azure endpoint URLs exactly the same?

## Next Debugging Action
**Most Important:** Check if you see this log message:
```
[AnalyzeContent] ✅ SUCCESS MARKER B: About to make Azure API call
```

If you DON'T see SUCCESS MARKER B, the error is happening before the Azure API call (payload building issue).
If you DO see SUCCESS MARKER B but not C, the error is in the Azure API call itself.
