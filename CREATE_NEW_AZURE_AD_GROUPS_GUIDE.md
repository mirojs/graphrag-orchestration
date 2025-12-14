# 🏢 Creating New Azure AD Groups for Your App

## Step 1: Create New Security Groups in Azure Portal

### Option A: Azure Portal UI
1. Go to **Azure Portal** → **Azure Active Directory**
2. Navigate to **Groups** → **All groups**
3. Click **New group**
4. Configure each group:

```
Group Type: Security
Group Name: ContentProcessor-TeamA
Description: Content Processing Application - Team A Access
Membership Type: Assigned (for controlled access)
```

Create these groups:
- `ContentProcessor-TeamA`
- `ContentProcessor-TeamB` 
- `ContentProcessor-TeamC`
- etc.

### Option B: PowerShell Script
```powershell
# Connect to Azure AD
Connect-AzureAD

# Create new groups for your app
$groups = @(
    @{Name="ContentProcessor-TeamA"; Description="Content Processing - Team A"},
    @{Name="ContentProcessor-TeamB"; Description="Content Processing - Team B"},
    @{Name="ContentProcessor-TeamC"; Description="Content Processing - Team C"}
)

foreach ($group in $groups) {
    $newGroup = New-AzureADGroup -DisplayName $group.Name -Description $group.Description -SecurityEnabled $true -MailEnabled $false
    Write-Host "Created group: $($newGroup.DisplayName) - ID: $($newGroup.ObjectId)"
}
```

## Step 2: Assign Users to Specific Groups

**Important**: Assign each user to ONLY ONE group for strict isolation:

```
User: alice@company.com → ContentProcessor-TeamA only
User: bob@company.com   → ContentProcessor-TeamB only  
User: carol@company.com → ContentProcessor-TeamC only
```

## Step 3: Update App Registration Token Configuration

1. Go to **Azure Portal** → **App Registrations** → **Your API App**
2. Navigate to **Token configuration**
3. Click **Add groups claim**
4. Select **Security groups**
5. **Important**: Choose **Emit groups as group IDs** (not names)

## Step 4: Get New Group IDs

After creating groups, get their Object IDs:

### Option A: Azure Portal
1. Go to **Azure Active Directory** → **Groups**
2. Click on each group
3. Copy the **Object ID**

### Option B: PowerShell
```powershell
Get-AzureADGroup | Where-Object {$_.DisplayName -like "ContentProcessor-*"} | Select-Object DisplayName, ObjectId
```

You'll get output like:
```
DisplayName              ObjectId
-----------              --------
ContentProcessor-TeamA   a1b2c3d4-e5f6-7890-abcd-ef1234567890
ContentProcessor-TeamB   b2c3d4e5-f6g7-8901-bcde-f23456789012
ContentProcessor-TeamC   c3d4e5f6-g7h8-9012-cdef-345678901234
```

## Step 5: Update GroupSelector Component (Optional)

Update the friendly names in your app:

```typescript
const GROUP_NAMES: Record<string, string> = {
  'a1b2c3d4-e5f6-7890-abcd-ef1234567890': 'Team A',
  'b2c3d4e5-f6g7-8901-bcde-f23456789012': 'Team B', 
  'c3d4e5f6-g7h8-9012-cdef-345678901234': 'Team C',
};
```

## Result: Clean Isolation

Each team will get their own containers:
```
Azure Storage:
├── pro-input-files-group-a1b2c3d4/     # Team A files
├── pro-schemas-group-a1b2c3d4/          # Team A schemas
├── pro-input-files-group-b2c3d4e5/     # Team B files  
├── pro-schemas-group-b2c3d4e5/          # Team B schemas
└── etc...
```

And Cosmos DB records will be tagged:
```json
{"id": "schema1", "name": "Invoice", "group_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
{"id": "case1", "name": "Q4 Review", "group_id": "b2c3d4e5-f6g7-8901-bcde-f23456789012"}
```