#!/bin/bash
set -e

echo "=========================================="
echo "Azure AD B2C / External ID Configuration"
echo "=========================================="
echo ""

# Auto-detect B2C tenant
echo "Auto-detecting B2C tenant..."
echo ""

# Based on the output we saw, graphrag-b2c tenant
B2C_TENANT_ID="aa5210de-5c3a-4383-adbb-13c7998b1be0"
B2C_TENANT_NAME="graphragb2c"
B2C_DOMAIN="graphragb2c.onmicrosoft.com"

echo "✅ Detected B2C tenant:"
echo "   Name: graphrag-b2c"
echo "   Domain: $B2C_DOMAIN"
echo "   Tenant ID: $B2C_TENANT_ID"
echo ""

read -p "Is this correct? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ]; then
    echo "Please enter B2C tenant details manually:"
    read -p "B2C Tenant ID: " B2C_TENANT_ID
    read -p "B2C Tenant Name (without .onmicrosoft.com): " B2C_TENANT_NAME
fi

# Step 2: Check for existing app registration
echo ""
echo "Step 2: App Registration"
echo "------------------------"
echo "Switching to B2C tenant..."

az login --tenant "$B2C_TENANT_ID" --allow-no-subscriptions --use-device-code

echo ""
echo "Checking for existing app registrations..."
APPS=$(az ad app list --query "[].{Name:displayName, AppId:appId, Id:id}" -o json)

if [ "$(echo "$APPS" | jq 'length')" -gt 0 ]; then
    echo ""
    echo "Existing app registrations:"
    echo "$APPS" | jq -r '.[] | "\(.Name) - \(.AppId)"'
    echo ""
fi

read -p "Do you have an existing app registration for GraphRAG? (y/n): " HAS_APP

if [ "$HAS_APP" = "y" ]; then
    read -p "Enter the existing Application (client) ID: " B2C_CLIENT_ID
    
    # Get the app details
    APP_OBJECT_ID=$(az ad app show --id "$B2C_CLIENT_ID" --query id -o tsv)
    echo "✅ Using existing app: $B2C_CLIENT_ID"
    
else
    echo ""
    echo "Creating new app registration..."
    
    # Create app registration
    APP_RESULT=$(az ad app create \
        --display-name "GraphRAG Frontend B2C" \
        --sign-in-audience "AzureADandPersonalMicrosoftAccount" \
        --enable-id-token-issuance true \
        --web-home-page-url "https://graphrag-api-b2c.salmonhill-df6033f3.swedencentral.azurecontainerapps.io" \
        --query "{appId: appId, id: id}" -o json)
    
    B2C_CLIENT_ID=$(echo "$APP_RESULT" | jq -r '.appId')
    APP_OBJECT_ID=$(echo "$APP_RESULT" | jq -r '.id')
    
    echo "✅ Created app registration: $B2C_CLIENT_ID"
    
    # Add redirect URIs for Easy Auth
    echo "Adding redirect URIs..."
    az ad app update --id "$APP_OBJECT_ID" \
        --web-redirect-uris \
            "https://graphrag-api-b2c.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/.auth/login/aad/callback" \
            "https://localhost:50505/.auth/login/aad/callback"
    
    # Expose API
    echo "Exposing API scope..."
    az ad app update --id "$APP_OBJECT_ID" \
        --identifier-uris "api://$B2C_CLIENT_ID"
    
    # Create client secret (optional)
    echo ""
    read -p "Create a client secret? (recommended: y/n): " CREATE_SECRET
    
    if [ "$CREATE_SECRET" = "y" ]; then
        SECRET_RESULT=$(az ad app credential reset \
            --id "$APP_OBJECT_ID" \
            --append \
            --display-name "graphrag-b2c-secret" \
            --years 2 \
            --query password -o tsv)
        
        B2C_CLIENT_SECRET="$SECRET_RESULT"
        echo "✅ Client secret created (save this!): $B2C_CLIENT_SECRET"
    fi
    
    echo "✅ App registration complete"
fi

# Step 3: Configure azd environment
echo ""
echo "Step 3: Configure AZD Environment"
echo "----------------------------------"

# Switch back to default subscription
DEFAULT_SUB=$(az account list --query "[?isDefault].id" -o tsv)
if [ -n "$DEFAULT_SUB" ]; then
    az account set --subscription "$DEFAULT_SUB"
    echo "Switched back to default subscription"
fi

echo "Setting azd environment variables..."
azd env set AZURE_ENABLE_B2C true
azd env set AZURE_B2C_TENANT_NAME "$B2C_TENANT_NAME"
azd env set AZURE_B2C_TENANT_ID "$B2C_TENANT_ID"
azd env set AZURE_B2C_CLIENT_ID "$B2C_CLIENT_ID"

if [ -n "$B2C_CLIENT_SECRET" ]; then
    azd env set AZURE_B2C_CLIENT_SECRET "$B2C_CLIENT_SECRET"
fi

echo ""
echo "=========================================="
echo "✅ B2C Configuration Complete!"
echo "=========================================="
echo ""
echo "Configuration Summary:"
echo "  B2C Tenant: ${B2C_TENANT_NAME}.onmicrosoft.com"
echo "  Tenant ID: $B2C_TENANT_ID"
echo "  Client ID: $B2C_CLIENT_ID"
if [ -n "$B2C_CLIENT_SECRET" ]; then
    echo "  Client Secret: *** (configured)"
fi
echo ""
echo "Next steps:"
echo "  1. Review configuration: azd env get-values | grep B2C"
echo "  2. Deploy B2C variant: azd up"
echo ""
echo "After deployment, the B2C app will be available at:"
echo "  https://graphrag-api-b2c.<region>.azurecontainerapps.io"
echo ""
