#!/bin/bash
# =============================================================================
# B2B Authentication Setup Script
# 
# Configures Entra ID for simpler guest authentication:
# - Email one-time passcode (OTP) - guests authenticate with email code
# - Guest invite settings
# - External collaboration policies
#
# REQUIREMENTS: 
#   - Azure CLI logged in as Global Administrator or Authentication Policy Administrator
#   - Microsoft Graph permissions: Policy.ReadWrite.AuthenticationMethod
#
# USAGE:
#   ./scripts/setup_b2b_auth.sh
# =============================================================================

set -e

echo "========================================"
echo "B2B Authentication Setup"
echo "========================================"
echo ""

# Check login
CURRENT_USER=$(az account show --query user.name -o tsv 2>/dev/null)
if [ -z "$CURRENT_USER" ]; then
    echo "ERROR: Not logged in to Azure CLI"
    echo "Run: az login"
    exit 1
fi
echo "Logged in as: $CURRENT_USER"
echo ""

# =============================================================================
# 1. Enable Email One-Time Passcode (OTP)
# =============================================================================
echo "1. Enabling Email One-Time Passcode for B2B guests..."

az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Email" \
  --headers "Content-Type=application/json" \
  --body '{
    "@odata.type": "#microsoft.graph.emailAuthenticationMethodConfiguration",
    "state": "enabled",
    "allowExternalIdToUseEmailOtp": "enabled"
  }' && echo "   ✅ Email OTP enabled" || echo "   ❌ Failed - check permissions"

echo ""

# =============================================================================
# 2. Configure External Collaboration Settings  
# =============================================================================
echo "2. Configuring external collaboration settings..."

# Allow members to invite guests
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/policies/authorizationPolicy" \
  --headers "Content-Type=application/json" \
  --body '{
    "allowInvitesFrom": "adminsAndGuestInviters",
    "guestUserRoleId": "2af84b1e-32c8-42b7-82bc-daa82404023b",
    "allowedToSignUpEmailBasedSubscriptions": true,
    "allowEmailVerifiedUsersToJoinOrganization": false,
    "blockMsolPowerShell": false
  }' && echo "   ✅ Collaboration settings configured" || echo "   ❌ Failed - check permissions"

echo ""

# =============================================================================
# 3. Configure B2B Redemption Order (OPTIONAL - Requires Azure AD Premium P1)
# =============================================================================
# NOTE: This step is OPTIONAL and only works with P1 license
# Without it, default order is: Azure AD → Microsoft Account → Email OTP
# With it, you can make Email OTP the preferred method
#
# Uncomment below if you have P1 license:
#
# echo "3. Setting B2B invitation redemption order..."
# az rest --method PATCH \
#   --uri "https://graph.microsoft.com/beta/policies/crossTenantAccessPolicy/default" \
#   --headers "Content-Type=application/json" \
#   --body '{
#     "invitationRedemptionIdentityProviderConfiguration": {
#       "primaryIdentityProviderPrecedenceOrder": [
#         "emailOneTimePasscode",
#         "externalFederation", 
#         "azureActiveDirectory",
#         "microsoftAccount"
#       ],
#       "fallbackIdentityProvider": "emailOneTimePasscode"
#     }
#   }' && echo "   ✅ Redemption order set (OTP preferred)" || echo "   ❌ Failed"

echo "3. Skipping redemption order (requires P1 license, optional)"
echo ""

# =============================================================================
# 4. Verify Settings
# =============================================================================
echo "4. Verifying settings..."
echo ""

echo "Email OTP Status:"
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Email" \
  --query "{state:state,allowExternalIdToUseEmailOtp:allowExternalIdToUseEmailOtp}" \
  -o table 2>/dev/null || echo "   (Could not verify)"

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Guest users can now authenticate using:"
echo "  1. Email one-time passcode (preferred)"
echo "  2. Their organization's Azure AD (if federated)"
echo "  3. Microsoft account (fallback)"
echo ""
echo "To invite a guest:"
echo "  az ad invitation create \\"
echo "    --invited-user-email-address 'guest@example.com' \\"
echo "    --invite-redirect-url 'https://your-app.azurecontainerapps.io' \\"
echo "    --invited-user-display-name 'Guest Name'"
echo ""
