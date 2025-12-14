# Azure Portal Monitoring Commands

## Step 1: Find your container app
```bash
az containerapp list -o table
```

## Step 2: Monitor for success markers (use the correct names from step 1)
```bash
az containerapp logs show \
  --name [YOUR_CONTAINER_APP_NAME] \
  --resource-group [YOUR_RESOURCE_GROUP] \
  --follow | grep -E "(SUCCESS MARKER|AnalyzeContent.*✅|🔄 SURVIVAL CHECK|🎉 Full execution completed)"
```

## Step 3: Alternative - Get recent logs without follow
```bash
az containerapp logs show \
  --name [YOUR_CONTAINER_APP_NAME] \
  --resource-group [YOUR_RESOURCE_GROUP] \
  --tail 100 | grep -E "(SUCCESS MARKER|AnalyzeContent.*✅|🔄 SURVIVAL CHECK)"
```

## What to look for:
- `SUCCESS MARKER A`: Both blob URI generations completed
- `SUCCESS MARKER B`: Azure API call starting  
- `SUCCESS MARKER C`: Azure API response received
- `SUCCESS MARKER D`: Complete success

## If you see iteration 4 logs but no SUCCESS MARKERS:
The success markers may not be deployed yet - check if you need to redeploy the updated code.
