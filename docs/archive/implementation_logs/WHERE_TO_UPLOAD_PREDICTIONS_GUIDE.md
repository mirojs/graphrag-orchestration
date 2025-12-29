# Where and How to Upload Predictions - Detailed Guide

## Understanding the Flow

### What You Currently Have

In your application, when a user clicks "Start Analysis" in the **Analysis tab**, this is what happens:

```
User clicks "Start Analysis" 
    ↓
handleStartAnalysisOrchestrated() is called
    ↓
startAnalysisOrchestratedAsync() dispatches to backend
    ↓
Backend processes documents and returns results
    ↓
Results are stored in Redux state (currentAnalysis)
    ↓
Results are displayed in the UI
```

### What's Missing (What Needs to Be Added)

**After the analysis completes**, you need to **save the prediction results** using the new storage pattern. Currently, results are only kept in memory (Redux state) and are lost when the page refreshes.

---

## Where to Add the Upload Code

**File**: `src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`

**Location**: In the `handleStartAnalysisOrchestrated` function, **after** the analysis completes successfully.

### Current Code (Line ~800-850)

```typescript
const result = await dispatch(startAnalysisOrchestratedAsync({
  // ... parameters
})).unwrap();

if (result.status === 'completed') {
  toast.success(`Analysis completed successfully!`);
  // ❌ Results are NOT being saved to blob storage
  return;
}

// Get the analysis results
const resultAction = await dispatch(getAnalysisResultAsync({ 
  analyzerId: result.analyzerId, 
  operationId: result.operationId || '',
  outputFormat: 'table'
}));
```

### Updated Code (What to Add)

```typescript
import { uploadPredictionResult } from '../ProModeServices/proModeApiService';

// ... inside handleStartAnalysisOrchestrated function ...

const result = await dispatch(startAnalysisOrchestratedAsync({
  // ... parameters
})).unwrap();

if (result.status === 'completed') {
  toast.success(`Analysis completed successfully!`);
  
  // ✅ NEW: Save prediction results to blob storage
  try {
    // Extract predictions from the result
    const predictions = result.result?.contents?.[0]?.fields || {};
    
    // Convert to the format expected by the API
    const predictionData: Record<string, any> = {};
    Object.entries(predictions).forEach(([fieldName, fieldValue]: [string, any]) => {
      predictionData[fieldName] = {
        value: fieldValue?.content || fieldValue?.valueString || '',
        confidence: fieldValue?.confidence || 0,
        source: fieldValue?.source,
        pageNumber: fieldValue?.pageNumber
      };
    });
    
    // Upload to blob storage
    const savedPrediction = await uploadPredictionResult(
      currentCase?.id || 'default-case',  // caseId from your case management
      selectedSchema.id,                   // schemaId
      inputFileIds[0],                     // fileId (primary file)
      predictionData
    );
    
    console.log('[PredictionTab] ✅ Prediction results saved:', savedPrediction);
    toast.success('Analysis results saved successfully!');
    
  } catch (saveError) {
    console.error('[PredictionTab] ❌ Failed to save prediction results:', saveError);
    toast.warning('Analysis completed but results could not be saved');
  }
  
  return;
}

// ... rest of the code
```

---

## What This Does

When you add this code and run an analysis:

1. **User triggers analysis** → Clicks "Start Analysis" button
2. **Analysis runs** → Backend processes the documents
3. **Results come back** → Stored in Redux state for display
4. **Automatic save happens** → Your new code uploads results to:
   - ✅ **Azure Blob Storage**: Full prediction data
   - ✅ **Cosmos DB**: Metadata + summary statistics

### What Gets Created Automatically

The **first time** this code runs:

```
Azure Blob Storage
└── predictions/                    ← Created automatically
    └── {case-id}/                  ← Created automatically
        └── {prediction-id}.json    ← Your prediction data

Cosmos DB
└── predictions container           ← Created automatically
    └── {
         "id": "...",
         "caseId": "...",
         "blobUrl": "https://...",
         "summary": { ... },
         "status": "completed"
       }
```

You don't need to create any containers or databases manually!

---

## Example: Complete Flow

### Step 1: User Performs Analysis

```
User opens Analysis tab
  ↓
Selects files: purchase_order.pdf
  ↓
Selects schema: "Invoice Extraction"
  ↓
Clicks "Start Analysis"
```

### Step 2: Analysis Completes

```
Backend extracts data:
{
  "Invoice Number": { value: "INV-12345", confidence: 0.95 },
  "Total Amount": { value: "$1,234.56", confidence: 0.88 },
  "Date": { value: "2025-01-15", confidence: 0.92 }
}
```

### Step 3: Automatic Save (Your New Code)

```typescript
// This happens automatically after analysis completes
await uploadPredictionResult(
  "case-abc-123",           // Current case
  "schema-invoice-001",     // Schema used
  "file-purchase-order",    // File analyzed
  {
    "Invoice Number": { value: "INV-12345", confidence: 0.95 },
    "Total Amount": { value: "$1,234.56", confidence: 0.88 },
    "Date": { value: "2025-01-15", confidence: 0.92 }
  }
);
```

### Step 4: Results Are Saved

```
✅ Blob Storage: predictions/case-abc-123/pred-xyz-789.json
✅ Cosmos DB: Metadata with summary
✅ User can now:
   - View results in UI (from Redux state)
   - Reload page and see results (from Cosmos DB)
   - View full details (loaded from Blob)
```

---

## Benefits You Get

1. **No data loss** - Results persist after page refresh
2. **Scalable** - Can handle huge prediction results (no 2MB limit)
3. **Fast previews** - Summary shows without loading full data
4. **Cost effective** - Less data in expensive Cosmos DB
5. **Historical tracking** - All predictions saved for later review

---

## Testing It

After adding the code:

1. **Run an analysis** in your application
2. **Check the console** - You should see:
   ```
   [PredictionTab] ✅ Prediction results saved: { id: "...", blobUrl: "...", summary: {...} }
   ```
3. **Check Azure Portal**:
   - Blob Storage → `predictions` container → Your JSON file
   - Cosmos DB → `predictions` container → Metadata record

---

## TL;DR

**"Upload the first prediction"** means:

- When your **analysis completes** and you have results
- Call `uploadPredictionResult()` to **save those results**
- This happens **automatically** when you add the code above
- The system **auto-creates** the necessary storage containers
- You **don't need** to do anything manually - just add the code!

The phrase doesn't mean you need to manually upload anything. It means "the first time your application saves prediction results using the new API, the storage containers will be created automatically."
