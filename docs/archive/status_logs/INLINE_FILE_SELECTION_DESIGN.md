# Inline File Selection Design - Replacing Popup

## Problem
Current design uses a popup (FileSelectorDialog) which:
- ❌ Requires extra clicks (open popup → select → close)
- ❌ Hides the main form context
- ❌ No file preview functionality
- ❌ Inconsistent with Files tab pattern

## Solution
Inline expandable file library, similar to Files tab:

### UI Flow

```
┌─────────────────────────────────────────────────┐
│ Input Files *                                   │
├─────────────────────────────────────────────────┤
│ [Upload New] [📂 Browse Library (15)]           │ ← Buttons
├─────────────────────────────────────────────────┤
│ Selected Files (2):                             │
│ ✅ 📄 contract.pdf · 2.5 MB · Jan 17      [X]   │
│ ✅ 📄 invoice.docx · 1.2 MB · Jan 16      [X]   │
└─────────────────────────────────────────────────┘

[When "Browse Library" clicked, expands below:]

┌─────────────────────────────────────────────────┐
│ 🔍 Search files...                              │ ← Search bar
├─────────────────────────────────────────────────┤
│ Available Files (15 total, 2 selected):         │
│ ☑ 📄 contract.pdf · 2.5 MB · Jan 17            │ ← Already selected
│ ☑ 📄 invoice.docx · 1.2 MB · Jan 16            │
│ ☐ 📄 report.xlsx · 850 KB · Jan 15             │
│ ☐ 📄 summary.txt · 45 KB · Jan 14              │
│ ...                                             │
└─────────────────────────────────────────────────┘
```

## Implementation Plan

### Step 1: Update State
```tsx
// REMOVE:
const [showFileSelector, setShowFileSelector] = useState(false);
const [currentFileType, setCurrentFileType] = useState<'input' | 'reference'>('input');

// ADD:
const [showInputLibrary, setShowInputLibrary] = useState(false);
const [showReferenceLibrary, setShowReferenceLibrary] = useState(false);
const [inputLibrarySearch, setInputLibrarySearch] = useState('');
const [referenceLibrarySearch, setReferenceLibrarySearch] = useState('');
```

### Step 2: Update Button Handler
```tsx
// BEFORE:
const handleSelectFromLibrary = (type: 'input' | 'reference') => {
  setCurrentFileType(type);
  setShowFileSelector(true); // Opens popup
};

// AFTER:
const toggleLibraryBrowser = (type: 'input' | 'reference') => {
  if (type === 'input') {
    setShowInputLibrary(!showInputLibrary);
  } else {
    setShowReferenceLibrary(!showReferenceLibrary);
  }
};
```

### Step 3: Add Inline Library Component
```tsx
{showInputLibrary && (
  <div className={styles.libraryBrowser}>
    {/* Search Bar */}
    <SearchBox 
      placeholder="Search files..."
      value={inputLibrarySearch}
      onChange={(_, data) => setInputLibrarySearch(data.value)}
    />
    
    {/* File List with Checkboxes */}
    <div className={styles.libraryFileList}>
      {getFilteredLibraryFiles(inputFiles, inputLibrarySearch).map(file => (
        <div key={file.id} className={styles.libraryFileItem}>
          <Checkbox 
            checked={selectedInputFiles.includes(file.name)}
            onChange={() => handleFileToggle(file.name, 'input')}
            label={
              <div className={styles.fileInfo}>
                {getFileIcon(file.name)}
                <span>{file.name}</span>
                <span className={styles.fileMetadata}>
                  {formatFileSize(file.size)} · {formatUploadDate(file.uploadedAt)}
                </span>
              </div>
            }
          />
        </div>
      ))}
    </div>
  </div>
)}
```

### Step 4: Remove FileSelectorDialog
```tsx
// REMOVE entire component:
<FileSelectorDialog
  open={showFileSelector}
  onOpenChange={setShowFileSelector}
  ...
/>

// REMOVE import:
import FileSelectorDialog from './FileSelectorDialog';
```

### Step 5: Add CSS Styles
```tsx
libraryBrowser: {
  marginTop: tokens.spacingVerticalM,
  padding: tokens.spacingVerticalM,
  border: `1px solid ${tokens.colorNeutralStroke2}`,
  borderRadius: tokens.borderRadiusMedium,
  backgroundColor: tokens.colorNeutralBackground2,
},
libraryFileList: {
  maxHeight: '300px',
  overflowY: 'auto',
  marginTop: tokens.spacingVerticalS,
},
libraryFileItem: {
  padding: tokens.spacingVerticalXS,
  borderBottom: `1px solid ${tokens.colorNeutralStroke3}`,
  '&:last-child': {
    borderBottom: 'none',
  },
},
```

## Benefits

### User Experience
- ✅ **One-click access**: No popup, library expands inline
- ✅ **Context preserved**: Can see selected files while browsing
- ✅ **Instant feedback**: Checkboxes show selection state immediately
- ✅ **Search integrated**: Filter files without switching views
- ✅ **Consistent**: Matches Files tab interaction pattern

### Technical
- ✅ **Simpler code**: No dialog state management, no focus issues
- ✅ **Better performance**: No dialog mounting/unmounting
- ✅ **Easier to extend**: Can add preview, drag-drop, etc.
- ✅ **Accessibility**: Standard checkbox pattern, keyboard navigation

## Future Enhancements

### Phase 3.1: File Preview (Easy to add)
```tsx
<div onClick={() => setPreviewFile(file)}>
  {getFileIcon(file.name)}
  <span>{file.name}</span>
</div>

{previewFile && (
  <div className={styles.inlinePreview}>
    <ProModeDocumentViewer file={previewFile} />
  </div>
)}
```

### Phase 3.2: Bulk Actions
```tsx
<div className={styles.libraryHeader}>
  <SearchBox ... />
  <Button onClick={() => selectAllVisible()}>Select All</Button>
  <Button onClick={() => clearSelection()}>Clear</Button>
</div>
```

### Phase 3.3: Sorting
```tsx
<Dropdown 
  placeholder="Sort by..."
  options={['Name', 'Size', 'Upload Date']}
  onChange={handleSortChange}
/>
```

## Comparison

| Feature | Popup (Old) | Inline (New) |
|---------|-------------|--------------|
| Clicks to select | 3 (open, select, close) | 1 (toggle checkbox) |
| Context visibility | Hidden | Visible |
| Search | In popup | Inline |
| Preview | Not possible | Easy to add |
| Keyboard nav | Limited | Full |
| Code complexity | High (dialog state) | Low (simple toggle) |
| Focus management | Complex | Simple |

## Implementation Time
- **Remove popup code**: 15 min
- **Add inline browser**: 30 min
- **Add search/filter**: 15 min
- **Add CSS styles**: 15 min
- **Testing**: 15 min
- **Total**: ~90 minutes

## Risks & Mitigation
- **Risk**: Longer form if library expanded
  - **Mitigation**: Max-height with scroll, collapsible by default
  
- **Risk**: Performance with many files
  - **Mitigation**: Virtualization (react-window) if >100 files
  
- **Risk**: Mobile layout
  - **Mitigation**: Responsive styles, stack on small screens

---

**Recommendation**: Proceed with inline implementation. Simpler, more intuitive, easier to extend.
