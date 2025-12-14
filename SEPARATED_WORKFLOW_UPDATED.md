# Separated Quick Query & Schema Generation - Updated Workflow

**Date**: November 10, 2025  
**Decision**: Separate Quick Query (fast) from Schema Generation (thorough) based on performance analysis  
**Rationale**: Quick Query = 60-90s, Schema Generation with 7-dimension = 3-5min  

---

## Architecture Decision

### Original Proposal (Nov 9, 2025)
- Single API call with GeneratedSchema field in Quick Query schema
- **Problem**: Makes Quick Query slow (3-5 minutes)
- **Breaks**: The "quick" promise of Quick Query

### Updated Approach (Nov 10, 2025)
- **Two separate API calls**
- Quick Query: Fast analysis (60-90s)
- Schema Generation: Thorough analysis (3-5min)

---

## Workflow Comparison

### Quick Query Workflow (UNCHANGED - Stays Fast)

```
User Action:
┌──────────────────────────────────────┐
│ Quick Query Tab                      │
├──────────────────────────────────────┤
│ Prompt: [Find payment discrepancies] │
│ Document: [invoice.pdf]              │
│                                      │
│ [Quick Inquiry] ← Click              │
└──────────────────────────────────────┘
                 ↓
Backend Processing (60-90 seconds):
┌──────────────────────────────────────┐
│ 1. Upload document to blob storage   │
│ 2. Create/use Quick Query analyzer   │
│ 3. Analyze with simple schema:       │
│    - Summary field                   │
│    - KeyFindings array               │
│ 4. Return results                    │
└──────────────────────────────────────┘
                 ↓
User Sees Results:
┌──────────────────────────────────────┐
│ ✓ Found 3 payment discrepancies      │
│   • Amount: $5,000 difference        │
│   • Due date: 15 days mismatch       │
│   • Missing: Office supplies         │
│                                      │
│ [Try Another Prompt] [Save as Schema]│
└──────────────────────────────────────┘
```

**Key Point**: Quick Query schema does NOT include GeneratedSchema field → Stays fast!

---

### Schema Generation Workflow (NEW - Separate Call)

```
User Action:
┌──────────────────────────────────────┐
│ User satisfied with Quick Query      │
│ Clicks: [Save as Schema]             │
└──────────────────────────────────────┘
                 ↓
Backend Processing (3-5 minutes):
┌──────────────────────────────────────┐
│ API: POST /api/schemas/generate      │
│                                      │
│ Function: _generate_schema_with_ai_self_correction() │
│                                      │
│ 1. Get blob URL from Quick Query     │
│    (document already uploaded)       │
│                                      │
│ 2. Create NEW analyzer with:         │
│    - GeneratedSchema field           │
│    - 7-dimension enhancement prompt  │
│                                      │
│ 3. Poll analyzer creation            │
│    Status: "Creating analyzer..."    │
│                                      │
│ 4. Analyze document (blob URL)       │
│    Status: "Step 1/3: Initial analysis..." │
│    Status: "Step 2/3: Name optimization..." │
│    Status: "Step 3/3: Quality enhancement..." │
│                                      │
│ 5. Poll analysis results             │
│    Status: "Finalizing schema..."    │
│                                      │
│ 6. Parse GeneratedSchema             │
│    Status: "Schema ready!"           │
└──────────────────────────────────────┘
                 ↓
User Sees Schema:
┌──────────────────────────────────────┐
│ Schema Preview                       │
├──────────────────────────────────────┤
│ Name: InvoiceContractVerificationSchema │
│ Description: Finds payment discrepancies... │
│                                      │
│ Fields (10):                         │
│ • AllInconsistencies (array)         │
│   - Category, Severity, Evidence...  │
│ • InconsistencySummary (object)      │
│   - TotalCount, KeyFindings...       │
│                                      │
│ [Edit Schema] [Save to Library]      │
└──────────────────────────────────────┘
```

**Key Point**: Separate API call → User knows it's thorough (3-5min acceptable)

---

## Frontend Changes Required

### 1. Quick Query Tab (Minor Update)

**Before**:
```typescript
// After Quick Query completes
showResults(results);
showButton("Review & Save as Schema");
```

**After**:
```typescript
// After Quick Query completes
showResults(results);
showButton("Save as Schema"); // Renamed, clearer action

// Store blob URL for schema generation
sessionStorage.setItem('quickQueryBlobUrl', blobUrl);
sessionStorage.setItem('quickQueryPrompt', userPrompt);
```

### 2. Schema Generation Modal (NEW)

```typescript
async function generateSchemaFromQuickQuery() {
  // Get stored data
  const blobUrl = sessionStorage.getItem('quickQueryBlobUrl');
  const prompt = sessionStorage.getItem('quickQueryPrompt');
  
  // Show modal with progress
  const modal = showModal({
    title: "Generating Production-Quality Schema",
    message: "Creating schema with 7-dimension quality enhancement...",
    showProgress: true,
    estimatedTime: "3-5 minutes"
  });
  
  try {
    // Call backend API
    const response = await fetch('/api/schemas/generate', {
      method: 'POST',
      body: JSON.stringify({
        query: prompt,
        sample_document_url: blobUrl
      })
    });
    
    // Poll for progress
    const pollUrl = response.headers.get('Operation-Location');
    const schema = await pollSchemaGeneration(pollUrl, (progress) => {
      modal.updateProgress(progress.step, progress.message);
    });
    
    // Show schema preview
    modal.close();
    showSchemaPreview(schema);
    
  } catch (error) {
    modal.close();
    showError("Schema generation failed", error);
  }
}
```

### 3. Progress Updates

```typescript
function updateProgress(step, message) {
  const steps = {
    'analyzer_creating': { step: 1, total: 3, message: 'Creating analyzer...' },
    'analyzer_ready': { step: 1, total: 3, message: 'Analyzer ready ✓' },
    'analysis_started': { step: 2, total: 3, message: 'Analyzing document...' },
    'step_1_complete': { step: 2, total: 3, message: 'Step 1/3: Initial analysis ✓' },
    'step_2_complete': { step: 2, total: 3, message: 'Step 2/3: Name optimization ✓' },
    'step_3_complete': { step: 3, total: 3, message: 'Step 3/3: Quality enhancement ✓' },
    'parsing_schema': { step: 3, total: 3, message: 'Finalizing schema...' },
    'complete': { step: 3, total: 3, message: 'Schema ready! ✓' }
  };
  
  const progress = steps[step] || { step: 1, total: 3, message };
  updateProgressBar(progress.step, progress.total, progress.message);
}
```

---

## Backend Changes Required

### 1. Quick Query Endpoint (NO CHANGE)

```python
@app.route('/api/quick-query', methods=['POST'])
def quick_query():
    """Fast analysis - NO GeneratedSchema field"""
    
    # Upload document to blob
    blob_url = upload_to_blob(file)
    
    # Quick Query schema (SIMPLE - keeps it fast)
    schema = {
        "fields": {
            "Summary": {
                "type": "string",
                "method": "generate",
                "description": user_prompt
            },
            "KeyFindings": {
                "type": "array",
                "method": "generate",
                "description": f"Key findings for: {user_prompt}"
            }
        }
    }
    
    # Analyze (60-90 seconds)
    result = analyze_document(schema, blob_url)
    
    # Return results + blob URL for schema generation
    return {
        "results": result,
        "blob_url": blob_url,  # NEW: for schema generation
        "prompt": user_prompt  # NEW: for schema generation
    }
```

### 2. Schema Generation Endpoint (NEW)

```python
@app.route('/api/schemas/generate', methods=['POST'])
def generate_schema():
    """
    Generate production-quality schema with 7-dimension enhancement.
    Separate from Quick Query - takes 3-5 minutes.
    """
    data = request.json
    query = data['query']
    blob_url = data['sample_document_url']  # From Quick Query
    
    # Use existing implementation
    generator = QuerySchemaGenerator()
    
    # This method already has 7-dimension enhancement
    schema = generator._generate_schema_with_ai_self_correction(
        query=query,
        sample_document_path=blob_url  # Blob URL from Quick Query
    )
    
    return {
        "schema": schema,
        "quality_score": assess_schema_quality(schema),
        "generated_at": datetime.now().isoformat()
    }
```

### 3. Progress Polling Endpoint (NEW)

```python
@app.route('/api/schemas/generate/status/<operation_id>', methods=['GET'])
def get_generation_status(operation_id):
    """
    Poll schema generation progress.
    Returns current step and status message.
    """
    # Check Azure Operation-Location
    status = poll_azure_operation(operation_id)
    
    # Map Azure status to user-friendly progress
    progress = {
        "Succeeded": {"step": "complete", "message": "Schema ready!"},
        "Running": {"step": "analysis_running", "message": "Analyzing document..."},
        "NotStarted": {"step": "analyzer_creating", "message": "Creating analyzer..."}
    }
    
    return progress.get(status['status'], {"step": "unknown", "message": "Processing..."})
```

---

## User Experience Comparison

### Quick Query (Fast Experimental Mode)
- **Duration**: 60-90 seconds
- **Purpose**: Test different prompts quickly
- **Output**: Summary and key findings
- **User can**: Try multiple prompts rapidly
- **Expectation**: "Quick" feedback

### Schema Generation (Thorough Production Mode)
- **Duration**: 3-5 minutes
- **Purpose**: Create production-quality reusable schema
- **Output**: Complete schema with 7-dimension quality
- **User does**: Wait once for high-quality result
- **Expectation**: "Thorough" quality worth the wait

---

## Benefits of Separation

### 1. Performance
- ✅ Quick Query stays quick (60-90s)
- ✅ Schema generation gets full time needed (3-5min)
- ✅ No performance compromise on either

### 2. User Experience
- ✅ Clear expectations (quick vs thorough)
- ✅ Progress feedback for long operation
- ✅ Can test many prompts quickly
- ✅ Only generate schema when committed

### 3. Resource Efficiency
- ✅ Don't run expensive 7-dimension for every test
- ✅ Reuse blob URL (no re-upload)
- ✅ Can cache Quick Query analyzers

### 4. Scalability
- ✅ Independent optimization paths
- ✅ Can add features to either without affecting other
- ✅ Future: Quick Query could use lighter models

---

## Implementation Priority

### Phase 1: Backend (Already Done ✅)
- ✅ `_generate_schema_with_ai_self_correction()` with 7-dimension enhancement
- ✅ Accepts blob URL parameter
- ⚠️ Need to add: `/api/schemas/generate` endpoint

### Phase 2: Frontend (To Do)
- 📋 Update Quick Query to store blob URL + prompt
- 📋 Create schema generation modal with progress
- 📋 Add polling for generation status
- 📋 Show schema preview

### Phase 3: Testing
- 📋 Test Quick Query still fast (60-90s)
- 📋 Test schema generation with 7-dimension (3-5min)
- 📋 Verify quality score 6-7/7
- 📋 User acceptance testing

---

## Timeline Estimate

- **Backend endpoint**: 2 hours
- **Frontend modal + polling**: 4 hours
- **Integration testing**: 2 hours
- **Total**: ~1 day

---

## Success Metrics

### Quick Query
- ✅ < 2 minutes response time
- ✅ Users can test 5+ prompts in 10 minutes
- ✅ High satisfaction with speed

### Schema Generation
- ✅ 3-5 minute generation time (acceptable)
- ✅ Quality score 6-7/7 dimensions
- ✅ 90%+ schemas usable without manual editing
- ✅ User satisfaction with thoroughness

---

## Conclusion

**Decision**: Implement as TWO separate API calls

**Justification**: 
- Preserves Quick Query speed (60-90s)
- Allows Schema Generation thoroughness (3-5min)
- Clear user expectations for each mode
- Better resource utilization

**Next Steps**:
1. Create `/api/schemas/generate` endpoint
2. Build frontend modal with progress
3. Test end-to-end workflow
4. Validate 7-dimension quality

