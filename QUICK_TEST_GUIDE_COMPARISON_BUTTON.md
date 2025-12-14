# 🎯 Comparison Button Testing Guide

## Quick Test Steps

1. **Upload 2+ files** in Files tab
2. **Select files** (check checkboxes)
3. **Navigate to Analysis tab**
4. **Run analysis**
5. **Click compare button** on any row

## Expected Results

### ✅ Success Case
**Console Output:**
```
[findFile] ✅ Process ID match
[identifyComparisonDocuments] ✅ MULTI-STRATEGY FILE MATCH
[handleCompareFiles] DEBUG: Row 0 got documents: {documentA: '...', documentB: '...'}
```

**Visual Result:** Comparison modal opens with both documents displayed

### ⚠️ Fallback Case
**Console Output:**
```
[identifyComparisonDocuments] ⚠️ Multi-strategy filename matching failed
[identifyComparisonDocuments] ✅ Using user-selected files as fallback
```

**Visual Result:** Comparison modal opens with user-selected files

### ❌ Error Case
**Console Output:**
```
[identifyComparisonDocuments] ❌ CONTENT SEARCH FAILED
```

**Toast Message:**
```
Cannot find documents containing the identified values.
Please ensure you have selected the correct files.
```

## What Changed

### File Matching (3 Strategies)
1. **Exact name match** - Direct comparison
2. **Process ID match** - Extract & compare UUIDs
3. **Clean filename match** - Ignore UUID prefixes

### Content Search
- **Before:** Array index alignment (unreliable)
- **After:** Process ID mapping (reliable)

### Fallback
- **Before:** None (complete failure)
- **After:** User-selected files

## Debugging Tips

**Check file matching:**
```javascript
// In console after clicking compare
console.log('Available files:', allFiles.map(f => ({
  name: f.name,
  processId: f.process_id
})));
```

**Check content mapping:**
```
Search console for "[findDocumentContentForFile]"
```

## Success Indicators

✅ Modal opens with 2 documents  
✅ Documents load in side-by-side view  
✅ No undefined errors  
✅ Console shows successful matching  

## Files Modified

- `PredictionTab.tsx` - Lines 1-19, 1175-1475
- `FileComparisonModal.tsx` - Line 63

## Need More Info?

See `COMPARISON_BUTTON_FILE_MATCHING_FIX_COMPLETE.md` for full details.
