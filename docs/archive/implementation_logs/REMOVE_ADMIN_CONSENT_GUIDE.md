# Removing Admin Consent Requirement - Implementation Guide

## Problem Statement

Current app requires **admin consent** for `Group.Read.All` permission, which:
- ❌ Blocks regular users from signing in until Global Administrator approves
- ❌ Delays deployment (requires IT admin involvement)
- ❌ Creates friction in user onboarding

## Understanding Admin Consent

### Who is the "Admin"?

**Azure AD Global Administrator** or **Privileged Role Administrator** - NOT your app's admin users.

```
Your Organization's Azure AD Tenant
├── Global Administrator (IT Director, Cloud Admin)
│   └── Can grant consent for ALL users in organization
│
├── Regular Users (Sales, Marketing, etc.)
│   └── ❌ Cannot grant admin consent
│   └── ❌ Blocked from using app until admin approves
│
└── Your App's Admin Role
    └── ❌ NOT the same as Azure AD Global Admin
    └── Application-level role with no Azure AD privileges
```

### What Requires Admin Consent?

Privileged Microsoft Graph API permissions:

| Permission | Requires Admin Consent? | What It Does |
|------------|------------------------|--------------|
| `user.read` | ❌ No | Read current user's profile |
| `openid`, `profile`, `email` | ❌ No | Basic identity info |
| **`Group.Read.All`** | ✅ **YES** | Read all groups in organization |
| `User.Read.All` | ✅ YES | Read all users in organization |
| `Directory.Read.All` | ✅ YES | Read entire directory |

### Current Configuration

**Frontend** (`src/ContentProcessorWeb/src/msal-auth/msaConfig.ts`):
```typescript
export const loginRequest = {
  scopes: ["user.read", "Group.Read.All"],  // ❌ Requires admin consent
};
```

**Environment Variables**:
```bash
REACT_APP_WEB_SCOPE="Group.Read.All"
REACT_APP_API_SCOPE="api://{client-id}/access_as_user"
```

**Azure Portal - API Permissions**:
- Microsoft Graph → `Group.Read.All` (Delegated) → ❌ Admin consent required

---

## Solution: Remove Admin Consent Requirement

### **Recommended Approach: Use Optional Claims**

Add group membership directly to JWT token without requiring privileged API permission.

#### ✅ Benefits
- No admin consent required
- No code changes needed
- Groups still available in token
- Faster sign-in (no Graph API call)
- Works for both B2B and B2C

#### Implementation Steps

### Step 1: Configure Token Claims in Azure Portal

**Portal Navigation:**
```
Azure Portal → Azure Active Directory → App registrations 
→ [Your App] → Token configuration → Add groups claim
```

**Detailed Instructions:**

1. **Navigate to App Registration**
   - Go to https://portal.azure.com
   - Select **Azure Active Directory** from left menu
   - Click **App registrations**
   - Find and select your app (Client ID: from `REACT_APP_WEB_CLIENT_ID`)

2. **Add Groups Claim**
   - Click **Token configuration** in left sidebar
   - Click **+ Add groups claim**
   - Select claim type:
     - ✅ **Security groups** (recommended - only shows groups user is member of)
     - ⚠️ All groups (includes distribution lists, might exceed token size limit)
     - ⚠️ Directory roles (only for admin role assignments)
   
3. **Configure Token Types**
   - Check **ID** token
   - Check **Access** token
   - Leave customization as default (groups will be array of group IDs)

4. **Save Configuration**
   - Click **Add** button
   - Verify "groups" appears in Token configuration list

**Screenshot Reference:**
```
Token configuration
├── groups (Security groups)
│   ├── Token type: ID, Access
│   ├── Claim value type: Group ID
│   └── Emit as: groups
└── [Your other claims]
```

### Step 2: Remove Group.Read.All Permission

**Portal Navigation:**
```
Azure Portal → Azure Active Directory → App registrations 
→ [Your App] → API permissions
```

**Instructions:**

1. Find **Microsoft Graph** permissions
2. Locate `Group.Read.All` permission
3. Click **...** (three dots) → **Remove permission**
4. Confirm removal
5. **Do NOT click "Grant admin consent"** - not needed anymore!

**Remaining permissions should be:**
- ✅ `User.Read` (Microsoft Graph, Delegated) - no admin consent needed
- ✅ `access_as_user` (your API, Delegated) - no admin consent needed

### Step 3: Update Frontend Environment Variables

**Update `.env` or Azure Container App environment:**

```bash
# Before:
REACT_APP_WEB_SCOPE="Group.Read.All"

# After:
REACT_APP_WEB_SCOPE="openid profile email"
```

**Using Azure CLI:**
```bash
# Update Container App environment variable
az containerapp update \
  --name ${APP_NAME}-web \
  --resource-group ${RESOURCE_GROUP} \
  --set-env-vars "REACT_APP_WEB_SCOPE=openid profile email"

# Or with azd:
azd env set REACT_APP_WEB_SCOPE "openid profile email"
azd deploy
```

**For local development** (`.env.local`):
```env
REACT_APP_WEB_SCOPE=openid profile email
REACT_APP_API_SCOPE=api://{your-api-client-id}/access_as_user
```

### Step 4: Update MSAL Config (Optional - for clarity)

**File:** `src/ContentProcessorWeb/src/msal-auth/msaConfig.ts`

```typescript
// Optional: Make scopes explicit instead of using environment variable
export const loginRequest = {
  scopes: [
    "openid",      // ✅ Standard OIDC scope
    "profile",     // ✅ User profile info
    "email",       // ✅ User email
    tokenScope     // ✅ Your API scope (no admin consent)
  ],
  // Removed: "Group.Read.All" - now using optional claims
};
```

**Or keep current code** - it will automatically use updated `REACT_APP_WEB_SCOPE` from environment.

### Step 5: Verify Backend Already Handles Groups

**File:** `src/ContentProcessorAPI/app/dependencies/auth.py`

**Current code (no changes needed):**
```python
def get_current_user(authorization: Optional[str] = Header(None)):
    payload = jwt.decode(token, options={"verify_signature": False})
    
    # ✅ Already reads groups from token claims
    groups = payload.get("groups", [])  
    
    # Groups will now come from optional claims instead of Graph API
    return UserContext(
        user_id=payload.get("oid"),
        groups=groups  # ✅ Works automatically!
    )
```

**No backend code changes required!**

---

## Testing the Changes

### Test 1: Verify Token Contains Groups

**Before deploying to users, test locally:**

1. **Sign in to your app** with updated configuration
2. **Open browser DevTools** → Application → Local Storage
3. **Find MSAL tokens** (key starts with `msal.`)
4. **Decode access token** at https://jwt.ms
5. **Verify claims:**

```json
{
  "oid": "12345678-1234-1234-1234-123456789abc",
  "email": "user@example.com",
  "groups": [                    // ✅ Groups array present!
    "group-id-1",
    "group-id-2"
  ],
  "iss": "https://login.microsoftonline.com/{tenant}/v2.0",
  // ... other claims
}
```

### Test 2: Verify No Consent Prompt

1. **Use incognito/private browser** (fresh session)
2. **Sign in as a regular user** (not Global Admin)
3. **Should NOT see** any consent dialogs
4. **Should redirect directly** to app after Microsoft login

### Test 3: Verify Group-Based Features Work

1. **Sign in as user with group membership**
2. **Check group selector** in app UI
3. **Verify API calls** use correct `X-Group-ID` header
4. **Test data isolation** (only see data for user's groups)

### Test 4: New User Sign-Up Flow

1. **Create test user** in Azure AD
2. **Add to security group**
3. **Sign in to app** (first time)
4. **Verify:**
   - ✅ No admin consent prompt
   - ✅ Groups immediately available
   - ✅ Can access group's data

---

## Comparison: Before vs After

### Before (Current - Requires Admin Consent)

```
User Sign-In Flow:
1. User clicks "Sign In"
2. Redirected to Microsoft login
3. ❌ BLOCKED: "Need admin approval"
4. User contacts IT helpdesk
5. IT admin goes to Azure Portal
6. Admin clicks "Grant admin consent for Organization"
7. User tries again → ✅ Now works
8. Graph API call to get user's groups

Timeline: Hours to days (waiting for admin)
Friction: High
User experience: Poor
```

### After (With Optional Claims)

```
User Sign-In Flow:
1. User clicks "Sign In"
2. Redirected to Microsoft login
3. ✅ Signs in immediately (no consent prompt)
4. Token includes groups automatically
5. App works instantly

Timeline: Seconds
Friction: None
User experience: Excellent
```

### Technical Comparison

| Aspect | Before (Group.Read.All) | After (Optional Claims) |
|--------|------------------------|------------------------|
| **Admin consent** | ✅ Required | ❌ Not required |
| **User consent** | ✅ Required | ❌ Not required |
| **Sign-in speed** | Slower (Graph API call) | Faster (no API call) |
| **Groups available** | ✅ Yes | ✅ Yes |
| **Token size** | Smaller | Slightly larger |
| **IT involvement** | Required | None |
| **Deployment friction** | High | Low |
| **Code changes** | N/A | None (just config) |

---

## Rollout Plan

### Phase 1: Preparation (Day 1 Morning)

- [ ] Backup current Azure AD app configuration
  ```bash
  az ad app show --id ${APP_CLIENT_ID} > app-backup-$(date +%Y%m%d).json
  ```

- [ ] Document current environment variables
  ```bash
  azd env get-values > env-backup-$(date +%Y%m%d).txt
  ```

- [ ] Test in development environment first

### Phase 2: Configuration (Day 1 Afternoon)

- [ ] **Step 1:** Add groups claim in Azure Portal (5 min)
- [ ] **Step 2:** Remove Group.Read.All permission (2 min)
- [ ] **Step 3:** Update environment variables (5 min)
- [ ] **Step 4:** Deploy updated configuration (10 min)
  ```bash
  azd deploy
  ```

### Phase 3: Testing (Day 1 Afternoon)

- [ ] Test with your own account (admin user)
- [ ] Test with regular test user account
- [ ] Verify groups appear in token
- [ ] Verify no consent prompts
- [ ] Test group-based data isolation

### Phase 4: User Communication (Before Rollout)

Send email to existing users:

```
Subject: Simplified Sign-In - No Admin Approval Needed

Hi team,

We've improved our app's sign-in process. Starting [date]:

✅ No admin approval required
✅ Faster sign-in
✅ Same functionality

If you previously saw "Need admin approval" errors, 
these are now resolved. Just sign in as usual.

Questions? Contact [support]
```

### Phase 5: Rollback Plan (If Needed)

If issues occur:

```bash
# Revert environment variables
azd env set REACT_APP_WEB_SCOPE "Group.Read.All"
azd deploy

# Re-add Group.Read.All permission in Azure Portal
# API permissions → Add permission → Microsoft Graph → Group.Read.All
# Grant admin consent
```

---

## Troubleshooting

### Issue: Groups not appearing in token

**Symptoms:** Token decoded at jwt.ms shows no `groups` claim

**Solutions:**
1. Verify optional claims configuration in Azure Portal
   - Token configuration → Should show "groups" claim
2. Check user is actually a member of security groups
   ```bash
   az ad user get-member-groups --id user@example.com
   ```
3. Ensure groups claim is configured for both ID and Access tokens
4. Wait 5 minutes for Azure AD configuration to propagate

---

## Fast Switch to 3‑Step Flow (Do Tomorrow)

Goal: Reduce onboarding to a single consent screen (B2B invitation) with minimal changes.

Steps (configuration-only):
1. Azure Portal → App registrations → Your app → Token configuration → Add groups claim
  - Choose "Security groups"
  - Include in "ID token" and "Access token"
2. Azure Portal → App registrations → Your app → API permissions
  - Remove `Group.Read.All` (or keep and grant admin consent once)
3. Frontend environment
  - Set `REACT_APP_WEB_SCOPE=openid profile email`
  - Ensure `loginRequest.scopes` uses this env var

Redeploy and test:

```bash
# Update env and deploy
azd env set REACT_APP_WEB_SCOPE "openid profile email"
azd deploy
```

Validation steps:
- Invite an external user, accept B2B invitation, sign in
- Confirm there is no app-permission consent prompt
- Decode JWT at jwt.ms and verify `groups` claim present

Rollback (if needed):
- Re-add `Group.Read.All` and grant admin consent; users will still only see B2B consent.

---

## Security Implications (No Protection Lost)

What changes:
- Source of `groups` moves from Graph API permission (`Group.Read.All`) to optional claims embedded in the token.

What stays the same:
- **Group-based isolation:** Backend continues enforcing `X-Group-ID` partition keys and reading `groups` from the JWT (`payload.get("groups", [])`).
- **Least privilege:** Removing `Group.Read.All` reduces scope exposure; optional claims provide only the user’s group IDs relevant to the token.
- **Consent security:** B2B invitation consent remains mandatory; app permission consent is eliminated without weakening access controls.
- **Auditing:** Sign-ins and token issuance are logged in Entra ID as before; admin consent (if used) is logged and revocable.

Threat model comparison:
- With `Group.Read.All`: Delegated Graph access to read groups; requires admin approval; potential over-permission.
- With optional claims: No Graph delegated read at sign-in; token contains necessary group IDs; strictly equal or lower exposure.

Conclusion:
- Switching to optional claims or pre-granted admin consent **does not reduce security protections**. Data isolation and access checks remain intact, and permission surface is smaller or equivalent.

### Issue: Token size too large error

**Symptoms:** Error: "Token size exceeds maximum"

**Cause:** User is member of 200+ groups (token size limit: ~8KB)

**Solutions:**
1. Use group filtering in optional claims configuration
2. Or switch to `groupIDs` instead of `groups` claim
3. Or use Group.Read.All with backend Graph API call (original approach)

**Check user's group count:**
```bash
az ad user get-member-groups --id user@example.com | jq 'length'
```

### Issue: Old users still see consent prompt

**Cause:** Cached tokens with old permissions

**Solution:**
1. Clear browser cache and cookies
2. Or sign out and sign back in
3. Or use incognito mode
4. Or revoke user's token in Azure Portal:
   ```
   Azure AD → Users → [User] → Revoke sessions
   ```

### Issue: Backend can't read groups

**Symptoms:** `current_user.groups` is empty array

**Debug:**
```python
# Add logging to auth.py
import logging
logger = logging.getLogger(__name__)

def get_current_user(authorization: str = Header(None)):
    payload = jwt.decode(token, options={"verify_signature": False})
    
    logger.info(f"Token claims: {payload.keys()}")  # See what's in token
    logger.info(f"Groups claim: {payload.get('groups')}")
    
    groups = payload.get("groups", [])
    return UserContext(groups=groups)
```

**Check:** Ensure token configuration added groups to **Access token**, not just ID token.

---

## Alternative Approaches (Not Recommended)

### Alternative 1: Keep Group.Read.All with Admin Consent URL

Provide admin consent URL to deployers:

```
https://login.microsoftonline.com/{tenant-id}/adminconsent
?client_id={app-client-id}
&redirect_uri={redirect-uri}
```

**Pros:** Quick fix for single-tenant deployments  
**Cons:** Still requires admin, doesn't scale for multi-tenant

### Alternative 2: Remove Groups Entirely

Use `oid` (user ID) for partitioning instead of groups:

```python
# Partition by user, not group
partition_key = current_user.user_id  # oid from token
```

**Pros:** Simplest, no permissions needed  
**Cons:** Loses multi-tenant group isolation

### Alternative 3: Application Permissions (Daemon App)

Use app-only permissions instead of delegated:

**Pros:** No user consent needed  
**Cons:** Requires client secret/certificate, harder to secure

---

## Security Considerations

### Token Size Limits

**Groups in token:**
- ✅ Each group ID: ~36 bytes (GUID)
- ✅ Max recommended: 150 groups per user
- ⚠️ If user has 200+ groups, consider overage claim handling

**Overage claim handling:**
```json
// If too many groups, token contains:
{
  "_claim_names": {
    "groups": "src1"
  },
  "_claim_sources": {
    "src1": {
      "endpoint": "https://graph.microsoft.com/v1.0/me/getMemberObjects"
    }
  }
}
```

**Backend code to handle overage** (add if needed):
```python
def get_user_groups(token_claims):
    if "groups" in token_claims:
        # Direct groups in token
        return token_claims["groups"]
    elif "_claim_names" in token_claims:
        # Overage - need to call Graph API
        # Fallback to Group.Read.All or use application permissions
        return fetch_groups_from_graph(token_claims["oid"])
    else:
        return []
```

### Privacy Implications

**Before (Group.Read.All):**
- App can read **ALL** groups in organization
- Even groups user is not a member of
- Broader access than needed

**After (Optional Claims):**
- Token only contains **user's own groups**
- Principle of least privilege
- Better privacy compliance (GDPR)

---

## Documentation Updates Needed

After implementation, update these docs:

- [ ] `DEPLOYMENT_GUIDE.md` - Remove admin consent requirement
- [ ] `AUTHENTICATION_IMPLEMENTATION_COMPLETE.md` - Update scope list
- [ ] `AZURE_AD_CONFIGURATION_COMPLETE.md` - Update API permissions
- [ ] `README.md` - Update prerequisites (no admin consent needed)

---

## Success Criteria

After implementation, verify:

- [ ] New users can sign in without admin approval
- [ ] No consent prompts appear during sign-in
- [ ] Groups are available in token (check jwt.ms)
- [ ] Backend receives groups in `current_user.groups`
- [ ] Group-based data isolation still works
- [ ] Existing users' sessions still work
- [ ] Sign-in speed improved (no Graph API call)

---

## Timeline Estimate

| Task | Time | Who |
|------|------|-----|
| Configure optional claims in Portal | 5 min | Developer/Admin |
| Remove Group.Read.All permission | 2 min | Developer/Admin |
| Update environment variables | 5 min | Developer |
| Deploy configuration | 10 min | Developer |
| Test with multiple users | 30 min | QA/Developer |
| **Total** | **~1 hour** | |

**Recommended time:** Tomorrow morning (low-risk change, easy rollback)

---

## Questions & Answers

**Q: Will existing signed-in users be affected?**  
A: No, their sessions continue. New tokens (after refresh) will use optional claims.

**Q: Do we need to update backend code?**  
A: No, backend already reads `groups` from token claims. It doesn't care where they come from.

**Q: What if a user has no groups?**  
A: Token will have `groups: []` (empty array). Backend handles this gracefully.

**Q: Can we use this with B2C (Entra External ID)?**  
A: Yes! B2C also supports custom claims for groups. Same approach works.

**Q: What about users with 200+ groups?**  
A: Use overage claim handling (see Security Considerations section). Or filter groups in optional claims configuration.

**Q: Is this production-ready?**  
A: Yes, Microsoft's recommended approach for group claims. Used by thousands of apps.

---

## Next Steps for Tomorrow

1. **Morning:** Configure optional claims in Azure Portal (5 min)
2. **Morning:** Update environment variables and deploy (15 min)
3. **Morning:** Test with your account + test users (30 min)
4. **Afternoon:** Monitor sign-in logs for any issues
5. **Afternoon:** Update documentation

**Total time commitment: ~1 hour**

**Risk level: Low** (easy rollback, non-breaking change)

**Impact: High** (removes major deployment blocker)

---

## Reference Links

- [Microsoft Docs: Optional Claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims)
- [Microsoft Docs: Groups Claim](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference#groups)
- [Microsoft Docs: Admin Consent](https://learn.microsoft.com/en-us/entra/identity-platform/v2-admin-consent)
- [JWT Decoder Tool](https://jwt.ms)

---

**Implementation Date:** [Tomorrow's Date]  
**Implemented By:** [Your Name]  
**Reviewed By:** [Reviewer Name]  
**Status:** Ready for implementation ✅
