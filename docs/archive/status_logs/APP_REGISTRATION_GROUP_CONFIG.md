# Azure App Registration Configuration - Group Claims

## Step-by-Step Instructions:

### 1. Navigate to Azure Portal
- Go to https://portal.azure.com
- Navigate to "Azure Active Directory" > "App registrations"
- Find your Content Processor API app registration

### 2. Configure Token Claims  
- Click on "Token configuration" in the left menu
- Click "Add groups claim"

### 3. IMPORTANT: Select Specific Groups Only
Instead of "All groups" or "Security groups", choose:
- ✅ **"Groups assigned to the application"**
- This ensures ONLY specific groups are included in tokens

### 4. Assign New Groups to Application
- Go to "Enterprise applications" in Azure AD
- Find your Content Processor app
- Click "Users and groups" 
- Click "Add user/group"
- Add ONLY your new groups:
  - ContentProcessor-TeamA
  - ContentProcessor-TeamB  
  - ContentProcessor-TeamC

### 5. Verify Token Claims
- Go to https://jwt.ms
- Login with a test user
- Verify the token contains ONLY the new group IDs

Example token payload:
```json
{
  "oid": "user-id-here",
  "groups": [
    "new-group-id-1", 
    "new-group-id-2"
  ]
}
```

## 🚫 Avoiding Existing Groups

By using "Groups assigned to the application" instead of "All groups":
- ✅ Only new ContentProcessor groups appear in tokens
- ✅ Existing company groups are excluded
- ✅ Clean separation from other systems
- ✅ Controlled access scope