# 🎯 Group Isolation - Quick Reference

> **TL;DR** - Fast reference for implementing group-based data isolation

---

## 📌 Decision: Azure AD Security Groups vs App Roles

### ⭐ **RECOMMENDED: Azure AD Security Groups**

**Why?**
- ✅ Enterprise-ready and IT-managed
- ✅ Better compliance and auditing
- ✅ Integrates with existing org structure
- ✅ Multi-application support
- ✅ Dynamic group membership possible

**When to use App Roles instead:**
- You're building a SaaS product
- Need app-specific permissions
- Want complete control in code

---

## 🚀 Quick Start (5 Steps)

### 1️⃣ Create Azure AD Groups (5 min)
```bash
# Azure Portal → Azure AD → Groups → New Group
# Create: Marketing Team, Sales Team, Engineering Team, etc.
# Save group Object IDs
```

### 2️⃣ Configure Token Claims (2 min)
```bash
# Azure Portal → App Registrations → Your API App
# Token Configuration → Add groups claim → Security groups
# Select: Group ID
```

### 3️⃣ Update Backend Auth (30 min)
```python
# Add groups to UserContext
class UserContext:
    groups: List[str]  # NEW!
    
# Extract from token
async def get_current_user(credentials):
    groups = claims.get("groups", [])
    return UserContext(..., groups=groups)
```

### 4️⃣ Add group_id to Data Models (1 hour)
```python
# Add to all models
class Schema:
    group_id: str  # NEW!
    
# Filter queries
query = {
    "group_id": {"$in": user_context.groups}
}
```

### 5️⃣ Update Frontend (2 hours)
```typescript
// Add GroupSelector component
<GroupSelector />

// Filter API calls by group
await api.getSchemas(selectedGroup);
```

---

## 📝 Code Snippets Cheat Sheet

### Backend: Check Group Access
```python
if not user_context.has_group_access(group_id):
    raise HTTPException(403, "No access to this group")
```

### Backend: Create with Group
```python
schema = {
    "id": str(uuid.uuid4()),
    "name": schema_data.name,
    "group_id": schema_data.group_id,  # Required!
    "created_by": user_context.user_id
}
```

### Backend: Query by Group
```python
query = {
    "tenant_id": user_context.tenant_id,
    "group_id": {"$in": user_context.groups}
}
schemas = await collection.find(query).to_list()
```

### Frontend: Use Selected Group
```typescript
const { selectedGroup } = useGroupContext();

useEffect(() => {
    loadData(selectedGroup);
}, [selectedGroup]);
```

---

## 🗂️ File Checklist

### Backend Files to Create/Update
- [ ] `app/models/user_context.py` - Add groups field
- [ ] `app/auth/dependencies.py` - Extract groups from token
- [ ] `app/auth/group_resolver.py` - Handle group overage
- [ ] `app/models/schema.py` - Add group_id field
- [ ] `app/services/schema_service.py` - Filter by group
- [ ] `app/services/blob_storage_service.py` - Group containers
- [ ] `app/routers/schemas.py` - Group-aware endpoints

### Frontend Files to Create/Update
- [ ] `src/types/auth.types.ts` - Group interfaces
- [ ] `src/contexts/GroupContext.tsx` - Group state management
- [ ] `src/components/GroupSelector.tsx` - UI component
- [ ] `src/services/apiService.ts` - Add group_id to requests
- [ ] `src/components/SchemaList.tsx` - Filter by selected group

### Configuration Files
- [ ] `groups_structure.yaml` - Group definitions
- [ ] `user_group_mapping.json` - User assignments
- [ ] `group_id_mapping.json` - Group ID lookup

### Migration Scripts
- [ ] `scripts/analyze_current_data.py` - Pre-migration analysis
- [ ] `scripts/create_azure_ad_groups.sh` - Create groups
- [ ] `scripts/migrate_data_to_groups.py` - Data migration
- [ ] `scripts/verify_token_groups.py` - Token verification

---

## 🔍 Testing Scenarios

### ✅ Must Pass Tests

1. **Cross-Group Isolation**
   - User A in Group 1 cannot see Group 2 data
   - API returns 403 for unauthorized group access

2. **Multi-Group Access**
   - User B in Groups 1 & 2 sees data from both
   - Group switching updates displayed data

3. **Create/Upload**
   - New items assigned to correct group
   - Items only visible to group members

4. **Security**
   - Cannot modify group_id in API calls
   - Token tampering rejected
   - No SQL injection via group filters

---

## 📊 Migration Phases

| Phase | Duration | Key Tasks |
|-------|----------|-----------|
| 1. Planning | 1 day | Inventory data, define groups |
| 2. Azure AD | 1-2 days | Create groups, configure tokens |
| 3. Backend | 2-4 days | Update auth, models, services |
| 4. Frontend | 2-3 days | GroupContext, UI updates |
| 5. Migration | 1-2 days | Migrate data, verify |
| 6. Deploy | 1-2 days | Staged rollout, testing |

**Total: 5-7 days**

---

## ⚠️ Common Pitfalls

### 1. Forgetting to Filter Queries
```python
# ❌ WRONG - Returns all schemas
schemas = await collection.find({})

# ✅ CORRECT - Filter by user's groups
schemas = await collection.find({
    "group_id": {"$in": user_context.groups}
})
```

### 2. Not Handling Group Overage
```python
# ✅ CORRECT - Handle both cases
groups = await resolve_user_groups(claims, token)
# Handles: direct groups claim OR overage endpoint
```

### 3. Missing group_id on Create
```python
# ❌ WRONG - No group assignment
schema = {"name": "Test"}

# ✅ CORRECT - Always include group_id
schema = {
    "name": "Test",
    "group_id": user_context.primary_group
}
```

### 4. Not Updating Storage Structure
```python
# ❌ WRONG - Still using user containers
container = f"user-{user_id}"

# ✅ CORRECT - Use group containers
container = f"tenant-{tenant_id}-group-{group_id}"
```

---

## 🔐 Security Checklist

- [ ] All queries filter by group_id
- [ ] User group membership verified from JWT
- [ ] Cannot bypass group filter via API
- [ ] Blob storage isolated per group
- [ ] Admin operations require special permission
- [ ] Audit logging includes group_id
- [ ] JWT signature validation enabled (production)

---

## 📈 Performance Optimization

### Database Indexes
```javascript
// MongoDB - Create compound index
db.pro_schemas.createIndex({
    "tenant_id": 1,
    "group_id": 1,
    "created_at": -1
})
```

### Caching
```python
# Cache group membership (15 min TTL)
@cache(ttl=900)
async def get_user_groups(user_id: str) -> List[str]:
    # Fetch from token or Graph API
```

### Frontend Optimization
```typescript
// Debounce group switching
const debouncedSelectGroup = useMemo(
    () => debounce(selectGroup, 300),
    [selectGroup]
);
```

---

## 🆘 Troubleshooting Quick Fixes

| Problem | Quick Fix |
|---------|-----------|
| Groups not in token | Check Token Configuration in Azure AD |
| 403 errors | Verify user assigned to group in Azure AD |
| Data not filtering | Add `group_id` filter to query |
| Slow queries | Create index on `group_id` field |
| Group overage | Implement Graph API fallback |

---

## 📚 Key Documentation References

- **Main Guide**: `GROUP_ISOLATION_MIGRATION_GUIDE.md`
- **Part 2 (Phases 4-7)**: `GROUP_ISOLATION_MIGRATION_GUIDE_PART2.md`
- **Data Isolation Comparison**: `data_isolation_functional_comparison.md`
- **Azure AD Config**: `azure_entra_id_configuration_analysis.md`
- **Private Networking**: `PRIVATE_DOMAIN_SECURITY_GUIDE.md`

---

## 💡 Pro Tips

1. **Start with Test Groups**: Create 2-3 test groups before production
2. **Dry Run Everything**: Always test migrations with `dry_run=True` first
3. **Monitor Token Size**: Users in 200+ groups trigger overage handling
4. **Cache Group Names**: Map group IDs to names in backend cache
5. **Graceful Degradation**: Handle missing group_id in legacy data
6. **Audit Trail**: Log all group-based operations for compliance

---

## ✅ Definition of Done

Migration is complete when:
- [x] All Azure AD groups created
- [x] Token includes groups claim
- [x] All data models have group_id
- [x] All queries filter by group
- [x] Frontend shows group selector
- [x] Existing data migrated
- [x] Cross-group isolation verified
- [x] Performance acceptable
- [x] Documentation updated
- [x] Team trained

---

## 🎯 Next Steps After Migration

1. **Remove Old Code**: Delete user-based container logic
2. **Add Group Admin UI**: Let admins manage group settings
3. **Analytics**: Track usage per group
4. **Billing**: Consider group-based pricing
5. **Advanced Features**: 
   - Group-level permissions
   - Cross-group sharing
   - Group hierarchies

---

**Last Updated**: October 16, 2025
**Estimated Implementation**: 5-7 days
**Recommendation**: Azure AD Security Groups ⭐
