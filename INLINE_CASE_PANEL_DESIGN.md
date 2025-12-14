# Convert Case Modal to Inline Panel - Design Document

## Overview
Transform CaseManagementModal from a popup dialog to an **inline expandable panel** in PredictionTab, similar to how FilesTab displays files with preview.

## Current vs. Proposed Design

### Current (Popup Modal)
```
┌─────────────────────────────────────────┐
│ Prediction Tab (Analysis Page)          │
│                                         │
│ [Create New Case] button                │
│   ↓ (clicks)                            │
│   Opens popup dialog ────────┐          │
│                               ↓          │
│                    ┌──────────────────┐ │
│                    │ Create New Case  │ │
│                    │                  │ │
│                    │ Name: [____]     │ │
│                    │ Files: ...       │ │
│                    │                  │ │
│                    │ [Cancel] [Save]  │ │
│                    └──────────────────┘ │
│                                         │
└─────────────────────────────────────────┘
```

### Proposed (Inline Panel - Like FilesTab)
```
┌──────────────────────────────────────────────────────────────────┐
│ Prediction Tab (Analysis Page)                                   │
├──────────────────────────────────────────────────────────────────┤
│ Cases Section                                                    │
│ [▼ Create New Case] [Existing Cases ▼]                          │
├──────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ CREATE NEW CASE PANEL (Expanded inline)                      │ │
│ │                                                               │ │
│ │ Case Name: [___________________________]                      │ │
│ │ Description: [_______________________________________]        │ │
│ │                                                               │ │
│ │ Input Files:  [Upload] [Browse Library]                      │ │
│ │ ┌──────────────────────────────────────────────┐             │ │
│ │ │ Selected (2): contract.pdf, invoice.docx     │             │ │
│ │ │ ┌─────────────────────────────────────────┐  │             │ │
│ │ │ │ 📚 Library (Browse expanded)            │  │             │ │
│ │ │ │ 🔍 Search... [Sort: Name ▼]             │  │             │ │
│ │ │ │ ☑ contract.pdf   2MB   [Preview]        │  │             │ │
│ │ │ │ ☑ invoice.docx   1MB   [Preview]        │  │             │ │
│ │ │ │ ☐ report.xlsx    500KB [Preview]        │  │             │ │
│ │ │ └─────────────────────────────────────────┘  │             │ │
│ │ └──────────────────────────────────────────────┘             │ │
│ │                                                               │ │
│ │ [▶ Preview Selected Files]  ← Collapsible                    │ │
│ │ ┌──────────────────────────────────────────────┐             │ │
│ │ │ contract.pdf                                 │             │ │
│ │ │ [PDF Preview Here]                           │             │ │
│ │ └──────────────────────────────────────────────┘             │ │
│ │                                                               │ │
│ │ [Cancel] [Save Case]                                         │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ Analysis Results Section (below)                                │
│ ...                                                              │
└──────────────────────────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Convert Dialog to Inline Panel (Core)

#### Step 1: Create Inline Panel Component
**File**: `src/ProModeComponents/CaseManagement/CaseCreationPanel.tsx` (NEW)

```tsx
/**
 * Inline Case Creation Panel
 * 
 * Expandable panel for creating/editing cases inline in PredictionTab
 * REUSES:
 * - All logic from CaseManagementModal
 * - File library browser (already inline)
 * - File preview from FilesTab
 */

import React, { useState } from 'react';
import {
  Card,
  CardHeader,
  Button,
  Input,
  Textarea,
  Label,
  // ... other imports from CaseManagementModal
} from '@fluentui/react-components';
import { ChevronDown20Regular, ChevronRight20Regular } from '@fluentui/react-icons';

interface CaseCreationPanelProps {
  isExpanded: boolean;
  onToggle: () => void;
  mode: 'create' | 'edit';
  existingCase?: AnalysisCase;
  onSave: (caseData: CaseCreateRequest | CaseUpdateRequest) => void;
  onCancel: () => void;
}

export const CaseCreationPanel: React.FC<CaseCreationPanelProps> = ({
  isExpanded,
  onToggle,
  mode,
  existingCase,
  onSave,
  onCancel
}) => {
  // Copy all state and logic from CaseManagementModal
  const [caseName, setCaseName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedInputFiles, setSelectedInputFiles] = useState<string[]>([]);
  // ... all other state from modal
  
  if (!isExpanded) {
    return (
      <Card style={{ marginBottom: '16px' }}>
        <CardHeader
          header={
            <Button 
              appearance="subtle" 
              icon={<ChevronRight20Regular />}
              onClick={onToggle}
            >
              {mode === 'create' ? 'Create New Case' : `Edit Case: ${existingCase?.case_name}`}
            </Button>
          }
        />
      </Card>
    );
  }
  
  return (
    <Card style={{ marginBottom: '16px', padding: '20px' }}>
      <CardHeader
        header={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Button 
              appearance="subtle" 
              icon={<ChevronDown20Regular />}
              onClick={onToggle}
            >
              {mode === 'create' ? 'Create New Case' : `Edit Case: ${existingCase?.case_name}`}
            </Button>
            <div>
              <Button onClick={onCancel}>Cancel</Button>
              <Button appearance="primary" onClick={handleSave}>Save Case</Button>
            </div>
          </div>
        }
      />
      
      {/* Copy all form content from CaseManagementModal DialogContent */}
      <div style={{ marginTop: '16px' }}>
        {/* Case Name */}
        <Label>Case Name *</Label>
        <Input value={caseName} onChange={(_, data) => setCaseName(data.value)} />
        
        {/* Description */}
        <Label>Description</Label>
        <Textarea value={description} onChange={(_, data) => setDescription(data.value)} />
        
        {/* Input Files Section - REUSE from modal */}
        {/* ... copy entire input files section */}
        
        {/* Reference Files Section - REUSE from modal */}
        {/* ... copy entire reference files section */}
        
        {/* FILE PREVIEW SECTION - NEW! */}
        {selectedInputFiles.length > 0 && (
          <FilePreviewSection 
            files={selectedInputFiles}
            fileType="input"
          />
        )}
      </div>
    </Card>
  );
};
```

#### Step 2: Add File Preview Component (REUSE from FilesTab)
**File**: `src/ProModeComponents/CaseManagement/FilePreviewSection.tsx` (NEW)

```tsx
/**
 * File Preview Section
 * 
 * Shows preview of selected files inline
 * REUSES: ProModeDocumentViewer from FilesTab
 */

import React, { useState } from 'react';
import ProModeDocumentViewer from '../ProModeDocumentViewer';
import { Button, Label } from '@fluentui/react-components';
import { ChevronDown20Regular, ChevronRight20Regular } from '@fluentui/react-icons';

interface FilePreviewSectionProps {
  files: string[];
  fileType: 'input' | 'reference';
}

export const FilePreviewSection: React.FC<FilePreviewSectionProps> = ({ files, fileType }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [activeFileIndex, setActiveFileIndex] = useState(0);
  
  // Get file objects from Redux (REUSE pattern from FilesTab)
  const fileObjects = useSelector((state: RootState) => 
    fileType === 'input' ? state.files.inputFiles : state.files.referenceFiles
  );
  
  const selectedFileObjects = fileObjects.filter(f => files.includes(f.name));
  
  if (selectedFileObjects.length === 0) return null;
  
  return (
    <div style={{ marginTop: '16px', border: '1px solid #ccc', borderRadius: '4px', padding: '12px' }}>
      <Button 
        appearance="subtle"
        icon={isExpanded ? <ChevronDown20Regular /> : <ChevronRight20Regular />}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        Preview Selected Files ({selectedFileObjects.length})
      </Button>
      
      {isExpanded && (
        <div style={{ marginTop: '12px' }}>
          {/* File tabs */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
            {selectedFileObjects.map((file, index) => (
              <Button
                key={file.id}
                appearance={activeFileIndex === index ? 'primary' : 'secondary'}
                size="small"
                onClick={() => setActiveFileIndex(index)}
              >
                {file.name}
              </Button>
            ))}
          </div>
          
          {/* Preview - REUSE ProModeDocumentViewer from FilesTab */}
          <div style={{ border: '1px solid #ddd', minHeight: '400px' }}>
            <ProModeDocumentViewer 
              files={[selectedFileObjects[activeFileIndex]]}
              activeFileId={selectedFileObjects[activeFileIndex].id}
            />
          </div>
        </div>
      )}
    </div>
  );
};
```

#### Step 3: Update PredictionTab
**File**: `src/ProModeComponents/PredictionTab.tsx` (UPDATE)

```tsx
// BEFORE:
const [showCaseModal, setShowCaseModal] = useState(false);
const [caseModalMode, setCaseModalMode] = useState<'create' | 'edit'>('create');

// Dialog at bottom:
<CaseManagementModal
  open={showCaseModal}
  onOpenChange={setShowCaseModal}
  mode={caseModalMode}
  ...
/>

// AFTER:
const [showCasePanel, setShowCasePanel] = useState(false);
const [casePanelMode, setCasePanelMode] = useState<'create' | 'edit'>('create');

// Inline panel at top (before analysis results):
<CaseCreationPanel
  isExpanded={showCasePanel}
  onToggle={() => setShowCasePanel(!showCasePanel)}
  mode={casePanelMode}
  existingCase={casePanelMode === 'edit' ? currentCase : undefined}
  onSave={handleSaveCase}
  onCancel={() => setShowCasePanel(false)}
/>

{/* Analysis Results below */}
```

### Phase 2: Add File Preview (REUSE FilesTab)

#### Component Reuse Map:
```
FilesTab Components                 → CaseCreationPanel
─────────────────────────────────────────────────────────
ProModeDocumentViewer               → FilePreviewSection
  - PDF preview                     →   ✅ Reuse 100%
  - Image preview                   →   ✅ Reuse 100%
  - Text preview                    →   ✅ Reuse 100%

File selection state                → Already implemented
  - selectedInputFileIds            →   ✅ Reuse pattern
  - activePreviewFileId             →   ✅ Reuse pattern

Preview UI                          → FilePreviewSection
  - File tabs                       →   ✅ Reuse pattern
  - Preview container               →   ✅ Reuse 90%
  - Loading states                  →   ✅ Reuse 100%
```

### Phase 3: Layout Optimization

#### Responsive Design:
```tsx
// Desktop (>1200px): Side-by-side
┌────────────────────┬──────────────────────┐
│ Case Form (50%)    │ File Preview (50%)   │
│ - Name             │ [PDF/Image Preview]  │
│ - Description      │                      │
│ - File Library     │                      │
└────────────────────┴──────────────────────┘

// Tablet (768-1200px): Stacked with preview below
┌──────────────────────────────────────────┐
│ Case Form (100%)                         │
│ - Name, Description, Files               │
├──────────────────────────────────────────┤
│ File Preview (100%)                      │
│ [Expanded preview]                       │
└──────────────────────────────────────────┘

// Mobile (<768px): Collapsible sections
┌──────────────────────────────────────────┐
│ ▼ Case Details                           │
│ ▼ Input Files                            │
│ ▼ Reference Files                        │
│ ▼ Preview Files                          │
│ [Save] [Cancel]                          │
└──────────────────────────────────────────┘
```

## Code Reuse Summary

### From CaseManagementModal (95% reuse):
- ✅ All state management
- ✅ Form validation logic
- ✅ File upload handlers
- ✅ File selection handlers
- ✅ Inline library browser (already done!)
- ✅ Search and sorting
- ✅ Helper functions (formatFileSize, getDisplayFileName, etc.)

### From FilesTab (90% reuse):
- ✅ ProModeDocumentViewer component
- ✅ File preview logic
- ✅ File loading states
- ✅ Preview container styling
- ✅ File tabs navigation

### New Code (~10%):
- Panel expand/collapse logic
- Card-based layout instead of Dialog
- Inline preview integration
- Responsive layout adjustments

## Benefits

### UX Benefits:
- ✅ **No context loss** - see analysis results while creating case
- ✅ **File preview** - verify files before saving
- ✅ **Faster workflow** - no popup switching
- ✅ **Better mobile** - scrollable instead of overlapping
- ✅ **Copy/paste friendly** - can reference analysis results

### Technical Benefits:
- ✅ **95% code reuse** from existing components
- ✅ **No dialog complexity** - simpler state management
- ✅ **Better performance** - no dialog mounting/unmounting
- ✅ **Easier to extend** - inline allows more features

### Developer Benefits:
- ✅ **Consistent pattern** with FilesTab
- ✅ **Less code to maintain** (remove Dialog wrapper)
- ✅ **Easier testing** - no modal state to mock

## Migration Path

### Step 1: Create new components (1-2 hours)
- Create `CaseCreationPanel.tsx`
- Create `FilePreviewSection.tsx`
- Copy logic from `CaseManagementModal.tsx`

### Step 2: Update PredictionTab (30 min)
- Replace modal with panel
- Add panel state
- Update button handlers

### Step 3: Add file preview (1 hour)
- Import ProModeDocumentViewer
- Add preview section
- Wire up file selection

### Step 4: Testing (1 hour)
- Test create/edit flows
- Test file preview
- Test responsive layout
- Test all browsers

**Total Time: ~4-5 hours**

## Rollback Plan
Keep CaseManagementModal.tsx for 1 release cycle, use feature flag to toggle:
```tsx
const USE_INLINE_PANEL = true; // Feature flag

{USE_INLINE_PANEL ? (
  <CaseCreationPanel ... />
) : (
  <CaseManagementModal ... />
)}
```

## Success Criteria
- ✅ 95%+ code reuse from existing components
- ✅ File preview works for PDF, images, text
- ✅ No loss of functionality from modal
- ✅ Faster user workflow (measured by clicks)
- ✅ Mobile responsive
- ✅ No TypeScript errors
- ✅ Passes all existing tests

## Next Steps
1. ✅ Get approval for design
2. Create CaseCreationPanel component
3. Create FilePreviewSection component
4. Update PredictionTab integration
5. Add file preview functionality
6. Test and refine
7. Document for users

---

**Recommendation**: Proceed with implementation. This provides significant UX improvement with minimal new code (~10% new, 90% reused).
