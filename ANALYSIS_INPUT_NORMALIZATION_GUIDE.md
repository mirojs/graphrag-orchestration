# Analysis Input Normalization Guide

## Overview

This guide documents the normalization and type interface patterns applied to the data input phase of the analysis process, mirroring the successful approach used for results display.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     NORMALIZED DATA FLOW                             │
└─────────────────────────────────────────────────────────────────────┘

1. FILE UPLOAD
   Backend Response → normalizeFiles() → NormalizedFile[]
   ├─ Handles both input and reference files
   ├─ Extracts process_id from various response formats
   ├─ Maps backend field names to frontend interface
   └─ Validates file metadata and status

2. SCHEMA FETCH
   Backend Response → normalizeSchemas() → NormalizedSchema[]
   ├─ Handles dual storage pattern (metadata + blob)
   ├─ Detects complete vs. lightweight schemas
   ├─ Normalizes timestamps and validation status
   └─ Supports both Azure and custom API formats

3. ANALYSIS CONFIGURATION
   User Selections → validateAnalysisConfig() → NormalizedAnalysisConfig
   ├─ Validates schema completeness
   ├─ Validates file selections
   ├─ Validates Azure API parameters
   └─ Returns detailed validation errors

4. REQUEST BUILDING
   NormalizedAnalysisConfig → buildAnalysisRequest() → NormalizedAnalysisRequest
   ├─ Generates analyzer ID
   ├─ Extracts process IDs from files
   ├─ Formats schema for backend
   └─ Applies Azure API parameters

5. OPERATION START
   Backend Response → normalizeAnalysisOperation() → NormalizedAnalysisOperation
   ├─ Extracts operation IDs
   ├─ Maps Azure status codes
   ├─ Handles immediate vs. async results
   └─ Provides consistent operation metadata
```

## Key Benefits

### 1. Type Safety Throughout
- **Before**: Inconsistent interfaces, any types, runtime errors
- **After**: Strict TypeScript interfaces, compile-time validation

### 2. Centralized Data Transformation
- **Before**: Multiple places handling backend responses differently
- **After**: Single normalization layer at API boundary

### 3. Consistent Error Handling
- **Before**: Errors handled ad-hoc in components
- **After**: Validation errors collected and returned consistently

### 4. Easier Testing
- **Before**: Mocking complex backend responses in every test
- **After**: Test normalizers once, use normalized types everywhere

### 5. Better Maintainability
- **Before**: Backend API changes break multiple components
- **After**: Update normalizers, components remain unchanged

## Normalization Functions

### File Upload Normalization

```typescript
import { normalizeFiles } from './ProModeTypes/analysisInputNormalizer';

// Example: Upload files and normalize response
const files = await uploadFiles(selectedFiles, 'input');
const normalizedFiles = normalizeFiles(files, 'input');

// Result: NormalizedFile[] with consistent structure
normalizedFiles.forEach(file => {
  console.log(file.id);          // Always string
  console.log(file.processId);   // Extracted from filename if needed
  console.log(file.displayName); // Clean name without UUID prefix
  console.log(file.isValid);     // Boolean validation status
});
```

### Schema Fetch Normalization

```typescript
import { normalizeSchemas } from './ProModeTypes/analysisInputNormalizer';

// Example: Fetch schemas and normalize response
const response = await fetchSchemas();
const normalizedSchemas = normalizeSchemas(response);

// Result: NormalizedSchema[] with consistent structure
normalizedSchemas.forEach(schema => {
  console.log(schema.id);              // Always string
  console.log(schema.hasCompleteData); // Boolean flag
  console.log(schema.isValid);         // Validation status
  console.log(schema.fieldCount);      // Number of fields
});
```

### Analysis Configuration Validation

```typescript
import { validateAnalysisConfig } from './ProModeTypes/analysisInputNormalizer';

// Example: Validate user selections before analysis
const config: Partial<NormalizedAnalysisConfig> = {
  schema: selectedSchema,
  inputFiles: selectedInputFiles,
  referenceFiles: selectedReferenceFiles,
  pages: '1-3,5'
};

const validation = validateAnalysisConfig(config);

if (!validation.isValid) {
  // Show errors to user
  validation.errors.forEach(error => {
    console.error(error);
  });
} else {
  // Proceed with analysis
  const request = buildAnalysisRequest(config);
}
```

### Analysis Request Building

```typescript
import { buildAnalysisRequest } from './ProModeTypes/analysisInputNormalizer';

// Example: Build typed request from configuration
const config: NormalizedAnalysisConfig = {
  schema: normalizedSchema,
  inputFiles: normalizedInputFiles,
  referenceFiles: normalizedReferenceFiles,
  outputFormat: 'json',
  includeTextDetails: true,
  isValid: true,
  validationErrors: [],
  configuredAt: new Date().toISOString()
};

const request = buildAnalysisRequest(config, {
  analyzerId: 'my-analyzer-123',
  analysisType: 'comprehensive'
});

// Result: NormalizedAnalysisRequest ready for backend
console.log(request.analyzerId);      // 'my-analyzer-123'
console.log(request.inputFileIds);    // string[] of process IDs
console.log(request.referenceFileIds); // string[] of process IDs
console.log(request.fieldSchema);     // Extracted schema for backend
```

### Analysis Operation Normalization

```typescript
import { normalizeAnalysisOperation } from './ProModeTypes/analysisInputNormalizer';

// Example: Normalize backend response after starting analysis
const backendResponse = await startAnalysis(request);
const normalizedOperation = normalizeAnalysisOperation(backendResponse, {
  analyzerId: request.analyzerId,
  analysisType: 'comprehensive'
});

// Result: NormalizedAnalysisOperation with consistent status
console.log(normalizedOperation.operationId);    // Extracted from various sources
console.log(normalizedOperation.status);         // 'starting' | 'running' | 'completed' | 'failed'
console.log(normalizedOperation.processingType); // 'single' | 'native-batch'
console.log(normalizedOperation.totalDocuments); // Number of documents
```

## Integration with API Service

The normalization layer is integrated directly into `proModeApiService.ts`:

```typescript
// File upload with normalization
export const uploadFiles = async (
  files: File[], 
  uploadType: 'input' | 'reference'
): Promise<NormalizedFile[]> => {
  const response = await httpUtility.upload(endpoint, formData);
  return normalizeFiles(response.data, uploadType); // ✅ Normalized
};

// Schema fetch with normalization
export const fetchSchemas = async (): Promise<NormalizedSchema[]> => {
  const response = await httpUtility.get(endpoint);
  return normalizeSchemas(response.data); // ✅ Normalized
};

// Analysis start with normalization
export const startAnalysis = async (
  request: AnalyzeInputRequest
): Promise<NormalizedAnalysisOperation> => {
  const response = await httpUtility.post(endpoint, payload);
  return normalizeAnalysisOperation(response.data, metadata); // ✅ Normalized
};
```

## Integration with Redux Store

The Redux store now uses normalized types:

```typescript
// Files state with normalized types
interface ProModeFilesState {
  inputFiles: NormalizedFile[];     // ✅ Type-safe
  referenceFiles: NormalizedFile[]; // ✅ Type-safe
  loading: boolean;
  error: string | null;
}

// Schemas state with normalized types
interface ProModeSchemasState {
  schemas: NormalizedSchema[];      // ✅ Type-safe
  loading: boolean;
  error: string | null;
}

// Analysis state with normalized types
interface AnalysisState {
  currentAnalysis: NormalizedAnalysisOperation | null; // ✅ Type-safe
  loading: boolean;
  error: string | null;
}
```

## Redux Thunks with Normalization

```typescript
// Example: Fetch files with normalization
export const fetchFilesByTypeAsync = createAsyncThunk(
  'proMode/fetchFilesByType',
  async (fileType: 'input' | 'reference') => {
    const normalizedFiles = await proModeApi.fetchFiles(fileType);
    // normalizedFiles is already NormalizedFile[] - no transformation needed
    return normalizedFiles;
  }
);

// Example: Start analysis with normalization
export const startAnalysisAsync = createAsyncThunk(
  'proMode/startAnalysis',
  async (params: StartAnalysisParams) => {
    // Build request using normalizer
    const config: NormalizedAnalysisConfig = {
      schema: params.schema,
      inputFiles: params.inputFiles,
      referenceFiles: params.referenceFiles,
      isValid: true,
      validationErrors: [],
      configuredAt: new Date().toISOString()
    };
    
    const request = buildAnalysisRequest(config, {
      analyzerId: params.analyzerId,
      analysisType: 'comprehensive'
    });
    
    // Start analysis (returns NormalizedAnalysisOperation)
    const operation = await proModeApi.startAnalysis(request);
    return operation; // Already normalized
  }
);
```

## Migration Guide

### Before (Without Normalization)

```typescript
// Manual transformation in every component
const response = await fetchFiles('input');
const files = response.data?.data?.map((file: any) => ({
  id: file.processId || file.id,
  name: file.filename || file.name,
  type: file.contentType || 'unknown',
  // ... manual mapping
})) || [];
```

### After (With Normalization)

```typescript
// Automatic normalization at API boundary
const files = await fetchFiles('input');
// files is already NormalizedFile[] - ready to use
```

## Error Handling Pattern

### Validation Errors

```typescript
const validation = validateAnalysisConfig(config);

if (!validation.isValid) {
  // Display all errors to user
  toast.error(validation.errors.join(', '));
  return;
}

// Proceed with confidence - config is valid
const request = buildAnalysisRequest(config);
```

### API Errors

```typescript
try {
  const files = await uploadFiles(selectedFiles, 'input');
  // files is NormalizedFile[] - all fields guaranteed present
} catch (error) {
  // Error already logged and formatted by API service
  toast.error('Failed to upload files');
}
```

## Testing Examples

### Test File Normalization

```typescript
import { normalizeFile } from './analysisInputNormalizer';

describe('normalizeFile', () => {
  it('should extract process_id from filename pattern', () => {
    const backendFile = {
      filename: '123e4567-e89b-12d3-a456-426614174000_invoice.pdf',
      size: 1024,
      contentType: 'application/pdf'
    };
    
    const normalized = normalizeFile(backendFile, 'input');
    
    expect(normalized.processId).toBe('123e4567-e89b-12d3-a456-426614174000');
    expect(normalized.displayName).toBe('invoice.pdf');
    expect(normalized.isValid).toBe(true);
  });
});
```

### Test Configuration Validation

```typescript
import { validateAnalysisConfig } from './analysisInputNormalizer';

describe('validateAnalysisConfig', () => {
  it('should validate required fields', () => {
    const config = {
      // Missing schema
      inputFiles: [mockFile1],
      referenceFiles: []
    };
    
    const validation = validateAnalysisConfig(config);
    
    expect(validation.isValid).toBe(false);
    expect(validation.errors).toContain('Schema is required for analysis');
  });
});
```

## Best Practices

### 1. Always Use Normalized Types

```typescript
// ✅ Good - Use normalized type
function processFiles(files: NormalizedFile[]) {
  files.forEach(file => {
    console.log(file.processId); // Type-safe
  });
}

// ❌ Bad - Use any type
function processFiles(files: any[]) {
  files.forEach(file => {
    console.log(file.id || file.processId || file.process_id); // Unsafe
  });
}
```

### 2. Validate Before Building Requests

```typescript
// ✅ Good - Validate first
const validation = validateAnalysisConfig(config);
if (!validation.isValid) {
  showErrors(validation.errors);
  return;
}
const request = buildAnalysisRequest(config);

// ❌ Bad - Skip validation
const request = buildAnalysisRequest(config); // May throw at runtime
```

### 3. Handle Errors at API Boundary

```typescript
// ✅ Good - Let API service normalize and handle errors
const files = await fetchFiles('input'); // Returns NormalizedFile[]

// ❌ Bad - Transform in component
const response = await httpUtility.get('/pro-mode/input-files');
const files = response.data?.map(...); // Duplicated logic
```

## Summary

The normalization layer provides:

1. **Type Safety**: Strict interfaces prevent runtime errors
2. **Consistency**: Same data structure across all components
3. **Validation**: Centralized validation with detailed errors
4. **Maintainability**: Single source of truth for transformations
5. **Testing**: Easy to test normalizers in isolation

This approach mirrors the successful pattern used for results display and creates a robust, type-safe data pipeline from user input through backend analysis.

## Related Files

- `ProModeTypes/analysisInputNormalizer.ts` - Normalization functions and types
- `ProModeServices/proModeApiService.ts` - API integration with normalization
- `ProModeStores/proModeStore.ts` - Redux state using normalized types
- `ANALYSIS_INPUT_NORMALIZATION_GUIDE.md` - This document
