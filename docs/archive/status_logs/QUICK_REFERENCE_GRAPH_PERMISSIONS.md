# 📋 Quick Reference: Adding Graph API Permissions

## 🎯 Visual Flow

```
Azure Portal
    ↓
App Registrations
    ↓
Select App (API or Web)
    ↓
API permissions (left sidebar)
    ↓
+ Add a permission
    ↓
Microsoft Graph
    ↓
Application permissions ← IMPORTANT: Choose "Application" not "Delegated"
    ↓
Search: "Group"
    ↓
☑ Group.Read.All
    ↓
Add permissions (button at bottom)
    ↓
Grant admin consent for [tenant] ← CRITICAL STEP
    ↓
Confirm "Yes"
    ↓
✅ Verify green checkmark appears
```

---

## ⚡ Quick Steps (Checklist)

### **For Each App (API + Web):**

- [ ] 1. Portal → App registrations
- [ ] 2. Click your app name
- [ ] 3. API permissions (left sidebar)
- [ ] 4. + Add a permission
- [ ] 5. Microsoft Graph
- [ ] 6. **Application permissions** tab
- [ ] 7. Search "Group"
- [ ] 8. Check Group.Read.All
- [ ] 9. Add permissions
- [ ] 10. **Grant admin consent**
- [ ] 11. Confirm "Yes"
- [ ] 12. Verify ✅ green checkmark

---

## 🚨 Common Mistakes to Avoid

| ❌ Wrong | ✅ Correct |
|---------|-----------|
| Delegated permissions | **Application permissions** |
| Group.ReadWrite.All | Group.Read.All (read only) |
| Forgot to grant consent | **Must grant admin consent!** |
| Only added to API app | Add to **BOTH** API and Web apps |
| Didn't verify green checkmark | Check status shows "Granted" |

---

## 📝 Apps to Configure

### **Your Apps:**
1. **API App:** `ca-cps-xh5lwkfq3vfm-api`
   - Client ID: `9f9b5bce-42a9-4eb0-b1dd-c7e5d454a2f5`
   - Status: ✅ Configured

2. **Web App:** `ca-cps-xh5lwkfq3vfm-web`
   - Client ID: `546fae19-24fb-4ff8-9e7c-b5ff64e17987`
   - Status: ✅ Configured

---

## 🔍 Verification

### **How to Check It's Working:**

**In Azure Portal:**
```
App Registrations → [Your App] → API permissions

Look for:
✅ Microsoft Graph
✅ Group.Read.All (Application)
✅ Status: "Granted for [tenant]" with green checkmark
```

**Via Azure CLI:**
```bash
# Check permissions
az ad app show --id 9f9b5bce-42a9-4eb0-b1dd-c7e5d454a2f5 \
  --query "requiredResourceAccess[?resourceAppId=='00000003-0000-0000-c000-000000000000']"

# Should show permission ID: 5b567255-7703-4780-807c-7be8301ae99b
```

---

## 💡 Why This Permission is Needed

**Without Group.Read.All:**
- App can get group IDs from JWT token
- But only sees: `7e9e0c33-a31e-4b56-8ebf-0fff973f328f`
- Users see GUIDs (confusing!)

**With Group.Read.All:**
- App can call Microsoft Graph API
- Resolves IDs to names: `Hulkdesign-AI-access`
- Users see friendly names (better UX!)

---

## 📚 Full Documentation

For detailed step-by-step with screenshots descriptions:
→ See: `AZURE_PORTAL_ADD_GRAPH_PERMISSIONS_GUIDE.md`

For complete Azure AD configuration:
→ See: `AZURE_AD_CONFIGURATION_COMPLETE.md`

---

## ⏱️ Time Estimate

- **Per App:** 5 minutes
- **Both Apps:** 10 minutes
- **If you have admin rights:** Can complete immediately
- **If you need approval:** May take 1-3 days

---

## 🆘 Need Help?

**Don't have admin rights?**
- Ask your Azure AD administrator
- Share this document with them
- They need: "Application Administrator" role or higher

**Permission not working?**
- Wait 2-3 minutes after granting consent
- Refresh browser
- Check Azure AD audit logs
- Verify green checkmark is present

**Can't find the permission?**
- Make sure you're in "Application permissions" tab (not Delegated)
- Search for exactly: `Group.Read.All`
- Alternative: Use `Directory.Read.All`

---

**Status:** ✅ Both apps configured  
**Last Updated:** 2025-10-20  
**Ready for:** Group isolation deployment
