#!/bin/bash
set -e

echo "=========================================="
echo "Azure AD B2C / External ID Configuration"
echo "=========================================="
echo ""

# Quick configuration for known B2C tenant
echo "Detected B2C Tenant:"
echo "  Name: graphrag-b2c"
echo "  Domain: graphragb2c.onmicrosoft.com"
echo "  Tenant ID: aa5210de-5c3a-4383-adbb-13c7998b1be0"
echo ""

read -p "Use this tenant? (y/n): " USE_DETECTED

if [ "$USE_DETECTED" = "y" ]; then
    B2C_TENANT_ID="aa5210de-5c3a-4383-adbb-13c7998b1be0"
    B2C_TENANT_NAME="graphragb2c"
else
    read -p "Enter B2C tenant ID: " B2C_TENANT_ID
    read -p "Enter B2C tenant name (without .onmicrosoft.com): " B2C_TENANT_NAME
fi

# Login to B2C tenant
echo ""
echo "Logging into B2C tenant..."
az login --tenant "$B2C_TENANT_ID" --allow-no-subscriptions --use-device-code

# Check for existing app registrations
echo ""
echo "Existing app registrations:"
az ad app list --query "[].{Name:displayName, AppId:appId}" --output table

echo ""
read -p "Do you have an existing app registration? (y/n): " HAS_APP

if [ "$HAS_APP" = "y" ]; then
    read -p "Enter the Application (client) ID: " B2C_CLIENT_ID
else
    echo ""
    echo "Creating new app registration..."
    
    # Get callback URL
    read -p "Enter Azure region (default: swedencentral): " AZURE_REGION
    AZURE_REGION=${AZURE_REGION:-swedencentral}
    CALLBACK_URL="https://graphrag-api-b2c.${AZURE_REGION}.azurecontainerapps.io/.auth/login/aad/callback"
    
    APP_RESULT=$(az ad app create \
        --display-name "GraphRAG Frontend B2C" \
        --sign-in-audience "AzureADandPersonalMicrosoftAccount" \
        --web-redirect-uris "$CALLBACK_URL" \
        --query "{appId: appId, id: id}" -o json)
    
    B2C_CLIENT_ID=$(echo $APP_RESULT | jq -r '.appId')
    APP_OBJECT_ID=$(echo $APP_RESULT | jq -r '.id')
    
    echo "✅ Created app: $B2C_CLIENT_ID"
    
    # Expose API
    az ad app update --id "$APP_OBJECT_ID" --identifier-uris "api://$B2C_CLIENT_ID"
    
    # Create secret
    read -p "Create client secret? (y/n): " CREATE_SECRET
    if [ "$CREATE_SECRET" = "y" ]; then
        B2C_CLIENT_SECRET=$(az ad app credential reset \
            --id "$APP_OBJECT_ID" \
            --append \
            --display-name "graphrag-b2c-secret" \
            --query password -o tsv)
        echo "✅ Secret created (save this!): $B2C_CLIENT_SECRET"
    fi
fi

# Switch back to default subscription
echo ""
echo "Switching back to default subscription..."
az account set --subscription "$(az account show --query id -o tsv)"

# Configure azd
echo ""
echo "Configuring azd environment..."
azd env set AZURE_ENABLE_B2C true
azd env set AZURE_B2C_TENANT_NAME "$B2C_TENANT_NAME"
azd env set AZURE_B2C_TENANT_ID "$B2C_TENANT_ID"
azd env set AZURE_B2C_CLIENT_ID "$B2C_CLIENT_ID"

if [ -n "$B2C_CLIENT_SECRET" ]; then
    azd env set AZURE_B2C_CLIENT_SECRET "$B2C_CLIENT_SECRET"
fi

echo ""
echo "=========================================="
echo "✅ Configuration Complete!"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Tenant: ${B2C_TENANT_NAME}.ciamlogin.com"
echo "  Tenant ID: $B2C_TENANT_ID"
echo "  Client ID: $B2C_CLIENT_ID"
echo ""
echo "Next: Run 'azd up' to deploy B2C variant"
echo ""
