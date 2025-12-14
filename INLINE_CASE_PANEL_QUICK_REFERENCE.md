# Quick Reference: Inline Case Panel vs Modal

## Before vs After

### Old Design (Modal Popup)
```
User clicks "Create Case" → Popup opens → Blocks view → Edit form → Save → Popup closes
Problems: Context loss, extra clicks, no preview, blocks analysis results
```

### New Design (Inline Panel)
```
User clicks "Create Case" → Panel expands inline → Edit form + preview → Save → Panel closes
Benefits: Context preserved, fewer clicks, file preview, see analysis while editing
```

## Key Files Changed

1. **NEW**: `CaseManagement/CaseCreationPanel.tsx` (1040 lines)
   - Inline expandable panel component
   - 95% reused from CaseManagementModal
   - File preview section added

2. **UPDATED**: `PredictionTab.tsx`
   - Import CaseCreationPanel
   - Change state: `showCaseModal` → `showCasePanel`
   - Render inline panel instead of modal
   - Old modal commented out for rollback

3. **UPDATED**: `CaseManagement/index.ts`
   - Export CaseCreationPanel

## Usage

### Opening the Panel
```typescript
// From CaseSelector
<CaseSelector
  onCreateNew={() => {
    setCasePanelMode('create');
    setShowCasePanel(true);
  }}
/>

// From Edit button
<Button onClick={() => {
  setCasePanelMode('edit');
  setShowCasePanel(true);
}}>
  Edit Case
</Button>
```

### Panel Component
```typescript
<CaseCreationPanel
  isExpanded={showCasePanel}
  onToggle={() => setShowCasePanel(!showCasePanel)}
  mode={casePanelMode}
  existingCase={casePanelMode === 'edit' ? currentCase : undefined}
  currentSchema={selectedSchema?.name || selectedSchema?.id || ''}
/>
```

## Features

### ✅ Implemented
- Inline collapsible panel (no popup)
- File upload/selection with inline library
- Search and sort files (Name, Size, Uploaded)
- File preview section with metadata
- Two-column layout (form + preview)
- Responsive design (mobile/tablet/desktop)
- Create and edit modes
- All validation from modal

### 🚧 Future Enhancement
- Full document preview (PDF/images like FilesTab)
  - Need to extract PreviewWithAuthenticatedBlob from FilesTab
  - Add blob URL management
  - Integrate ProModeDocumentViewer

## Testing

### Must Test
1. Create new case flow
2. Edit existing case flow
3. File upload (input + reference)
4. File selection from library
5. Search/sort in library
6. File preview (metadata display)
7. Save validation (name, files, schema required)
8. Cancel/close panel
9. Responsive layout on mobile

### Rollback If Needed
Uncomment CaseManagementModal in PredictionTab.tsx (lines 1943-1950)

## Code Reuse Stats
- **95%** from CaseManagementModal (state, handlers, validation)
- **90%** from FilesTab (sorting, searching, file utils)
- **5%** new code (panel UI, FilePreviewInfo component)

## Benefits
- ✅ **Fewer clicks**: No popup open/close
- ✅ **Context preserved**: See analysis while creating case
- ✅ **File preview**: Verify selection before saving
- ✅ **Better mobile**: Scrollable instead of overlapping
- ✅ **Copy-paste friendly**: Can reference other content
- ✅ **Faster**: No dialog mounting/unmounting

## Next Steps
1. Deploy and test
2. Gather user feedback
3. Optionally add full document preview
4. Remove old modal after validation
