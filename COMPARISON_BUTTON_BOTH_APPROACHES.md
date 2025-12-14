# Comparison Button Fix - Both Approaches

## The Question

**How does Azure return filenames in `DocumentASourceDocument` and `DocumentBSourceDocument`?**

We need to handle both possibilities:
1. **Blob name with UUID**: `"7543c5b8-903b-466c-95dc-1a920040d10c_invoice.pdf"`
2. **Just the filename**: `"invoice.pdf"`

## ✅ Solution Implemented: Handle Both Cases (Defensive)

### Multi-Strategy Matching

```typescript
const findFileByAzureResponse = (allFiles, azureFilename) => {
  // Strategy 1: UUID extraction (if blob name with UUID prefix)
  const uuid = extractUuidFromBlobName(azureFilename);
  if (uuid) {
    const match = allFiles.find(f => f.id === uuid);
    if (match) return match; // ✅ "7543c5b8-..._invoice.pdf" → match by UUID
  }
  
  // Strategy 2: Direct filename match
  const match = allFiles.find(f => f.name === azureFilename);
  if (match) return match; // ✅ "invoice.pdf" → match by name
  
  // Strategy 3: Clean filename (remove UUID if present)
  const cleanName = removeUuidPrefix(azureFilename);
  const match = allFiles.find(f => f.name === cleanName);
  if (match) return match; // ✅ "uuid_invoice.pdf" → "invoice.pdf"
  
  // Strategy 4: Case-insensitive match
  const match = allFiles.find(f => 
    f.name.toLowerCase() === cleanName.toLowerCase()
  );
  if (match) return match; // ✅ "Invoice.pdf" → "invoice.pdf"
  
  return null; // ❌ No match
};
```

### Benefits
- ✅ **Handles both formats** - Works regardless of Azure's output
- ✅ **Defensive** - Won't break if Azure changes behavior
- ✅ **Fallback strategies** - Multiple attempts to find match
- ✅ **No schema changes needed** - Works with current schema

### Drawbacks
- ⚠️ More complex logic
- ⚠️ Potentially ambiguous if multiple files have similar names

## Alternative: Control via Schema (Cleaner)

### Option A: Tell Azure to Return Original Filenames Only

Update your schema descriptions to explicitly request just filenames:

```json
{
  "DocumentASourceDocument": {
    "type": "string",
    "method": "generate",
    "description": "The original filename (without UUID prefix) of document A where this value was found. Example: 'invoice_2024.pdf', NOT '7543c5b8-..._invoice_2024.pdf'. Return ONLY the filename as uploaded by the user."
  },
  "DocumentBSourceDocument": {
    "type": "string",
    "method": "generate",
    "description": "The original filename (without UUID prefix) of document B where this value was found. Example: 'contract.pdf', NOT 'b4a7651c-..._contract.pdf'. Return ONLY the filename as uploaded by the user."
  }
}
```

**Then simplify code to:**
```typescript
const findFileByFilename = (allFiles, filename) => {
  return allFiles.find(f => f.name === filename);
};
```

### Option B: Tell Azure to Return Full Blob Names

```json
{
  "DocumentASourceDocument": {
    "type": "string",
    "method": "generate",
    "description": "The EXACT blob storage name of document A including UUID prefix. Example: '7543c5b8-903b-466c-95dc-1a920040d10c_invoice_2024.pdf'. This should match the filename as stored in blob storage."
  }
}
```

**Then simplify code to:**
```typescript
const findFileByUuid = (allFiles, blobName) => {
  const uuid = extractUuidFromBlobName(blobName);
  return allFiles.find(f => f.id === uuid);
};
```

### Option C: Add New Field for UUID (Most Explicit)

Add separate fields to schema:

```json
{
  "DocumentASourceDocument": {
    "type": "string",
    "method": "generate",
    "description": "The original filename of document A (e.g., 'invoice_2024.pdf')"
  },
  "DocumentAFileId": {
    "type": "string",
    "method": "generate",
    "description": "The UUID/file identifier of document A (e.g., '7543c5b8-903b-466c-95dc-1a920040d10c')"
  }
}
```

**Then code is trivial:**
```typescript
const docA = allFiles.find(f => f.id === inconsistencyData.DocumentAFileId);
```

## Recommendation

### For Now: ✅ Use Multi-Strategy (Already Implemented)

The code I just updated handles **both cases automatically**:
- Works if Azure returns blob names with UUIDs
- Works if Azure returns just filenames
- Provides clear logging to see which strategy worked

### For Future: Consider Schema Update (Option C)

If you control the schema and want the cleanest solution:

1. Add `DocumentAFileId` and `DocumentBFileId` to schema
2. Tell Azure to output the UUID directly
3. Simplify code to direct UUID matching

## Testing the Current Implementation

### Test Case 1: Azure Returns Blob Names
```
Input: "7543c5b8-903b-466c-95dc-1a920040d10c_invoice.pdf"
Strategy 1: Extract UUID → "7543c5b8-..." → Match to file.id ✅
```

### Test Case 2: Azure Returns Filenames
```
Input: "invoice.pdf"
Strategy 1: No UUID found → Skip
Strategy 2: Direct match → file.name === "invoice.pdf" ✅
```

### Test Case 3: Case Mismatch
```
Input: "Invoice.PDF"
Strategy 1-3: No match
Strategy 4: Case-insensitive → "invoice.pdf" ✅
```

## Console Logging

You'll see which strategy worked:

```javascript
[findFileByAzureResponse] ✅ Strategy 1: UUID match: {
  azureFilename: "7543c5b8-..._invoice.pdf",
  extractedUuid: "7543c5b8-...",
  matchedFile: { id: "7543c5b8-...", name: "invoice.pdf" }
}
```

OR

```javascript
[findFileByAzureResponse] ✅ Strategy 2: Direct filename match: {
  azureFilename: "invoice.pdf",
  matchedFile: { id: "7543c5b8-...", name: "invoice.pdf" }
}
```

## Summary

| Approach | Pros | Cons | Status |
|----------|------|------|--------|
| **Multi-Strategy Matching** | Handles both cases, defensive, no schema changes | More complex | ✅ Implemented |
| **Schema: Original Filename** | Simple code, clear intent | Requires schema update, may have name collisions | Option |
| **Schema: Blob Name** | Simple code, UUID-based (unique) | Requires schema update | Option |
| **Schema: Separate UUID Field** | Cleanest, most explicit | Requires schema update, extra field | Best for future |

The current implementation is **production-ready** and will work regardless of what Azure returns! 🎉
