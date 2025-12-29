# 🎯 Quick Reference: Azure AD Roles for Content Processor Groups

## 👥 **Role Requirements Summary**

| Task | Required Role | Can Delegate To | Frequency |
|------|---------------|-----------------|-----------|
| **Initial Setup** | Application Administrator | ❌ Cannot delegate | One-time |
| **Create Groups** | Groups Administrator | ❌ Cannot delegate | As needed |
| **Add/Remove Users** | Groups Administrator | ✅ Group Owners | Daily |
| **Rename Groups** | Groups Administrator | ❌ Cannot delegate | Rarely |
| **Delete Groups** | Groups Administrator | ❌ Cannot delegate | Rarely |

## 🔧 **Setup Checklist**

### **One-Time Setup (Global Administrator)**
- [ ] Assign **Groups Administrator** role to 2-3 designated users
- [ ] Assign **Application Administrator** role to 1-2 IT personnel
- [ ] Configure app registration token claims
- [ ] Grant Microsoft Graph API permissions

### **Per-Group Setup (Groups Administrator)**
- [ ] Create security group with descriptive name
- [ ] Add initial members
- [ ] Assign group owners for ongoing management
- [ ] **IF using "Assigned Groups Only"**: Ask Application Administrator to assign group to enterprise app (see below)
- [ ] **IF using "All Security Groups"**: Group works automatically - no registration needed! ✅

### **Group Registration (ONLY if using "Assigned Groups Only" mode)**

**Check your configuration first:**
- Azure Portal → App Registrations → [App] → Token configuration
- Look at "groups" claim → Check "Group types" column
- If it says "Groups assigned to the application", follow this process:

**For each new group (Application Administrator):**
- [ ] Navigate to Enterprise Applications → [Your App]
- [ ] Click "Users and groups" → "Add user/group"
- [ ] Select the newly created group
- [ ] Assign default or custom role
- [ ] Click "Assign"

**If it says "Security groups", skip this - all groups work automatically!**

### **Daily Management (Group Owners)**
- [ ] Add new team members to groups
- [ ] Remove departing team members
- [ ] Monitor group membership

## 📞 **Who to Contact**

| Need Help With | Contact | Role Required |
|----------------|---------|---------------|
| Creating new groups | Groups Administrator | Groups Administrator |
| Adding team members | Group Owner or Groups Administrator | Group Owner |
| App not showing groups | Application Administrator | Application Administrator |
| Permission errors | Global Administrator | Global Administrator |
| Role assignments | Global Administrator | Global Administrator |

## 🚨 **Escalation Path**

1. **Group Member Issues** → Group Owner
2. **Group Owner Issues** → Groups Administrator  
3. **Groups Administrator Issues** → Application Administrator
4. **Application Administrator Issues** → Global Administrator

## 💡 **Quick Commands**

### **Check User's Current Roles**
```
Azure Portal → Azure AD → Users → [User] → Directory role assignments
```

### **Verify Group Membership**
```
Azure Portal → Azure AD → Groups → [Group] → Members
```

### **Test JWT Token**
```
Go to: https://jwt.ms
Login with test user
Check for "groups" claim in token
```

### **Check App Permissions**
```
Azure Portal → App Registrations → [App] → API permissions
Look for: Microsoft Graph → Directory.Read.All (or Group.Read.All)
Status should be: "Granted for [tenant]"
```