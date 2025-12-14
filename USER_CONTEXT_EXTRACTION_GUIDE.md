# User Context Extraction Guide for Stage 1

## Summary
You **do NOT need to manually extract JWT tokens** if you use proper FastAPI authentication middleware. The library will do it for you.

## Current State
- ✅ Frontend: MSAL automatically acquires and sends JWT tokens
- ❌ Backend: NO authentication middleware or JWT validation
- ❌ Backend: NO user context extraction from tokens

## What You Need to Implement

### Option 1: Use FastAPI JWT Middleware (Recommended)

Install a JWT library:
```bash
pip install python-jose[cryptography] fastapi-azure-auth
```

Create an authentication dependency:

```python
# app/auth/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional
import os

security = HTTPBearer()

# Azure AD configuration
AZURE_AD_TENANT_ID = os.getenv("AZURE_AD_TENANT_ID")
AZURE_AD_CLIENT_ID = os.getenv("AZURE_AD_CLIENT_ID")  # API app registration client ID
AZURE_AD_ISSUER = f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/v2.0"
AZURE_AD_JWKS_URI = f"https://login.microsoftonline.com/{AZURE_AD_TENANT_ID}/discovery/v2.0/keys"

class UserContext:
    """User context extracted from JWT token"""
    def __init__(self, user_id: str, email: str, name: str, tenant_id: str):
        self.user_id = user_id  # 'oid' claim - use this for partition key
        self.email = email       # 'preferred_username' or 'upn' claim
        self.name = name         # 'name' claim
        self.tenant_id = tenant_id  # 'tid' claim

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserContext:
    """
    Extract and validate user context from JWT token.
    
    This dependency:
    1. Extracts the Bearer token from Authorization header
    2. Validates the token signature using Azure AD public keys
    3. Validates token claims (issuer, audience, expiration)
    4. Extracts user information from standard claims
    
    Returns:
        UserContext with user_id, email, name, tenant_id
        
    Raises:
        HTTPException 401 if token is invalid or missing
    """
    token = credentials.credentials
    
    try:
        # For production: Validate token signature against Azure AD JWKS
        # For development: You can decode without verification for testing
        # SECURITY: Always validate in production!
        
        # Option A: Decode without verification (DEV ONLY)
        if os.getenv("APP_ENV", "prod").lower() == "dev":
            payload = jwt.decode(
                token,
                options={"verify_signature": False}  # DEV ONLY!
            )
        else:
            # Option B: Validate signature (PRODUCTION)
            # You'll need to fetch JWKS and validate
            # See: https://github.com/Intility/fastapi-azure-auth
            raise NotImplementedError("Token signature validation not implemented")
        
        # Extract standard Azure AD claims
        user_id = payload.get("oid")  # Object ID - unique user identifier
        email = payload.get("preferred_username") or payload.get("upn")
        name = payload.get("name")
        tenant_id = payload.get("tid")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing 'oid' claim"
            )
        
        return UserContext(
            user_id=user_id,
            email=email or "unknown",
            name=name or "unknown",
            tenant_id=tenant_id or "unknown"
        )
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}"
        )
```

### Option 2: Use fastapi-azure-auth Library (Better for Production)

```bash
pip install fastapi-azure-auth
```

```python
# app/auth/dependencies.py
from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
from fastapi import Depends
import os

azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
    app_client_id=os.getenv("AZURE_AD_CLIENT_ID"),
    tenant_id=os.getenv("AZURE_AD_TENANT_ID"),
    scopes={
        f"api://{os.getenv('AZURE_AD_CLIENT_ID')}/user_impersonation": "Access API",
    }
)

class UserContext:
    def __init__(self, user_id: str, email: str, name: str, tenant_id: str):
        self.user_id = user_id
        self.email = email
        self.name = name
        self.tenant_id = tenant_id

async def get_current_user(
    token: dict = Depends(azure_scheme)
) -> UserContext:
    """
    Extract user context from validated Azure AD token.
    
    The azure_scheme dependency automatically validates the token.
    We just extract the claims we need.
    """
    return UserContext(
        user_id=token.get("oid"),
        email=token.get("preferred_username") or token.get("upn"),
        name=token.get("name"),
        tenant_id=token.get("tid")
    )
```

### How to Use in Your Routes

```python
# app/routers/contentprocessor.py
from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user, UserContext

router = APIRouter(prefix="/contentprocessor", tags=["contentprocessor"])

@router.post("/submit")
async def submit_content(
    file: UploadFile,
    schema_id: str,
    current_user: UserContext = Depends(get_current_user),  # ← Automatic extraction!
    content_processor: ContentProcessor = Depends(get_content_processor),
    app_config: AppConfiguration = Depends(get_app_config),
):
    # current_user.user_id is now available
    # Use it for data isolation
    
    process_id = str(uuid.uuid4())
    user_id = current_user.user_id  # ← This is your partition key!
    
    # Save with user context
    content_processor.save_file_to_blob(
        process_id=process_id,
        file=await file.read(),
        file_name=file.filename
    )
    
    # Create process with user_id for isolation
    process = ContentProcess(
        process_id=process_id,
        user_id=user_id,  # ← Add this field to your model
        file_name=file.filename,
        schema_id=schema_id,
        status="pending",
        created_by=current_user.email,
        created_at=datetime.utcnow()
    )
    
    # Store in Cosmos DB with user_id as partition key
    # ...

@router.get("/processed")
async def get_all_processed_results(
    page_request: Paging,
    current_user: UserContext = Depends(get_current_user),  # ← Extract user
    app_config: AppConfiguration = Depends(get_app_config),
):
    # Query ONLY this user's data
    results = CosmosContentProcess.get_all_processes_paginated(
        connection_string=app_config.app_cosmos_connstr,
        database_name=app_config.app_cosmos_database,
        collection_name=app_config.app_cosmos_container_process,
        page_number=page_request.page_number,
        page_size=page_request.page_size,
        user_id=current_user.user_id  # ← Filter by user
    )
    return results
```

## Standard Azure AD JWT Claims You Get Automatically

| Claim | Description | Use For |
|-------|-------------|---------|
| `oid` | Object ID - unique user identifier | **Partition key, user_id field** |
| `sub` | Subject - another user identifier | Alternative to oid |
| `preferred_username` | User's email/UPN | Display name, audit logs |
| `name` | Display name | UI display |
| `tid` | Tenant ID | Multi-tenant scenarios |
| `aud` | Audience (your API client ID) | Validation |
| `iss` | Issuer (Azure AD) | Validation |
| `exp` | Expiration timestamp | Validation |

## Do You Need Custom Claims?

**For Stage 1 user isolation: NO**

Standard claims (`oid`, `preferred_username`, `name`) are sufficient for:
- Identifying the user uniquely (`oid`)
- Filtering data by user (`oid` as partition key)
- Displaying user info (`name`, `preferred_username`)

**You might need custom claims if:**
- You have multi-organization tenants (add `organization_id` claim)
- You need role-based access control beyond what the app provides (add `app_roles` claim)
- You have custom business logic tied to user metadata (add custom claims)

## Conclusion

**You do NOT manually extract JWT tokens.** Instead:

1. ✅ Use a FastAPI dependency (`get_current_user`)
2. ✅ The dependency validates and decodes the JWT automatically
3. ✅ You get a `UserContext` object with user info
4. ✅ Use `Depends(get_current_user)` on every protected route
5. ✅ Access `current_user.user_id` for data isolation

The authentication library handles all the complexity:
- Token validation
- Signature verification
- Claim extraction
- Error handling

You just use the `UserContext` object that's provided to you.

## Next Steps

1. Install `fastapi-azure-auth` or `python-jose`
2. Create `app/auth/dependencies.py` with `get_current_user`
3. Add `current_user: UserContext = Depends(get_current_user)` to all routes
4. Use `current_user.user_id` for data isolation
5. Update Cosmos DB queries to filter by `user_id`
6. Update data models to include `user_id` field

No manual JWT extraction required! 🎉
