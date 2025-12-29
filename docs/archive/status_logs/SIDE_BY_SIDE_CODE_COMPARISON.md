# Side-by-Side Code Comparison: Key Sections

## Section 1: Button Handler Assignment

### 40 Commits Ago (Working):
```typescript
<Button
  appearance="primary"
  disabled={!canStartAnalysis}
  onClick={handleStartAnalysis}  // ← DIRECT CALL TO LEGACY METHOD
  icon={analysisLoading ? <Spinner size="tiny" /> : undefined}
>
  {analysisLoading ? 'Starting Analysis...' : 'Start Analysis'}
</Button>
```

### Current Version (Fallback):
```typescript
<Button
  appearance="primary"
  disabled={!canStartAnalysis}
  onClick={handleStartAnalysisOrchestrated}  // ← CALLS ORCHESTRATED METHOD FIRST
  icon={analysisLoading ? <Spinner size="tiny" /> : undefined}
>
  {analysisLoading ? 'Starting Analysis...' : 'Start Analysis (Orchestrated)'}
</Button>
```

## Section 2: handleStartAnalysis Function (The Core Logic)

### 40 Commits Ago:
```typescript
const handleStartAnalysis = async () => {
  // ✅ Enhanced validation with specific feedback
  if (!selectedSchema || selectedInputFiles.length === 0) {
    const missingItems = [];
    if (!selectedSchema) missingItems.push('schema');
    if (selectedInputFiles.length === 0) missingItems.push('input files');
    
    toast.error(`Please select ${missingItems.join(' and ')} from the ${missingItems.length > 1 ? 'Schema and Files tabs' : missingItems[0] === 'schema' ? 'Schema tab' : 'Files tab'}.`);
    return;
  }

  try {
    // Generate a unique analyzer ID
    const analyzerId = `analyzer-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // Use only blobName for input/reference files (enhanced processing)
    const inputFileIds = selectedInputFiles.map(f => f.id);
    const referenceFileIds = selectedReferenceFiles.map(f => f.id);

    // ✅ Enhanced schema configuration with production-ready format support
    let schemaConfig = selectedSchema;
    if (schemaConfig && (schemaConfig as any).blobUrl && !(schemaConfig as any).blobName) {
      const urlParts = (schemaConfig as any).blobUrl.split('/');
      schemaConfig = {
        ...schemaConfig,
        blobName: urlParts.slice(-2).join('/'),
      } as any;
    }

    // Enable real API calls (disable mock) - confirmed for production use
    window.__MOCK_ANALYSIS_API__ = false;
    window.__FORCE_REAL_API__ = true;

    // ✅ Enhanced analysis request with better schema handling
    const result = await dispatch(startAnalysisAsync({  // ← USES LEGACY ASYNC THUNK
      analyzerId,
      schemaId: selectedSchema.id,
      inputFileIds,
      referenceFileIds,
      schema: schemaConfig,
      configuration: { mode: 'pro' },
      // ✅ Add enhanced document processing parameters
      locale: 'en-US',
      outputFormat: 'json',
      includeTextDetails: true
    })).unwrap();

    // ✅ Enhanced success feedback with operation location diagnostics
    console.log('[PredictionTab] Analysis started successfully with enhanced config:', result);
    
    // ... polling logic continues ...
  } catch (error: any) {
    // ... error handling ...
  }
};
```

### Current Version:
```typescript
// IDENTICAL TO 40 COMMITS AGO - NO CHANGES!
const handleStartAnalysis = async () => {
  // ... EXACT SAME CODE AS ABOVE ...
};
```

## Section 3: NEW Orchestrated Function (Added in Current Version)

### Current Version Only:
```typescript
const handleStartAnalysisOrchestrated = async () => {
  // ✅ Enhanced validation with specific feedback (SAME AS LEGACY)
  if (!selectedSchema || selectedInputFiles.length === 0) {
    const missingItems = [];
    if (!selectedSchema) missingItems.push('schema');
    if (selectedInputFiles.length === 0) missingItems.push('input files');
    
    toast.error(`Please select ${missingItems.join(' and ')} from the ${missingItems.length > 1 ? 'Schema and Files tabs' : missingItems[0] === 'schema' ? 'Schema tab' : 'Files tab'}.`);
    return;
  }

  try {
    // Generate a unique analyzer ID (SAME AS LEGACY)
    const analyzerId = `analyzer-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // Use only blobName for input/reference files (SAME AS LEGACY)
    const inputFileIds = selectedInputFiles.map(f => f.id);
    const referenceFileIds = selectedReferenceFiles.map(f => f.id);

    // Enable real API calls (SAME AS LEGACY)
    window.__MOCK_ANALYSIS_API__ = false;
    window.__FORCE_REAL_API__ = true;

    // ✅ KEY DIFFERENCE: Uses orchestrated analysis thunk
    const result = await dispatch(startAnalysisOrchestratedAsync({  // ← USES NEW ORCHESTRATED THUNK
      analyzerId,
      schemaId: selectedSchema.id,
      inputFileIds,
      referenceFileIds,
      configuration: { mode: 'pro' },
      // ✅ Add enhanced document processing parameters
      locale: 'en-US',
      outputFormat: 'json',
      includeTextDetails: true
    })).unwrap();

    // ✅ Enhanced success feedback (DIFFERENT - NO POLLING)
    console.log('[PredictionTab] Orchestrated analysis completed successfully:', result);
    
    if (result.status === 'completed') {
      toast.success(`Analysis completed successfully in orchestrated mode! Processed ${result.totalDocuments || inputFileIds.length} documents.`);
      // NO POLLING - Orchestrated flow completes synchronously
    } else {
      toast.info(`Orchestrated analysis started. Status: ${result.status}`);
    }

  } catch (error: any) {
    // Enhanced error handling with FALLBACK
    console.error('[PredictionTab] Orchestrated analysis failed:', error);
    
    // FALLBACK TO LEGACY METHOD
    console.log('[PredictionTab] Attempting fallback to legacy analysis method...');
    try {
      await handleStartAnalysis();  // ← CALLS THE WORKING LEGACY METHOD
      toast.info('Fallback to legacy analysis method succeeded.');
    } catch (fallbackError: any) {
      console.error('[PredictionTab] Both orchestrated and legacy methods failed:', fallbackError);
      toast.error('Both orchestrated and legacy analysis methods failed. Please check your configuration.');
    }
  }
};
```

## Key Insights

1. **The `handleStartAnalysis` function is IDENTICAL** between both versions
2. **The button now calls `handleStartAnalysisOrchestrated` instead of `handleStartAnalysis`**
3. **The fallback only triggers when the orchestrated method fails**
4. **To restore working behavior, change the button to call `handleStartAnalysis` directly**

## Quick Fix

To make the fallback work as the main function, make this simple change:

```typescript
// In the Button component, change:
onClick={handleStartAnalysisOrchestrated}

// To:
onClick={handleStartAnalysis}

// And change the button text from:
'Start Analysis (Orchestrated)'

// To:
'Start Analysis'
```

This will restore the exact working behavior from 40 commits ago.