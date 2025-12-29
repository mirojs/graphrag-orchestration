# Blob URL Partition Issue - Visual Explanation

## 🎨 The Root Cause: React Portal Creates Different Partition

```
╔════════════════════════════════════════════════════════════════════════════╗
║                         BROWSER WINDOW (Chrome 115+)                        ║
║                         https://app.example.com                             ║
╠════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐   ║
║  │ Main React App Context (Partition A)                                │   ║
║  │                                                                      │   ║
║  │  const blob = await response.blob();                                │   ║
║  │  const blobURL = URL.createObjectURL(blob);                         │   ║
║  │  // blobURL = "blob:https://app.example.com/abc-123"                │   ║
║  │                                                                      │   ║
║  │  BLOB URL CREATED IN: Partition A ✅                                │   ║
║  └─────────────────────────────────────────────────────────────────────┘   ║
║                                                                              ║
║  ┌────────────────────────────────────────────────────────────────────┐    ║
║  │ SCENARIO 1: FilesTab (Normal DOM) - WORKS ✅                        │    ║
║  │                                                                      │    ║
║  │  <div id="root">                                                    │    ║
║  │    <FilesTab>                                                       │    ║
║  │      <PreviewPanel>                                                 │    ║
║  │        <ProModeDocumentViewer>                                      │    ║
║  │          <iframe src="blob:https://app.example.com/abc-123">       │    ║
║  │            ↑                                                        │    ║
║  │            └─ Accessing blob URL in SAME partition (A) ✅          │    ║
║  │                                                                      │    ║
║  │        </ProModeDocumentViewer>                                     │    ║
║  │      </PreviewPanel>                                                │    ║
║  │    </FilesTab>                                                      │    ║
║  │  </div>                                                             │    ║
║  └──────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  ┌────────────────────────────────────────────────────────────────────┐    ║
║  │ SCENARIO 2: FileComparisonModal (Portal) - FAILS ❌                 │    ║
║  │                                                                      │    ║
║  │  <div id="root">                                                    │    ║
║  │    <FilesTab>                                                       │    ║
║  │      <Button onClick={() => openModal()}>                          │    ║
║  │        Compare Files                                                │    ║
║  │      </Button>                                                      │    ║
║  │    </FilesTab>                                                      │    ║
║  │  </div>                                                             │    ║
║  │                                                                      │    ║
║  │  ┌────────────────────────────────────────────────────────────┐    │    ║
║  │  │ React Portal (Fluent UI Dialog)                            │    │    ║
║  │  │ Rendered at: document.body (Partition B)                   │    │    ║
║  │  │                                                             │    │    ║
║  │  │  <div role="dialog">                                       │    │    ║
║  │  │    <DialogSurface>                                         │    │    ║
║  │  │      <ProModeDocumentViewer>                               │    │    ║
║  │  │        <iframe src="blob:https://app.example.com/abc-123"> │    │    ║
║  │  │          ↑                                                 │    │    ║
║  │  │          └─ Trying to access blob from Partition A        │    │    ║
║  │  │             but iframe is in Partition B ❌                │    │    ║
║  │  │                                                             │    │    ║
║  │  │             Chrome 115+ BLOCKS this!                       │    │    ║
║  │  │             Error: ERR_ACCESS_DENIED                       │    │    ║
║  │  │                                                             │    │    ║
║  │  │        </iframe>                                           │    │    ║
║  │  │      </ProModeDocumentViewer>                              │    │    ║
║  │  │    </DialogSurface>                                        │    │    ║
║  │  │  </div>                                                    │    │    ║
║  │  └────────────────────────────────────────────────────────────┘    │    ║
║  └──────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

## 🔍 Detailed Partition Flow

### FilesTab (Works ✅)

```
Step 1: Create Blob URL
┌─────────────────────────────────┐
│ const blob = new Blob([data])  │
│ const url = URL.createObjectURL│
│                                 │
│ Partition: MAIN (A)             │
│ URL: blob:https://app.com/123   │
└─────────────────────────────────┘
         │
         │ Pass blob URL as prop
         ▼
┌─────────────────────────────────┐
│ <ProModeDocumentViewer          │
│   urlWithSasToken={url}         │
│ />                              │
│                                 │
│ Rendered in: MAIN DOM TREE      │
│ Partition: MAIN (A)             │
└─────────────────────────────────┘
         │
         │ Create iframe
         ▼
┌─────────────────────────────────┐
│ <iframe src={url} />            │
│                                 │
│ Context: MAIN (A)               │
│ Accessing blob from: MAIN (A)   │
│                                 │
│ Result: ✅ ALLOWED              │
│ (Same partition)                │
└─────────────────────────────────┘
```

### FileComparisonModal (Fails ❌)

```
Step 1: Create Blob URL
┌─────────────────────────────────┐
│ const blob = new Blob([data])  │
│ const url = URL.createObjectURL│
│                                 │
│ Partition: MAIN (A)             │
│ URL: blob:https://app.com/123   │
└─────────────────────────────────┘
         │
         │ Pass blob URL as prop
         ▼
┌─────────────────────────────────┐
│ <Dialog> (Fluent UI)            │
│   <DialogSurface>               │
│     <ProModeDocumentViewer      │
│       urlWithSasToken={url}     │
│     />                          │
│   </DialogSurface>              │
│ </Dialog>                       │
│                                 │
│ Rendered via: REACT PORTAL ⚠️   │
│ Target: document.body           │
│ Partition: DIALOG (B) ≠ MAIN(A) │
└─────────────────────────────────┘
         │
         │ Create iframe
         ▼
┌─────────────────────────────────┐
│ <iframe src={url} />            │
│                                 │
│ Context: DIALOG (B)             │
│ Accessing blob from: MAIN (A)   │
│                                 │
│ Result: ❌ BLOCKED              │
│ (Cross-partition access)        │
│                                 │
│ Error: ERR_ACCESS_DENIED        │
└─────────────────────────────────┘
```

## 🎯 The Critical Difference

### Same Partition (FilesTab)
```
Blob Created: Partition A
                ↓
            [blob URL]
                ↓
iframe Access: Partition A
                ↓
          ✅ ALLOWED
```

### Cross Partition (FileComparisonModal)
```
Blob Created: Partition A
                ↓
            [blob URL]
                ↓
            Portal Boundary
                ↓
iframe Access: Partition B
                ↓
          ❌ BLOCKED
```

## 🔧 The Fix

### Before (Broken)
```typescript
// Create blob URL in main context
const blobURL = URL.createObjectURL(blob);

// Use in portal (different partition)
<Dialog>
  <iframe src={blobURL} />  ❌
</Dialog>
```

### After (Fixed)
```typescript
// Use direct API URL (no partition restrictions)
const apiURL = `/pro-mode/files/${processId}/preview`;

// Use in portal (works in any context)
<Dialog>
  <iframe src={apiURL} />  ✅
</Dialog>
```

## 📊 Comparison Matrix

| Aspect | FilesTab | FileComparisonModal |
|--------|----------|---------------------|
| **Blob URL Created In** | Main context (A) | Main context (A) |
| **iframe Rendered In** | Main DOM tree (A) | Portal DOM tree (B) |
| **Partition Match?** | ✅ Yes (A = A) | ❌ No (A ≠ B) |
| **Chrome 115+ Behavior** | ✅ Allows access | ❌ Blocks access |
| **Error Message** | None | ERR_ACCESS_DENIED |

## 🎓 Key Takeaway

**The problem is NOT:**
- ❌ Using blob URLs
- ❌ Using iframes
- ❌ The blob creation process
- ❌ File types or MIME types

**The problem IS:**
- ✅ **React Portal creates a separate partition context**
- ✅ **Chrome 115+ blocks cross-partition blob access**
- ✅ **Fluent UI Dialog uses React Portal internally**

**The solution:**
- 💡 Don't use blob URLs in portal-rendered components
- 💡 Use direct API URLs that work across all contexts
- 💡 Let the browser handle authentication via existing session
