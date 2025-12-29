# Azure Storage Queue Configuration Guide for Container Apps

## 🎯 Overview
This guide provides step-by-step instructions to properly configure Azure Storage Queue in your Container Apps environment for the Pro Mode API.

## 📋 Prerequisites Checklist

### ✅ Required Azure Resources
- [ ] Azure Storage Account (with Queue service enabled)
- [ ] Azure Container Apps Environment
- [ ] Container App (for your API)
- [ ] Managed Identity or Service Principal for authentication

### ✅ Required Permissions
- [ ] Storage Queue Data Contributor (on Storage Account)
- [ ] Container Apps Contributor (for configuration)
- [ ] Key Vault Secrets User (if using Key Vault)

## 🔧 Step 1: Azure Storage Account Configuration

### 1.1 Create/Verify Storage Account
```bash
# Check if storage account exists
az storage account show --name <your-storage-account> --resource-group <your-rg>

# Create if needed
az storage account create \
  --name <your-storage-account> \
  --resource-group <your-rg> \
  --location <your-location> \
  --sku Standard_LRS \
  --kind StorageV2
```

### 1.2 Enable Queue Service
```bash
# Verify queue service is enabled (should be by default)
az storage account show --name <your-storage-account> --resource-group <your-rg> \
  --query "primaryEndpoints.queue"
```

### 1.3 Get Storage Queue URL
```bash
# Get the queue service endpoint
QUEUE_URL=$(az storage account show --name <your-storage-account> --resource-group <your-rg> \
  --query "primaryEndpoints.queue" -o tsv)
echo "Queue URL: $QUEUE_URL"
```

## 🔐 Step 2: Authentication Configuration

### Option A: Managed Identity (Recommended)

#### 2.1 Enable System-Assigned Managed Identity
```bash
# Enable managed identity for Container App
az containerapp identity assign \
  --name <your-container-app> \
  --resource-group <your-rg> \
  --system-assigned
```

#### 2.2 Grant Storage Permissions
```bash
# Get the managed identity principal ID
PRINCIPAL_ID=$(az containerapp identity show \
  --name <your-container-app> \
  --resource-group <your-rg> \
  --query "principalId" -o tsv)

# Get storage account resource ID
STORAGE_ID=$(az storage account show \
  --name <your-storage-account> \
  --resource-group <your-rg> \
  --query "id" -o tsv)

# Assign Storage Queue Data Contributor role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Storage Queue Data Contributor" \
  --scope $STORAGE_ID
```

### Option B: Connection String (Less Secure)

#### 2.1 Get Connection String
```bash
# Get storage account connection string
az storage account show-connection-string \
  --name <your-storage-account> \
  --resource-group <your-rg> \
  --query "connectionString" -o tsv
```

## ⚙️ Step 3: Container Apps Environment Variables

### 3.1 Required Environment Variables
Set these environment variables in your Container App:

```bash
# Using Azure CLI
az containerapp update \
  --name <your-container-app> \
  --resource-group <your-rg> \
  --set-env-vars \
    APP_STORAGE_QUEUE_URL="https://<your-storage-account>.queue.core.windows.net/" \
    APP_MESSAGE_QUEUE_EXTRACT="extract-queue" \
    APP_MESSAGE_QUEUE_PRO="pro-mode-queue"
```

### 3.2 Using Azure Portal
1. Navigate to your Container App
2. Go to **Configuration** → **Environment variables**
3. Add the following variables:

| Name | Value | Source |
|------|-------|---------|
| `APP_STORAGE_QUEUE_URL` | `https://<storage-account>.queue.core.windows.net/` | Manual |
| `APP_MESSAGE_QUEUE_EXTRACT` | `extract-queue` | Manual |
| `APP_MESSAGE_QUEUE_PRO` | `pro-mode-queue` | Manual |

### 3.3 Using Bicep/ARM Template
```json
{
  "type": "Microsoft.App/containerApps",
  "properties": {
    "template": {
      "containers": [{
        "env": [
          {
            "name": "APP_STORAGE_QUEUE_URL",
            "value": "https://[parameters('storageAccountName')].queue.core.windows.net/"
          },
          {
            "name": "APP_MESSAGE_QUEUE_EXTRACT", 
            "value": "extract-queue"
          },
          {
            "name": "APP_MESSAGE_QUEUE_PRO",
            "value": "pro-mode-queue"
          }
        ]
      }]
    }
  }
}
```

## 🧪 Step 4: Configuration Verification

### 4.1 Test Queue Access
```bash
# Test queue creation (requires Azure CLI with storage extension)
az storage queue create \
  --name "test-queue" \
  --account-name <your-storage-account> \
  --auth-mode login

# Test message sending
az storage message put \
  --queue-name "test-queue" \
  --content "test message" \
  --account-name <your-storage-account> \
  --auth-mode login

# Clean up test queue
az storage queue delete \
  --name "test-queue" \
  --account-name <your-storage-account> \
  --auth-mode login
```

### 4.2 Container App Health Check
Create a health check endpoint to verify configuration:

```python
@router.get("/health/queue", summary="Queue configuration health check")
async def queue_health_check(app_config: AppConfiguration = Depends(get_app_config)):
    """Check queue configuration and connectivity."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "queue_config": {}
    }
    
    # Check configuration
    if app_config.app_storage_queue_url:
        health_status["queue_config"]["storage_queue_url"] = "✅ Configured"
    else:
        health_status["queue_config"]["storage_queue_url"] = "❌ Missing"
        health_status["status"] = "unhealthy"
    
    if app_config.app_message_queue_extract:
        health_status["queue_config"]["extract_queue"] = "✅ Configured"
    else:
        health_status["queue_config"]["extract_queue"] = "❌ Missing"
        health_status["status"] = "unhealthy"
    
    # Test queue connectivity
    try:
        queue_helper = StorageQueueHelper(
            app_config.app_storage_queue_url,
            "health-check-queue"
        )
        # Just test creation, don't send messages
        health_status["queue_config"]["connectivity"] = "✅ Connected"
    except Exception as e:
        health_status["queue_config"]["connectivity"] = f"❌ Failed: {str(e)}"
        health_status["status"] = "unhealthy"
    
    return health_status
```

## 🔍 Step 5: Troubleshooting Common Issues

### Issue 1: Authentication Failures
```
Error: DefaultAzureCredential failed to retrieve a token
```

**Solutions:**
1. Verify Managed Identity is enabled
2. Check role assignments
3. Ensure Container App has restarted after identity assignment

### Issue 2: Queue URL Format
```
Error: Invalid URL format
```

**Solutions:**
1. Ensure URL ends with `/`
2. Use HTTPS (not HTTP)
3. Format: `https://<account>.queue.core.windows.net/`

### Issue 3: Missing Environment Variables
```
Error: Field required [type=missing, input_value={}, input_type=dict]
```

**Solutions:**
1. Verify all required env vars are set
2. Check variable names match exactly
3. Restart Container App after configuration changes

### Issue 4: Permission Denied
```
Error: This request is not authorized to perform this operation
```

**Solutions:**
1. Grant `Storage Queue Data Contributor` role
2. Wait for role assignment propagation (up to 5 minutes)
3. Verify scope is set to storage account level

## 📊 Step 6: Monitoring and Logging

### 6.1 Enable Container App Logs
```bash
# Enable Container Apps logging
az containerapp logs show \
  --name <your-container-app> \
  --resource-group <your-rg> \
  --follow
```

### 6.2 Monitor Queue Metrics
```bash
# View queue metrics
az monitor metrics list \
  --resource $STORAGE_ID \
  --metric QueueCount,QueueMessageCount \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)
```

### 6.3 Set Up Alerts
```bash
# Create alert for queue message count
az monitor metrics alert create \
  --name "Queue-Message-Count-High" \
  --resource-group <your-rg> \
  --scopes $STORAGE_ID \
  --condition "max QueueMessageCount > 1000" \
  --description "High number of messages in queue"
```

## ✅ Configuration Checklist

Before deploying to production, verify:

- [ ] Storage Account created and accessible
- [ ] Queue service endpoint URL configured
- [ ] Managed Identity enabled and assigned
- [ ] Storage Queue Data Contributor role granted
- [ ] Environment variables set correctly
- [ ] Container App restarted after configuration
- [ ] Health check endpoint returns healthy status
- [ ] Test message can be sent and received
- [ ] Monitoring and alerting configured

## 🚀 Next Steps

1. **Deploy Updated Code**: Ensure the fixed `StorageQueueHelper` is deployed
2. **Test Pro Mode API**: Use the `/pro/content-analyzers` endpoint
3. **Monitor Queue Activity**: Check that messages are being processed
4. **Scale if Needed**: Configure queue processing based on load

## 📝 Configuration Templates

### Environment Variables Template
```bash
export APP_STORAGE_QUEUE_URL="https://yourstorageaccount.queue.core.windows.net/"
export APP_MESSAGE_QUEUE_EXTRACT="extract-queue"
export APP_MESSAGE_QUEUE_PRO="pro-mode-queue"
export APP_COSMOS_CONNSTR="your-cosmos-connection-string"
export APP_COSMOS_DATABASE="your-database-name"
export APP_COSMOS_CONTAINER_SCHEMA="your-schema-container"
```

### Azure CLI Configuration Script
```bash
#!/bin/bash
RESOURCE_GROUP="your-resource-group"
CONTAINER_APP="your-container-app"
STORAGE_ACCOUNT="your-storage-account"

# Configure environment variables
az containerapp update \
  --name $CONTAINER_APP \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    APP_STORAGE_QUEUE_URL="https://$STORAGE_ACCOUNT.queue.core.windows.net/" \
    APP_MESSAGE_QUEUE_EXTRACT="extract-queue" \
    APP_MESSAGE_QUEUE_PRO="pro-mode-queue"

echo "✅ Configuration complete!"
```
