# Azure Deployment Testing Commands

## Quick Health Check
```bash
# Test ProMode health endpoint
curl -X GET "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/health" | jq .

# Expected: {"status": "healthy", "timestamp": "...", "checks": {...}}
```

## Test Individual Components

### 1. CORS Headers
```bash
curl -I -H "Origin: http://localhost:3000" \
  "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/health"

# Expected: access-control-allow-origin header present
```

### 2. Schema Upload
```bash
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/schemas/upload" \
  -F "files=@test-schema.json"

# Expected: {"schemas": [...], "count": 1}
```

### 3. File Uploads
```bash
# Input files
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/input-files" \
  -F "files=@test-document.pdf"

# Reference files  
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files" \
  -F "files=@test-reference.pdf"

# Expected: {"files": [...], "count": 1}
```

### 4. Content Analyzer (2025 API)
```bash
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/content-analyzers?api-version=2025-05-01-preview" \
  -H "Content-Type: application/json" \
  -d '{
    "analyzerId": "test-analyzer",
    "analysisMode": "pro",
    "baseAnalyzerId": "prebuilt-documentAnalyzer"
  }'

# Expected: {"analyzerId": "...", "status": "created", ...}
```

## Troubleshooting

### If Health Check Fails
1. Check Azure Container Apps logs
2. Verify environment variables are set
3. Test database connectivity
4. Check blob storage configuration

### If CORS Errors Persist
1. Verify main.py has CORSMiddleware
2. Check Azure deployment includes latest code
3. Restart Azure Container Apps if needed

### If File Uploads Fail
1. Check blob storage permissions
2. Verify container creation works
3. Test with smaller files first
4. Check Azure storage account access

### If Schema Uploads Get 500 Errors
1. Test database connection with health endpoint
2. Verify Cosmos DB connection string
3. Check database name and container name
4. Test with simple schema first (use test-schema.json)
