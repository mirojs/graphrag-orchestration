# Frontend Interface Updates for Multiple Documents Support

## Overview

The frontend interfaces have been successfully updated to align with the enhanced backend that supports native multiple document processing through the Azure Content Understanding API 2025-05-01-preview.

## Key Interface Changes Made

### 1. **Enhanced AnalyzeInputRequest Interface**

**File**: `proModeApiService.ts`

```typescript
interface AnalyzeInputRequest {
  schemaId: string;
  inputFileIds: string[];
  referenceFileIds: string[];
  configuration: any;
  schema?: any;
  analyzerId?: string;
  // Enhanced AnalyzeInput parameters following Azure Content Understanding API 2025-05-01-preview
  pages?: string; // Page range specification (e.g., "1-3,5")
  locale?: string; // Document locale (e.g., "en-US", "fr-FR")
  outputFormat?: string; // Output format preference ("json", "text", etc.)
  includeTextDetails?: boolean; // Include detailed text extraction (default: true)
}
```

**Benefits**:
- ✅ **Type Safety**: Strongly typed interface for all API parameters
- ✅ **Azure API Compliance**: Matches official Microsoft specification
- ✅ **Enhanced Parameters**: Supports pages, locale, outputFormat, includeTextDetails
- ✅ **Multiple Documents**: Array of inputFileIds processed natively

### 2. **Updated StartAnalysisParams Interface**

**File**: `proModeStore.ts`

```typescript
interface StartAnalysisParams {
  analyzerId: string;
  schemaId: string;
  inputFileIds: string[];
  referenceFileIds: string[];
  schema?: any;
  configuration?: any;
  // Enhanced AnalyzeInput parameters applied to ALL documents in the batch
  pages?: string; // Page range specification applied to all documents
  locale?: string; // Document locale applied to all documents
  outputFormat?: string; // Output format preference for all documents
  includeTextDetails?: boolean; // Text extraction detail level for all documents
}
```

**Benefits**:
- ✅ **Consistent Processing**: Same parameters applied to all documents
- ✅ **Redux Integration**: Seamless state management
- ✅ **Batch Awareness**: Understands multiple document context

### 3. **Enhanced ExtractionResult Interface**

**File**: `proModeTypes.ts`

```typescript
export interface ExtractionResult extends BaseResult {
  results: any;
  confidenceScore: number;
  extractedFields: ExtractedField[];
  correlationId?: string;
  batchId?: string;
  // Enhanced for native multiple document support
  processingType?: 'single' | 'native-batch';
  totalDocuments?: number;
  documentResults?: DocumentResult[];
}

export interface DocumentResult {
  documentIndex: number;
  documentUrl: string;
  status: 'processed' | 'failed' | 'skipped';
  extractedFields: ExtractedField[];
  confidenceScore: number;
  errors?: string[];
  processingTimeMs?: number;
}
```

**Benefits**:
- ✅ **Batch Result Tracking**: Individual document results within batch
- ✅ **Processing Type Awareness**: Distinguishes single vs batch processing
- ✅ **Document Status**: Per-document success/failure tracking
- ✅ **Performance Metrics**: Processing time per document

### 4. **Enhanced AnalyzeInputParameters Interface**

**File**: `proModeTypes.ts`

```typescript
export interface AnalyzeInputParameters {
  pages?: string; // Page range specification (e.g., "1-3,5")
  locale?: string; // Document locale (e.g., "en-US", "fr-FR")
  outputFormat?: string; // Output format preference ("json", "text", etc.)
  includeTextDetails?: boolean; // Include detailed text extraction (default: true)
}
```

**Benefits**:
- ✅ **Reusable Interface**: Can be used across components
- ✅ **Azure API Alignment**: Matches official specification
- ✅ **Type Safety**: Prevents parameter misuse

## Updated API Service Functions

### 1. **Enhanced startAnalysis Function**

**Changes Made**:
- ✅ **Removed Batch Endpoint**: No longer uses separate batch processing endpoint
- ✅ **Native Multiple Document Support**: Single endpoint handles multiple documents
- ✅ **Enhanced Parameters**: Supports all Azure API AnalyzeInput parameters
- ✅ **Consistent Processing**: Same parameters applied to all documents in batch

**Key Features**:
```typescript
// ALIGNED WITH BACKEND: Native multiple document processing
const payload = {
  analyzerId: generatedAnalyzerId,
  analysisMode: "pro",
  baseAnalyzerId: "prebuilt-documentAnalyzer",
  schema_config: analysisRequest.schema,
  inputFiles: analysisRequest.inputFileIds, // Multiple documents processed natively
  referenceFiles: analysisRequest.referenceFileIds,
  
  // Enhanced AnalyzeInput parameters applied to all documents
  pages: analysisRequest.pages,
  locale: analysisRequest.locale,
  outputFormat: analysisRequest.outputFormat,
  includeTextDetails: analysisRequest.includeTextDetails
};
```

### 2. **Enhanced Redux Store Actions**

**Changes Made**:
- ✅ **Batch Awareness**: Tracks multiple document processing
- ✅ **Processing Type**: Distinguishes native-batch vs single document
- ✅ **Enhanced Logging**: Detailed logging for multiple document scenarios

**Key Features**:
```typescript
console.log('[startAnalysisAsync] Starting native multiple document analysis with:', {
  analyzerId: params.analyzerId,
  totalDocuments: selectedInputFiles.length,
  processingType: selectedInputFiles.length > 1 ? 'native-batch' : 'single',
  enhancedParams: {
    pages: params.pages,
    locale: params.locale,
    outputFormat: params.outputFormat,
    includeTextDetails: params.includeTextDetails
  }
});
```

## Benefits of Updated Interfaces

### 🚀 **Performance Benefits**
- **Native Batch Processing**: Multiple documents processed simultaneously by Azure
- **Reduced Latency**: Single API call instead of multiple sequential calls
- **Better Resource Utilization**: Azure optimizes batch processing internally

### 🎯 **Accuracy Benefits**
- **Consistent Processing**: Same parameters applied to all documents
- **Unified Analysis**: All documents processed with same analyzer version
- **Cross-Document Context**: Azure can consider relationships between documents

### 🔧 **Developer Experience**
- **Type Safety**: TypeScript interfaces prevent parameter errors
- **Clear Interfaces**: Well-documented parameter purposes
- **Consistent API**: Unified approach for single and multiple documents

### 📊 **Monitoring & Debugging**
- **Enhanced Logging**: Detailed tracking of multiple document processing
- **Processing Type Tracking**: Clear distinction between single/batch processing
- **Document-Level Results**: Individual success/failure tracking

## Frontend Usage Examples

### **Single Document Processing**
```typescript
dispatch(startAnalysisAsync({
  analyzerId: "custom-analyzer-123",
  schemaId: "schema-456",
  inputFileIds: ["doc1.pdf"],
  referenceFileIds: [],
  pages: "1-2",
  locale: "en-US"
}));
```

### **Multiple Document Processing** 
```typescript
dispatch(startAnalysisAsync({
  analyzerId: "custom-analyzer-123",
  schemaId: "schema-456",
  inputFileIds: ["doc1.pdf", "doc2.pdf", "doc3.pdf"],
  referenceFileIds: [],
  pages: "1-3",
  locale: "en-US",
  includeTextDetails: true
}));
```

## Removed Interfaces

### ❌ **Batch Processing Endpoint**
- **Removed**: Separate batch analysis endpoint references
- **Reason**: Azure API natively supports multiple documents
- **Benefit**: Simplified architecture, better performance

### ❌ **Sequential Processing Logic**
- **Removed**: Client-side sequential document processing
- **Reason**: Azure handles multiple documents natively
- **Benefit**: Better performance and consistency

## Compatibility

### ✅ **Backward Compatibility**
- **Single Document**: Still works exactly as before
- **Existing Components**: No breaking changes to UI components
- **API Contracts**: Enhanced but backward compatible

### ✅ **Forward Compatibility**
- **Azure API Updates**: Ready for future Azure API enhancements
- **Parameter Extensions**: Easy to add new AnalyzeInput parameters
- **Scaling**: Can handle larger document batches

## Summary

The frontend interfaces have been successfully updated to:

1. **✅ Remove redundant batch processing code**
2. **✅ Support native multiple document processing**
3. **✅ Align with Azure Content Understanding API 2025-05-01-preview**
4. **✅ Provide enhanced AnalyzeInput parameter support**
5. **✅ Maintain type safety throughout the application**
6. **✅ Enable better monitoring and debugging capabilities**

The interfaces now properly reflect the enhanced backend capabilities for native multiple document processing through the Azure Content Understanding API! 🎉
