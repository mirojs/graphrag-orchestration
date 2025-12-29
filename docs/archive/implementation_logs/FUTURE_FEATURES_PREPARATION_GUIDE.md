# Preparing for Training Data & Reference Documents Support

## Current State Analysis ✅

### What's Already in Place:

1. **Training Data Support** (Lines 4836-4850 in proMode.py)
   ```python
   # OPTIONAL: Add trainingData configuration if available
   training_data_container = getattr(app_config, "app_training_data_container_url", None)
   if training_data_container and training_data_container.strip():
       official_payload["trainingData"] = {
           "kind": "blob",
           "containerUrl": training_data_container,
           "prefix": "trainingData",
           "fileListPath": "trainingData/fileList.jsonl"
       }
   ```
   **Status**: ✅ Infrastructure ready, just needs config

2. **Knowledge Sources (Reference Documents) Support** (Lines 3081-3140 in proMode.py)
   ```python
   def configure_knowledge_sources(payload: dict, official_payload: dict, app_config):
       # Currently sets: official_payload["knowledgeSources"] = []
       # But infrastructure to process reference files exists
   ```
   **Status**: ✅ Infrastructure ready, intentionally disabled

3. **Analyzer Creation with Conditional Polling** (Lines 5345-5365)
   ```python
   operation_location = response.headers.get('operation-location')
   if operation_location:
       # Currently returns immediately
       # But track_analyzer_operation function exists (line 1686)
   ```
   **Status**: ✅ Polling function exists, ready to re-enable

## What Needs To Change When You Enable These Features

### Option 1: Minimal Changes (Recommended for Initial Testing)

Just enable the polling when training data or reference docs are present:

```python
# Around line 5345-5365 in proMode.py
operation_location = response.headers.get('operation-location')
if operation_location:
    # Check if we have training data or knowledge sources
    has_training_data = 'trainingData' in official_payload
    has_knowledge_sources = ('knowledgeSources' in official_payload and 
                             len(official_payload.get('knowledgeSources', [])) > 0)
    
    if has_training_data or has_knowledge_sources:
        print(f"[AnalyzerCreate] 🔄 Background processing required")
        print(f"[AnalyzerCreate] Training data: {'YES' if has_training_data else 'NO'}")
        print(f"[AnalyzerCreate] Knowledge sources: {len(official_payload.get('knowledgeSources', []))} sources")
        print(f"[AnalyzerCreate] ⏳ Polling operation status until ready...")
        
        # Poll the operation until complete
        operation_result = await track_analyzer_operation(operation_location, headers)
        
        result['operation_tracking'] = {
            'status': operation_result.get('status', 'unknown'),
            'operation_location': operation_location,
            'note': 'Background processing completed for training data/reference documents'
        }
    else:
        # No background work - immediate return
        print(f"[AnalyzerCreate] ⚡ No background processing needed")
        result['operation_tracking'] = {
            'status': 'ready',
            'operation_location': operation_location,
            'note': 'Analyzer is immediately usable'
        }
else:
    print(f"[AnalyzerCreate] ✅ Analyzer created successfully")

return result
```

### Option 2: Full Feature Implementation

#### 1. Training Data Configuration

**Backend Config (app_config)**:
```python
# Add to your configuration
app_training_data_container_url = "https://<storage>.blob.core.windows.net/<container>?<sas>"
```

**What This Enables**:
- Analyzer learns from your labeled samples
- Better field extraction accuracy
- Custom patterns specific to your documents

**When to Use**:
- You have labeled training samples (documents with annotations)
- You want to improve extraction accuracy for specific document types
- You're processing standardized forms with consistent layouts

#### 2. Reference Documents (Knowledge Sources)

**Enable in `configure_knowledge_sources`** (line 3081):
```python
def configure_knowledge_sources(payload: dict, official_payload: dict, app_config) -> None:
    selected_reference_files = payload.get('selectedReferenceFiles', []) if payload else []
    
    if selected_reference_files:
        # Build knowledge sources from reference files
        knowledge_sources = []
        
        for ref_file_id in selected_reference_files:
            # Get file info from your storage
            file_info = get_reference_file_info(ref_file_id, app_config)
            
            knowledge_source = {
                "kind": "reference",
                "containerUrl": app_config.reference_docs_container_url,
                "prefix": file_info['prefix'],
                "fileListPath": f"{file_info['prefix']}/sources.jsonl"
            }
            knowledge_sources.append(knowledge_source)
        
        official_payload["knowledgeSources"] = knowledge_sources
        print(f"[AnalyzerCreate] ✅ Added {len(knowledge_sources)} knowledge sources")
    else:
        official_payload["knowledgeSources"] = []
```

**What This Enables**:
- Pro mode cross-document reasoning
- Contract validation against policies
- Compliance checking against regulations
- Contextual analysis using reference materials

**When to Use**:
- You need to validate documents against policies/contracts
- Cross-referencing multiple documents
- Compliance checking scenarios
- Documents need context from reference materials

## Required Configuration Updates

### Environment/Config Variables to Add:

```python
# For Training Data
app_training_data_container_url: str = "https://<storage-account>.blob.core.windows.net/<container>?<sas-token>"
app_training_data_path_prefix: str = "training_files/"

# For Reference Documents (Pro Mode)
app_reference_docs_container_url: str = "https://<storage-account>.blob.core.windows.net/<container>?<sas-token>"
app_reference_docs_path_prefix: str = "reference_docs/"
```

### Azure Blob Storage Setup:

1. **Create Blob Containers**:
   - Training data container (for labeled samples)
   - Reference docs container (for knowledge base)

2. **Container Structure**:
   ```
   training_files/
   ├── fileList.jsonl              # List of training files
   ├── invoice_001.pdf             # Training document
   ├── invoice_001.pdf.labels.json # Annotations
   ├── invoice_001.pdf.result.json # OCR results
   └── ...

   reference_docs/
   ├── sources.jsonl               # List of reference docs
   ├── contract_template.pdf       # Reference document
   ├── contract_template.pdf.result.json
   ├── policy_guidelines.pdf
   └── ...
   ```

3. **Generate SAS Tokens** with:
   - Read permission
   - Write permission (for uploading)
   - List permission
   - Expiry date set appropriately

## Testing Strategy

### Phase 1: Simple Schema Only (Current - Working ✅)
```
Schema → Analyzer → Analysis
No training, no references
Returns immediately (< 1 second)
```

### Phase 2: Add Training Data
```
Schema + Training Data → Analyzer → Analysis
Poll until training complete (1-5 minutes)
Test with small training set first
```

### Phase 3: Add Reference Documents
```
Schema + Reference Docs → Analyzer → Analysis
Poll until indexing complete (2-10 minutes)
Test with 1-2 reference docs first
```

### Phase 4: Combined
```
Schema + Training + Reference → Analyzer → Analysis
Poll until all processing complete
Full production setup
```

## Monitoring & Debugging

### Key Logs to Watch:

When training data/reference docs are enabled:

```python
# You'll see these in logs:
[AnalyzerCreate] ✓ Added trainingData configuration to payload
[AnalyzerCreate] ✅ Added 3 knowledge sources
[AnalyzerCreate] 🔄 Background processing required
[AnalyzerCreate] ⏳ Polling operation status until ready...
[OperationTracker] Attempt 1: Status code 200, Body: {"status": "running"}
[OperationTracker] Attempt 2: Status code 200, Body: {"status": "running"}
...
[OperationTracker] Attempt N: Status code 200, Body: {"status": "succeeded"}
[AnalyzerCreate] ✅ Background processing completed
```

### Expected Timing:

| Feature | Processing Time | What's Happening |
|---------|----------------|------------------|
| Simple schema | < 1 second | Immediate creation |
| + Training data (5 docs) | 1-2 minutes | Learning patterns |
| + Training data (50 docs) | 3-5 minutes | Deep learning |
| + Reference docs (3 files) | 2-4 minutes | OCR + indexing |
| + Reference docs (20 files) | 5-10 minutes | Full knowledge base |
| Combined (training + refs) | 5-15 minutes | All processing |

## Code Changes Needed: Summary

### ✅ No Changes Required:
- Infrastructure is ready
- Polling function exists
- Config placeholders exist
- Data structures correct

### 🔧 Changes to Make When Ready:

**1. Update `create_or_replace_content_analyzer` (line ~5345)**:
```python
# Add conditional polling logic (see Option 1 above)
```

**2. Update `configure_knowledge_sources` (line ~3081)**:
```python
# Change from: official_payload["knowledgeSources"] = []
# To: Build actual knowledge sources from selected files
```

**3. Add configuration**:
```python
# Add to AppConfiguration or environment
app_training_data_container_url = "..."
app_reference_docs_container_url = "..."
```

**4. Optional: Update UI**:
```typescript
// Show progress indicator during background processing
// Display estimated wait time based on feature usage
```

## Decision Points

### When to Poll:
```python
should_poll = (
    'trainingData' in official_payload or
    (operation_location and len(official_payload.get('knowledgeSources', [])) > 0)
)
```

### Timeout Settings:
```python
# Simple schema: No timeout needed (immediate)
# Training data: 300 seconds (5 minutes)
# Reference docs: 600 seconds (10 minutes)
# Combined: 900 seconds (15 minutes)
```

## Recommendations

### For Initial Implementation:
1. ✅ **Keep current code as-is** - it works perfectly for simple schemas
2. 🔧 **Add conditional polling** - only when features are enabled
3. 📊 **Start with training data** - easier to test, faster processing
4. 📚 **Then add reference docs** - more complex, longer processing
5. 🧪 **Test incrementally** - small datasets first, scale up gradually

### For Production:
1. **Monitor operation times** - adjust timeouts based on real data
2. **Implement retry logic** - for transient failures
3. **Add user notifications** - "Processing... this may take several minutes"
4. **Consider async workflows** - for very large training/reference sets
5. **Cache analyzers** - if reusing same training/reference data

## Risk Assessment

### Low Risk ✅:
- Infrastructure already exists
- No breaking changes needed
- Backward compatible (simple schemas still work)
- Can enable feature-by-feature

### Medium Risk ⚠️:
- Increased wait times when features enabled
- Need user communication about delays
- Timeout tuning may be needed

### High Risk ❌:
- **None** - Changes are additive, not destructive

## Conclusion

**You don't need to update code NOW.** Everything is already in place and ready for when you decide to enable these features:

✅ **Training data infrastructure**: Ready, just needs config
✅ **Reference docs infrastructure**: Ready, intentionally disabled
✅ **Polling mechanism**: Exists, just needs conditional activation
✅ **Current simple schema flow**: Working perfectly, won't break

**When you're ready to enable**:
1. Add configuration (storage URLs)
2. Enable conditional polling (small code change)
3. Enable knowledge sources (small code change)
4. Test incrementally
5. Deploy

**Estimated effort**: 2-4 hours of development + testing time

---

**Status**: ✅ PREPARED - No immediate action required
**Date**: 2025-01-XX  
**Action**: Enable features when business requirements demand them
