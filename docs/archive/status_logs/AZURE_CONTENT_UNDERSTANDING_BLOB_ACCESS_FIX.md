# Azure Content Understanding Blob Access Fix - SAS Token Implementation

## Issue Identified ✅
**"ContentSourceNotAccessible"** - Azure Content Understanding API cannot access blob storage URLs because they lack authentication.

## Root Cause Analysis ✅
You were absolutely correct to point to managed identity! The issue was:

1. **Our Backend → Azure Content Understanding API**: ✅ Working with managed identity authentication
2. **Azure Content Understanding API → Our Blob Storage**: ❌ Failed because blob URLs had no access tokens

## Solution Implemented: User Delegation SAS Tokens

### What We Fixed
- **Added `generate_blob_uris_with_sas()` function** that creates blob URLs with SAS tokens
- **Uses User Delegation Key** approach compatible with managed identity
- **Provides 1-hour read access** to Azure Content Understanding service
- **Includes fallback mechanism** to basic URLs if SAS generation fails

### Technical Implementation
```python
# Get user delegation key (works with managed identity)
user_delegation_key = blob_service_client.get_user_delegation_key(
    key_start_time=datetime.utcnow(),
    key_expiry_time=datetime.utcnow() + timedelta(hours=2)
)

# Generate user delegation SAS token with read permissions
sas_token = generate_blob_sas(
    account_name=blob_service_client.account_name,
    container_name=container_name,
    blob_name=blob_name,
    user_delegation_key=user_delegation_key,
    permission=BlobSasPermissions(read=True),
    expiry=datetime.utcnow() + timedelta(hours=1)
)

# Create accessible URL: https://storage.blob.core.windows.net/container/blob?sas_token
blob_uri_with_sas = f"{account_url}/{container_name}/{blob_name}?{sas_token}"
```

### Updated Function Calls
- `generate_blob_uris()` → `generate_blob_uris_with_sas()` for both input and reference files
- Added comprehensive error handling and fallback mechanisms
- Enhanced logging to track SAS token generation process

## Expected Outcome
The Azure Content Understanding API should now be able to access the blob storage URLs with the SAS tokens, resolving the "ContentSourceNotAccessible" error.

## Security Benefits
- ✅ **Time-limited access**: SAS tokens expire after 1 hour
- ✅ **Read-only permissions**: Only allows reading blob content
- ✅ **Managed identity compatible**: Uses user delegation keys instead of account keys
- ✅ **Specific blob access**: Each token grants access only to the specific blob needed

## Testing Ready
The fix is ready for deployment and testing. The analyze endpoint should now work with proper blob access for Azure Content Understanding API.

---
*Your insight about managed identity was exactly right - we just needed to extend that authentication to blob storage access!*
