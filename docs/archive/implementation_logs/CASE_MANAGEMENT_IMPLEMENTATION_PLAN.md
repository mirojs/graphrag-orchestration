# 🚀 Case Management Implementation Plan (Simplified)

## Overview
Implement a lightweight case management system for the Comprehensive Analysis section that stores only metadata references to existing files and schemas.

---

## 🎯 Simplified Requirements

### What Cases Store
- ✅ Case ID (user-defined)
- ✅ Case Name (user-defined)
- ✅ Description (optional)
- ✅ Input file names (references to Files tab)
- ✅ Reference file names (references to Files tab)
- ✅ Schema name (reference to Schema tab)
- ✅ Analysis history (run records)
- ✅ Timestamps (created/updated)
- ✅ Creator info (audit only)

### What Cases DON'T Store
- ❌ Actual files (use existing Files tab)
- ❌ Actual schemas (use existing Schema tab)
- ❌ Permissions (organization-wide access)
- ❌ Tags/categories (keep it simple)

---

## 📊 Database Schema

### Table: `analysis_cases`

```sql
CREATE TABLE analysis_cases (
    case_id VARCHAR(255) PRIMARY KEY,
    case_name VARCHAR(500) NOT NULL,
    description TEXT,
    input_file_names JSON NOT NULL,      -- Array of file names
    reference_file_names JSON NOT NULL,  -- Array of file names
    schema_name VARCHAR(255) NOT NULL,
    analysis_history JSON,                -- Array of run records
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    INDEX idx_case_name (case_name),
    INDEX idx_created_at (created_at),
    INDEX idx_updated_at (updated_at)
);
```

### Example Record
```json
{
  "case_id": "CASE-Q4-2025-001",
  "case_name": "Q4 Contract Compliance Review",
  "description": "Monthly contract verification for Q4 2025",
  "input_file_names": ["invoice_oct_2025.pdf", "contract_vendor_a.pdf"],
  "reference_file_names": ["template_standard.pdf"],
  "schema_name": "InvoiceContractVerification",
  "analysis_history": [
    {
      "run_id": "run_001",
      "timestamp": "2025-10-13T10:00:00Z",
      "analyzer_id": "az123",
      "operation_id": "op456",
      "status": "completed"
    }
  ],
  "created_at": "2025-10-13T09:00:00Z",
  "updated_at": "2025-10-13T10:05:00Z",
  "created_by": "user@example.com"
}
```

---

## 🏗️ Implementation Steps

### Step 1: Backend - Database Model
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/models/case_model.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class AnalysisRun(BaseModel):
    run_id: str
    timestamp: datetime
    analyzer_id: Optional[str] = None
    operation_id: Optional[str] = None
    status: str  # 'running', 'completed', 'failed'
    result_summary: Optional[dict] = None

class AnalysisCase(BaseModel):
    case_id: str = Field(..., description="User-defined case identifier")
    case_name: str = Field(..., description="Descriptive case name")
    description: Optional[str] = None
    input_file_names: List[str] = Field(default_factory=list)
    reference_file_names: List[str] = Field(default_factory=list)
    schema_name: str
    analysis_history: List[AnalysisRun] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str

class CaseCreateRequest(BaseModel):
    case_id: str
    case_name: str
    description: Optional[str] = None
    input_file_names: List[str]
    reference_file_names: List[str]
    schema_name: str

class CaseUpdateRequest(BaseModel):
    case_name: Optional[str] = None
    description: Optional[str] = None
    input_file_names: Optional[List[str]] = None
    reference_file_names: Optional[List[str]] = None
    schema_name: Optional[str] = None
```

### Step 2: Backend - Database Service
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/services/case_service.py`

### Step 3: Backend - API Routes
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/case_management.py`

### Step 4: Frontend - Redux State
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/redux/slices/casesSlice.ts`

### Step 5: Frontend - Case Selector Component
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/CaseManagement/CaseSelector.tsx`

### Step 6: Frontend - Case Management Modal
**File**: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/CaseManagement/CaseManagementModal.tsx`

### Step 7: Frontend - Integration with PredictionTab
**Update**: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`

---

## 🔌 API Endpoints

```
POST   /api/cases                    # Create new case
GET    /api/cases                    # List all cases
GET    /api/cases/{case_id}          # Get case details
PUT    /api/cases/{case_id}          # Update case
DELETE /api/cases/{case_id}          # Delete case
POST   /api/cases/{case_id}/analyze  # Start analysis from case
GET    /api/cases/{case_id}/history  # Get analysis history
```

---

## 🎨 UI Workflow

### Comprehensive Analysis Section Layout

```
┌─────────────────────────────────────────────────────────┐
│  📋 Comprehensive Analysis                               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  🔍 Case Management                                      │
│  ┌────────────────────────────────────────────────┐    │
│  │ Select Case:  [Dropdown: CASE-Q4-2025-001 ▼] │    │
│  │                                                 │    │
│  │ [➕ Create New]  [✏️ Edit]  [🗑️ Delete]        │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  📊 Case Summary (when case selected)                   │
│  ┌────────────────────────────────────────────────┐    │
│  │ Case: Q4 Contract Compliance Review            │    │
│  │ ID: CASE-Q4-2025-001                           │    │
│  │                                                 │    │
│  │ Input Files (2):                               │    │
│  │  • invoice_oct_2025.pdf                        │    │
│  │  • contract_vendor_a.pdf                       │    │
│  │                                                 │    │
│  │ Reference Files (1):                           │    │
│  │  • template_standard.pdf                       │    │
│  │                                                 │    │
│  │ Schema: InvoiceContractVerification            │    │
│  │                                                 │    │
│  │ Last Run: Oct 13, 2025 10:00 AM               │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  ⚙️ Analysis Actions                                     │
│  [▶️ Start Analysis]  [📊 View History]                │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Create/Edit Case Modal

```
┌─────────────────────────────────────────────────┐
│  ➕ Create New Case                   [✖️]      │
├─────────────────────────────────────────────────┤
│                                                  │
│  Case ID: [________________]  (e.g., CASE-001) │
│                                                  │
│  Case Name: [_____________________________]     │
│                                                  │
│  Description (optional):                        │
│  [____________________________________________] │
│  [____________________________________________] │
│                                                  │
│  Input Files (from Files tab):                 │
│  [✓] invoice_oct_2025.pdf                      │
│  [✓] contract_vendor_a.pdf                     │
│  [ ] other_document.pdf                        │
│                                                  │
│  Reference Files (from Files tab):             │
│  [✓] template_standard.pdf                     │
│  [ ] reference_doc_2.pdf                       │
│                                                  │
│  Schema (from Schema tab):                     │
│  [InvoiceContractVerification ▼]               │
│                                                  │
│  [Cancel]              [Save Case]              │
└─────────────────────────────────────────────────┘
```

---

## 🔄 Integration with Existing System

### When User Selects a Case:
1. Fetch case metadata from database
2. **Automatically populate** the file selection in PredictionTab:
   - Set `selectedInputFiles` to match `case.input_file_names`
   - Set `selectedReferenceFiles` to match `case.reference_file_names`
3. **Automatically select schema** in Schema tab:
   - Set `selectedSchema` to match `case.schema_name`
4. User can immediately click "Start Analysis"

### When Analysis Completes:
1. Create new `AnalysisRun` record
2. Add to `case.analysis_history`
3. Update `case.updated_at`
4. Save to database

### File/Schema Validation:
- Before starting analysis, verify that:
  - All referenced files exist in Files tab
  - Referenced schema exists in Schema tab
- If missing, show warning: "Some files or schema no longer exist. Please update case."

---

## 📝 Database Setup Script

**File**: `code/content-processing-solution-accelerator/database/migrations/create_analysis_cases_table.sql`

```sql
-- Create analysis_cases table for case management
CREATE TABLE IF NOT EXISTS analysis_cases (
    case_id VARCHAR(255) PRIMARY KEY,
    case_name VARCHAR(500) NOT NULL,
    description TEXT,
    input_file_names JSON NOT NULL,
    reference_file_names JSON NOT NULL,
    schema_name VARCHAR(255) NOT NULL,
    analysis_history JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    
    INDEX idx_case_name (case_name),
    INDEX idx_created_at (created_at),
    INDEX idx_updated_at (updated_at)
);
```

---

## ✅ Testing Checklist

### Backend Tests
- [ ] Create case with valid data
- [ ] Create case with duplicate ID (should fail)
- [ ] Get case by ID
- [ ] List all cases
- [ ] Update case configuration
- [ ] Delete case
- [ ] Start analysis from case
- [ ] Add run to case history

### Frontend Tests
- [ ] Display case dropdown
- [ ] Create new case via modal
- [ ] Edit existing case
- [ ] Delete case with confirmation
- [ ] Select case and auto-populate files/schema
- [ ] Start analysis from selected case
- [ ] View case history
- [ ] Handle missing files/schema gracefully

### Integration Tests
- [ ] Complete workflow: Create → Select → Analyze
- [ ] Update case and re-run analysis
- [ ] Multiple sequential analyses on same case
- [ ] Case with non-existent files (error handling)

---

## 🎯 Success Metrics

- [ ] Cases load in < 500ms
- [ ] Case selection auto-populates correctly
- [ ] Analysis starts without manual file selection
- [ ] Case history tracking works
- [ ] UI is intuitive and responsive

---

## 🚀 Deployment Steps

1. **Database Migration**
   ```bash
   # Run migration script
   mysql -u user -p database < create_analysis_cases_table.sql
   ```

2. **Backend Deployment**
   - Deploy new case management service
   - Deploy new API routes
   - Update environment config

3. **Frontend Deployment**
   - Build frontend with new components
   - Deploy updated UI
   - Clear browser cache

4. **User Communication**
   - Release notes
   - Quick start guide
   - Demo video

---

## 📚 Next Steps

Once basic implementation is complete:

1. **Enhanced Search**: Filter cases by name, date range
2. **Case Duplication**: Clone existing cases
3. **Export/Import**: Backup cases as JSON
4. **Analytics**: Most used cases, success rates
5. **Batch Operations**: Run multiple cases at once

---

This simplified design ensures quick implementation while providing maximum value to users!
