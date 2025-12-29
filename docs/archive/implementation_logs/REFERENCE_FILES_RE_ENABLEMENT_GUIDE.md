# Reference Files Re-enablement Guide

## Overview
This document provides a comprehensive guide for re-enabling reference files in the Pro Mode application after successful "input files only" testing has been completed.

## Current State (Input Files Only)
Following the proven working test pattern from `test_pro_mode_corrected_multiple_inputs.py`, the application currently:
- ✅ Uses only input files for analysis
- ✅ Sets `knowledgeSources: []` (empty array)
- ✅ Achieves 100% success rate matching the working test
- ✅ Preserves all reference file infrastructure

## Key Functions Modified

### 1. configure_knowledge_sources() Function
**Location**: `proMode.py` lines ~2118-2172

**Current Implementation (Simplified)**:
```python
def configure_knowledge_sources(payload: dict, official_payload: dict, app_config):
    # CRITICAL CHANGE: Following proven working test pattern - SKIP REFERENCE FILES
    # Set knowledge sources to empty array (matches working test)
    official_payload["knowledgeSources"] = []
```

**Original Implementation (Complex)**:
- Fetched reference files from Azure Storage
- Created sources.jsonl files dynamically  
- Configured knowledge sources with file mapping
- Handled selected vs all reference files logic
- Created analysis-specific JSONL uploads

**Re-enablement Steps**:
1. Restore reference file storage access logic
2. Re-implement sources.jsonl creation
3. Add knowledge sources configuration back
4. Test with input + reference file combination

### 2. analyze_content() Function  
**Location**: `proMode.py` lines ~4547-4970

#### **Blob Content Download Changes**
**Current (Simplified)**:
```python
# PROVEN WORKING PATTERN: Skip reference file downloads
reference_file_contents = []  # Empty to match working test
```

**Original (Complex)**:
```python
reference_file_contents = download_blob_contents(request.referenceFiles, "pro-reference-files", "reference")
```

#### **Payload Assembly Changes**  
**Current (Inputs Array)**:
```python
# URL Approach - Inputs array format (proven successful)
payload: Dict[str, Any] = {
    "inputs": inputs_array  # Array of {"url": "..."} objects
}
```

**Original (Single URL + Reference Files)**:
```python
# Single URL + reference files approach
payload: Dict[str, Any] = {
    "url": input_file_url,
    "referenceFiles": reference_files_array
}
```

**Re-enablement Steps**:
1. Restore reference file blob downloading
2. Add reference files to payload structure
3. Test both approaches: inputs array vs single URL
4. Validate against Azure API 2025-05-01-preview

### 3. Frontend Property Cleanup
**Location**: `proMode.py` lines ~3614-3648

**Current Enhanced Logging**:
```python
if key == 'selectedReferenceFiles':
    print(f"[AnalyzerCreate][CLEANUP] 📋 Reference files received: {len(value)}")
    print(f"[AnalyzerCreate][CLEANUP] 📋 STRATEGY: Keep infrastructure but exclude from analysis")
    print(f"[AnalyzerCreate][CLEANUP] 📋 FUTURE: May be re-enabled after successful testing")
```

**Re-enablement Steps**:
1. Modify cleanup logic to preserve selectedReferenceFiles when needed
2. Update logging to reflect active reference file usage
3. Ensure proper frontend-to-backend property mapping

### 4. Safety Validation
**Location**: `proMode.py` lines ~4049-4055  

**Current Safety Check**:
```python
if 'selectedReferenceFiles' in official_payload:
    removed_ref_files = official_payload.pop('selectedReferenceFiles')
    print(f"[AnalyzerCreate][SAFETY] 🚨 CRITICAL: Removed unexpected selectedReferenceFiles")
```

**Re-enablement Steps**:
1. Remove or modify safety check to allow reference files
2. Update validation logic for reference file payloads
3. Ensure Azure API compliance

## Testing Strategy for Re-enablement

### Phase 1: Reference Files + Input Files Test
Create a new test file: `test_pro_mode_with_reference_files.py`

**Test Structure**:
1. Upload reference files to `pro-reference-files` container
2. Upload input files to `pro-input-files` container  
3. Create analyzer with both file types
4. Analyze content with full configuration
5. Verify results match or exceed input-only success rate

### Phase 2: Gradual Re-enablement
1. **Step 1**: Re-enable knowledge sources configuration
2. **Step 2**: Test analyzer creation with reference files
3. **Step 3**: Re-enable reference file downloads
4. **Step 4**: Test analysis with reference files
5. **Step 5**: Full integration testing

### Phase 3: Validation
1. Compare results: input-only vs input+reference
2. Measure performance impact
3. Validate Azure API compliance
4. Test error scenarios and edge cases

## Code Restoration Checklist

### Essential Changes to Reverse
- [ ] Restore `configure_knowledge_sources()` complex logic
- [ ] Re-enable reference file blob downloading in `analyze_content()`
- [ ] Update payload assembly to include reference files
- [ ] Modify frontend property cleanup to preserve reference files
- [ ] Update safety validation to allow reference files
- [ ] Add comprehensive error handling for reference file failures

### Configuration Updates Needed
- [ ] Update Azure Storage permissions for reference file containers
- [ ] Verify SAS token generation for reference files
- [ ] Test knowledge sources container URL construction
- [ ] Validate sources.jsonl file creation and upload

### Testing Requirements
- [ ] Create test with both input and reference files
- [ ] Validate against Azure Content Understanding API 2025-05-01-preview
- [ ] Test with multiple reference file selection scenarios
- [ ] Verify error handling with invalid reference files
- [ ] Performance testing with large reference file sets

## Risk Mitigation

### Potential Issues
1. **API Complexity**: Reference files may cause Azure API rejections
2. **Performance**: Additional blob operations may slow requests
3. **Storage Costs**: More Azure Storage operations
4. **Error Handling**: Complex failure scenarios with multiple file types

### Mitigation Strategies
1. **Gradual Rollout**: Enable reference files for subset of users first
2. **Fallback Logic**: Automatically retry with input-only if reference files fail
3. **Monitoring**: Comprehensive logging and success rate tracking
4. **Feature Toggle**: Easy way to disable reference files if needed

## Success Criteria for Re-enablement

### Minimum Requirements
- [ ] Analyzer creation success rate ≥ current input-only rate
- [ ] Analysis success rate ≥ current input-only rate  
- [ ] No regression in performance (within 20% of current speed)
- [ ] Comprehensive error handling and recovery

### Optimal Goals
- [ ] Improved analysis accuracy with reference files
- [ ] Better field extraction using reference context
- [ ] Enhanced Pro mode capabilities
- [ ] Maintained system stability and reliability

## Conclusion

This guide provides a clear path for re-enabling reference files while preserving the proven success of the current input-only approach. The key is gradual testing and validation to ensure reference files add value without compromising reliability.
