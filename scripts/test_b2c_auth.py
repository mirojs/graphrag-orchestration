#!/usr/bin/env python3
"""
Test script for External ID (B2C) authentication.

This script demonstrates how to authenticate with the GraphRAG API B2C endpoint
using Microsoft External ID (formerly Azure AD B2C / CIAM).

Usage:
    # Interactive login (opens browser)
    python scripts/test_b2c_auth.py

    # With username/password (for test accounts only)
    python scripts/test_b2c_auth.py --username user@example.com --password secret

Requirements:
    pip install msal requests
"""

import argparse
import json
import sys
import requests
from msal import PublicClientApplication

# External ID Configuration
B2C_TENANT_NAME = "graphragb2c"
B2C_TENANT_ID = "aa5210de-5c3a-4383-adbb-13c7998b1be0"
B2C_CLIENT_ID = "0a8e8140-2f22-4110-bc57-c2316add0b13"

# Authority URL for External ID (ciamlogin.com)
AUTHORITY = f"https://{B2C_TENANT_NAME}.ciamlogin.com/{B2C_TENANT_ID}"

# API Configuration
API_BASE_URL = "https://graphrag-api-b2c.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Scopes - for External ID, use the client ID as the scope
SCOPES = [f"{B2C_CLIENT_ID}/.default"]


def get_token_interactive():
    """Get access token using interactive browser login."""
    app = PublicClientApplication(
        client_id=B2C_CLIENT_ID,
        authority=AUTHORITY,
    )
    
    # Try to get token from cache first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("✓ Got token from cache")
            return result["access_token"]
    
    # Interactive login
    print(f"Opening browser for login at {AUTHORITY}...")
    print("If browser doesn't open, manually visit the URL shown.")
    
    result = app.acquire_token_interactive(
        scopes=SCOPES,
        prompt="select_account",
    )
    
    if "access_token" in result:
        print("✓ Authentication successful!")
        return result["access_token"]
    else:
        print(f"✗ Authentication failed: {result.get('error_description', result)}")
        return None


def get_token_username_password(username: str, password: str):
    """Get access token using username/password (ROPC flow - for testing only)."""
    app = PublicClientApplication(
        client_id=B2C_CLIENT_ID,
        authority=AUTHORITY,
    )
    
    result = app.acquire_token_by_username_password(
        username=username,
        password=password,
        scopes=SCOPES,
    )
    
    if "access_token" in result:
        print("✓ Authentication successful!")
        return result["access_token"]
    else:
        print(f"✗ Authentication failed: {result.get('error_description', result)}")
        return None


def test_api(token: str):
    """Test API endpoints with the token."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    print("\n" + "="*60)
    print("Testing API Endpoints")
    print("="*60)
    
    # Test health endpoint
    print("\n1. Testing /health endpoint...")
    try:
        resp = requests.get(f"{API_BASE_URL}/health", headers=headers, timeout=30)
        print(f"   Status: {resp.status_code}")
        if resp.ok:
            print(f"   Response: {resp.json()}")
        else:
            print(f"   Error: {resp.text[:200]}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test config endpoint
    print("\n2. Testing /config endpoint...")
    try:
        resp = requests.get(f"{API_BASE_URL}/config", headers=headers, timeout=30)
        print(f"   Status: {resp.status_code}")
        if resp.ok:
            config = resp.json()
            print(f"   Auth Type: {config.get('authType')}")
            print(f"   Require Auth: {config.get('requireAuth')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test hybrid query endpoint
    print("\n3. Testing /hybrid/query endpoint...")
    try:
        payload = {
            "query": "What documents are available?",
            "response_type": "concise",
        }
        resp = requests.post(
            f"{API_BASE_URL}/hybrid/query",
            headers=headers,
            json=payload,
            timeout=60,
        )
        print(f"   Status: {resp.status_code}")
        if resp.ok:
            result = resp.json()
            print(f"   Route Used: {result.get('route_used')}")
            print(f"   Response Preview: {result.get('response', '')[:100]}...")
        else:
            print(f"   Error: {resp.text[:200]}")
    except Exception as e:
        print(f"   Error: {e}")


def decode_token(token: str):
    """Decode and display token claims (without verification)."""
    import base64
    
    # Split the token
    parts = token.split(".")
    if len(parts) != 3:
        print("Invalid token format")
        return
    
    # Decode the payload (middle part)
    payload = parts[1]
    # Add padding if needed
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    
    try:
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        
        print("\n" + "="*60)
        print("Token Claims")
        print("="*60)
        print(f"  Subject (sub): {claims.get('sub')}")
        print(f"  Object ID (oid): {claims.get('oid')}")
        print(f"  Email: {claims.get('email') or claims.get('preferred_username')}")
        print(f"  Name: {claims.get('name')}")
        print(f"  Issuer (iss): {claims.get('iss')}")
        print(f"  Audience (aud): {claims.get('aud')}")
        print(f"  Tenant ID (tid): {claims.get('tid')}")
        
        # The oid will be used as group_id for B2C
        print(f"\n  → This user's partition key (oid): {claims.get('oid')}")
        
    except Exception as e:
        print(f"Failed to decode token: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test External ID (B2C) authentication")
    parser.add_argument("--username", help="Username for ROPC flow (testing only)")
    parser.add_argument("--password", help="Password for ROPC flow (testing only)")
    parser.add_argument("--decode-only", action="store_true", help="Only decode a provided token")
    parser.add_argument("--token", help="Token to decode (with --decode-only)")
    args = parser.parse_args()
    
    print("="*60)
    print("GraphRAG External ID (B2C) Authentication Test")
    print("="*60)
    print(f"Tenant: {B2C_TENANT_NAME} ({B2C_TENANT_ID})")
    print(f"Client ID: {B2C_CLIENT_ID}")
    print(f"Authority: {AUTHORITY}")
    print(f"API: {API_BASE_URL}")
    
    if args.decode_only and args.token:
        decode_token(args.token)
        return
    
    # Get token
    if args.username and args.password:
        token = get_token_username_password(args.username, args.password)
    else:
        token = get_token_interactive()
    
    if not token:
        print("\nFailed to obtain access token. Exiting.")
        sys.exit(1)
    
    # Decode and show token claims
    decode_token(token)
    
    # Test API
    test_api(token)
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)


if __name__ == "__main__":
    main()
