#!/usr/bin/env python3
"""
Enable Email One-Time Passcode for B2B Guest Authentication

This script uses MSAL interactive authentication to get proper consent
for Graph API permissions that Azure CLI cannot request.

Usage:
    python scripts/enable_email_otp.py
"""

import json
import sys

try:
    import msal
    import requests
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "msal", "requests", "-q"])
    import msal
    import requests


# Microsoft Graph API settings
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/Policy.ReadWrite.AuthenticationMethod"]

# Use Microsoft's well-known public client app ID for device code flow
# This is a common approach for admin scripts
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"  # Microsoft Graph PowerShell

# Your tenant ID - use specific tenant to avoid account confusion
TENANT_ID = "ecaa729a-f04c-4558-a31a-ab714740ee8b"  # Default Directory


def get_access_token():
    """Get access token using interactive browser authentication."""
    
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    
    # Try to get token from cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]
    
    # Interactive authentication
    print("\n" + "="*60)
    print("AUTHENTICATION REQUIRED")
    print("="*60)
    print("\nA browser window will open for you to sign in.")
    print("Sign in with your Global Administrator account.")
    print("\nIf no browser opens, use this URL manually:")
    
    # Try device code flow (works in remote/SSH scenarios)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" in flow:
        print(f"\n{flow['message']}\n")
        result = app.acquire_token_by_device_flow(flow)
    else:
        # Fallback to interactive
        result = app.acquire_token_interactive(scopes=SCOPES)
    
    if "access_token" in result:
        print("✅ Authentication successful!\n")
        return result["access_token"]
    else:
        print(f"❌ Authentication failed: {result.get('error_description', 'Unknown error')}")
        sys.exit(1)


def enable_email_otp(token: str):
    """Enable Email OTP for B2B guests."""
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # First, check current status
    print("Checking current Email OTP status...")
    url = f"{GRAPH_ENDPOINT}/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Email"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        current = response.json()
        print(f"  Current state: {current.get('state', 'unknown')}")
        print(f"  Allow external ID: {current.get('allowExternalIdToUseEmailOtp', 'unknown')}")
    else:
        print(f"  Could not check status: {response.status_code}")
    
    # Enable Email OTP
    print("\nEnabling Email OTP for B2B guests...")
    
    payload = {
        "@odata.type": "#microsoft.graph.emailAuthenticationMethodConfiguration",
        "state": "enabled",
        "allowExternalIdToUseEmailOtp": "enabled"
    }
    
    response = requests.patch(url, headers=headers, json=payload)
    
    if response.status_code in [200, 204]:
        print("✅ Email OTP enabled successfully!")
        return True
    else:
        print(f"❌ Failed to enable Email OTP: {response.status_code}")
        try:
            error = response.json()
            print(f"   Error: {error.get('error', {}).get('message', 'Unknown')}")
        except:
            print(f"   Response: {response.text}")
        return False


def verify_settings(token: str):
    """Verify the settings were applied."""
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("\nVerifying settings...")
    url = f"{GRAPH_ENDPOINT}/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Email"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        current = response.json()
        print(f"  State: {current.get('state', 'unknown')}")
        print(f"  Allow External ID OTP: {current.get('allowExternalIdToUseEmailOtp', 'unknown')}")
        
        if current.get('state') == 'enabled' and current.get('allowExternalIdToUseEmailOtp') == 'enabled':
            print("\n✅ Email OTP is now enabled for B2B guests!")
            print("\nGuests can now authenticate using:")
            print("  1. A one-time code sent to their email")
            print("  2. No Microsoft account required")
        else:
            print("\n⚠️ Settings may not be fully applied. Check Azure Portal.")
    else:
        print(f"  Could not verify: {response.status_code}")


def main():
    print("="*60)
    print("Enable Email One-Time Passcode for B2B Guests")
    print("="*60)
    
    # Get access token
    token = get_access_token()
    
    # Enable Email OTP
    success = enable_email_otp(token)
    
    if success:
        verify_settings(token)
    
    print("\n" + "="*60)
    print("Done!")
    print("="*60)


if __name__ == "__main__":
    main()
