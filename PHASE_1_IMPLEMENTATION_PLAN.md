# PHASE 1: Inline File Management for Case Management Modal
## Implementation Plan - Maximum Code Reuse Strategy

---

## 🎯 Goal
Enhance `CaseManagementModal` to allow users to:
1. **Upload files** directly within the modal (reuse `ProModeUploadFilesModal` logic)
2. **Select files** from existing library (reuse file list display)
3. **Preview files** inline (reuse existing preview components)
4. **Remove files** from case selection

**NO BACKEND CHANGES NEEDED** - Everything reuses existing endpoints and `httpUtility`!

---

## 📦 Code Reuse Map

### 1. File Upload Logic → COPY FROM ProModeUploadFilesModal.tsx
```typescript
// REUSE: Lines 335-410 from ProModeUploadFilesModal.tsx
const handleUpload = async () => {
  await dispatch(uploadFilesAsync({ files, uploadType })).unwrap();
  // ✅ Already uses httpUtility
  // ✅ Already uploads to correct container
  // ✅ Already handles errors
};
```

### 2. File List Display → COPY FROM ProModeUploadFilesModal.tsx
```typescript
// REUSE: File input, drag-drop, progress bars (Lines 415-566)
<input
  ref={fileInputRef}
  type="file"
  multiple
  onChange={handleFileSelect}
  style={{ display: 'none' }}
/>
```

### 3. File Preview → REUSE Existing FilePreview Component
```typescript
// CHECK IF EXISTS: FilePreview component or similar
// If not, simple preview with file metadata
```

### 4. Redux Actions → ALREADY EXISTS
```typescript
// ✅ uploadFilesAsync - already uses httpUtility
// ✅ fetchFilesByTypeAsync - already uses httpUtility  
// ✅ deleteFileAsync - already uses httpUtility
```

---

## 🛠️ Implementation Steps

### STEP 1: Add File Management Section to CaseManagementModal (2-3 hours)

**File**: `CaseManagementModal.tsx`

**Changes**:
1. Import file management hooks from `ProModeUploadFilesModal`
2. Add state for selected files (input & reference)
3. Copy file selection UI from `ProModeUploadFilesModal`

**Exact Code to Reuse**:
```typescript
// FROM: ProModeUploadFilesModal.tsx lines 1-50
import { uploadFilesAsync, fetchFilesByTypeAsync } from "../ProModeStores/proModeStore";
const { inputFiles, referenceFiles, uploading } = useSelector((state: RootState) => state.files);
const [selectedInputFiles, setSelectedInputFiles] = useState<string[]>([]);
const [selectedReferenceFiles, setSelectedReferenceFiles] = useState<string[]>([]);
```

### STEP 2: Add File Upload Button (1 hour)

**Copy from**: `ProModeUploadFilesModal.tsx` lines 415-450

```typescript
// EXACT REUSE - Just change uploadType dynamically
const handleUploadClick = (type: 'input' | 'reference') => {
  setCurrentUploadType(type);
  fileInputRef.current?.click();
};

const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const files = Array.from(e.target.files || []);
  // REUSE: uploadFilesAsync from ProModeStore (already uses httpUtility!)
  await dispatch(uploadFilesAsync({ files, uploadType: currentUploadType }));
  // REUSE: fetchFilesByTypeAsync to refresh list
  await dispatch(fetchFilesByTypeAsync(currentUploadType));
};
```

### STEP 3: Add File Selection from Library (2 hours)

**New Component**: `FileSelector.tsx` (simple checkbox list)

```typescript
// REUSE: inputFiles/referenceFiles from Redux store
// REUSE: File list display pattern from ProModeUploadFilesModal

interface FileSelectorProps {
  availableFiles: any[]; // From Redux store
  selectedFiles: string[];
  onSelectionChange: (files: string[]) => void;
  fileType: 'input' | 'reference';
}

const FileSelector: React.FC<FileSelectorProps> = ({ 
  availableFiles, 
  selectedFiles, 
  onSelectionChange 
}) => {
  // Simple checkbox list - REUSE Fluent UI Checkbox component
  return (
    <div>
      {availableFiles.map(file => (
        <Checkbox
          key={file.id}
          label={file.name}
          checked={selectedFiles.includes(file.name)}
          onChange={(e, data) => {
            // Add/remove from selection
          }}
        />
      ))}
    </div>
  );
};
```

### STEP 4: Add File Preview (2 hours)

**Option A: Reuse Existing Preview (if available)**
```typescript
// Search for existing preview components
import { FilePreview } from '../Components/FilePreview';
```

**Option B: Simple Preview (if no existing component)**
```typescript
const FilePreviewSimple: React.FC<{ file: any }> = ({ file }) => {
  return (
    <div>
      <p>Name: {file.name}</p>
      <p>Size: {(file.size / 1024).toFixed(2)} KB</p>
      <p>Uploaded: {new Date(file.uploadedAt).toLocaleDateString()}</p>
      {/* REUSE: Download logic from existing file management */}
      <Button onClick={() => handleDownload(file.id)}>Download</Button>
    </div>
  );
};
```

### STEP 5: Update Case Save Logic (30 mins)

**No changes needed!** The backend already accepts `input_file_names` array:

```typescript
// ALREADY EXISTS in caseManagementService.ts
export const createCase = async (request: CaseCreateRequest): Promise<AnalysisCase> => {
  const response = await httpUtility.post('/pro-mode/cases', request);
  // ✅ request.input_file_names: string[] - already supported
  // ✅ request.reference_file_names: string[] - already supported
  return response.data as AnalysisCase;
};
```

Just pass the selected file names:
```typescript
const handleSave = async () => {
  const request: CaseCreateRequest = {
    case_id: generateCaseId(caseName),
    case_name: caseName,
    description: description,
    input_file_names: selectedInputFiles,      // ← From file selector
    reference_file_names: selectedReferenceFiles, // ← From file selector
    schema_name: currentSchema,
  };
  
  await dispatch(createCase(request)).unwrap(); // ✅ Already uses httpUtility!
};
```

---

## 📋 Detailed Code Changes

### File 1: CaseManagementModal.tsx

**Lines to Add** (after line 100):

```typescript
// ========== REUSE: File Management State (from ProModeUploadFilesModal) ==========
import { uploadFilesAsync, fetchFilesByTypeAsync } from '../../ProModeStores/proModeStore';

// Get available files from Redux store (REUSE existing state)
const { inputFiles, referenceFiles, uploading } = useSelector(
  (state: RootState) => state.files
);

// Local state for selected files
const [selectedInputFiles, setSelectedInputFiles] = useState<string[]>([]);
const [selectedReferenceFiles, setSelectedReferenceFiles] = useState<string[]>([]);
const [showFileSelector, setShowFileSelector] = useState(false);
const [currentFileType, setCurrentFileType] = useState<'input' | 'reference'>('input');

// REUSE: File upload ref (from ProModeUploadFilesModal line 122)
const fileInputRef = useRef<HTMLInputElement>(null);

// ========== REUSE: File Upload Logic (from ProModeUploadFilesModal lines 335-350) ==========
const handleUploadFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;
  
  try {
    // ✅ REUSE: uploadFilesAsync (already uses httpUtility!)
    await dispatch(uploadFilesAsync({ 
      files, 
      uploadType: currentFileType 
    })).unwrap();
    
    // ✅ REUSE: fetchFilesByTypeAsync to refresh list
    await dispatch(fetchFilesByTypeAsync(currentFileType));
    
    // Auto-select uploaded files
    const fileNames = files.map(f => f.name);
    if (currentFileType === 'input') {
      setSelectedInputFiles(prev => [...prev, ...fileNames]);
    } else {
      setSelectedReferenceFiles(prev => [...prev, ...fileNames]);
    }
  } catch (error) {
    console.error('Upload failed:', error);
  }
};

const handleUploadClick = (type: 'input' | 'reference') => {
  setCurrentFileType(type);
  fileInputRef.current?.click();
};
```

**Lines to Add** (in JSX, after description field around line 240):

```typescript
{/* ========== FILE MANAGEMENT SECTION (NEW) ========== */}

{/* Hidden file input - REUSE from ProModeUploadFilesModal */}
<input
  ref={fileInputRef}
  type="file"
  multiple
  accept="*/*"
  onChange={handleUploadFiles}
  style={{ display: 'none' }}
/>

{/* Input Files Section */}
<div className={styles.formGroup}>
  <Label className={styles.label}>
    Input Files <span className={styles.requiredMark}>*</span>
  </Label>
  
  {/* Action Buttons */}
  <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
    <Button 
      size="small"
      onClick={() => handleUploadClick('input')}
      disabled={isLoading}
    >
      📤 Upload New
    </Button>
    <Button 
      size="small"
      onClick={() => {
        setCurrentFileType('input');
        setShowFileSelector(true);
      }}
      disabled={isLoading}
    >
      📁 Select from Library ({inputFiles.length} available)
    </Button>
  </div>
  
  {/* Selected Files List */}
  <div className={styles.fileCheckboxGroup}>
    {selectedInputFiles.length === 0 ? (
      <div className={styles.hint}>
        No files selected. Upload new files or select from library.
      </div>
    ) : (
      selectedInputFiles.map((fileName, index) => (
        <div key={index} style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          padding: '4px 8px',
          backgroundColor: tokens.colorNeutralBackground1Hover,
          borderRadius: tokens.borderRadiusSmall
        }}>
          <span>📄 {fileName}</span>
          <Button
            size="small"
            appearance="subtle"
            onClick={() => {
              setSelectedInputFiles(prev => 
                prev.filter((_, i) => i !== index)
              );
            }}
            disabled={isLoading}
          >
            ✖️
          </Button>
        </div>
      ))
    )}
  </div>
</div>

{/* Reference Files Section - SAME PATTERN */}
<div className={styles.formGroup}>
  <Label className={styles.label}>
    Reference Files (optional)
  </Label>
  
  <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
    <Button 
      size="small"
      onClick={() => handleUploadClick('reference')}
      disabled={isLoading}
    >
      📤 Upload New
    </Button>
    <Button 
      size="small"
      onClick={() => {
        setCurrentFileType('reference');
        setShowFileSelector(true);
      }}
      disabled={isLoading}
    >
      📁 Select from Library ({referenceFiles.length} available)
    </Button>
  </div>
  
  <div className={styles.fileCheckboxGroup}>
    {selectedReferenceFiles.length === 0 ? (
      <div className={styles.hint}>
        No reference files selected (optional).
      </div>
    ) : (
      selectedReferenceFiles.map((fileName, index) => (
        <div key={index} style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          padding: '4px 8px',
          backgroundColor: tokens.colorNeutralBackground1Hover,
          borderRadius: tokens.borderRadiusSmall
        }}>
          <span>📄 {fileName}</span>
          <Button
            size="small"
            appearance="subtle"
            onClick={() => {
              setSelectedReferenceFiles(prev => 
                prev.filter((_, i) => i !== index)
              );
            }}
            disabled={isLoading}
          >
            ✖️
          </Button>
        </div>
      ))
    )}
  </div>
</div>
```

**Update handleSave** (around line 165):

```typescript
const handleSave = async () => {
  // Update validation
  if (!caseName.trim()) return;
  if (selectedInputFiles.length === 0) return; // ← Changed from availableFiles
  if (!currentSchema) return;
  
  try {
    if (mode === 'create') {
      const request: CaseCreateRequest = {
        case_id: generateCaseId(caseName),
        case_name: caseName,
        description: description || undefined,
        input_file_names: selectedInputFiles,      // ← Use selected files
        reference_file_names: selectedReferenceFiles, // ← Use selected files
        schema_name: currentSchema,
      };
      
      await dispatch(createCase(request)).unwrap(); // ✅ Already uses httpUtility!
    } else {
      // ... similar for edit mode
    }
    
    resetForm();
    onOpenChange(false);
  } catch (err) {
    console.error('Failed to save case:', err);
  }
};
```

---

## 📦 New Component: FileSelectorDialog.tsx

**Create new file**: `FileSelectorDialog.tsx` (2 hours)

```typescript
/**
 * File Selector Dialog
 * 
 * Reusable modal for selecting files from library
 * REUSES: Redux state, Fluent UI components
 */

import React, { useState } from 'react';
import {
  Dialog,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Button,
  Checkbox,
  SearchBox,
  makeStyles,
} from '@fluentui/react-components';

interface FileSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  availableFiles: any[]; // From Redux store
  selectedFiles: string[];
  onConfirm: (files: string[]) => void;
  fileType: 'input' | 'reference';
}

const useStyles = makeStyles({
  fileList: {
    maxHeight: '400px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
});

export const FileSelectorDialog: React.FC<FileSelectorDialogProps> = ({
  open,
  onOpenChange,
  availableFiles,
  selectedFiles,
  onConfirm,
  fileType,
}) => {
  const styles = useStyles();
  const [localSelection, setLocalSelection] = useState<string[]>(selectedFiles);
  const [searchQuery, setSearchQuery] = useState('');
  
  const filteredFiles = availableFiles.filter(file =>
    file.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  
  const handleToggle = (fileName: string) => {
    setLocalSelection(prev =>
      prev.includes(fileName)
        ? prev.filter(f => f !== fileName)
        : [...prev, fileName]
    );
  };
  
  const handleConfirm = () => {
    onConfirm(localSelection);
    onOpenChange(false);
  };
  
  return (
    <Dialog open={open} onOpenChange={(_, data) => onOpenChange(data.open)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>
            Select {fileType === 'input' ? 'Input' : 'Reference'} Files
          </DialogTitle>
          
          <DialogContent>
            <SearchBox
              placeholder="Search files..."
              value={searchQuery}
              onChange={(_, data) => setSearchQuery(data.value || '')}
            />
            
            <div className={styles.fileList}>
              {filteredFiles.map(file => (
                <Checkbox
                  key={file.id}
                  label={`${file.name} (${(file.size / 1024).toFixed(2)} KB)`}
                  checked={localSelection.includes(file.name)}
                  onChange={() => handleToggle(file.name)}
                />
              ))}
            </div>
            
            <div style={{ marginTop: '16px', fontSize: '14px', color: '#666' }}>
              {localSelection.length} file(s) selected
            </div>
          </DialogContent>
          
          <DialogActions>
            <Button appearance="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button appearance="primary" onClick={handleConfirm}>
              Confirm Selection
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};
```

**Import and Use in CaseManagementModal**:

```typescript
import { FileSelectorDialog } from './FileSelectorDialog';

// In JSX, add at the end:
<FileSelectorDialog
  open={showFileSelector}
  onOpenChange={setShowFileSelector}
  availableFiles={currentFileType === 'input' ? inputFiles : referenceFiles}
  selectedFiles={currentFileType === 'input' ? selectedInputFiles : selectedReferenceFiles}
  onConfirm={(files) => {
    if (currentFileType === 'input') {
      setSelectedInputFiles(files);
    } else {
      setSelectedReferenceFiles(files);
    }
  }}
  fileType={currentFileType}
/>
```

---

## ✅ Verification Checklist

- [ ] File upload reuses `uploadFilesAsync` (✅ uses httpUtility)
- [ ] File fetching reuses `fetchFilesByTypeAsync` (✅ uses httpUtility)
- [ ] Case creation reuses `createCase` (✅ uses httpUtility via caseManagementService)
- [ ] UI components reuse Fluent UI (✅ consistent with existing code)
- [ ] No new backend endpoints needed (✅ all existing endpoints)
- [ ] No changes to backend code (✅ frontend-only)
- [ ] File storage uses existing containers (✅ pro-input-files, pro-reference-files)

---

## 🎉 Benefits of This Approach

1. **Zero Backend Changes** - All endpoints already exist
2. **Maximum Code Reuse** - 80% copy-paste from existing components
3. **Consistent UX** - Uses same patterns as Files tab
4. **Fast Implementation** - 1-2 days instead of 1-2 weeks
5. **Low Risk** - Reusing battle-tested code
6. **Maintainable** - Following existing patterns

---

## 📊 Time Estimate

| Task | Hours | Approach |
|------|-------|----------|
| Add file state management | 1 | Copy from ProModeUploadFilesModal |
| Add upload button + logic | 1 | Copy from ProModeUploadFilesModal |
| Create FileSelectorDialog | 2 | New component, reuse Checkbox list |
| Add selected files display | 1 | Simple list with remove buttons |
| Update save logic | 0.5 | Just pass selected file names |
| Testing | 2 | Verify upload, select, save |
| **TOTAL** | **7.5 hours** | **~1 day of work** |

---

## 🚀 Next Steps

1. **Shall I start with CaseManagementModal.tsx updates?**
2. **Or create FileSelectorDialog.tsx first?**
3. **Want me to show you the exact diff of what will change?**

**Ready to implement when you are!** 🎯
