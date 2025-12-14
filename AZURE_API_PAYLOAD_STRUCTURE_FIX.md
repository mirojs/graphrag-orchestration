# Azure Content Understanding API Payload Structure Fix

## Issue Identified
The POST request to Azure Content Understanding API was returning a 500 InternalServerError because the payload structure was incorrect according to the official API specification.

## Root Cause
The code was sending a flat array of URLs instead of following the proper `AnalyzeRequest` object structure defined in the Azure API documentation.

### Previous (Incorrect) Payload Structure:
```json
[
  {"url": "input_file_url"},
  {"url": "reference_file_url1"},  
  {"url": "reference_file_url2"},
  {"url": "reference_file_url3"},
  {"url": "reference_file_url4"}
]
```

### Fixed (Correct) Payload Structure:
```json
{
  "url": "primary_input_url",  // OR "data": "base64_content"
  "inputs": [
    {"url": "reference_file_url1"},
    {"url": "reference_file_url2"}, 
    {"url": "reference_file_url3"},
    {"url": "reference_file_url4"}
  ]
}
```

## API Specification Reference
According to Microsoft documentation: https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/analyze?view=rest-contentunderstanding-2025-05-01-preview&tabs=HTTP#analyzeinput

### AnalyzeRequest Object:
- **data**: `string (byte)` - Base64-encoded binary content of the primary input to analyze. Only one of url or data should be specified.
- **inputs**: `AnalyzeInput[]` - Additional inputs to analyze. Only supported in analyzers with mode=pro.
- **url**: `string (uri)` - The URL of the primary input to analyze. Only one of url or data should be specified.

## Changes Made

### 1. URL Approach (Multiple files or reference files present):
- Primary input file goes in the root `url` field
- Reference files go in the `inputs` array field
- Each reference file is an object with a `url` field

### 2. Bytes Approach (Single file, no reference files):
- Primary input file content is base64-encoded and goes in the `data` field
- Content-Type changed from `application/octet-stream` to `application/json`
- No reference files supported in this approach

### 3. HTTP Request Method:
- Both approaches now use `client.post(url, json=payload)` instead of mixed approaches
- Consistent JSON payload handling

## Key Benefits
1. **Compliance**: Follows official Azure API specification exactly
2. **Error Prevention**: Eliminates 500 InternalServerError caused by malformed payload
3. **Pro Mode Support**: Properly supports reference files in pro mode analyzers
4. **Flexibility**: Supports both URL and base64 data approaches as per API spec

## Testing Recommendations
1. Test with single input file (should use bytes/data approach)
2. Test with input + reference files (should use URL approach with inputs array)
3. Verify payload structure in logs matches the corrected format
4. Confirm Azure API accepts the new payload without 500 errors

## Files Modified
- `/app/routers/proMode.py` - Updated payload building logic for both URL and bytes approaches
