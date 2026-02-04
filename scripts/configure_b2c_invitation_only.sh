#!/bin/bash
set -e

echo "=========================================="
echo "Configure B2C for Invitation-Only Access"
echo "=========================================="
echo ""

# Get B2C configuration
B2C_TENANT_ID=$(azd env get-values | grep AZURE_B2C_TENANT_ID | cut -d'=' -f2 | tr -d '"')
B2C_TENANT_NAME=$(azd env get-values | grep AZURE_B2C_TENANT_NAME | cut -d'=' -f2 | tr -d '"')
B2C_CLIENT_ID=$(azd env get-values | grep AZURE_B2C_CLIENT_ID | cut -d'=' -f2 | tr -d '"')

echo "B2C Tenant: ${B2C_TENANT_NAME}.onmicrosoft.com"
echo "Tenant ID: $B2C_TENANT_ID"
echo ""

# Switch to B2C tenant
echo "Switching to B2C tenant..."
az login --tenant "$B2C_TENANT_ID" --allow-no-subscriptions --use-device-code

echo ""
echo "=========================================="
echo "Options for Invitation-Only Access:"
echo "=========================================="
echo ""
echo "1. Disable Self-Service Sign-Up (Recommended)"
echo "   - Users can only sign in after being invited"
echo "   - You manually create users via Azure Portal or CLI"
echo "   - Still uses B2C authentication flows"
echo ""
echo "2. Use B2B Invitations Instead"
echo "   - Switch to main tenant with B2B guest invitations"
echo "   - More control over user lifecycle"
echo "   - Uses standard Azure AD guest flows"
echo ""

read -p "Select option (1 or 2): " OPTION

if [ "$OPTION" = "1" ]; then
    echo ""
    echo "=========================================="
    echo "Option 1: Disable Self-Service Sign-Up"
    echo "=========================================="
    echo ""
    
    # Get tenant settings
    echo "Getting current tenant settings..."
    SETTINGS=$(az rest --method GET \
        --url "https://graph.microsoft.com/beta/policies/authorizationPolicy" \
        --headers "Content-Type=application/json")
    
    CURRENT_SIGNUP=$(echo "$SETTINGS" | jq -r '.allowedToSignUpEmailBasedSubscriptions')
    echo "Current self-service sign-up: $CURRENT_SIGNUP"
    
    if [ "$CURRENT_SIGNUP" = "true" ]; then
        echo ""
        echo "Disabling self-service sign-up..."
        
        az rest --method PATCH \
            --url "https://graph.microsoft.com/beta/policies/authorizationPolicy/authorizationPolicy" \
            --headers "Content-Type=application/json" \
            --body '{
                "allowedToSignUpEmailBasedSubscriptions": false
            }'
        
        echo "✅ Self-service sign-up disabled"
    else
        echo "✅ Self-service sign-up already disabled"
    fi
    
    echo ""
    echo "=========================================="
    echo "How to Invite Users (Option 1):"
    echo "=========================================="
    echo ""
    echo "Method 1: Azure Portal"
    echo "  1. Go to: https://portal.azure.com → ${B2C_TENANT_NAME}.onmicrosoft.com"
    echo "  2. Navigate to: Users → New user → Create new user"
    echo "  3. Set username and password, send credentials to user"
    echo ""
    echo "Method 2: Azure CLI"
    echo "  # Create user"
    echo "  az ad user create \\"
    echo "    --display-name \"User Name\" \\"
    echo "    --user-principal-name \"user@${B2C_TENANT_NAME}.onmicrosoft.com\" \\"
    echo "    --password \"TempPassword123!\" \\"
    echo "    --force-change-password-next-sign-in true"
    echo ""
    echo "Method 3: Graph API (Bulk Invitations)"
    echo "  See: scripts/invite_b2c_users.py"
    echo ""

elif [ "$OPTION" = "2" ]; then
    echo ""
    echo "=========================================="
    echo "Option 2: Switch to B2B Invitations"
    echo "=========================================="
    echo ""
    echo "To use B2B invitation flow instead of B2C:"
    echo ""
    echo "1. Disable B2C deployment:"
    echo "   azd env set AZURE_ENABLE_B2C false"
    echo ""
    echo "2. Use the main B2B endpoint instead:"
    echo "   https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
    echo ""
    echo "3. Invite external users with B2B:"
    echo "   az rest --method POST \\"
    echo "     --url 'https://graph.microsoft.com/v1.0/invitations' \\"
    echo "     --headers 'Content-Type=application/json' \\"
    echo "     --body '{"
    echo "       \"invitedUserEmailAddress\": \"user@example.com\","
    echo "       \"inviteRedirectUrl\": \"https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io\","
    echo "       \"sendInvitationMessage\": true"
    echo "     }'"
    echo ""
    echo "Note: B2B invitations provide better control and audit trails"
    echo ""
else
    echo "Invalid option"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ Configuration Complete!"
echo "=========================================="
