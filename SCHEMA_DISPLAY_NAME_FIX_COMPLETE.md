# Schema Selection Display Name Fix

## Issue
CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION schema was showing "Updated Schema" in the schema list instead of its actual displayName.

## Root Cause
The schema list was displaying `schema.name` instead of `schema.displayName || schema.name`, causing schemas to show their internal ID-like names instead of their user-friendly display names.

## Fix Applied

### Schema List Display (2 locations)

**Location 1**: Desktop schema list (line ~2052)  
**Location 2**: Mobile schema list (line ~2812)

**Before**:
```tsx
<span title={schema.name}>
  {schema.name}
</span>
```

**After**:
```tsx
<span title={schema.displayName || schema.name}>
  {schema.displayName || schema.name}
</span>
```

## Files Modified
- `SchemaTab.tsx` - Lines 2052 and 2812 (schema list display)

## Impact
- ✅ Schema list now displays user-friendly names (displayName) when available
- ✅ Falls back to technical name if displayName is not set
- ✅ Consistent with schema header display (line 2129) which already used this pattern
- ✅ Both desktop and mobile views fixed

## Display Examples

### Before Fix:
Schema in list shows:
- `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION` → Displays as "Updated Schema" (wrong!)

### After Fix:
Schema in list shows:
- If `displayName` exists: Shows "Invoice Contract Verification" (correct!)
- If `displayName` is empty: Falls back to "CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION"

## Related Code Patterns

The schema header (line 2129) was already using the correct pattern:
```tsx
{selectedSchema!.displayName || selectedSchema!.name}
```

Now the schema list matches this same pattern for consistency.

## Testing

### Test Case 1: Schema with displayName
1. Create or select a schema that has both `name` and `displayName`
2. Expected: List shows `displayName`
3. Expected: Header shows `displayName`

### Test Case 2: Schema without displayName
1. Select a schema that only has `name` (no `displayName`)
2. Expected: List shows `name`
3. Expected: Header shows `name`

### Test Case 3: CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION
1. Select CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION
2. Expected: If it has displayName "Invoice Contract Verification", shows that
3. Expected: Otherwise shows technical name
4. Expected: Both list and header show same name

## Deployment Steps

1. **Rebuild Docker Images**:
   ```bash
   cd ./code/content-processing-solution-accelerator/infra/scripts
   conda deactivate
   ./docker-build.sh
   ```

2. **Deploy** updated containers

3. **Test** schema list displays correct names

## Status
✅ **COMPLETE** - Schema list now displays displayName when available
✅ **NO COMPILATION ERRORS** - TypeScript validation passed
✅ **READY FOR DEPLOYMENT** - Can be deployed with next build
