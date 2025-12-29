# Azure AD Authentication Setup Guide

This guide explains how to configure Azure AD authentication for the Content Processing Solution with group-based isolation. Based on [Microsoft's Azure Search OpenAI Demo](https://github.com/Azure-Samples/azure-search-openai-demo/blob/main/docs/login_and_acl.md).

---

## Overview

The application uses Azure Active Directory (Azure AD / Entra ID) for authentication with the following features:

- **User Authentication**: Users sign in with their Azure AD credentials
- **Group-Based Isolation**: Each user's data is isolated by their Azure AD group membership
- **Group Name Display**: Shows friendly group names (e.g., "Sales Team") instead of GUIDs
- **Delegated Permissions**: Uses user's own permissions (no elevated app permissions needed)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Browser                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ MSAL.js Frontend (React)                                   │ │
│  │ • Authenticates with Azure AD                              │ │
│  │ • Receives token with groups claim                         │ │
│  │ • Sends Authorization: Bearer <token> to backend           │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓ HTTPS + JWT Token
┌─────────────────────────────────────────────────────────────────┐
│                      Backend API (FastAPI)                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Authentication Flow:                                       │ │
│  │ 1. Validates JWT token                                     │ │
│  │ 2. Extracts groups claim                                   │ │
│  │ 3. Calls Graph API with user's token (delegated)          │ │
│  │ 4. Returns friendly group names                            │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓ User's Token
┌─────────────────────────────────────────────────────────────────┐
│                  Microsoft Graph API                             │
│  • Returns group display names                                  │
│  • User can only see groups they belong to (secure!)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- **Azure AD Tenant**: You need an Azure Active Directory tenant
- **Admin Access**: Global Administrator or Application Administrator role
- **User Groups**: Users should be members of Azure AD groups

---

## Step 1: Verify App Registration

Your app is already registered in Azure AD. Let's verify and configure it properly.

### Find Your App Registration

1. Sign in to the [Azure Portal](https://portal.azure.com/)
2. Navigate to **Azure Active Directory** (or **Microsoft Entra ID**)
3. Select **App registrations** from the left menu
4. Find your app: **`ca-cps-gw6br2ms6mxy-web`**
   - Client ID: `b4aa58e1-8b31-445d-9fc9-1a1b6a044deb`

---

## Step 2: Configure API Permissions

### Add Required Permissions

1. In your app registration, click **API permissions** (left menu)

2. You should see existing permissions. Click **+ Add a permission**

3. Select **Microsoft Graph**

4. Select **Delegated permissions** (NOT Application permissions!)

5. Search for and expand **Group**

6. Check the box for:
   - ✅ **Group.Read.All** - Read all groups

7. Click **Add permissions**

### Why Delegated Permissions?

- **Delegated permissions** = User's own permissions
- User can only see groups **they belong to**
- ✅ **No admin consent required** (works by default)
- ✅ **More secure** - users can't see all directory groups
- ✅ **Compliant** - follows principle of least privilege

---

## Step 3: Grant Admin Consent

Even though delegated permissions don't strictly require admin consent, it's best practice to grant it upfront to avoid user-by-user consent prompts.

### Grant Consent

1. In **API permissions**, you should see:
   ```
   Permission Name          Type        Status
   ─────────────────────────────────────────────
   User.Read               Delegated    ✅ Granted
   Group.Read.All          Delegated    ⚠️  Not granted
   [Your API Scope]        Delegated    ✅ Granted
   ```

2. Click the button: **"✓ Grant admin consent for [Your Organization]"**

3. Confirm the consent dialog

4. Wait for status to update (refresh page if needed):
   ```
   Permission Name          Type        Status
   ─────────────────────────────────────────────
   User.Read               Delegated    ✅ Granted for [Org]
   Group.Read.All          Delegated    ✅ Granted for [Org]
   [Your API Scope]        Delegated    ✅ Granted for [Org]
   ```

---

## Step 4: Configure Group Claims (Optional but Recommended)

To include group memberships in the token automatically:

### Enable Groups Claim

1. In your app registration, click **Token configuration** (left menu)

2. Click **+ Add groups claim**

3. Select:
   - ✅ **Security groups**
   - Group ID format: **Group ID** (recommended)
   
4. Click **Add**

### Why This Helps

- Frontend can immediately know which groups user belongs to
- No extra Graph API call needed just to list groups
- Token includes `groups` claim with array of group IDs

---

## Step 5: Verify Redirect URIs

Make sure your app can redirect properly after login:

### Check Redirect URIs

1. In your app registration, click **Authentication** (left menu)

2. Under **Single-page application**, verify these URIs exist:
   ```
   ✅ https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io/redirect
   ✅ http://localhost:5173/redirect  (for local development)
   ✅ http://localhost:50505/redirect (for local development)
   ```

3. If missing, click **+ Add URI** and add them

---

## Step 6: Deploy Updated Application

Now that Azure AD is configured, deploy your updated code:

### Build Docker Images

```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/infra/scripts

# Build images with updated auth config
./docker-build.sh
```

### Deploy to Azure

```bash
# Deploy containers to Azure Container Apps
./deploy.sh
```

---

## Step 7: Test Authentication

### Clear Browser Cache

**Important**: Clear cached tokens before testing

**Chrome/Edge**:
1. Open DevTools (F12)
2. Go to **Application** tab
3. Click **Clear storage**
4. Check all boxes
5. Click **Clear site data**

**Or**: Use Incognito/Private window

### Test Login Flow

1. Navigate to your app: `https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io`

2. Click **Sign In**

3. Authenticate with your Azure AD credentials

4. **First login**: You'll see a consent prompt (if admin consent wasn't granted):
   ```
   Permissions requested:
   • View your basic profile
   • Read all groups you belong to
   • Access [App Name]
   
   [Accept] [Cancel]
   ```
   Click **Accept**

5. After login, verify:
   - ✅ You're logged in
   - ✅ Group selector shows **friendly names** (not GUIDs)
   - ✅ No console errors

### Expected Behavior

**Before (without Graph API)**:
```
Active Group: Group abc12345...
```

**After (with Graph API)**:
```
Active Group: Sales Team
```

---

## Troubleshooting

### Error: AADSTS65001 (Consent Required)

**Symptom**: 
```
AADSTS65001: The user or administrator has not consented to use the application
```

**Solution**:
1. Go back to Step 3 and grant admin consent
2. Or, have each user accept consent on first login

---

### Error: 401 Unauthorized on /api/groups/resolve-names

**Symptom**: Group names don't load, browser console shows 401 error

**Possible Causes**:

1. **Admin consent not granted**:
   - Solution: Complete Step 3 above

2. **Token doesn't include Group.Read.All scope**:
   - Solution: Clear browser cache and re-login
   - Check browser DevTools → Application → Local Storage → `token`
   - Decode JWT at https://jwt.ms/ and verify `scp` claim includes `Group.Read.All`

3. **User not a member of any groups**:
   - Solution: Add user to Azure AD groups in Azure Portal

---

### Group Names Show as "Group abc12345..."

**This is normal fallback behavior** if:
- Graph API call fails
- User's token doesn't have required permissions
- Network issues

**App still works** - just shows truncated GUIDs instead of friendly names.

---

## Security Considerations

### What Users Can See

✅ **Users CAN**:
- See their own groups
- See group names of groups they belong to
- Access documents in their groups only

❌ **Users CANNOT**:
- See other users' groups
- See all directory groups
- Access documents outside their groups
- Elevate permissions

### Data Isolation

The app uses **group_id** as partition key in Cosmos DB:
- Each group's data is physically separated
- Queries automatically filtered by user's groups
- No risk of cross-group data leakage

---

## For Developers: How It Works

### Frontend Token Request

```typescript
// msaConfig.ts
export const loginRequest = {
  scopes: [
    "user.read",                    // Basic profile
    "Group.Read.All",               // Read user's groups
    "<your-api-scope>"              // Access your API
  ],
};
```

### Backend Token Validation

```python
# groups.py
@router.post("/resolve-names")
def resolve_group_names(
    group_ids: List[str],
    authorization: Optional[str] = Header(None)
):
    # Extract user's token from Authorization header
    user_token = authorization[7:]  # Remove "Bearer " prefix
    
    # Call Graph API with user's delegated token
    headers = {"Authorization": f"Bearer {user_token}"}
    resp = requests.get(
        f"https://graph.microsoft.com/v1.0/groups/{gid}", 
        headers=headers
    )
    
    return group_display_names
```

### Token Flow

1. User logs in → Azure AD issues token
2. Token includes:
   - `sub`: User ID
   - `groups`: Array of group IDs user belongs to
   - `scp`: Scopes (including `Group.Read.All`)
3. Frontend sends token to backend
4. Backend uses token to call Graph API
5. Graph API returns group names (only for user's groups)

---

## References

- [Microsoft's RAG Chat Authentication Guide](https://github.com/Azure-Samples/azure-search-openai-demo/blob/main/docs/login_and_acl.md)
- [Azure AD Token Reference](https://learn.microsoft.com/entra/identity-platform/id-token-claims-reference)
- [Microsoft Graph API Groups](https://learn.microsoft.com/graph/api/group-get)
- [Delegated vs Application Permissions](https://learn.microsoft.com/graph/auth/auth-concepts#delegated-and-application-permissions)

---

## Summary Checklist

Before going to production, verify:

- [ ] App registration exists in Azure AD
- [ ] API Permissions include `Group.Read.All` (Delegated)
- [ ] Admin consent granted for all permissions
- [ ] Token configuration includes groups claim
- [ ] Redirect URIs configured for production URL
- [ ] Application deployed with updated code
- [ ] Login tested in clean browser session
- [ ] Group names display correctly (not GUIDs)
- [ ] No console errors related to authentication

---

## Support

If you encounter issues:

1. Check browser console for detailed error messages
2. Verify token contents at https://jwt.ms/
3. Review Azure AD sign-in logs: Azure Portal → Azure AD → Sign-in logs
4. Check API logs in Azure Container Apps

**Common issues are usually**:
- Missing admin consent (most common)
- Cached tokens (clear browser cache)
- Wrong redirect URI configuration
