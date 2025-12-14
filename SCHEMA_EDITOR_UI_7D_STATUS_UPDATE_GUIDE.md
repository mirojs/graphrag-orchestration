# Schema Editor UI - 7D Enhancement Status Display

This document describes the UI updates needed to show 7D enhancement status in the schema editor and schema list.

## Overview

After implementing 7D enhancement in the backend (Phases 1.1-1.2) and frontend actions (Phase 1.3), we need to update the UI to:
1. Show which schemas have 7D enhancement
2. Provide visual indicator of enhancement status
3. Allow users to understand the quality level of their schemas

## Implementation Details

### 1. Schema List View Updates

**File**: `ContentProcessorWeb/src/components/ProMode/SchemaList.tsx` (or similar)

**Changes Needed**:
```typescript
// Add 7D status indicator to schema list items
interface SchemaListItemProps {
  schema: ProModeSchema;
  // ... existing props
}

function SchemaListItem({ schema }: SchemaListItemProps) {
  const has7d = schema.has7dEnhancement || false;
  
  return (
    <div className="schema-list-item">
      {/* Existing schema info */}
      <div className="schema-name">{schema.displayName}</div>
      <div className="schema-description">{schema.description}</div>
      
      {/* NEW: 7D Enhancement Badge */}
      {has7d && (
        <span className="badge badge-success" title="Enhanced with 7D for production quality">
          🚀 7D Enhanced
        </span>
      )}
      
      {/* Field count and other metadata */}
      <div className="schema-metadata">
        <span>{schema.fieldCount} fields</span>
        {/* ... existing metadata */}
      </div>
    </div>
  );
}
```

**CSS Styling**:
```css
.badge-success {
  background-color: #28a745;
  color: white;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  margin-left: 8px;
}

.badge-success::before {
  content: "🚀 ";
}
```

### 2. Schema Editor View Updates

**File**: `ContentProcessorWeb/src/components/ProMode/SchemaEditor.tsx` (or similar)

**Changes Needed**:
```typescript
// Add 7D status display in schema editor header
function SchemaEditorHeader({ schema }: { schema: ProModeSchema }) {
  const has7d = schema.has7dEnhancement || false;
  
  return (
    <div className="schema-editor-header">
      <h2>{schema.displayName}</h2>
      
      {/* NEW: 7D Enhancement Status */}
      <div className="enhancement-status">
        {has7d ? (
          <div className="status-badge enhanced">
            <span className="icon">✅</span>
            <span className="label">7D Enhanced</span>
            <span className="description">
              Production-quality descriptions for consistency and accuracy
            </span>
          </div>
        ) : (
          <div className="status-badge basic">
            <span className="icon">ℹ️</span>
            <span className="label">Basic Schema</span>
            <span className="description">
              Consider applying 7D enhancement for better extraction quality
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
```

**CSS Styling**:
```css
.enhancement-status {
  margin: 16px 0;
}

.status-badge {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid;
  gap: 12px;
}

.status-badge.enhanced {
  background-color: #d4edda;
  border-color: #c3e6cb;
  color: #155724;
}

.status-badge.basic {
  background-color: #d1ecf1;
  border-color: #bee5eb;
  color: #0c5460;
}

.status-badge .icon {
  font-size: 24px;
}

.status-badge .label {
  font-weight: 600;
  font-size: 14px;
}

.status-badge .description {
  font-size: 12px;
  opacity: 0.8;
}
```

### 3. Schema Review Dialog Updates

**File**: `ContentProcessorWeb/src/components/ProMode/SchemaReviewDialog.tsx`

**Changes Needed**:
```typescript
// Show 7D status when reviewing schema before save
function SchemaReviewDialog({ schema, onSave, onCancel }: SchemaReviewDialogProps) {
  // Schema will automatically have 7D applied via updated createSchema action
  
  return (
    <Dialog>
      <DialogHeader>
        <DialogTitle>Review Schema</DialogTitle>
      </DialogHeader>
      
      <DialogContent>
        {/* Existing schema preview */}
        <SchemaPreview schema={schema} />
        
        {/* NEW: 7D Enhancement Notice */}
        <div className="enhancement-notice">
          <p>
            <strong>✅ 7D Enhancement Applied</strong>
          </p>
          <p className="notice-description">
            This schema will include production-quality descriptions for:
          </p>
          <ul>
            <li>Field formatting and examples</li>
            <li>Cross-document consistency</li>
            <li>Data validation rules</li>
            <li>Relationship tracking</li>
          </ul>
        </div>
      </DialogContent>
      
      <DialogFooter>
        <button onClick={onCancel}>Cancel</button>
        <button onClick={onSave} className="btn-primary">
          Save Schema (with 7D)
        </button>
      </DialogFooter>
    </Dialog>
  );
}
```

### 4. Type Definitions Update

**File**: `ContentProcessorWeb/src/types/ProModeSchema.ts`

**Changes Needed**:
```typescript
export interface ProModeSchema {
  id: string;
  displayName: string;
  description: string;
  kind: string;
  fields: ProModeField[];
  fieldSchema?: any;
  fieldCount?: number;
  
  // NEW: 7D Enhancement tracking
  has7dEnhancement?: boolean;
  
  // Existing metadata
  created?: string;
  updated?: string;
  createdBy?: string;
}
```

## Implementation Priority

### High Priority (Immediate)
1. ✅ **Type definitions** - Add `has7dEnhancement` field to ProModeSchema interface
2. ✅ **Schema list badge** - Show 7D status in schema list for quick identification
3. ✅ **Schema review dialog** - Inform users that 7D will be applied on save

### Medium Priority (Next Sprint)
4. **Schema editor header** - Full status display with explanation
5. **Filter/sort by enhancement** - Allow filtering schemas by 7D status

### Low Priority (Future Enhancement)
6. **Tooltip with 7D dimensions** - Hover tooltip showing which 7D dimensions are applied
7. **Enhancement toggle** - UI control to enable/disable 7D on individual schemas
8. **Re-enhancement button** - Allow updating old schemas with latest 7D templates

## Testing Checklist

- [ ] Schema list shows 7D badge for enhanced schemas
- [ ] Schema list does NOT show badge for basic schemas
- [ ] Schema review dialog displays 7D notice before save
- [ ] Newly saved schemas have `has7dEnhancement: true` in database
- [ ] Migration script successfully adds badge to migrated schemas
- [ ] UI updates responsive on mobile/tablet
- [ ] Accessibility: Badge has proper ARIA labels
- [ ] Tooltips provide helpful context about 7D

## Rollout Plan

### Phase 1: Backend Complete ✅
- [x] Schema 7D enhancer utility
- [x] Backend endpoint accepts `apply7d` flag
- [x] Frontend action passes `apply7d: true`
- [x] Database stores `has7dEnhancement` field

### Phase 2: UI Updates (Current)
- [ ] Update TypeScript interfaces
- [ ] Add badge to schema list
- [ ] Update schema review dialog
- [ ] Add schema editor status display

### Phase 3: Migration
- [ ] Run migration script on staging environment
- [ ] Verify all schemas enhanced correctly
- [ ] Run migration script on production
- [ ] Monitor for any issues

## Notes

- All new schemas created via Quick Query → Save will automatically have 7D enhancement
- Existing schemas need migration via `enhance_existing_schemas_with_7d.py` script
- The `has7dEnhancement` field is the source of truth for UI display
- 7D enhancement is backward compatible - enhanced schemas work with existing extraction code

## Questions & Answers

**Q: Will 7D enhancement slow down the UI?**
A: No. Enhancement happens server-side during save. The UI only displays the status flag.

**Q: Can users disable 7D enhancement?**
A: Currently, it's enabled by default for all new schemas. A toggle could be added in future if needed.

**Q: What happens to schemas created before 7D?**
A: They work fine as basic schemas. Run the migration script to enhance them retroactively.

**Q: How can I see the actual 7D descriptions?**
A: View the schema JSON in the editor, or inspect the `fieldSchema.fields[fieldName].description` field.
