# 🔍 Partitioned Blob URL Issue - Diagnostic Guide

## 📍 EXACT ISSUE LOCATION FOUND

### **Root Cause**
The Partitioned Blob URL error occurs because:
1. **Blob URL created in main context** (line 276 in `FileComparisonModal.tsx`)
2. **Blob URL passed to iframe** (lines 757, 776 in `FileComparisonModal.tsx`)
3. **Browser blocks cross-partition access** between parent window and iframe

---

## 🎯 Affected Files & Lines

### **Primary Issue: FileComparisonModal.tsx**

#### **Location 1: Blob URL Creation** (Line 276)
```tsx
File: FileComparisonModal.tsx
Line: 276
Code: const objectUrl = URL.createObjectURL(blob);

Context:
const createAuthenticatedBlobUrl = async (file: ProModeFile) => {
  try {
    const response = await httpUtility.headers(relativePath);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);  // ⚠️ CREATED HERE
    return { url: objectUrl, mimeType: contentType, filename: getDisplayFileName(file) };
  }
}
```

#### **Location 2: Blob URL Used in iframe** (Line 757)
```tsx
File: FileComparisonModal.tsx
Line: 757
Code: (iframes[index] as HTMLIFrameElement).src = `${blob.url}#page=${jumpPage}`;

Context:
<Button onClick={() => {
  const iframes = window.document.querySelectorAll('iframe');
  if (iframes && iframes[index]) {
    (iframes[index] as HTMLIFrameElement).src = `${blob.url}#page=${jumpPage}`;
                                                 ^^^^^^^^^ ⚠️ USED IN IFRAME
  }
}}>Jump to page {jumpPage}</Button>
```

#### **Location 3: Blob URL Passed to ProModeDocumentViewer** (Lines 774-776)
```tsx
File: FileComparisonModal.tsx
Lines: 774-776
Code: urlWithSasToken={blob.url}

Context:
<ProModeDocumentViewer
  metadata={{ mimeType: blob.mimeType, filename: blob.filename }}
  urlWithSasToken={blob.url}  // ⚠️ PASSED TO COMPONENT
  iframeKey={index}
/>
```

#### **Location 4: iframe Rendering** (Line 341 in EnhancedDocumentViewer.tsx)
```tsx
File: EnhancedDocumentViewer.tsx
Line: 341
Code: <iframe src={documentUrl} ... />

Context:
<iframe
  ref={documentRef}
  src={documentUrl}  // ⚠️ documentUrl = blob.url from parent context
  width="100%"
  height="100%"
  title="PDF Document"
/>
```

---

## 🔍 How to Locate the Issue in Browser DevTools

### **Step 1: Open Browser Console**
1. Open your app in Chrome/Edge
2. Press `F12` to open DevTools
3. Go to **Console** tab

### **Step 2: Look for the Error**
You'll see something like:
```
Access to the Blob URL blob:https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/a4184d6f-3f7d-490b-bf87-d3492cb463bb was blocked because it was performed from a cross-partition context.
```

### **Step 3: Identify the Stack Trace**
Click on the error to expand the stack trace. You'll see:
```
at HTMLIFrameElement.src (FileComparisonModal.tsx:757)
at ProModeDocumentViewer (ProModeDocumentViewer.tsx:39)
```

### **Step 4: Check Network Tab**
1. Go to **Network** tab
2. Filter by "Blob"
3. Look for failed requests with blob: URLs

### **Step 5: Check Application Tab**
1. Go to **Application** tab
2. Expand **Frames** in left sidebar
3. You'll see:
   - **top** (main window)
   - **iframe** (nested context)
4. The Blob URL is created in "top" but accessed in "iframe" ⚠️

---

## 🧪 Test to Reproduce the Issue

### **Quick Test in Browser Console**

Run this in your browser console when on the file comparison page:

```javascript
// Test 1: Check if Blob URLs are being created
console.log('Current Blob URLs:', 
  Array.from(document.querySelectorAll('iframe'))
    .map(iframe => iframe.src)
    .filter(src => src.startsWith('blob:'))
);

// Test 2: Check partition context
console.log('Main window origin:', window.origin);
console.log('Iframe origins:', 
  Array.from(document.querySelectorAll('iframe'))
    .map(iframe => {
      try {
        return iframe.contentWindow?.location.origin || 'cross-origin';
      } catch (e) {
        return 'access-denied';
      }
    })
);

// Test 3: Try to access a blob URL from iframe (will fail)
const iframe = document.querySelector('iframe');
if (iframe && iframe.src.startsWith('blob:')) {
  console.log('⚠️ Blob URL in iframe detected:', iframe.src);
  console.log('This will cause the partition error!');
}
```

---

## 🎯 Step-by-Step Debugging Process

### **Step 1: Add Console Logs**

Add these logs to **FileComparisonModal.tsx**:

```tsx
// At line 276, after createObjectURL
const objectUrl = URL.createObjectURL(blob);
console.log('[DEBUG] Blob URL created in MAIN context:', objectUrl);
console.log('[DEBUG] Will be used in iframe - this causes partition issue!');
```

```tsx
// At line 757, in the Button onClick
console.log('[DEBUG] Attempting to set iframe src to:', `${blob.url}#page=${jumpPage}`);
console.log('[DEBUG] This will fail due to partition!');
```

### **Step 2: Monitor Network Requests**

1. Open DevTools → Network tab
2. Click "File Comparison" or open a file
3. Watch for:
   - ✅ Successful: `/pro-mode/files/{id}/preview` (actual file fetch)
   - ❌ Failed: `blob:https://...` (partition error)

### **Step 3: Check Console for Partition Warnings**

Look for these specific messages:
```
⚠️ Fetching Partitioned Blob URL Issue
⚠️ Access to the Blob URL blob:https://... was blocked
```

### **Step 4: Inspect iframe Elements**

In DevTools → Elements tab:
```html
<iframe src="blob:https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/a4184d6f-3f7d-490b-bf87-d3492cb463bb#zoom=page-width">
            ^^^^^^ This is the problem - blob URL created in parent context
</iframe>
```

---

## 📊 Visual Flow of the Problem

```
┌─────────────────────────────────────────────────────────────┐
│ Main Window Context (Parent)                                │
│                                                              │
│  1. User clicks "Compare Files"                             │
│     ↓                                                        │
│  2. createAuthenticatedBlobUrl() called                     │
│     ↓                                                        │
│  3. Fetch file from API                                     │
│     ↓                                                        │
│  4. response.blob() creates Blob                            │
│     ↓                                                        │
│  5. URL.createObjectURL(blob)                               │
│     → Creates: blob:https://.../a4184d6f-...                │
│     → Blob URL SCOPED to Main Window Context ⚠️             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Pass blob.url to child
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ iframe Context (Child)                                       │
│                                                              │
│  6. <ProModeDocumentViewer urlWithSasToken={blob.url} />    │
│     ↓                                                        │
│  7. Renders: <iframe src={blob.url} />                      │
│     ↓                                                        │
│  8. iframe tries to load blob:https://.../a4184d6f-...      │
│     ↓                                                        │
│  9. ❌ BROWSER BLOCKS ACCESS                                 │
│     → "Blob URL was blocked because it was performed         │
│        from a cross-partition context"                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Quick Diagnostic Commands

### **Command 1: Find All Blob URL Usage**
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939
grep -r "URL.createObjectURL" code/content-processing-solution-accelerator/src --include="*.tsx" --include="*.ts" -n
```

### **Command 2: Find All iframe Usage**
```bash
grep -r "<iframe" code/content-processing-solution-accelerator/src --include="*.tsx" -n
```

### **Command 3: Find Where Blob URLs Are Passed to iframes**
```bash
grep -r "urlWithSasToken.*blob" code/content-processing-solution-accelerator/src --include="*.tsx" -n
```

---

## 🎯 Summary: Exact Issue Location

| Component | File | Line | What Happens |
|-----------|------|------|--------------|
| **Blob Creation** | `FileComparisonModal.tsx` | 276 | `URL.createObjectURL(blob)` creates blob URL in MAIN context |
| **Blob Pass-through** | `FileComparisonModal.tsx` | 774-776 | Passes `blob.url` to ProModeDocumentViewer |
| **iframe Render** | `ProModeDocumentViewer.tsx` | 39-51 | Renders `<iframe src={documentUrl}>` where documentUrl is the blob URL |
| **Browser Block** | Browser (Runtime) | N/A | Browser blocks cross-partition blob URL access |

---

## 🚨 Why This Happens

### **Browser Security Feature: Partitioned Storage**

Modern browsers (Chrome 115+, Edge) partition storage and blob URLs by context to prevent:
1. **Cross-site tracking**
2. **Data leakage between contexts**
3. **Security vulnerabilities**

When you create a Blob URL in the **main window** and try to use it in an **iframe**, the browser sees them as **different partitions** even though they're same-origin.

---

## ✅ Next Steps

Now that you know the exact location, you can:

1. **Option A**: Use direct HTTP URLs instead of Blob URLs for iframes
2. **Option B**: Create Blob URLs inside the iframe context
3. **Option C**: Use inline data (base64) for small files
4. **Option D**: Use Storage Access API (requires user permission)

See the next document for implementation solutions: `BLOB_URL_PARTITION_FIX.md`

---

**Diagnostic Summary:**
- ✅ Issue Located: `FileComparisonModal.tsx` line 276 → 757/776
- ✅ Root Cause: Blob URL created in main context, used in iframe
- ✅ Browser: Partitioned storage blocks cross-context blob access
- ✅ Fix Required: Avoid passing blob URLs to iframes

---

*Last Updated: October 16, 2025*
*Status: Issue fully diagnosed, ready for fix implementation*
