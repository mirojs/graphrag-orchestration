# PUT vs POST Request Payload Comparison

## Browser Console Analysis

### Step 1 - PUT Request (WORKING - 200)
- **URL**: `/pro-mode/content-analyzers/analyzer-1755769475079-9cr0fb4lu`
- **Method**: PUT
- **Status**: 200 ✅
- **Purpose**: Create content analyzer
- **Analyzer ID**: analyzer-1755769475079-9cr0fb4lu

### Step 2 - POST Request (FAILING - 500)  
- **URL**: `/pro-mode/content-analyzers/analyzer-1755769475079-9cr0fb4lu:analyze`
- **Method**: POST  
- **Status**: 500 ❌
- **Purpose**: Analyze content using the created analyzer

## Key Investigation Points

### 1. Payload Structure Comparison
**PUT Request Payload (Analyzer Creation):**
```json
{
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "schemaId": "705c6202-3cd5-4a09-9a3e-a7f5bbacc560", 
  "fieldSchema": {
    "fields": [...]
  },
  "description": "Custom analyzer for invoice_contract_verification_pro_mode"
}
```

**POST Request Payload (Content Analysis):**
```json
{
  "inputFiles": ["blob1"],
  "referenceFiles": ["ref1", "ref2", "ref3", "ref4"],
  "schema": {...}
}
```

### 2. Schema Processing Differences
- **PUT**: Processes schema for analyzer creation
- **POST**: Uses existing analyzer but processes files + schema for analysis

### 3. Backend Processing Differences
- **PUT**: Simpler flow - just create analyzer in Azure
- **POST**: Complex flow - blob URIs + Azure API analysis call

## Next Investigation Steps

1. **Compare exact payloads** from browser Network tab
2. **Check what happens after authentication** in POST logs
3. **Look for SUCCESS MARKER B, C, D** in POST request
4. **Compare Azure API endpoint URLs** being called

## Likely Issues
1. **Payload format mismatch** for Azure Content Understanding API
2. **Schema transformation error** in POST request  
3. **Blob URI format issues** in POST payload
4. **Azure API compatibility** between analyzer creation vs analysis calls
