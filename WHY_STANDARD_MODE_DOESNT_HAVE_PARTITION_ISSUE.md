# Why Standard Mode Doesn't Have the Blob URL Partition Issue

## Date: October 18, 2025

## User Question
> "The standard mode does not have the same issue. Is it because the window is narrow so the thumbnail was not displayed?"

## Answer: No, it's about DOM Context, Not Window Width

### The Real Reason Standard Mode Works

Standard Mode **also creates blob URLs** (in `rightPanelSlice.ts` line 27):
```typescript
const blob = await response.blob();
const blobURL = URL.createObjectURL(blob);  // ✅ Creates blob URL in MAIN context
```

But it **doesn't have the partition issue** because:

```
Standard Mode Flow (Works ✅):
┌────────────────────────────────────────┐
│ 1. Main Window Context                 │
│    - Create blob URL                   │
│    - URL.createObjectURL(blob)         │
│    Partition: MAIN (A)                 │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│ 2. Render DocumentViewer               │
│    - Direct child in DOM tree          │
│    - NOT in React Portal               │
│    Partition: MAIN (A) ✅ SAME         │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│ 3. iframe loads blob URL               │
│    - <iframe src={blobURL} />          │
│    Partition: MAIN (A) ✅ SAME         │
│    Result: ✅ ACCESS GRANTED           │
└────────────────────────────────────────┘
```

### Why Pro Mode Had the Issue (Before Fix)

```
Pro Mode Flow (Failed ❌):
┌────────────────────────────────────────┐
│ 1. Main Window Context                 │
│    - Create blob URL                   │
│    - URL.createObjectURL(blob)         │
│    Partition: MAIN (A)                 │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│ 2. Render FileComparisonModal          │
│    - Uses Fluent UI <Dialog>           │
│    - Rendered via createPortal()       │
│    - Target: document.body             │
│    Partition: PORTAL (B) ❌ DIFFERENT  │
└────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────┐
│ 3. iframe tries to load blob URL       │
│    - <iframe src={blobURL} />          │
│    - Blob URL from partition A         │
│    - iframe in partition B             │
│    Result: ❌ ACCESS BLOCKED           │
│    Error: "cross-partition context"    │
└────────────────────────────────────────┘
```

## Key Technical Differences

| Aspect | Standard Mode | Pro Mode (Before Fix) | Pro Mode (After Fix) |
|--------|---------------|----------------------|---------------------|
| **Blob URL Creation** | ✅ Yes (`rightPanelSlice.ts`) | ✅ Yes (FilesTab, etc.) | ❌ No (direct URLs) |
| **DOM Context** | Main window | React Portal (Dialog) | React Portal (Dialog) |
| **iframe Location** | Same as blob creation | Different partition | N/A (no blob) |
| **Partition Issue** | ❌ No (same partition) | ✅ Yes (cross-partition) | ❌ No (no blob URLs) |
| **Thumbnails Shown** | Depends on PDF viewer | Depends on PDF viewer | Hidden via #pagemode=none |

## Why It's NOT About Window Width

The thumbnail sidebar visibility is controlled by:
1. **Browser's native PDF viewer settings** (user preference)
2. **PDF open parameters** like `#pagemode=none`
3. **Available screen space** (browser decides)

But the **partition blocking error** is completely independent of thumbnails:
- Even if thumbnails are hidden, the partition error would still occur
- Even in a wide window, Standard Mode works because it's in the same partition

## Our Solution: Better Than Both

Instead of relying on partition context (like Standard Mode does), we:

### Eliminated Blob URLs Entirely
```typescript
// OLD (Both Standard and Pro Mode):
const blob = await response.blob();
const blobURL = URL.createObjectURL(blob);  // Memory to manage
return { url: blobURL, ... };

// NEW (Pro Mode after fix):
const relativePath = `/pro-mode/files/${processId}/preview`;
return { url: relativePath, ... };  // Direct URL, no blob
```

### Benefits of Our Approach
1. **No partition issues** - Direct URLs work in any context
2. **No memory management** - No need to revoke blob URLs
3. **Better performance** - No blob creation overhead
4. **Simpler code** - Less cleanup logic needed
5. **Works with portals** - Dialog/Modal context is fine now

## Summary

**Standard Mode doesn't have the issue because:**
- ✅ Blob URL and iframe are in the **same DOM partition** (both in main window)
- ✅ No React Portal involved
- ✅ Direct DOM tree rendering

**Pro Mode had the issue because:**
- ❌ Blob URL created in **main partition**
- ❌ iframe rendered in **portal partition** (Fluent UI Dialog)
- ❌ Chrome 115+ blocks cross-partition blob access

**Our fix is superior because:**
- ✅ No blob URLs at all (use direct API endpoints)
- ✅ Works in any rendering context (portal or not)
- ✅ No memory leaks or cleanup needed
- ✅ Better performance

---

**Conclusion**: The issue was never about window width or thumbnails. It was about **blob URL creation in one partition and iframe rendering in another**. Standard Mode works because it keeps everything in one partition. Our fix works everywhere by avoiding blob URLs entirely.
