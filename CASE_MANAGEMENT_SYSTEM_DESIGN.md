# 📋 Case Management System Design

## Overview
Transform the Comprehensive Analysis section into a **case-based workflow system** that allows users to create, manage, and reuse analysis configurations as distinct cases.

---

## 🎯 Business Value

### Key Benefits
1. **Contextual Organization**: Group related analyses by business case (e.g., "Q4 2025 Contract Review", "Vendor Invoice Audit")
2. **Time Savings**: Quickly retrieve and re-run previous analysis configurations
3. **Consistency**: Standardize analysis approach for recurring workflows
4. **Collaboration**: Share case IDs across teams for consistent analysis
5. **Audit Trail**: Track what was analyzed, when, and with what configuration
6. **Version Control**: See how analysis configurations evolved over time

### Use Cases
- **Contract Reviews**: Save specific contract type + reference document combinations
- **Compliance Audits**: Reusable templates for monthly/quarterly audits
- **Invoice Processing**: Standard verification workflows for different vendors
- **Legal Discovery**: Track analysis across multiple related documents
- **Quality Assurance**: Consistent testing with predefined cases

---

## 🏗️ Architecture Design

### Data Model

#### Case Entity (Simplified for Universal Use)
```typescript
interface AnalysisCase {
  // Identification
  caseId: string;                    // User-defined case ID/number
  caseName: string;                  // User-defined case name
  
  // Metadata
  createdAt: Date;
  updatedAt: Date;
  createdBy: string;                 // User identifier (for audit trail only)
  description?: string;              // Optional case description
  
  // Analysis Configuration (References Only - No File Storage)
  inputFileNames: string[];          // Names of files from Files tab
  referenceFileNames: string[];      // Names of reference files from Files tab
  schemaName: string;                // Name of schema from Schema tab
  
  // State & History
  analysisHistory: AnalysisRun[];    // Track all runs
  lastRunAt?: Date;
}

// Note: Files are NOT stored with cases - only references to existing uploaded files
// Users select files from the Files tab and schemas from the Schema tab
// Case only stores the NAMES to enable quick reconfiguration

interface AnalysisRun {
  runId: string;
  timestamp: Date;
  analyzerId: string;                // Azure analyzer ID
  operationId: string;               // Azure operation ID
  status: 'running' | 'completed' | 'failed';
  resultBlobUrl?: string;            // Link to stored results
  metadata?: Record<string, any>;    // Custom run metadata
}
```

### Storage Architecture

#### Storage Structure (Simplified)
```
Database/Table Storage:
  ├── cases_metadata
  │   ├── {caseId}: {
  │   │     caseName: "Q4 Contract Review",
  │   │     inputFileNames: ["invoice.pdf", "contract.pdf"],
  │   │     referenceFileNames: ["template.pdf"],
  │   │     schemaName: "InvoiceContractVerification",
  │   │     createdAt: "2025-10-13T10:00:00Z",
  │   │     updatedAt: "2025-10-13T10:00:00Z",
  │   │     analysisHistory: [...]
  │   │   }
  │   └── ...

Note: 
- Files remain in existing Files tab storage
- Schemas remain in existing Schema tab storage
- Cases only store REFERENCES (names) to these existing resources
- No duplicate file storage needed
- Simpler retention: delete case = delete metadata only
```

#### Backend Storage Service
```python
# New service: case_management_service.py

class CaseManagementService:
    """Manages analysis case lifecycle and storage"""
    
    async def create_case(
        self,
        case_name: str,
        input_files: List[UploadFile],
        reference_files: List[UploadFile],
        schema_id: str,
        user_id: str,
        description: Optional[str] = None
    ) -> AnalysisCase:
        """Create new case and upload files to blob storage"""
        
    async def get_case(self, case_id: str) -> AnalysisCase:
        """Retrieve case configuration"""
        
    async def update_case(
        self,
        case_id: str,
        input_files: Optional[List[UploadFile]] = None,
        reference_files: Optional[List[UploadFile]] = None,
        schema_id: Optional[str] = None
    ) -> AnalysisCase:
        """Update case configuration (maintains version history)"""
        
    async def delete_case(self, case_id: str) -> bool:
        """Archive or delete case"""
        
    async def list_cases(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[AnalysisCase]:
        """List cases with optional filtering"""
        
    async def start_analysis_from_case(
        self,
        case_id: str
    ) -> str:
        """Start analysis using case configuration"""
        
    async def get_case_history(
        self,
        case_id: str
    ) -> List[AnalysisRun]:
        """Retrieve all analysis runs for a case"""
```

---

## 🎨 Frontend Implementation

### UI Components

#### 1. Case Selector (Similar to Quick Query Dropdown)
```tsx
<CaseSelector
  selectedCaseId={selectedCaseId}
  onCaseSelect={handleCaseSelect}
  onCreateNew={() => setShowCaseModal(true)}
  cases={availableCases}
/>
```

**Features:**
- Dropdown with search/filter
- Show: Case Name, Last Modified, Status badge
- "Create New Case" option at top
- Recent cases prioritized

#### 2. Case Management Modal
```tsx
<CaseManagementModal
  mode="create" | "edit" | "view"
  case={currentCase}
  onSave={handleSaveCase}
  onDelete={handleDeleteCase}
  onClose={handleCloseModal}
/>
```

**Tabs:**
- **Details**: Name, Description, Tags
- **Files**: Input/Reference file management
- **Schema**: Schema selection
- **History**: Previous analysis runs (view mode only)

#### 3. Enhanced Comprehensive Analysis Section
```tsx
<Card>
  <div style={{ display: 'flex', gap: 16 }}>
    {/* Case Selection */}
    <CaseSelector ... />
    
    {/* Case Actions */}
    <Button 
      icon={<EditIcon />} 
      onClick={handleEditCase}
      disabled={!selectedCaseId}
    >
      Edit Case
    </Button>
    
    <Button 
      icon={<HistoryIcon />}
      onClick={handleViewHistory}
      disabled={!selectedCaseId}
    >
      View History
    </Button>
  </div>
  
  {/* Case Summary */}
  {selectedCase && (
    <CaseSummaryCard case={selectedCase} />
  )}
  
  {/* File Update Options */}
  <Checkbox
    checked={allowFileOverride}
    onChange={setAllowFileOverride}
    label="Allow temporary file changes for this run"
  />
  
  {allowFileOverride && (
    <FileSelectionPanel
      inputFiles={tempInputFiles}
      referenceFiles={tempReferenceFiles}
      onUpdate={handleTempFileUpdate}
    />
  )}
  
  {/* Analysis Actions */}
  <div>
    <Button
      appearance="primary"
      onClick={handleStartAnalysis}
      disabled={!selectedCase}
    >
      Start Analysis
    </Button>
    
    <Button
      appearance="secondary"
      onClick={handleSaveAndAnalyze}
      disabled={!hasUnsavedChanges}
    >
      Save Changes & Analyze
    </Button>
  </div>
</Card>
```

#### 4. Case History Viewer
```tsx
<CaseHistoryPanel
  caseId={selectedCaseId}
  runs={analysisRuns}
  onRunSelect={handleViewRunResults}
  onCompareRuns={handleCompareResults}
/>
```

**Features:**
- Timeline view of all runs
- Quick access to results
- Compare results between runs
- Download/export results

### State Management (Redux)

```typescript
// New slice: casesSlice.ts

interface CasesState {
  cases: AnalysisCase[];
  selectedCaseId: string | null;
  currentCase: AnalysisCase | null;
  analysisHistory: AnalysisRun[];
  loading: boolean;
  error: string | null;
}

// Actions
export const {
  setCases,
  selectCase,
  updateCaseConfig,
  addAnalysisRun,
  clearCaseSelection
} = casesSlice.actions;

// Thunks
export const fetchCases = createAsyncThunk(...)
export const createCase = createAsyncThunk(...)
export const updateCase = createAsyncThunk(...)
export const deleteCase = createAsyncThunk(...)
export const startCaseAnalysis = createAsyncThunk(...)
```

---

## 🔌 API Endpoints

### Backend Routes

```python
# New router: case_management.py

from fastapi import APIRouter, UploadFile, Depends

router = APIRouter(prefix="/api/cases", tags=["Case Management"])

@router.post("/")
async def create_case(
    case_name: str = Form(...),
    description: str = Form(None),
    tags: List[str] = Form([]),
    input_files: List[UploadFile] = File(...),
    reference_files: List[UploadFile] = File(...),
    schema_id: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    """Create new analysis case"""

@router.get("/")
async def list_cases(
    status: Optional[str] = None,
    tags: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """List all cases for current user"""

@router.get("/{case_id}")
async def get_case(case_id: str):
    """Retrieve case details"""

@router.put("/{case_id}")
async def update_case(
    case_id: str,
    updates: CaseUpdate,
    input_files: Optional[List[UploadFile]] = File(None),
    reference_files: Optional[List[UploadFile]] = File(None)
):
    """Update case configuration"""

@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
    permanent: bool = False
):
    """Archive or permanently delete case"""

@router.post("/{case_id}/analyze")
async def start_case_analysis(
    case_id: str,
    override_schema_id: Optional[str] = None,
    temporary_file_changes: Optional[Dict] = None
):
    """Start analysis using case configuration"""

@router.get("/{case_id}/history")
async def get_case_history(case_id: str):
    """Retrieve analysis run history"""

@router.get("/{case_id}/runs/{run_id}")
async def get_run_results(case_id: str, run_id: str):
    """Retrieve specific run results"""

@router.post("/{case_id}/duplicate")
async def duplicate_case(
    case_id: str,
    new_name: str
):
    """Create copy of existing case"""
```

---

## 🔄 User Workflow

### Creating a New Case
1. User clicks "Create New Case" in comprehensive analysis section
2. Modal opens with form:
   - **Enter Case ID/Number** (required, user-defined, e.g., "CASE-001", "Q4-Contract-Review")
   - **Enter Case Name** (required, descriptive name)
   - **Add description** (optional)
3. **Select input files** from Files tab dropdown (files already uploaded)
4. **Select reference files** from Files tab dropdown (files already uploaded)
5. **Select schema** from Schema tab dropdown (schemas already created)
6. Click "Save Case"
7. Case appears in dropdown for future use

**Note**: Files and schemas must already exist in their respective tabs - cases only store references.

### Using an Existing Case
1. **Select case** from dropdown (shows Case ID and Name)
2. **Case summary displayed** showing:
   - Case ID and name
   - Description
   - Input file names (from Files tab)
   - Reference file names (from Files tab)
   - Schema name (from Schema tab)
   - Last run date/time
3. **Start Analysis**:
   - System automatically selects the referenced files from Files tab
   - System automatically selects the referenced schema from Schema tab
   - Click "Start Analysis" button
   - Analysis runs with current versions of the files/schema

### Editing a Case
1. Select case and click "Edit Case"
2. Modal opens in edit mode
3. Modify any configuration:
   - Update name/description
   - Add/remove files
   - Change schema
4. Changes saved with timestamp
5. Option to start analysis immediately

### Viewing Case History
1. Select case and click "View History"
2. Panel shows:
   - Timeline of all analysis runs
   - Status of each run
   - Link to results
3. Can select any run to view results
4. Compare feature to see differences between runs

---

## 🚀 Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] Backend: Case management service
- [ ] Backend: Blob storage integration
- [ ] Backend: API endpoints (create, read, update, delete)
- [ ] Database: Case metadata storage
- [ ] Frontend: Basic Redux slice

### Phase 2: UI Components (Week 2-3)
- [ ] Case selector dropdown
- [ ] Case creation modal
- [ ] Case edit modal
- [ ] Case summary card
- [ ] Integration with comprehensive analysis section

### Phase 3: Analysis Integration (Week 3-4)
- [ ] Connect case selection to analysis start
- [ ] Handle temporary file overrides
- [ ] Store analysis run history
- [ ] Link results to cases

### Phase 4: Advanced Features (Week 4-5)
- [ ] Case history viewer
- [ ] Result comparison
- [ ] Case duplication
- [ ] Search & filter
- [ ] Tag management
- [ ] Export/import cases

### Phase 5: Polish & Optimization (Week 5-6)
- [ ] Performance optimization
- [ ] Caching strategy
- [ ] UI/UX refinements
- [ ] Error handling
- [ ] Documentation
- [ ] User testing

---

## 🔒 Security Considerations

### Access Control
- **Organization-wide access**: All users can view, edit, and delete any case
- **Simple audit trail**: Track who created/modified each case (for reference only)
- **No permission layers**: Universal access model for simplicity

### Data Protection
- **No file storage in cases**: Files remain in their original locations (Files tab)
- **Metadata only**: Case database stores configuration references only
- **Simple retention**: Delete case = delete metadata only (files unaffected)
- **Audit logs**: Track case creation, modification, deletion

### Validation
- File size limits
- File type restrictions
- Schema validation
- Input sanitization

---

## 📊 Monitoring & Analytics

### Metrics to Track
- Number of cases created per user/organization
- Most used cases
- Average analysis runs per case
- Case reuse rate
- File storage utilization
- API performance

### User Analytics
- Feature adoption rate
- Most common workflows
- Pain points (abandoned case creations)
- Time saved vs. manual configuration

---

## 🎓 Documentation & Training

### User Documentation
- **Quick Start Guide**: Create your first case
- **Best Practices**: Naming conventions, organization
- **Video Tutorials**: Common workflows
- **FAQ**: Troubleshooting

### Developer Documentation
- API reference
- Data model specification
- Storage architecture
- Integration guide

---

## 🔮 Future Enhancements

### V2 Features
- **Case Templates**: Pre-configured templates for common scenarios
- **Batch Analysis**: Run multiple cases at once
- **Scheduled Analysis**: Automatic periodic runs
- **Case Workflows**: Multi-step analysis pipelines
- **Collaboration**: Share cases with team members
- **Version Control**: Git-like branching for cases
- **Smart Recommendations**: AI-suggested similar cases
- **Result Dashboards**: Aggregate insights across cases

### Integrations
- Export to Power BI
- Webhook notifications
- Third-party storage (S3, GCS)
- CI/CD pipeline integration

---

## 💡 Implementation Tips

### Backend
1. Use Azure Table Storage for case metadata (fast lookup)
2. Implement soft delete for cases (archive first)
3. Use optimistic locking for concurrent updates
4. Add caching layer for frequently accessed cases
5. Implement pagination for case lists

### Frontend
1. Debounce search/filter operations
2. Lazy load case history
3. Cache case list in Redux
4. Optimistic UI updates
5. Implement infinite scroll for large case lists

### Testing
1. Unit tests for case CRUD operations
2. Integration tests for analysis workflow
3. E2E tests for complete user journeys
4. Load testing for concurrent case operations
5. Storage stress testing

---

## 📝 Migration Strategy

### For Existing Users
1. **Initial Release**: Case management optional (comprehensive analysis still works standalone)
2. **"Save as Case" Button**: Convert current configuration to case
3. **Auto-save**: Prompt to save frequently used configurations
4. **Gradual Migration**: Incentivize case usage with benefits (history, reuse, etc.)
5. **No Breaking Changes**: Existing workflows remain functional

---

## ✅ Success Criteria

### Technical
- [ ] Sub-second case retrieval
- [ ] Support 1000+ cases per user
- [ ] 99.9% API uptime
- [ ] Concurrent case analysis support

### User Experience
- [ ] < 30 seconds to create first case
- [ ] 50%+ adoption rate within 3 months
- [ ] 4.5+ star user satisfaction rating
- [ ] 30%+ reduction in analysis setup time

### Business
- [ ] Increased user engagement
- [ ] Reduced support tickets
- [ ] Higher feature utilization
- [ ] Positive user feedback

---

## 🤝 Stakeholder Alignment

### Product Team
- Aligns with organizational workflow needs
- Differentiates from competitors
- Opens new use case opportunities

### Engineering Team
- Clean architecture with clear separation of concerns
- Reusable components and services
- Scalable storage solution

### Users
- Saves time and reduces repetitive work
- Better organization and management
- Professional audit trail

---

This design provides a comprehensive, production-ready approach to implementing case management for your analysis system. The phased approach ensures incremental value delivery while maintaining system stability.
