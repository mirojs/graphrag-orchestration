# Manual Test Guide for Your Azure Content Understanding API

## Quick Test Steps

### 1. First, get your actual Content Understanding endpoint from Azure Portal:

1. Go to https://portal.azure.com
2. Navigate to your resource group (should contain "cps" in the name)
3. Find the **Cognitive Services** resource (might be named like `aisa-cps-...`)
4. Click on it → **Keys and Endpoint** → Copy the **Endpoint** URL

### 2. Or use Azure CLI to get it from App Configuration:

```bash
# Login to Azure
az login

# Get the Content Understanding endpoint from your App Configuration
az appconfig kv show --endpoint https://appcs-cps-xh5lwkfq3vfm.azconfig.io --key APP_CONTENT_UNDERSTANDING_ENDPOINT --query "value" --output tsv
```

### 3. Test the API directly with curl:

Replace `YOUR_ENDPOINT` with the actual endpoint you found:

```bash
# Test if the endpoint is reachable and supports 2025-05-01-preview
curl -H "Authorization: Bearer $(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken --output tsv)" \
     "YOUR_ENDPOINT/contentunderstanding/analyzers?api-version=2025-05-01-preview"
```

### 4. Expected Results:

- **✅ Success**: You should see a JSON response with available analyzers
- **❌ 404 Error**: The endpoint doesn't support 2025-05-01-preview yet
- **❌ 401 Error**: Authentication issue (try running `az login` first)

### 5. If you get analyzers, look for:

```json
{
  "analyzers": [
    {
      "id": "prebuilt-layout",  // ← This is what your code uses
      "kind": "prebuilt",
      ...
    }
  ]
}
```

### 6. Test your actual code:

If the curl test works, you can test your Python code:

```bash
# Set the environment variable
export APP_CONTENT_UNDERSTANDING_ENDPOINT="YOUR_ACTUAL_ENDPOINT"

# Run your test
python quick_test_2025_api.py
```

## What We're Testing:

1. **API Version Support**: Does your Azure service support 2025-05-01-preview?
2. **Analyzer Availability**: Is "prebuilt-layout" available in the new API version?
3. **Authentication**: Are your Azure credentials working?
4. **Code Compatibility**: Does your updated code work with the new API?

## Next Steps Based on Results:

- **If curl works**: Your endpoint supports 2025-05-01-preview ✅
- **If you get 404**: Your Azure service might be on an older version, may need to wait for rollout
- **If you get different analyzer names**: Update your code to use the correct analyzer IDs

Let me know what you find with the curl test!
