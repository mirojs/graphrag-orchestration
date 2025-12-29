# 🔌 Case Management Frontend Integration Guide

## Overview
This guide explains how to integrate the case management system with your existing `PredictionTab` component.

---

## ✅ What's Been Implemented

### Redux State Management
**File**: `src/redux/slices/casesSlice.ts`
- ✅ Complete Redux slice with actions and thunks
- ✅ CRUD operations for cases
- ✅ Case selection and filtering
- ✅ Error handling

### UI Components
**Directory**: `src/ProModeComponents/CaseManagement/`
- ✅ `CaseSelector.tsx` - Dropdown for selecting cases
- ✅ `CaseSummaryCard.tsx` - Display case details
- ✅ `CaseManagementModal.tsx` - Create/edit cases
- ✅ `index.ts` - Component exports

---

## 🔧 Integration Steps

### Step 1: Register Redux Slice

**File**: `src/redux/store.ts`

Add the cases reducer to your store:

```typescript
import { configureStore } from '@reduxjs/toolkit';
import casesReducer from './slices/casesSlice';
// ... other imports

export const store = configureStore({
  reducer: {
    // ... existing reducers
    cases: casesReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
```

### Step 2: Update Redux Hooks (if not already done)

**File**: `src/redux/hooks.ts`

```typescript
import { TypedUseSelectorHook, useDispatch, useSelector } from 'react-redux';
import type { RootState, AppDispatch } from './store';

export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
```

### Step 3: Integrate with PredictionTab

**File**: `src/ProModeComponents/PredictionTab.tsx`

Add these imports at the top:

```typescript
import { useState } from 'react';
import {
  CaseSelector,
  CaseSummaryCard,
  CaseManagementModal,
} from './CaseManagement';
import { useAppDispatch, useAppSelector } from '../redux/hooks';
import {
  selectCurrentCase,
  selectCasesAnalyzing,
  startCaseAnalysis,
  deleteCase,
} from '../redux/slices/casesSlice';
```

Add state for modal control:

```typescript
const [showCaseModal, setShowCaseModal] = useState(false);
const [caseModalMode, setCaseModalMode] = useState<'create' | 'edit'>('create');

// Get current case from Redux
const currentCase = useAppSelector(selectCurrentCase);
const analyzingCase = useAppSelector(selectCasesAnalyzing);
```

Add helper functions:

```typescript
// Handle case selection - auto-populate files and schema
const handleCaseSelected = () => {
  if (!currentCase) return;
  
  // Auto-select input files
  const inputFilesToSelect = availableFiles.filter(file =>
    currentCase.input_file_names.includes(file.fileName)
  );
  setSelectedInputFiles(inputFilesToSelect.map(f => f.fileName));
  
  // Auto-select reference files
  const referenceFilesToSelect = availableFiles.filter(file =>
    currentCase.reference_file_names.includes(file.fileName)
  );
  setSelectedReferenceFiles(referenceFilesToSelect.map(f => f.fileName));
  
  // Auto-select schema
  setSelectedSchema(currentCase.schema_name);
};

// Call this whenever currentCase changes
useEffect(() => {
  handleCaseSelected();
}, [currentCase]);

// Handle case-based analysis
const handleStartCaseAnalysis = async () => {
  if (!currentCase) return;
  
  try {
    await dispatch(startCaseAnalysis(currentCase.case_id)).unwrap();
    // The actual analysis will use the auto-populated files/schema
    // You may want to trigger your existing analysis logic here
  } catch (error) {
    console.error('Failed to start case analysis:', error);
  }
};

// Get available files and schemas for the modal
const getAvailableFileNames = (): string[] => {
  // Return array of file names from your Files tab
  return availableFiles.map(f => f.fileName);
};

const getAvailableSchemas = (): string[] => {
  // Return array of schema names from your Schema tab
  return availableSchemas.map(s => s.name);
};
```

### Step 4: Add UI to PredictionTab

Add this section **above** the existing "Comprehensive Query Section":

```tsx
{/* 📁 CASE MANAGEMENT SECTION */}
<Card style={{ 
  marginBottom: responsiveSpacing, 
  padding: responsiveSpacing,
  background: colors.background.secondary,
  border: `1px solid ${colors.border.subtle}`,
  borderRadius: '8px'
}}>
  {/* Header */}
  <div style={{ 
    display: 'flex', 
    alignItems: 'center', 
    marginBottom: 12,
    gap: 8
  }}>
    <Label
      size="large"
      weight="semibold"
      style={{ color: colors.text.primary }}
    >
      📁 Case Management
    </Label>
  </div>

  {/* Description */}
  <MessageBar intent="info" style={{ marginBottom: 12 }}>
    Save and reuse analysis configurations as cases. Select a case to auto-populate files and schema.
  </MessageBar>

  {/* Case Selector */}
  <CaseSelector
    onCreateNew={() => {
      setCaseModalMode('create');
      setShowCaseModal(true);
    }}
  />

  {/* Case Actions */}
  {currentCase && (
    <div style={{ 
      display: 'flex', 
      gap: 12, 
      marginTop: 12,
      flexWrap: 'wrap'
    }}>
      <Button
        appearance="secondary"
        onClick={() => {
          setCaseModalMode('edit');
          setShowCaseModal(true);
        }}
      >
        ✏️ Edit Case
      </Button>
      
      <Button
        appearance="secondary"
        onClick={async () => {
          if (window.confirm(`Delete case "${currentCase.case_name}"?`)) {
            await dispatch(deleteCase(currentCase.case_id));
          }
        }}
      >
        🗑️ Delete Case
      </Button>
    </div>
  )}

  {/* Case Summary */}
  {currentCase && (
    <div style={{ marginTop: 16 }}>
      <CaseSummaryCard case={currentCase} />
    </div>
  )}
</Card>

{/* Case Management Modal */}
<CaseManagementModal
  open={showCaseModal}
  onOpenChange={setShowCaseModal}
  mode={caseModalMode}
  existingCase={caseModalMode === 'edit' ? currentCase ?? undefined : undefined}
  availableFiles={getAvailableFileNames()}
  availableSchemas={getAvailableSchemas()}
/>
```

### Step 5: Update "Start Analysis" Button

Modify your existing "Start Analysis" button to support case-based analysis:

```tsx
<Button
  appearance="primary"
  disabled={!canStartAnalysis && !currentCase}
  onClick={() => {
    if (currentCase) {
      handleStartCaseAnalysis();
    } else {
      handleStartAnalysisOrchestrated(); // Your existing function
    }
  }}
  icon={analysisLoading || analyzingCase ? <Spinner size="tiny" /> : undefined}
>
  {analysisLoading || analyzingCase ? 
    t('proMode.prediction.analyzing') : 
    currentCase ? 'Start Analysis from Case' : t('proMode.prediction.startAnalysis')
  }
</Button>
```

---

## 📋 Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    User Actions                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
    1. Select Case      2. Create Case
         │                   │
         ▼                   ▼
┌────────────────────┐  ┌────────────────────┐
│ Redux: selectCase  │  │ Redux: createCase  │
│ Fetches case data  │  │ Opens modal        │
└────────┬───────────┘  └────────┬───────────┘
         │                        │
         ▼                        ▼
┌────────────────────────────────────────────┐
│     Auto-populate PredictionTab            │
│  - Input files → selectedInputFiles        │
│  - Reference files → selectedReferenceFiles│
│  - Schema → selectedSchema                 │
└────────┬───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│     User clicks "Start Analysis"           │
└────────┬───────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│  Redux: startCaseAnalysis(caseId)         │
│  Triggers existing analysis workflow       │
│  Records run in case history               │
└────────────────────────────────────────────┘
```

---

## 🎯 Key Integration Points

### 1. File Selection Sync

When a case is selected, sync with your file selection:

```typescript
useEffect(() => {
  if (currentCase) {
    // Your existing file selection state
    const inputFiles = yourFileList.filter(f => 
      currentCase.input_file_names.includes(f.name)
    );
    setYourInputFiles(inputFiles);
    
    const refFiles = yourFileList.filter(f => 
      currentCase.reference_file_names.includes(f.name)
    );
    setYourReferenceFiles(refFiles);
  }
}, [currentCase]);
```

### 2. Schema Selection Sync

```typescript
useEffect(() => {
  if (currentCase) {
    const schema = yourSchemaList.find(s => 
      s.name === currentCase.schema_name
    );
    setYourSelectedSchema(schema);
  }
}, [currentCase]);
```

### 3. Analysis Execution

Integrate with your existing analysis logic:

```typescript
const executeAnalysis = async () => {
  if (currentCase) {
    // Record that this is a case-based analysis
    const result = await yourExistingAnalysisFunction({
      inputFiles: selectedInputFiles,
      referenceFiles: selectedReferenceFiles,
      schema: selectedSchema,
      caseId: currentCase.case_id, // Pass for tracking
    });
    
    // Update case history via API
    // (This happens automatically in the backend)
  } else {
    // Regular analysis without case
    await yourExistingAnalysisFunction({
      inputFiles: selectedInputFiles,
      referenceFiles: selectedReferenceFiles,
      schema: selectedSchema,
    });
  }
};
```

---

## 🔗 API Connection

Ensure your backend router is registered in the main app:

**File**: `ContentProcessorAPI/app/main.py`

```python
from app.routers import case_management

app.include_router(case_management.router)
```

Verify CORS settings allow frontend requests:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your frontend URL
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 🧪 Testing Checklist

### Manual Testing

1. **Create Case**
   - [ ] Open modal and create new case
   - [ ] Verify case appears in dropdown
   - [ ] Check case saved to backend

2. **Select Case**
   - [ ] Select case from dropdown
   - [ ] Verify files auto-populate
   - [ ] Verify schema auto-selects
   - [ ] Check summary card displays correctly

3. **Edit Case**
   - [ ] Click "Edit Case" button
   - [ ] Modify case details
   - [ ] Save and verify updates

4. **Delete Case**
   - [ ] Click "Delete Case" button
   - [ ] Confirm deletion
   - [ ] Verify case removed from list

5. **Run Analysis**
   - [ ] Select case
   - [ ] Click "Start Analysis"
   - [ ] Verify analysis executes
   - [ ] Check case history updated

### Error Scenarios

- [ ] Create case with duplicate ID
- [ ] Select case with missing files
- [ ] Select case with missing schema
- [ ] Network error during save
- [ ] Invalid form data

---

## 🎨 Styling Customization

All components use Fluent UI tokens for theming. To customize:

```typescript
import { tokens } from '@fluentui/react-components';

// Use tokens for consistency
const customStyles = makeStyles({
  myElement: {
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorBrandForeground1,
    padding: tokens.spacingVerticalM,
  },
});
```

---

## 🐛 Troubleshooting

### Cases not loading
- Check API endpoint is accessible: `GET /api/cases`
- Verify Redux store includes `cases` reducer
- Check browser console for errors

### Files not auto-populating
- Verify `handleCaseSelected` is called on case change
- Check file name matching is exact (case-sensitive)
- Log `currentCase` and `availableFiles` for debugging

### Modal not opening
- Ensure `showCaseModal` state is managed correctly
- Check Modal component is rendered in JSX
- Verify no z-index conflicts

### Analysis not starting
- Check `startCaseAnalysis` thunk is dispatched
- Verify backend `/api/cases/{id}/analyze` endpoint works
- Check network tab for API errors

---

## 📚 Additional Resources

- **Redux Toolkit**: https://redux-toolkit.js.org/
- **Fluent UI React**: https://react.fluentui.dev/
- **Case Management Design**: See `CASE_MANAGEMENT_SYSTEM_DESIGN.md`
- **API Documentation**: See `CASE_MANAGEMENT_IMPLEMENTATION_PLAN.md`

---

## ✅ Integration Checklist

- [ ] Redux slice registered in store
- [ ] Redux hooks configured
- [ ] Components imported in PredictionTab
- [ ] Case selector added to UI
- [ ] Modal component added
- [ ] Case summary card integrated
- [ ] File auto-population logic added
- [ ] Schema auto-selection logic added
- [ ] Analysis execution updated
- [ ] Backend API connected
- [ ] CORS configured
- [ ] Manual testing completed
- [ ] Error handling tested

---

## 🎉 Next Steps

Once integrated:

1. **User Testing**: Get feedback from real users
2. **Analytics**: Track case usage metrics
3. **Enhancements**: Add advanced features like:
   - Case history timeline view
   - Batch case operations
   - Case templates
   - Export/import cases

---

Need help? Refer to the component source code for detailed implementation examples!
