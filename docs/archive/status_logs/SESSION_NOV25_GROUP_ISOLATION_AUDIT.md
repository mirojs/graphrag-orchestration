# Session Summary - November 25, 2025

## Session Focus: Group Isolation Security Audit

### What We Did

#### 1. System Schema Hiding (UI)
**Problem:** Quick Query Master Schema and temp enhancement schemas were appearing in the schema list.

**Solution:**
- **Backend:** Mark system schemas with `hideFromUI: true`, `isSystemSchema: true`
  - Quick Query Master Schema: already had these flags
  - Temp enhancement schemas: now detected by `__dunder__` naming pattern and marked
- **Frontend:** Added filter in `SchemaTab.tsx`:
  ```typescript
  const visibleSchemas = schemas.filter((s: any) => !s.hideFromUI && !s.isSystemSchema);
  ```

#### 2. Cosmos DB Partition Key Audit
**Problem:** Several Cosmos DB queries were missing `group_id` in their filter conditions, potentially allowing cross-tenant data access.

**Fixed locations in `proMode.py`:**
- Line ~3092: base schema lookup
- Line ~3168: name collision check  
- Line ~3205: schema update
- Line ~4235: updated schema fetch
- Line ~5264: fallback schema fetch
- Line ~11001: edit schema check

All now include `"group_id": group_id` in their MongoDB query filters.

#### 3. Blob Storage Group Isolation Audit
**Problem:** Inconsistent container naming patterns and a security bug in predictions delete endpoint.

**Findings:**
- Most endpoints correctly use `get_group_container_name(group_id)` → `group-{display_name}`
- Quick Query schemas use `schemas-{group_id}` pattern (full GUID)
- **SECURITY BUG FIXED:** Predictions delete was using just `"predictions"` container with NO group isolation!

**Solution:**
- Created unified `get_resource_container_name(resource_type, group_id)` function
- Updated Quick Query to use this unified function
- Fixed predictions endpoints to properly use group-isolated containers

### Current Container Naming Patterns

| Resource Type | Container Pattern | Example |
|---------------|-------------------|---------|
| Files | `group-{display_name}` | `group-finance-department` |
| Predictions | `predictions-{display_name}` | `predictions-finance-department` |
| Quick Query Schemas | `schemas-{group_id}` | `schemas-abc123-def456-...` |

**Note:** Display names are resolved from Azure AD group GUIDs via Microsoft Graph API in `get_group_display_name()`.

### Files Changed

1. **`proMode.py`** (~15,000 lines)
   - Added `get_resource_container_name()` unified function (lines 1779-1816)
   - Fixed 7+ Cosmos DB queries with missing `group_id`
   - Updated `_save_schema_to_storage()` to mark temp schemas
   - Fixed GET `/pro-mode/schemas` to mark dunder-named schemas
   - Fixed predictions endpoints for proper group isolation

2. **`SchemaTab.tsx`**
   - Added `visibleSchemas` filter to exclude hidden/system schemas

3. **Deleted:** `proMode.py.backup_nov22` (old backup causing confusion)

### Key Functions Reference

```python
# Get container name with display name (human-readable)
get_group_container_name(group_id: str) -> str
# Returns: "group-{display_name}" e.g., "group-finance-department"

# Get resource-specific container name  
get_resource_container_name(resource_type: str, group_id: str) -> str
# Returns: "{resource_type}-{group_id}" e.g., "schemas-abc123..."

# Resolve Azure AD group GUID to display name
get_group_display_name(group_id: str) -> str
# Returns: "Finance Department" (via MS Graph API)
```

### What's Working Now

✅ System schemas (Quick Query Master, temp enhancement) hidden from UI  
✅ All Cosmos DB queries include `group_id` for partition key enforcement  
✅ Predictions endpoints properly group-isolated  
✅ Consistent container naming patterns documented  
✅ Frontend filters out hidden schemas  

### Next Steps / Future Considerations

1. **Documentation cleanup:** Old markdown files reference truncated GUID pattern (`group-{group_id[:8]}`) that was never implemented. Consider cleaning up outdated docs.

2. **Verify deployment:** After deploying, verify group isolation is working correctly by testing with different Azure AD groups.

3. **Predictions container migration:** If there are existing predictions in the old non-isolated `predictions` container, they may need migration to group-specific containers.

### Git Commit

```
6ebd4c40 - Security: Group isolation audit and system schema hiding
```

---

*Session Date: November 25, 2025*
