# Content Search Page Number Display Update - Complete ✅

## 🎯 Objective
Update the file comparison modal to properly display and utilize the exact page numbers found by content search matching method.

## 📋 Problem Analysis

### Previous Behavior:
- Content search successfully found the correct page with inconsistencies
- However, the page display showed only the general page range (e.g., "Pages: 1-5")
- The specific page found by content search wasn't highlighted in the display
- Jump functionality existed but page discovery was computed multiple times

### Issues Identified:
1. **No specific page highlight**: Display didn't show which page was found by content search
2. **Duplicate computation**: Page search logic was executed multiple times
3. **Inconsistent display**: Page info and jump functionality used separate logic

## ✅ Solution Implemented

### 1. **Memoized Page Number Computation**

Added a `useMemo` hook to compute page numbers once for all documents:

```typescript
// Memoized computation of page numbers found by content search for each document
const documentPageNumbers = useMemo(() => {
  const pageMap = new Map<string, number | null>();
  
  relevantDocuments.forEach(doc => {
    const pageNumber = findFirstPageWithDifference(doc, evidenceString);
    pageMap.set(doc.id, pageNumber);
    
    console.log('[FileComparisonModal] Content search found page for document:', {
      documentName: doc.name,
      documentId: doc.id,
      foundPage: pageNumber,
      evidenceUsed: evidenceString?.substring(0, 50)
    });
  });
  
  return pageMap;
}, [relevantDocuments, evidenceString, currentAnalysis]);
```

**Benefits:**
- ✅ Computes page numbers only once per modal open
- ✅ Stores results in a Map for quick lookup by document ID
- ✅ Automatically recomputes when relevant dependencies change
- ✅ Includes debug logging for troubleshooting

### 2. **Enhanced Page Display**

Updated the page info display to show the specific page found:

```typescript
{(() => {
  // Use memoized page number for this document
  const jumpPage = documentPageNumbers.get(document.id);
  const pageInfo = extractPageInfo(document, evidenceString);
  const pageDisplay = jumpPage
    ? `📍 ${pageInfo} • 🎯 Found on page ${jumpPage}`
    : `📍 ${pageInfo}`;
  return (
    <>
      <span>{pageDisplay}</span>
      {jumpPage && (
        <Button size="small" appearance="subtle" onClick={() => {
          // For PDFs, update iframe src with #page=jumpPage
          const iframes = window.document.querySelectorAll('iframe');
          if (iframes && iframes[index] && blob.mimeType === 'application/pdf') {
            (iframes[index] as HTMLIFrameElement).src = `${blob.url}#page=${jumpPage}`;
          }
        }}>Jump to page {jumpPage}</Button>
      )}
    </>
  );
})()}
```

**Display Examples:**
- **Without specific page**: `📍 Pages: 1-5`
- **With specific page found**: `📍 Pages: 1-5 • 🎯 Found on page 3`

### 3. **Consistent Auto-Jump Logic**

Updated the document viewer URL generation to use the same memoized page number:

```typescript
urlWithSasToken={(() => {
  // Auto-jump to first page with differences for PDFs using memoized value
  const jumpPage = documentPageNumbers.get(document.id);
  if (blob.mimeType === 'application/pdf' && jumpPage) {
    return `${blob.url}#page=${jumpPage}`;
  }
  return blob.url;
})()}
```

**Benefits:**
- ✅ Uses the same page number for display and navigation
- ✅ Guarantees consistency between UI and PDF viewer
- ✅ Eliminates duplicate page search computations

## 🎨 User Experience Improvements

### Before:
```
📄 Invoice: invoice.pdf
📍 Pages: 1-5
[Jump to page 3]  ← Button appears but page not highlighted in text
```

### After:
```
📄 Invoice: invoice.pdf
📍 Pages: 1-5 • 🎯 Found on page 3  ← Specific page highlighted!
[Jump to page 3]  ← Button matches highlighted page
```

## 🔧 Technical Benefits

1. **Performance Optimization**
   - Page search runs once per modal open instead of multiple times
   - Results cached in memory for instant access

2. **Code Maintainability**
   - Single source of truth for page numbers (documentPageNumbers Map)
   - Easier to debug with centralized logging

3. **Consistency Guarantee**
   - Display, jump button, and auto-jump all use the same page number
   - No possibility of mismatched page numbers

4. **Better Debugging**
   - Added console logging shows exactly which page was found for each document
   - Includes evidence snippet used for search

## 📊 Content Search Flow

```
User clicks Compare button
         ↓
Modal opens with evidence data
         ↓
useMemo: documentPageNumbers computes
         ↓
For each document:
  1. Extract search terms from evidence
  2. Search through document pages
  3. Find first page containing terms
  4. Store in Map: documentId → pageNumber
         ↓
Display renders:
  - Shows: "📍 Pages: X-Y • 🎯 Found on page Z"
  - Includes: [Jump to page Z] button
         ↓
PDF viewer initializes:
  - Auto-loads with URL: document.pdf#page=Z
         ↓
User sees document at exact inconsistency location! ✅
```

## 🧪 Testing Recommendations

### Test Scenarios:

1. **Single Page Document**
   - Expected: `📍 Page: 1 • 🎯 Found on page 1`

2. **Multi-Page Document with Match on Page 3**
   - Expected: `📍 Pages: 1-5 • 🎯 Found on page 3`
   - PDF should auto-scroll to page 3

3. **No Match Found**
   - Expected: `📍 Pages: 1-5` (no "Found on" text)
   - No jump button appears

4. **Multiple Documents**
   - Each document should show its own found page
   - Jump buttons should navigate to correct pages independently

## 📝 Files Modified

1. **FileComparisonModal.tsx**
   - Added `documentPageNumbers` useMemo hook
   - Updated page display to show specific found page
   - Simplified auto-jump logic using memoized values

## 🎉 Summary

The file comparison modal now:
- ✅ **Shows exact page numbers** found by content search
- ✅ **Displays clear visual indicator** (🎯) when page is found
- ✅ **Auto-jumps to the correct page** on modal open
- ✅ **Provides jump button** for manual navigation
- ✅ **Computes efficiently** with memoization
- ✅ **Maintains consistency** across all page number uses

Users can now clearly see which page contains the inconsistency and navigate directly to it with confidence! 🚀
