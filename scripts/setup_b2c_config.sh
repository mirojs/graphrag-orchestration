#!/bin/bash
set -e

echo "=========================================="
echo "Azure AD B2C / External ID Configuration"
echo "=========================================="
echo ""

# Step 1: Get B2C Tenant Information
echo "Step 1: B2C Tenant Information"
echo "------------------------------"
echo "Available Azure AD tenants:"
echo ""

# Try to get tenant details from current token
for tenant_id in $(az account tenant list --query "[].tenantId" -o tsv); do
    tenant_info=$(az rest --method GET \
        --url "https://graph.microsoft.com/v1.0/tenantRelationships/findTenantInformationByTenantId(tenantId='$tenant_id')" \
        2>/dev/null || echo "")
    
    if [ -n "$tenant_info" ]; then
        name=$(echo "$tenant_info" | jq -r '.displayName // "N/A"')
        domain=$(echo "$tenant_info" | jq -r '.defaultDomainName // "N/A"')
        echo "  Name: $name"
        echo "  Domain: $domain"
        echo "  TenantId: $tenant_id"
        echo ""
    else
        echo "  TenantId: $tenant_id"
        echo ""
    fi
done

echo ""
read -p "Enter your B2C tenant ID (GUID): " B2C_TENANT_ID
read -p "Enter your B2C tenant name (e.g., graphragb2c - without .onmicrosoft.com): " B2C_TENANT_NAME

# Step 2: Check if app registration exists
echo ""
echo "Step 2: App Registration"
echo "------------------------"
echo "Checking for existing app registrations in B2C tenant..."

# Switch to B2C tenant
az login --tenant "$B2C_TENANT_ID" --allow-no-subscriptions --use-device-code

echo ""
echo "Existing app registrations:"
az ad app list --query "[].{Name:displayName, AppId:appId, Id:id}" --output table

echo ""
read -p "Do you have an existing app registration for GraphRAG? (y/n): " HAS_APP

if [ "$HAS_APP" = "y" ]; then
    read -p "Enter the existing Application (client) ID: " B2C_CLIENT_ID
else
    echo ""
    echo "Creating new app registration..."
    
    # Get the callback URL (will be set after deployment)
    read -p "Enter your Azure region (e.g., swedencentral): " AZURE_REGION
    CALLBACK_URL="https://graphrag-api-b2c.${AZURE_REGION}.azurecontainerapps.io/.auth/login/aad/callback"
    
    APP_RESULT=$(az ad app create \
        --display-name "GraphRAG Frontend B2C" \
        --sign-in-audience "AzureADandPersonalMicrosoftAccount" \
        --web-redirect-uris "$CALLBACK_URL" \
        --required-resource-accesses '[{
            "resourceAppId": "00000003-0000-0000-c000-000000000000",
            "resourceAccess": [
                {"id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d", "type": "Scope"},
                {"id": "37f7f235-527c-4136-accd-4a02d197296e", "type": "Scope"},
                {"id": "14dad69e-099b-42c9-810b-d002981feec1", "type": "Scope"}
            ]
        }]' \
        --query "{appId: appId, id: id}" -o json)
    
    B2C_CLIENT_ID=$(echo $APP_RESULT | jq -r '.appId')
    APP_OBJECT_ID=$(echo $APP_RESULT | jq -r '.id')
    
    echo "✅ Created app registration: $B2C_CLIENT_ID"
    
    # Create client secret
    echo ""
    read -p "Create a client secret? (y/n): " CREATE_SECRET
    
    if [ "$CREATE_SECRET" = "y" ]; then
        SECRET_RESULT=$(az ad app credential reset \
            --id "$APP_OBJECT_ID" \
            --append \
            --display-name "graphrag-b2c-secret" \
            --query password -o tsv)
        
        B2C_CLIENT_SECRET="$SECRET_RESULT"
        echo "✅ Client secret created (save this - it won't be shown again)"
    fi
    
    # Expose API
    echo ""
    echo "Exposing API scope..."
    az ad app update --id "$APP_OBJECT_ID" \
        --identifier-uris "api://$B2C_CLIENT_ID"
    
    echo "✅ App registration complete"
fi

# Step 3: Configure azd environment
echo ""
echo "Step 3: Configure AZD Environment"
echo "----------------------------------"

# Switch back to default subscription
az account set --subscription "$(az account list --query "[?isDefault].id" -o tsv)"

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
echo "  B2C Tenant: ${B2C_TENANT_NAME}.ciamlogin.com"
echo "  Tenant ID: $B2C_TENANT_ID"
echo "  Client ID: $B2C_CLIENT_ID"
if [ -n "$B2C_CLIENT_SECRET" ]; then
    echo "  Client Secret: *** (configured)"
fi
echo ""
echo "Next steps:"
echo "  1. Review azd environment: azd env get-values | grep B2C"
echo "  2. Deploy B2C variant: azd up"
echo "  3. After deployment, update redirect URI if needed:"
echo "     - Portal: App registrations → GraphRAG Frontend B2C → Authentication"
echo "     - Add: https://<actual-url>/.auth/login/aad/callback"
echo ""
echo "User Flows (optional but recommended):"
echo "  - Sign up and sign in flow: B2C_1_signupsignin"
echo "  - Configure in: https://portal.azure.com → ${B2C_TENANT_NAME}.onmicrosoft.com → User flows"
echo ""
