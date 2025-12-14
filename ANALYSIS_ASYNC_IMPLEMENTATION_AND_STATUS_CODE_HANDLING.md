# Analysis: Async Implementation & Status Code Handling

**Document Created:** October 14, 2025  
**Purpose:** Comprehensive analysis of the current analysis implementation, status code handling, and HTTP 200/async overlap scenarios

---

## Table of Contents
1. [Current Implementation Overview](#current-implementation-overview)
2. [Two-Step Azure API Process](#two-step-azure-api-process)
3. [Status Code Detection Pattern](#status-code-detection-pattern)
4. [HTTP 200 vs Async Processing Overlap](#http-200-vs-async-processing-overlap)
5. [Loading State Logic](#loading-state-logic)
6. [Analysis Completion Detection Flow](#analysis-completion-detection-flow)
7. [Key Code References](#key-code-references)

---

## Current Implementation Overview

### **We're Using: Async (Orchestrated) Function** ✅

**Location:** `PredictionTab.tsx` line 1521

```typescript
<Button
  appearance="primary"
  disabled={!canStartAnalysis}
  onClick={handleStartAnalysisOrchestrated}  // ← Orchestrated async function
  icon={analysisLoading ? <Spinner size="tiny" /> : undefined}
>
  {analysisLoading ? t('proMode.prediction.analyzing') : t('proMode.prediction.startAnalysis')}
</Button>
```

**Function Chain:**
```
handleStartAnalysisOrchestrated (line 733)
  ↓
dispatch(startAnalysisOrchestratedAsync) (line 279)
  ↓
proModeApi.startAnalysis() (line 574 in proModeStore.ts)
  ↓
Azure Content Understanding API 2025-05-01-preview
```

---

## Two-Step Azure API Process

The `startAnalysis` function (`proModeApiService.ts` line 843) follows the official **Azure Content Understanding API 2025-05-01-preview** pattern:

### **Step 1: PUT - Create Content Analyzer**

**Endpoint:** `/pro-mode/content-analyzers/{analyzerId}?api-version=2025-05-01-preview`

**Purpose:** Define the schema and create the analyzer

**Expected Status Codes:** `200` or `201`

**Validation:**
```typescript
const createData = validateApiResponse(
  createResponse, 
  'Create Content Analyzer (PUT)', 
  [200, 201]  // PUT returns 200 (updated) or 201 (created)
);
```

**Status Code Meaning:**
- **200 OK** - Analyzer updated (already existed)
- **201 Created** - New analyzer created

---

### **Step 2: POST - Analyze Documents**

**Endpoint:** `/pro-mode/content-analyzers/{analyzerId}:analyze?api-version=2025-05-01-preview`

**Purpose:** Submit documents for analysis using the created analyzer

**Expected Status Codes:** `200` or `202`

**Validation:**
```typescript
const analysisData = validateApiResponse(
  analysisResponse,
  'Start Document Analysis (POST)',
  [200, 202]  // POST returns 200 (sync) or 202 (async)
);
```

**Status Code Meaning:**
- **200 OK** - Request processed successfully (may or may not be complete)
- **202 Accepted** - Request accepted for asynchronous processing

---

## Status Code Detection Pattern

### **HTTP Status Codes (Infrastructure Level)**

Validated by `validateApiResponse()` function (`proModeApiService.ts` lines 48-77):

```typescript
const validateApiResponse = (
  response: { data: any; status: number }, 
  operation: string, 
  expectedStatuses: number[] = [200, 201, 202]
): any => {
  const { status, data } = response;
  
  console.log(`[validateApiResponse] ${operation}: Received status ${status}`);
  
  if (!expectedStatuses.includes(status)) {
    const errorMsg = `${operation} failed: Expected status ${expectedStatuses.join(' or ')}, received ${status}`;
    throw new Error(errorMsg);
  }
  
  console.log(`[validateApiResponse] ${operation}: Status ${status} validated successfully`);
  return data;
};
```

**What it checks:** HTTP transport layer success/failure

**Categories:**
- ✅ **200-299**: Success range
- ❌ **400-499**: Client errors
- ❌ **500-599**: Server errors

---

### **Response Body Status (Application Level)**

Validated by `hasImmediateResults` check (`proModeStore.ts` lines 1325, 1421):

```typescript
const hasImmediateResults = 
  action.payload?.status === 'completed' &&  // Body status check
  (action.payload as any)?.result?.results;   // Has actual data
```

**What it checks:** Azure analysis job completion state

**Status Mapping** (`proModeStore.ts` lines 289-315):
```typescript
mapAzureStatusToInternalStatus(azureStatus):
  // Analysis complete
  'succeeded' | 'completed' → 'completed'  ✅ Clear loading
  
  // Analysis in progress
  'running' | 'submitted' | 'building' | 'processing' → 'running'  ⏳ Keep loading
  
  // Analysis failed
  'failed' | 'error' → 'failed'  ❌ Error state
  
  // Analysis not yet started
  'notstarted' | 'pending' | 'starting' → 'starting'  🔄 Initializing
```

---

## HTTP 200 vs Async Processing Overlap

### **⚠️ YES - There IS Potential Overlap!**

The code checks **TWO DIFFERENT things** that can have overlapping states:

#### **1. HTTP Status Code** (Transport Layer)
- Indicates if the HTTP request was successful
- Set by web server/API gateway
- Example: `200 OK`, `202 Accepted`, `404 Not Found`

#### **2. Response Body Status** (Application Layer)
- Indicates if the analysis job is complete
- Set by Azure Content Understanding service
- Example: `'running'`, `'completed'`, `'failed'`

---

### **Overlap Scenario Example:**

```json
POST /content-analyzers/{id}:analyze
Response:
{
  "httpStatus": 200,           ← HTTP layer: "Request processed"
  "body": {
    "status": "running",       ← App layer: "Analysis not done"
    "operationId": "xyz123",
    "operationLocation": "https://..."
  }
}
```

**What this means:**
- ✅ HTTP 200 = "I successfully received and queued your analysis request"
- ⏳ Body status 'running' = "The analysis job is still processing"
- 📡 operationId provided = "Poll this ID to get results later"

---

### **Why This Makes Sense:**

| Scenario | HTTP Status | Body Status | Meaning |
|----------|-------------|-------------|---------|
| **Instant analysis** | 200 | `completed` | Small file, finished immediately |
| **Queued analysis** | 200 | `running` | Large file, queued for processing |
| **Async accepted** | 202 | `submitted` | Explicitly async, not started yet |
| **Processing** | 200 | `processing` | Request accepted, job in progress |
| **Request error** | 400 | N/A | Invalid request (bad schema, etc.) |
| **Server error** | 500 | N/A | Backend service failure |

---

### **Current Code Handles This Correctly ✅**

The detection logic in `proModeStore.ts` (lines 1325, 1421) checks BOTH:

```typescript
const hasImmediateResults = 
  action.payload?.status === 'completed' &&        // ← Body status must be 'completed'
  (action.payload as any)?.result?.results;        // ← AND actual results must exist

if (hasImmediateResults) {
  state.loading = false;  // ✅ Safe to clear - we have results
} else {
  // ⏳ Keep loading=true until results are polled
  // Even if HTTP was 200, analysis might still be running
}
```

**Why this is correct:**
1. **Doesn't rely on HTTP status code** for completion detection
2. **Checks response body status** (`'completed'`)
3. **Validates actual data exists** (`result?.results`)
4. **Only clears loading when BOTH conditions met**

---

## Loading State Logic

### **Button Disable Control**

**Location:** `PredictionTab.tsx` line 981

```typescript
const canStartAnalysis = 
  selectedSchema && 
  selectedInputFiles.length > 0 && 
  !analysisLoading;  // ← From Redux state.analysis.loading
```

Both "Quick Inquiry" and "Start Analysis" buttons use this flag:

```typescript
// Quick Inquiry (line 1396)
<QuickQuerySection
  isExecuting={analysisLoading}  // ← Disables during analysis
  onQueryExecute={handleQuickQueryExecute}
/>

// Start Analysis (line 1520)
<Button
  disabled={!canStartAnalysis}  // ← Disables when loading
  onClick={handleStartAnalysisOrchestrated}
/>
```

---

### **Loading State Transitions**

#### **1. Analysis Starts** (`.pending` reducer)
```typescript
startAnalysisOrchestratedAsync.pending: (state) => {
  state.loading = true;  // ✅ Buttons become disabled
}
```

#### **2. Initial Response** (`.fulfilled` reducer)
```typescript
startAnalysisOrchestratedAsync.fulfilled: (state, action) => {
  const hasImmediateResults = 
    action.payload.status === 'completed' && 
    orchestratedResults;
  
  if (hasImmediateResults) {
    state.loading = false;  // ✅ Sync response - clear loading
  } else {
    // ⏳ Async response - keep loading=true
    // Will be cleared by getAnalysisResultAsync.fulfilled
  }
}
```

**Key Logic:**
- **HTTP 200 with body status 'completed'** → Clear loading immediately
- **HTTP 200 with body status 'running'** → Keep loading (requires polling)
- **HTTP 202** → Keep loading (explicitly async)

#### **3. Results Retrieved** (`.fulfilled` reducer)
```typescript
getAnalysisResultAsync.fulfilled: (state, action) => {
  state.loading = false;  // ✅ Always clear - results are here
  state.currentAnalysis.result = action.payload.result;
  state.currentAnalysis.status = 'completed';
}
```

This fires when `GET /results/{operationId}` returns **status 200** with actual results.

---

## Analysis Completion Detection Flow

### **Full End-to-End Flow:**

```
1. USER CLICKS "Start Analysis"
   ↓
2. handleStartAnalysisOrchestrated() called
   ↓
3. dispatch(clearAnalysis())  ← Clear previous state
   ↓
4. dispatch(startAnalysisOrchestratedAsync())
   ├─ .pending fires
   │  └─ state.loading = true  ✅ Buttons disabled
   ↓
5. API Call: PUT /content-analyzers/{id}
   ├─ Response: HTTP 200/201
   └─ Analyzer created ✅
   ↓
6. API Call: POST /content-analyzers/{id}:analyze
   ├─ Response: HTTP 200 or 202
   └─ Body: { status: 'running', operationId: 'xyz' }
   ↓
7. startAnalysisOrchestratedAsync.fulfilled fires
   ├─ Check: hasImmediateResults?
   ├─ NO (status='running', no results)
   └─ Keep state.loading = true  ⏳
   ↓
8. dispatch(getAnalysisResultAsync({ analyzerId, operationId }))
   ↓
9. POLLING LOOP (retry with backoff)
   ├─ API Call: GET /results/{operationId}?output_format=table
   ├─ Response: HTTP 200
   │  └─ Body: { status: 'running' }  ⏳ Still processing
   ├─ Retry with exponential backoff...
   │
   └─ Response: HTTP 200
      └─ Body: { status: 'completed', contents: [...] }  ✅
   ↓
10. getAnalysisResultAsync.fulfilled fires
    ├─ state.loading = false  ✅ Buttons re-enabled
    ├─ state.currentAnalysis.result = results
    └─ state.currentAnalysis.status = 'completed'
    ↓
11. UI Updates
    ├─ Status bar shows "Analysis complete"
    ├─ Buttons become clickable
    └─ Results displayed in table
```

---

### **Status Code Checkpoints:**

| Step | Endpoint | HTTP Status | Body Status | Action |
|------|----------|-------------|-------------|--------|
| 5 | PUT /analyzers/{id} | **200/201** | N/A | Create analyzer ✅ |
| 6 | POST :analyze | **200/202** | `'running'` | Start analysis, keep loading ⏳ |
| 9a | GET /results/{id} | **200** | `'running'` | Retry polling ⏳ |
| 9b | GET /results/{id} | **200** | `'completed'` | Clear loading, show results ✅ |

---

## Key Code References

### **Frontend Files**

#### **1. PredictionTab.tsx** (1972 lines)
- **Line 733:** `handleStartAnalysisOrchestrated` - Main analysis handler
- **Line 822:** `dispatch(getAnalysisResultAsync())` - Polling for results
- **Line 981:** `canStartAnalysis` - Button enable/disable logic
- **Line 1396:** QuickQuerySection with `isExecuting` prop
- **Line 1520:** Start Analysis button

#### **2. proModeStore.ts** (1757 lines)
- **Line 289:** `mapAzureStatusToInternalStatus` - Status mapping function
- **Line 558:** `startAnalysisOrchestratedAsync` - Main async thunk
- **Line 723:** `getAnalysisResultAsync` - Results polling thunk
- **Line 1305:** `startAnalysisAsync.fulfilled` - Conditional loading logic
- **Line 1405:** `startAnalysisOrchestratedAsync.fulfilled` - Conditional loading logic
- **Line 1449:** `getAnalysisResultAsync.fulfilled` - Clear loading when results arrive

#### **3. proModeApiService.ts** (1740 lines)
- **Line 48:** `validateApiResponse` - HTTP status validation utility
- **Line 843:** `startAnalysis` - Two-step Azure API implementation
- **Line 950:** Step 1: PUT create analyzer (expects 200/201)
- **Line 963:** Step 2: POST analyze documents (expects 200/202)
- **Line 1391:** `getAnalyzerResult` - GET results endpoint (expects 200)

---

### **Critical Logic Sections**

#### **HTTP Status Validation**
```typescript
// proModeApiService.ts lines 48-77
const validateApiResponse = (
  response: { data: any; status: number }, 
  operation: string, 
  expectedStatuses: number[] = [200, 201, 202]
): any => {
  if (!expectedStatuses.includes(status)) {
    throw new Error(`Expected ${expectedStatuses}, received ${status}`);
  }
  return data;
};
```

#### **Body Status Detection**
```typescript
// proModeStore.ts lines 1421-1428
const hasImmediateResults = 
  action.payload.status === 'completed' && 
  orchestratedResults;

if (hasImmediateResults) {
  console.log('[Redux] ✅ Orchestrated analysis completed synchronously');
  state.loading = false;
} else {
  console.log('[Redux] ⏳ Orchestrated analysis requires polling');
  // Keep state.loading = true
}
```

#### **Polling with Retry**
```typescript
// proModeStore.ts lines 690-720
const retryWithBackoff = async <T>(
  operation: () => Promise<T>,
  maxRetries: number = 5,
  initialDelay: number = 2000
): Promise<T> => {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const result = await operation();
    
    if ((result as any)?.data && isResultStillProcessing((result as any).data)) {
      if (attempt < maxRetries) {
        const delay = initialDelay * Math.pow(2, attempt);
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }
    }
    return result;
  }
};
```

---

## Summary & Conclusions

### **✅ Implementation is Correct**

1. **Using async orchestrated function** - Proper for multi-document batch processing
2. **Two-step Azure API pattern** - Following official 2025-05-01-preview specification
3. **Dual status checking** - HTTP codes AND response body status
4. **Conditional loading state** - Only clears when analysis actually completes
5. **Retry with backoff** - Handles Azure API timing gracefully

### **✅ HTTP 200 / Async Overlap is Handled**

The code **correctly distinguishes** between:
- **HTTP 200** = "Request processed successfully" (transport layer)
- **Body status 'running'** = "Analysis still in progress" (application layer)

Buttons stay disabled until `status === 'completed'` AND results exist, regardless of HTTP status code.

### **✅ Status Code Usage**

| Operation | HTTP Status | Meaning | Next Action |
|-----------|-------------|---------|-------------|
| PUT create analyzer | 200/201 | Analyzer ready | Proceed to POST |
| POST analyze | 200/202 | Analysis started | Check body status |
| - Body: 'completed' | 200 | Sync completion | Show results immediately |
| - Body: 'running' | 200 | Async processing | Start polling |
| GET results (polling) | 200 | Request succeeded | Check body status |
| - Body: 'running' | 200 | Still processing | Retry with backoff |
| - Body: 'completed' | 200 | Analysis done | Display results ✅ |

### **🎯 Key Insight**

**HTTP 200 does NOT mean "analysis complete"** - it means **"request processed"**. 

The actual completion is determined by:
1. Response body `status === 'completed'`
2. Actual results data exists
3. Both conditions must be true to clear loading state

This architecture is **robust** and handles both synchronous and asynchronous analysis patterns correctly! 🚀

---

**Document End**
