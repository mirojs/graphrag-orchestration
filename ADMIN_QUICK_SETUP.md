# Quick Setup: Azure AD Admin Consent

## For Azure AD Administrators

**Time Required**: 5 minutes  
**Required Role**: Application Administrator or Global Administrator

---

## What We're Doing

Granting permission for the Content Processing app to read group names so users see "Sales Team" instead of "Group abc-123-def-456...".

**Security Note**: Uses **delegated permissions** - users can only see their own groups, not all directory groups.

---

## Steps

### 1. Navigate to App Registration

1. Open [Azure Portal](https://portal.azure.com/)
2. Go to **Azure Active Directory** (or **Microsoft Entra ID**)
3. Click **App registrations** (left menu)
4. Search for: `ca-cps-gw6br2ms6mxy-web`
   - Or search by Client ID: `b4aa58e1-8b31-445d-9fc9-1a1b6a044deb`

### 2. Add API Permission (if not already added)

1. Click **API permissions** (left menu)
2. Check if `Group.Read.All` (Delegated) exists
   - ✅ If yes → Skip to Step 3
   - ❌ If no → Continue below

3. Click **+ Add a permission**
4. Select **Microsoft Graph**
5. Select **Delegated permissions**
6. Search for `Group.Read.All`
7. Check the box
8. Click **Add permissions**

### 3. Grant Admin Consent

1. In **API permissions** page, you should see:
   ```
   Microsoft Graph
   ├── User.Read (Delegated)
   ├── Group.Read.All (Delegated)  ← This one needs consent
   └── [Other permissions]
   ```

2. Click button: **"✓ Grant admin consent for [Your Organization]"**

3. Click **Yes** to confirm

4. Wait for status to show green checkmarks:
   ```
   Permission                  Status
   ─────────────────────────────────────────
   User.Read                   ✅ Granted for [Org]
   Group.Read.All              ✅ Granted for [Org]
   ```

---

## Done! ✅

The application can now:
- ✅ Display friendly group names
- ✅ Still maintain group-based data isolation
- ✅ Users can only see their own groups (secure!)

---

## Optional: Enable Groups Claim in Token

This makes tokens include group IDs automatically (recommended):

1. In your app registration, click **Token configuration** (left menu)
2. Click **+ Add groups claim**
3. Select **Security groups**
4. Click **Add**

---

## Questions?

**What permission did we grant?**
- `Group.Read.All` (Delegated) - Allows users to read group info for groups they belong to

**Is this secure?**
- Yes! Users can ONLY see groups they're members of
- They cannot see other users' groups or all directory groups

**Can we revoke this later?**
- Yes, just remove the permission from API Permissions page

**Do users need to consent individually?**
- No, admin consent covers all users in the organization

---

**Reference**: See `AZURE_AD_SETUP_GUIDE.md` for detailed documentation
