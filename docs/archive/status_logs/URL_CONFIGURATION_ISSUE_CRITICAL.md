# URL Configuration Issue Analysis - CRITICAL

## Problem Summary
The system is attempting to make API requests to `learn.microsoft.com` (Microsoft documentation site) instead of the correct Azure Cognitive Services endpoint, resulting in **HTTP 501 - Unsupported Request** errors.

## Error Details
```
PUT to http://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/contentunderstanding/analyzers/analyzer-1756489373497-0nmkiy051
```

### URL Analysis
- **Wrong**: `learn.microsoft.com` (documentation site, doesn't accept API calls)
- **Correct**: `aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com` (actual Azure service)

## Root Cause Analysis

### 1. Configuration State
- ✅ Backend code logic is correct
- ❌ `APP_CONTENT_UNDERSTANDING_ENDPOINT` not set in current environment
- ⚠️  Possible configuration corruption in deployment

### 2. Evidence from Backend Logs
Earlier logs showed the system working correctly:
```
[DEBUG] Content Understanding Endpoint: https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com/
```

But current attempt shows misconfigured URL mixing documentation and service URLs.

### 3. Timing Analysis
- Error timestamp: `Fri, 29 Aug 2025 18:09:48 GMT`
- This suggests a recent configuration change or deployment issue

## Immediate Solutions

### Option 1: Fix Azure App Configuration
```bash
az appconfig kv set \
  --endpoint https://appcs-cps-xh5lwkfq3vfm.azconfig.io \
  --key APP_CONTENT_UNDERSTANDING_ENDPOINT \
  --value 'https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com'
```

### Option 2: Fix Container App Environment Variable
```bash
az containerapp update \
  --name ca-cps-xh5lwkfq3vfm-api \
  --resource-group rg-contentaccelerator \
  --set-env-vars APP_CONTENT_UNDERSTANDING_ENDPOINT='https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com'
```

### Option 3: Restart Container App (if config cached)
```bash
az containerapp restart \
  --name ca-cps-xh5lwkfq3vfm-api \
  --resource-group rg-contentaccelerator
```

## Verification Steps

### 1. Check Current Configuration
```bash
# Check App Configuration
az appconfig kv show \
  --endpoint https://appcs-cps-xh5lwkfq3vfm.azconfig.io \
  --key APP_CONTENT_UNDERSTANDING_ENDPOINT \
  --query "value" --output tsv

# Check Container App Environment
az containerapp show \
  --name ca-cps-xh5lwkfq3vfm-api \
  --resource-group rg-contentaccelerator \
  --query "properties.template.containers[0].env" \
  --output table
```

### 2. Test Endpoint Accessibility
```bash
# Test the correct endpoint
curl -X GET 'https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com/contentunderstanding/analyzers?api-version=2025-05-01-preview' \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

### 3. Monitor Backend Logs
Look for these log entries after fix:
```
[DEBUG] Content Understanding Endpoint: https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com
[AnalyzerCreate] Azure URL: https://aicu-cps-xh5lwkfq3vfm.cognitiveservices.azure.com/contentunderstanding/analyzers/...
```

## Prevention Measures

### 1. Add Configuration Validation
Add startup checks to validate the endpoint format and accessibility.

### 2. Environment Variable Monitoring
Set up alerts for configuration changes to critical environment variables.

### 3. Health Checks
Implement health checks that verify Azure service connectivity.

## Expected Outcome

After fixing the configuration:
1. ✅ Requests will go to correct Azure endpoint
2. ✅ Schema uploads should work (with method property cleaning)
3. ✅ Analyzer creation should succeed
4. ✅ Backend logs will show correct URL construction

## Priority: URGENT

This is a deployment configuration issue that prevents all Azure API functionality. The method property fix we implemented earlier is ready to work once this URL configuration is corrected.

## Next Steps
1. **Immediate**: Fix the endpoint configuration using one of the solutions above
2. **Verify**: Test schema upload after configuration fix
3. **Monitor**: Check backend logs for correct URL usage
4. **Test**: Verify the method property deprecation fix works with correct endpoint
