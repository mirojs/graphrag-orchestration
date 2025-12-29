# Document Matching Performance Analysis & Architecture Decision

## 🎯 Problem Statement

When comparing documents in CrossDocumentInconsistencies, we need to match evidence text to actual uploaded files. Two approaches:

1. **On-the-Fly Matching**: Search documents when user clicks Compare button
2. **Pre-Computed Matching**: Match documents when analysis results arrive, store in table data

## ⚡ Performance Comparison

### On-the-Fly Matching (Current Approach)

```typescript
// User clicks Compare button
onClick={() => {
  // Search through all documents NOW
  const docs = searchDocumentsForEvidence(evidence);
  openModal(docs);
}}
```

**Performance Characteristics:**
- **Time Complexity**: O(n × m) where n = documents, m = evidence length
- **When**: Every button click (could be 10-50+ clicks per session)
- **CPU Impact**: Repeated string matching operations
- **User Experience**: 50-200ms delay on button click (noticeable lag)

**Pros:**
- ✅ Simple to implement
- ✅ Always uses latest file list
- ✅ No memory overhead

**Cons:**
- ❌ **Slow for large documents** (1000+ page PDFs)
- ❌ **Repeated computation** - Same search done multiple times
- ❌ **UI lag** - User waits after clicking
- ❌ **Scales badly** - More inconsistencies = more repeated searches

### Pre-Computed Matching (Recommended)

```typescript
// When analysis results arrive
const enhancedResults = analysisResult.CrossDocumentInconsistencies.map(row => ({
  ...row,
  _matchedDocuments: precomputeDocumentMatch(row.Evidence, row.InvoiceValue, row.ContractValue),
  _modalId: generateUniqueId(row)
}));

// User clicks Compare button
onClick={() => {
  // Documents already identified!
  openModal(row._matchedDocuments);
}}
```

**Performance Characteristics:**
- **Time Complexity**: O(n × m) but ONCE, then O(1) lookups
- **When**: Once per analysis result load
- **CPU Impact**: One-time cost, amortized across all clicks
- **User Experience**: Instant button response (<1ms)

**Pros:**
- ✅ **Instant button clicks** - No search delay
- ✅ **Compute once, use many** - Efficient
- ✅ **Better UX** - Immediate modal open
- ✅ **Scales well** - More buttons = same speed

**Cons:**
- ⚠️ **Memory overhead** - Store matched docs in each row (~1-2KB per row)
- ⚠️ **Stale data** - If files change, need to recompute

## 🧮 Performance Math

### Scenario: 10 CrossDocumentInconsistencies, User Tests All Buttons

#### On-the-Fly:
```
Per-click search: 100ms (typical for 2 documents × 100 pages each)
Total time: 100ms × 10 clicks = 1000ms = 1 second of delays
User experience: Noticeable lag on every click
```

#### Pre-Computed:
```
Initial computation: 100ms × 10 rows = 1000ms (one-time, happens in background)
Per-click lookup: <1ms
Total time: 1000ms + (1ms × 10) = ~1000ms
User experience: Initial load delay, then instant clicks
```

**Result**: Same total computation, but better UX distribution

### Scenario: 50 CrossDocumentInconsistencies, Large Documents (500 pages each)

#### On-the-Fly:
```
Per-click search: 500ms (large documents)
If user tests 20 buttons: 500ms × 20 = 10 seconds of accumulated delays
User experience: Frustrating, feels broken
```

#### Pre-Computed:
```
Initial computation: 500ms × 50 = 25 seconds (background, shows loading spinner)
Per-click lookup: <1ms
User tests 20 buttons: <20ms total
User experience: Initial wait (acceptable), then smooth interaction
```

**Result**: Pre-computed is 500× faster for button clicks

## 🎯 Recommendation: **Pre-Computed Matching**

### Why Pre-Computed Wins:

1. **User Psychology**: 
   - Users tolerate initial loading (they expect it)
   - Users hate per-interaction delays (feels laggy/broken)

2. **Performance**:
   - Same total computation
   - Better distribution: one pause vs many micro-pauses

3. **Scalability**:
   - Handles large documents gracefully
   - More inconsistencies = same click speed

4. **Code Quality**:
   - Separation of concerns (data prep vs UI interaction)
   - Easier to optimize (can parallelize document matching)
   - Better testability

## 🏗️ Implementation Architecture

### Approach: Enhance Results When They Arrive

```typescript
// In proModeStore.ts or PredictionTab.tsx
const enhanceAnalysisResults = (rawResults: any, allDocuments: ProModeFile[]): any => {
  console.log('[enhanceAnalysisResults] Pre-computing document matches...');
  
  const startTime = performance.now();
  
  // Enhance each field that contains inconsistencies
  const enhanced = {
    ...rawResults,
    contents: rawResults.contents.map((content: any) => ({
      ...content,
      fields: Object.entries(content.fields).reduce((acc, [fieldName, fieldData]: [string, any]) => {
        // Only process array fields (inconsistencies)
        if (fieldData.type === 'array' && fieldData.valueArray) {
          acc[fieldName] = {
            ...fieldData,
            valueArray: fieldData.valueArray.map((item: any, index: number) => {
              // Pre-compute document matches for this row
              const matchedDocs = identifyDocumentsForInconsistency(
                item.valueObject,
                fieldName,
                allDocuments,
                index
              );
              
              return {
                ...item,
                valueObject: {
                  ...item.valueObject,
                  // Store matched documents directly in the data
                  _matchedDocuments: matchedDocs,
                  _modalId: `${fieldName}-${index}-${Date.now()}-${Math.random()}`
                }
              };
            })
          };
        } else {
          // Pass through non-array fields unchanged
          acc[fieldName] = fieldData;
        }
        return acc;
      }, {} as any)
    }))
  };
  
  const duration = performance.now() - startTime;
  console.log(`[enhanceAnalysisResults] ✅ Enhanced ${
    Object.keys(enhanced.contents[0]?.fields || {}).length
  } fields in ${duration.toFixed(2)}ms`);
  
  return enhanced;
};

// Use it when results arrive
dispatch(getAnalysisResultAsync(analysisId))
  .unwrap()
  .then(result => {
    // Enhance results with pre-computed matches
    const enhancedResult = enhanceAnalysisResults(
      result,
      [...inputFiles, ...referenceFiles]
    );
    
    // Store enhanced results in Redux
    dispatch(setAnalysisResult(enhancedResult));
  });
```

### Updated Compare Button Handler

```typescript
// In PredictionTab.tsx - Much simpler now!
const handleCompareFiles = (
  evidence: string,
  fieldName: string,
  inconsistencyData: any,
  rowIndex?: number
) => {
  console.log(`[handleCompareFiles] Using pre-computed documents for row ${rowIndex}`);
  
  // Documents already matched and stored!
  const matchedDocs = inconsistencyData._matchedDocuments;
  
  if (!matchedDocs || matchedDocs.length < 2) {
    console.warn('[handleCompareFiles] No pre-computed documents found, using fallback');
    // Fallback to generic selection
    const allFiles = [...selectedInputFiles, ...selectedReferenceFiles];
    matchedDocs = allFiles.slice(0, 2);
  }
  
  // Instant modal open - no search delay!
  updateAnalysisState({
    selectedInconsistency: {
      ...inconsistencyData,
      _modalId: inconsistencyData._modalId
    },
    selectedFieldName: fieldName,
    comparisonDocuments: {
      documentA: matchedDocs[0],
      documentB: matchedDocs[1],
      comparisonType: 'pre-matched'
    }
  });
  
  updateUiState({ showComparisonModal: true });
};
```

## 🔍 Document Matching Strategy (Pre-Compute Phase)

### Intelligent Multi-Strategy Matching

```typescript
const identifyDocumentsForInconsistency = (
  inconsistency: any,
  fieldName: string,
  allDocuments: ProModeFile[],
  rowIndex: number
): ProModeFile[] => {
  
  // Strategy 1: Use InvoiceValue/ContractValue if available (BEST)
  if (inconsistency.InvoiceValue && inconsistency.ContractValue) {
    const invoiceDoc = findDocumentByContentMatch(
      inconsistency.InvoiceValue.valueString || inconsistency.InvoiceValue,
      allDocuments,
      'invoice'
    );
    const contractDoc = findDocumentByContentMatch(
      inconsistency.ContractValue.valueString || inconsistency.ContractValue,
      allDocuments,
      'contract'
    );
    
    if (invoiceDoc && contractDoc) {
      return [invoiceDoc, contractDoc];
    }
  }
  
  // Strategy 2: Search Evidence text in document contents (GOOD)
  const evidence = inconsistency.Evidence?.valueString || inconsistency.Evidence || '';
  if (evidence.length > 20) {
    const matchedDocs = searchDocumentsForEvidence(evidence, allDocuments);
    if (matchedDocs.length >= 2) {
      return matchedDocs.slice(0, 2);
    }
  }
  
  // Strategy 3: Use DocumentType field if available (AZURE METADATA)
  const docTypes = extractDocumentTypesFromInconsistency(inconsistency);
  if (docTypes.length >= 2) {
    const matched = docTypes.map(type => 
      findDocumentByType(type, allDocuments)
    ).filter(Boolean);
    if (matched.length >= 2) {
      return matched;
    }
  }
  
  // Strategy 4: Filename pattern matching (FALLBACK)
  const invoiceFile = allDocuments.find(f => /invoice/i.test(f.name));
  const contractFile = allDocuments.find(f => /contract/i.test(f.name));
  if (invoiceFile && contractFile) {
    return [invoiceFile, contractFile];
  }
  
  // Strategy 5: Use first 2 selected files (LAST RESORT)
  console.warn(`[identifyDocumentsForInconsistency] Row ${rowIndex}: All matching strategies failed, using fallback`);
  return allDocuments.slice(0, 2);
};
```

### Content-Based Search (Fast Enough)

```typescript
const searchDocumentsForEvidence = (
  evidence: string,
  documents: ProModeFile[]
): ProModeFile[] => {
  // Extract key phrases (more reliable than full text)
  const keyPhrases = extractKeyPhrases(evidence); // e.g., ["$5,000", "payment terms", "30 days"]
  
  const scores = documents.map(doc => {
    let score = 0;
    
    // Quick scan of document metadata first (fast)
    if (doc.extractedText) {
      keyPhrases.forEach(phrase => {
        if (doc.extractedText.includes(phrase)) {
          score += 10;
        }
      });
    }
    
    // Fuzzy match on document name
    if (matchesDocumentType(doc.name, evidence)) {
      score += 5;
    }
    
    return { doc, score };
  });
  
  // Return documents sorted by match confidence
  return scores
    .filter(s => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(s => s.doc);
};
```

## ⚡ Performance Optimization: Lazy Pre-Computation

For very large result sets, we can compute on-demand with caching:

```typescript
// Compute only visible rows initially
const lazyEnhanceResults = (results: any, documents: ProModeFile[]) => {
  const cache = new Map();
  
  return new Proxy(results, {
    get(target, prop) {
      if (prop === 'getMatchedDocuments') {
        return (rowIndex: number) => {
          // Check cache first
          if (cache.has(rowIndex)) {
            return cache.get(rowIndex);
          }
          
          // Compute on first access
          const matched = identifyDocumentsForInconsistency(...);
          cache.set(rowIndex, matched);
          return matched;
        };
      }
      return target[prop];
    }
  });
};
```

## 📊 Memory Impact Analysis

### Pre-Computed Data Size:

```typescript
// Per inconsistency row:
_matchedDocuments: [
  { id: "uuid", name: "invoice.pdf", ... },  // ~500 bytes
  { id: "uuid", name: "contract.pdf", ... }  // ~500 bytes
]
_modalId: "CrossDocumentInconsistencies-0-1234567890-0.123"  // ~60 bytes

Total per row: ~1KB
```

**For 100 inconsistencies**: 100KB additional memory
**For 1000 inconsistencies**: 1MB additional memory

**Verdict**: Negligible memory impact for massive UX improvement

## ✅ Final Recommendation

### **Use Pre-Computed Matching with Intelligent Strategies**

```typescript
// Implementation Phases:

// Phase 1: Basic Pre-Computation (Immediate)
- Enhance results when they arrive
- Store _matchedDocuments in each row
- Update handleCompareFiles to use pre-matched docs

// Phase 2: Intelligent Matching (Next)
- Implement multi-strategy matching
- Content-based search with key phrases
- Azure metadata utilization

// Phase 3: Optimization (If Needed)
- Lazy computation for 1000+ rows
- Background web worker for heavy matching
- Cache invalidation on file updates
```

## 🎯 Summary

| Aspect | On-the-Fly | Pre-Computed | Winner |
|--------|------------|--------------|--------|
| **Button Click Speed** | 50-500ms | <1ms | ✅ Pre-Computed |
| **Total Computation** | Same | Same | 🤝 Tie |
| **User Experience** | Laggy clicks | Smooth clicks | ✅ Pre-Computed |
| **Memory Usage** | Minimal | ~1KB per row | ✅ Pre-Computed (acceptable) |
| **Code Complexity** | Simple | Moderate | ⚠️ On-the-Fly |
| **Scalability** | Poor (500+ rows) | Excellent | ✅ Pre-Computed |
| **Maintenance** | Harder to debug | Easier to test | ✅ Pre-Computed |

**Decision**: **Pre-Computed Matching** is the clear winner for production use.

---

**Next Steps:**
1. Implement `enhanceAnalysisResults()` function
2. Call it when analysis results arrive
3. Update `handleCompareFiles()` to use pre-matched documents
4. Add loading indicator during pre-computation phase
5. Test with real analysis results
