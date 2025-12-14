# Group ID Validation & Logging Implementation ✅

## Overview

Added comprehensive group_id validation and logging to the Quick Query flow to prevent 500 errors caused by missing group context.

---

## Root Cause Analysis

### Original Problem:
```
500 Internal Server Error
Error: Failed to get group container: container='None'
```

**Why it happened**:
- Frontend didn't validate group selection before execution
- Backend received requests without group_id
- Blob storage operations failed (no container name)

---

## Solution Implemented

### 1. Frontend Validation (QuickQuerySection.tsx)

**Location**: `handleExecuteQuery` function (line ~142)

```typescript
// ✅ CRITICAL: Validate group selection before execution
if (!selectedGroup) {
  console.error('[QuickQuery] No group selected - group_id is required for analysis');
  toast.error('Please select a security group before running Quick Query');
  trackProModeEvent('QuickQueryError', {
    error: 'No group selected',
    phase: 'pre-execution-validation'
  });
  return;  // STOP execution if no group
}
```

**Benefits**:
- ✅ Prevents API calls without group context
- ✅ User-friendly error message
- ✅ Tracks validation failures in AppInsights
- ✅ Fails fast (no unnecessary backend calls)

---

### 2. Comprehensive Logging (PredictionTab.tsx)

**Location**: `handleQuickQueryExecute` function (line ~365)

#### Step 1: Validate Group at Function Entry
```typescript
// ✅ CRITICAL: Validate group context at function entry
if (!selectedGroup) {
  console.error('🚨 [QuickQuery] No group selected - aborting execution', {
    hasSelectedGroup: false,
    timestamp: new Date().toISOString()
  });
  toast.error('Please select a security group before running Quick Query');
  trackProModeEvent('QuickQueryError', {
    error: 'No group selected in handleQuickQueryExecute',
    phase: 'function-entry'
  });
  return;
}
```

#### Step 2: Log Group Context at Function Start
```typescript
console.log('✅ [QuickQuery] Starting with group context:', {
  groupId: selectedGroup,
  prompt: prompt.substring(0, 100),
  timestamp: new Date().toISOString()
});
```

#### Step 3: Log Redux Schema Validation
```typescript
// ✅ Log schema validation with group context
console.log('[QuickQuery] Schema validation:', {
  hasSchemas: schemas.length > 0,
  schemaCount: schemas.length,
  groupContext: selectedGroup ? 'present' : 'MISSING',
  groupId: selectedGroup
});
```

#### Step 4: Log Schema Selection
```typescript
console.log('[QuickQuery] Using schema for Quick Query:', {
  schemaId: targetSchema.id,
  schemaName: targetSchema.name,
  groupId: selectedGroup,
  timestamp: new Date().toISOString()
});
```

#### Step 5: Log Orchestration Dispatch
```typescript
console.log('[QuickQuery] Dispatching startAnalysisOrchestratedAsync with group context:', {
  analyzerId: targetSchema.id,
  groupId: selectedGroup,
  timestamp: new Date().toISOString()
});
```

#### Step 6: Track Success/Failure
```typescript
// Success
console.log('✅ [QuickQuery] Analysis orchestration started successfully with group context:', {
  analyzerId: targetSchema.id,
  groupId: selectedGroup,
  timestamp: new Date().toISOString()
});

// Error
console.error('🚨 [QuickQuery] Analysis orchestration failed:', {
  error: error.message,
  groupContext: selectedGroup ? 'present' : 'MISSING',
  groupId: selectedGroup,
  timestamp: new Date().toISOString()
});
```

---

## Logging Output Example

### Successful Execution:
```
✅ [QuickQuery] Starting with group context: {
  groupId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  prompt: "Extract invoice number and total",
  timestamp: "2025-01-XX..."
}

[QuickQuery] Schema validation: {
  hasSchemas: true,
  schemaCount: 5,
  groupContext: "present",
  groupId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}

[QuickQuery] Using schema for Quick Query: {
  schemaId: "schema-uuid-123",
  schemaName: "Invoice Analysis",
  groupId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  timestamp: "2025-01-XX..."
}

[QuickQuery] Dispatching startAnalysisOrchestratedAsync with group context: {
  analyzerId: "schema-uuid-123",
  groupId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  timestamp: "2025-01-XX..."
}

✅ [QuickQuery] Analysis orchestration started successfully with group context: {
  analyzerId: "schema-uuid-123",
  groupId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  timestamp: "2025-01-XX..."
}
```

### Failed Execution (No Group):
```
🚨 [QuickQuery] No group selected - aborting execution {
  hasSelectedGroup: false,
  timestamp: "2025-01-XX..."
}

[Toast Error] Please select a security group before running Quick Query
[AppInsights] QuickQueryError: No group selected in handleQuickQueryExecute
```

---

## Validation Points

### Before Any API Calls:
1. ✅ QuickQuerySection.tsx validates `selectedGroup` exists
2. ✅ PredictionTab.tsx validates `selectedGroup` at function entry
3. ✅ User sees friendly error message
4. ✅ Execution stops before reaching backend

### During Execution:
1. ✅ Group context logged at each major step
2. ✅ group_id included in all log statements
3. ✅ Errors log group context (present/MISSING)

### Backend (Existing):
1. ✅ X-Group-ID header sent by httpUtility
2. ✅ Backend validates group access
3. ✅ Defensive validation for missing group_id

---

## Error Prevention Strategy

### Layer 1: UI Validation (QuickQuerySection.tsx)
- Prevents execution if no group selected
- Shows user-friendly error toast
- Tracks validation failures

### Layer 2: Function Entry Validation (PredictionTab.tsx)
- Double-checks group context at function start
- Logs detailed error context
- Tracks validation failures with phase information

### Layer 3: Comprehensive Logging
- Logs group_id at every step
- Makes debugging trivial (just search logs for group_id)
- Identifies exactly where group context is lost (if it happens)

### Layer 4: Backend Validation (Existing)
- validate_group_access middleware
- Defensive group_id checks
- Returns 400 if group_id missing

---

## Testing Scenarios

### Scenario 1: No Group Selected
**Steps**:
1. Open Quick Query
2. Don't select a group
3. Enter prompt and click "Quick Inquiry"

**Expected**:
- ❌ Execution blocked at QuickQuerySection validation
- 🔔 Toast: "Please select a security group before running Quick Query"
- 📊 AppInsights event: `QuickQueryError` with `phase: 'pre-execution-validation'`
- 📝 Console log: `[QuickQuery] No group selected - group_id is required`

---

### Scenario 2: Group Selected
**Steps**:
1. Select "Testing-access" group
2. Enter prompt: "Extract invoice number"
3. Click "Quick Inquiry"

**Expected**:
- ✅ Passes QuickQuerySection validation
- ✅ Passes PredictionTab validation
- 📝 Console logs show group_id at each step:
  - Function entry
  - Schema validation
  - Schema selection
  - Orchestration dispatch
  - Success confirmation
- 🌐 Backend receives X-Group-ID header
- 💾 Results saved to group-specific container

---

### Scenario 3: Group Switched Mid-Session
**Steps**:
1. Select "test-users" group
2. Start Quick Query analysis
3. Switch to "Testing-access" group
4. Start another Quick Query

**Expected**:
- ✅ First query uses "test-users" container
- ✅ Second query uses "Testing-access" container
- 📝 Logs show group_id change
- 💾 Results isolated per group

---

## Debugging Guide

### If 500 Error Still Occurs:

1. **Check Frontend Logs**:
   ```
   Search for: "[QuickQuery]"
   Look for: group_id values at each step
   ```

2. **Check Backend Logs**:
   ```
   Search for: "group_id" or "X-Group-ID"
   Look for: Missing or None values
   ```

3. **Check Network Tab**:
   ```
   Look for: X-Group-ID header in request
   Verify: Header value matches selected group
   ```

4. **Check GroupContext**:
   ```typescript
   // Add temporary logging in GroupContext
   console.log('GroupContext selectedGroup:', selectedGroup);
   ```

5. **Check httpUtility**:
   ```typescript
   // Verify X-Group-ID header is added
   // Should be in httpUtility.get/post/put methods
   ```

---

## Code Quality Improvements

### Consistency:
- ✅ All Quick Query logs use `[QuickQuery]` prefix
- ✅ All logs include `timestamp` field
- ✅ All errors use 🚨 emoji for visibility
- ✅ All success logs use ✅ emoji

### Context:
- ✅ Every log includes group_id when available
- ✅ Error logs include `groupContext: 'present' | 'MISSING'`
- ✅ Phase information for multi-step processes

### Actionability:
- ✅ Error messages tell user what to do
- ✅ AppInsights events include phase for debugging
- ✅ Logs provide enough context to diagnose issues

---

## Files Modified

1. **QuickQuerySection.tsx**
   - Added: Group validation in `handleExecuteQuery`
   - Added: Error toast and AppInsights tracking
   - Added: Early return if no group selected

2. **PredictionTab.tsx**
   - Added: Group validation at function entry
   - Added: Comprehensive logging (6 log points)
   - Added: Group context in all log statements
   - Added: Error logging with group context

---

## Success Metrics

### Before Implementation:
- ❌ 500 errors when no group selected
- ❌ No visibility into group_id propagation
- ❌ Hard to debug missing group context
- ❌ Users confused by generic errors

### After Implementation:
- ✅ Execution blocked if no group selected
- ✅ Full visibility into group_id at every step
- ✅ Easy debugging (just search for group_id in logs)
- ✅ User-friendly error messages
- ✅ AppInsights tracking for analytics

---

## Related Files

- `QuickQuerySection.tsx` - UI validation
- `PredictionTab.tsx` - Execution logging
- `GroupContext.tsx` - Group selection state
- `httpUtility.ts` - X-Group-ID header injection
- `proMode.py` - Backend group validation

---

**Last Updated**: 2025-01-XX
**Status**: Implementation Complete ✅
**Next Step**: QA Testing with Testing-access group
