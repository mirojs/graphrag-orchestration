#!/usr/bin/env python3
"""
Bulk invite users to Azure AD B2C tenant
Pre-create users with temporary passwords and force password change on first login
"""

import os
import sys
from msal import PublicClientApplication
import requests
import json

# B2C Tenant Configuration
TENANT_ID = "aa5210de-5c3a-4383-adbb-13c7998b1be0"  # graphragb2c tenant
TENANT_NAME = "graphragb2c"

# Microsoft Graph PowerShell app (public client)
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

# Required Graph API scope for user management
SCOPES = ["https://graph.microsoft.com/User.ReadWrite.All"]

def authenticate():
    """Authenticate using device code flow"""
    app = PublicClientApplication(
        client_id=CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    
    # Try to get token silently first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            return result["access_token"]
    
    # Fall back to device code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    
    if "user_code" not in flow:
        raise Exception("Failed to create device flow")
    
    print("\nAUTHENTICATION REQUIRED")
    print(flow["message"])
    
    result = app.acquire_token_by_device_flow(flow)
    
    if "access_token" in result:
        print("✅ Authentication successful!\n")
        return result["access_token"]
    else:
        raise Exception(f"Authentication failed: {result.get('error_description', 'Unknown error')}")

def create_user(token, email, display_name, temp_password="TempPass123!"):
    """Create a new user in B2C tenant"""
    
    # For B2C, user principal name uses the tenant domain
    user_principal_name = f"{email.split('@')[0]}@{TENANT_NAME}.onmicrosoft.com"
    
    user_data = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": email.split('@')[0],
        "userPrincipalName": user_principal_name,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": temp_password
        },
        "identities": [
            {
                "signInType": "emailAddress",
                "issuer": f"{TENANT_NAME}.onmicrosoft.com",
                "issuerAssignedId": email
            }
        ]
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        "https://graph.microsoft.com/v1.0/users",
        headers=headers,
        json=user_data
    )
    
    if response.status_code == 201:
        user = response.json()
        return user["id"]
    else:
        raise Exception(f"Failed to create user: {response.status_code} - {response.text}")

def main():
    print("========================================")
    print("B2C User Invitation Tool")
    print("========================================\n")
    
    # Authenticate
    token = authenticate()
    
    # Example: Read users from CSV or input
    print("Enter user details (or 'done' to finish):\n")
    
    users_created = []
    
    while True:
        email = input("Email address (or 'done'): ").strip()
        if email.lower() == 'done':
            break
        
        display_name = input("Display name: ").strip()
        temp_password = input("Temporary password (or press Enter for default): ").strip()
        
        if not temp_password:
            temp_password = "TempPass123!"
        
        try:
            print(f"\nCreating user {email}...")
            user_id = create_user(token, email, display_name, temp_password)
            
            users_created.append({
                "email": email,
                "display_name": display_name,
                "user_id": user_id,
                "temp_password": temp_password
            })
            
            print(f"✅ User created: {display_name} ({email})")
            print(f"   User ID: {user_id}")
            print(f"   Temp Password: {temp_password}")
            print(f"   User must change password on first login\n")
            
        except Exception as e:
            print(f"❌ Error creating user: {e}\n")
    
    # Summary
    if users_created:
        print("\n========================================")
        print("Summary of Created Users")
        print("========================================\n")
        
        for user in users_created:
            print(f"Email: {user['email']}")
            print(f"Name: {user['display_name']}")
            print(f"Temp Password: {user['temp_password']}")
            print(f"Login URL: https://graphrag-api-b2c.salmonhill-df6033f3.swedencentral.azurecontainerapps.io")
            print()
        
        print("⚠️  Send these credentials securely to users")
        print("⚠️  Users will be forced to change password on first login")
    
    print("\n✅ Done!")

if __name__ == "__main__":
    main()
