# TableFormat Architecture Correction - Backend Responsibility

## Overview

**CORRECTED**: Reverted frontend `tableFormat` changes after understanding the proper architecture. The `tableFormat` configuration should be **hardcoded in the backend**, not sent from the frontend.

## Architecture Understanding

Based on the comments at line 599 and throughout the code, the architecture clearly separates responsibilities:

### ✅ Frontend Responsibility (Dynamic Content Only)
- `schemaId`: Used for naming and backend tracking
- `fieldSchema`: The actual schema definition from upload  
- `selectedReferenceFiles`: Reference files for knowledgeSources assembly

### ✅ Backend Responsibility (Hardcoded Configuration)
- `mode`: Analysis mode
- `baseAnalyzerId`: Base analyzer configuration
- `config`: **Including `tableFormat: "html"`**
- `processingLocation`: Processing configuration
- `tags`: Tagging configuration

## What Was Wrong

I initially added `tableFormat` to the frontend payloads, but this violated the established architecture where:

> "Backend hardcodes: mode, baseAnalyzerId, config, processingLocation, etc."

The `config` object (which includes `tableFormat`) should be hardcoded by the backend, not sent from the frontend.

## Corrected Changes

### 1. Reverted CreateContentAnalyzerPayload Interface

**Incorrect (What I Did First):**
```typescript
interface CreateContentAnalyzerPayload {
  schemaId: string;
  fieldSchema: any;
  selectedReferenceFiles?: string[];
  tableFormat?: string; // ❌ WRONG - Should be hardcoded in backend
}
```

**Correct (Reverted To):**
```typescript
interface CreateContentAnalyzerPayload {
  schemaId: string;                  // ✅ DYNAMIC: Used for naming and backend tracking  
  fieldSchema: any;                  // ✅ DYNAMIC: The actual schema definition from upload
  selectedReferenceFiles?: string[]; // ✅ DYNAMIC: Reference files for knowledgeSources assembly
  // ❌ REMOVED: analysisMode, baseAnalyzerId, tableFormat (now hardcoded in backend per architecture)
}
```

### 2. Reverted createContentAnalyzer Function

**Incorrect (What I Did First):**
```typescript
const cleanPayload = {
  schemaId: payload.schemaId || analyzerId,
  fieldSchema: payload.fieldSchema,
  selectedReferenceFiles: payload.selectedReferenceFiles || [],
  config: {
    tableFormat: payload.tableFormat || "html" // ❌ WRONG
  }
};
```

**Correct (Reverted To):**
```typescript
const cleanPayload = {
  schemaId: payload.schemaId || analyzerId, // For backend tracking
  fieldSchema: payload.fieldSchema, // Only the fieldSchema part
  selectedReferenceFiles: payload.selectedReferenceFiles || [] // For knowledgeSources assembly in backend
};
```

### 3. Reverted Analysis Functions

**Incorrect (What I Did First):**
```typescript
const createPayload = {
  schemaId: analysisRequest.schemaId,
  fieldSchema: fieldSchema,
  selectedReferenceFiles: analysisRequest.referenceFileIds || [],
  tableFormat: "html" // ❌ WRONG - Should be hardcoded in backend
};
```

**Correct (Reverted To):**
```typescript
const createPayload = {
  schemaId: analysisRequest.schemaId,          // ✅ DYNAMIC: Used for naming and tracking
  fieldSchema: fieldSchema,                    // ✅ DYNAMIC: The actual schema definition from upload
  selectedReferenceFiles: analysisRequest.referenceFileIds || []  // ✅ DYNAMIC: Reference files for knowledgeSources
  // ❌ REMOVED: analysisMode, baseAnalyzerId, tableFormat (now hardcoded in backend per architecture)
};
```

## Where TableFormat Should Be Handled

The `tableFormat` configuration should be handled in the **backend** when it processes the PUT request to create the content analyzer. The backend should:

1. Receive the clean payload from frontend (schemaId, fieldSchema, selectedReferenceFiles)
2. **Hardcode** the config object including `tableFormat: "html"`
3. Construct the full Azure API payload with all required configuration
4. Send the complete payload to Azure Content Understanding API

## Architecture Benefits

This separation provides:

1. **Clean Frontend**: Only sends dynamic, user-specific content
2. **Centralized Configuration**: Backend controls all API-specific settings
3. **Consistency**: All analyzer configurations use the same hardcoded settings
4. **Maintainability**: Config changes only require backend updates
5. **Security**: Frontend can't override critical API configuration

## Final State

✅ **Frontend**: Sends only dynamic content (schemaId, fieldSchema, selectedReferenceFiles)  
✅ **Backend**: Hardcodes all configuration including tableFormat  
✅ **Azure API**: Receives properly formatted requests with correct tableFormat setting  

**Status: ✅ ARCHITECTURE CORRECTED**
**Responsibility: Backend hardcodes tableFormat configuration**