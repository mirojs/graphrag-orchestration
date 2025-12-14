# 🎯 How to Locate the Exact Blob URL Partition Issue

**Date:** October 16, 2025  
**Status:** ✅ Issue Located & Diagnosed  
**Severity:** High (Blocks file viewing in modern browsers)

---

## 📍 Quick Answer

**The exact issue is in:**
- **File:** `FileComparisonModal.tsx`
- **Line 276:** Blob URL created in main window context
- **Lines 757, 774-776:** Blob URL passed to iframe (different partition)
- **Result:** Browser blocks access with partition error

---

## 🔍 Three Ways to Locate the Issue

### **Method 1: Browser DevTools (5 minutes)** ⭐ Recommended

1. **Open your app** in Chrome/Edge
2. **Press F12** to open DevTools
3. **Go to Console tab**
4. **Look for the error:**
   ```
   ⚠️ Fetching Partitioned Blob URL Issue
   Access to the Blob URL blob:https://ca-cps-xh5lwkfq3vfm-web...
   was blocked because it was performed from a cross-partition context.
   ```

5. **Click on the error** to see the stack trace:
   ```
   at HTMLIFrameElement.src (FileComparisonModal.tsx:757)
   at ProModeDocumentViewer (ProModeDocumentViewer.tsx:39)
   ```

6. **Go to Elements tab:**
   - Find `<iframe>` elements
   - Look for `src="blob:https://..."`
   - This is your problematic iframe!

---

### **Method 2: Run Diagnostic Script (2 minutes)** ⚡ Fastest

1. **Open your app**
2. **Open browser console** (F12)
3. **Copy and paste** the detector script from `blob_url_partition_detector.js`
4. **Press Enter** to run

You'll see a detailed report like:
```
🔍 Blob URL Partition Issue Detector
─────────────────────────────────────────
📋 Test 1: Blob URLs in Main Context
  ⚠️  Found 2 Blob URL(s) in main context:
    1. iframes <iframe> → blob:https://ca-cps-xh5lwkfq...
    
🖼️  Test 2: Iframe Blob URL Usage
  ❌ ISSUE DETECTED: 2 iframe(s) using Blob URLs!
    1. iframe[0]:
       Blob URL: blob:https://ca-cps-xh5lwkfq3vfm-web...
       ⚠️  This will cause partition errors!
       
📊 DIAGNOSTIC SUMMARY
─────────────────────────────────────────
Status: ❌ FAIL
Problematic iframes: 2
⚠️  ACTION REQUIRED: Blob URLs in iframes will cause partition errors
```

---

### **Method 3: Search the Code (10 minutes)** 🔎 Most Thorough

Run these commands in your terminal:

```bash
# Navigate to project
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939

# Find all Blob URL creations
grep -rn "URL.createObjectURL" \
  code/content-processing-solution-accelerator/src \
  --include="*.tsx" --include="*.ts"

# Find all iframe usages
grep -rn "<iframe" \
  code/content-processing-solution-accelerator/src \
  --include="*.tsx"

# Find where blob URLs are passed to components
grep -rn "urlWithSasToken.*blob\|blob\.url" \
  code/content-processing-solution-accelerator/src \
  --include="*.tsx"
```

**Results will show:**
```
FileComparisonModal.tsx:276: const objectUrl = URL.createObjectURL(blob);
FileComparisonModal.tsx:757: (iframes[index]).src = `${blob.url}#page=${jumpPage}`;
FileComparisonModal.tsx:776: urlWithSasToken={blob.url}
```

---

## 🎯 Exact Code Locations

### **Location 1: Blob URL Creation** ⚠️

```typescript
File: code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.tsx
Line: 276

const createAuthenticatedBlobUrl = async (file: ProModeFile) => {
  try {
    let processId = file.process_id || file.id;
    if (typeof processId === 'string' && processId.includes('_')) 
      processId = processId.split('_')[0];
    
    const relativePath = `/pro-mode/files/${processId}/preview`;
    const response = await httpUtility.headers(relativePath);
    if (!response.ok) throw new Error(`Failed to fetch file: ${response.status}`);
    
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);  // ⚠️ CREATED HERE (Main Context)
    
    const contentType = response.headers.get('content-type') || 'application/octet-stream';
    return { 
      url: objectUrl,  // This blob URL is scoped to main window
      mimeType: contentType, 
      filename: getDisplayFileName(file) 
    };
  } catch (e) {
    console.error('[FileComparisonModal] Failed to create authenticated blob URL:', e);
    return null;
  }
};
```

**Why it's a problem:**
- Blob URL is created in the **main window context**
- It's scoped to that specific partition
- Cannot be accessed from iframes (different partition)

---

### **Location 2: Blob URL Passed to iframe** ❌

```typescript
File: code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.tsx
Lines: 774-780

<ProModeDocumentViewer
  metadata={{ mimeType: blob.mimeType, filename: blob.filename }}
  urlWithSasToken={(() => {
    const jumpPage = documentPageNumbers.get(document.id);
    if (blob.mimeType === 'application/pdf' && jumpPage) {
      return `${blob.url}#page=${jumpPage}`;  // ⚠️ BLOB URL PASSED HERE
    }
    return blob.url;  // ⚠️ BLOB URL PASSED HERE
  })()}
  iframeKey={index}
  fitToWidth={fitToWidth}
/>
```

**What happens:**
- `blob.url` (created in main context) is passed to component
- Component renders an iframe with this URL
- Browser sees it as cross-partition access
- **Result: Blocked!**

---

### **Location 3: iframe Rendering** 🖼️

```typescript
File: code/content-processing-solution-accelerator/src/ProModeComponents/ProModeDocumentViewer.tsx
Lines: 39-51

<iframe
  key={iframeKey}
  src={urlWithSasToken}  // ⚠️ urlWithSasToken = blob.url from parent
  width="100%"
  height="100%"
  style={{ border: 'none' }}
  title="Document Preview"
/>
```

**Final stage:**
- iframe tries to load `blob:https://...`
- Browser checks: "Was this blob URL created in this partition?"
- Answer: No, it was created in parent window
- **Result: Access Denied**

---

## 🧪 Visual Debugging Steps

### **Step-by-Step in Browser:**

#### **1. Open the File Comparison View**
```
Your App → Pro Mode → Files Tab → Compare Files
```

#### **2. Open DevTools (F12)**
```
Console tab → Look for red errors
Elements tab → Inspect <iframe> elements
Network tab → Filter by "blob:"
```

#### **3. Check Console for Error**
You should see:
```
⚠️ Fetching Partitioned Blob URL Issue
Blob URL issues count: 1

Access to the Blob URL blob:https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/a4184d6f-3f7d-490b-bf87-d3492cb463bb#zoom=page-width was blocked because it was performed from a cross-partition context.

Learn more: https://developer.chrome.com/blog/partitioning-blobs/
```

#### **4. Inspect iframe Element**
```html
<iframe 
  src="blob:https://ca-cps-xh5lwkfq3vfm-web.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/a4184d6f-3f7d-490b-bf87-d3492cb463bb#zoom=page-width"
  width="100%" 
  height="100%"
  title="Document Preview">
</iframe>
```

The `src` attribute shows the blob URL that's causing the issue!

#### **5. Check Network Tab**
```
Filter: "blob:"
Status: (failed) - Red X
Type: Other
Initiator: FileComparisonModal.tsx:757
```

---

## 📊 Understanding the Problem

### **What is Storage Partitioning?**

```
┌─────────────────────────────────────────────────┐
│ Main Window (ca-cps-xh5lwkfq3vfm-web...)       │
│                                                 │
│ Storage Partition A                            │
│ ├─ LocalStorage                                │
│ ├─ SessionStorage                              │
│ ├─ IndexedDB                                   │
│ └─ Blob URLs                                   │
│    └─ blob://a4184d6f-3f7d-490b... ✅          │
│                                                 │
│  ┌──────────────────────────────────────────┐  │
│  │ <iframe> (nested context)                │  │
│  │                                          │  │
│  │ Storage Partition B                     │  │
│  │ ├─ LocalStorage (separate)              │  │
│  │ ├─ SessionStorage (separate)            │  │
│  │ └─ Blob URLs (separate partition)       │  │
│  │    └─ Cannot access parent's blobs ❌   │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### **Why It's Blocked**

1. **Security:** Prevents cross-context data leakage
2. **Privacy:** Stops tracking across contexts
3. **Spec Compliance:** Following modern web standards

---

## 🎯 Quick Verification Test

Run this in your browser console:

```javascript
// Test if you have the issue
const iframes = document.querySelectorAll('iframe');
const blobIframes = Array.from(iframes).filter(f => f.src.startsWith('blob:'));

if (blobIframes.length > 0) {
  console.log('❌ ISSUE FOUND!');
  console.log(`${blobIframes.length} iframe(s) using Blob URLs`);
  blobIframes.forEach((iframe, i) => {
    console.log(`iframe[${i}]: ${iframe.src}`);
  });
} else {
  console.log('✅ No issue detected');
}
```

---

## 📋 Checklist: Confirming the Issue

- [ ] Error appears in Chrome/Edge console
- [ ] Error message mentions "Partitioned Blob URL"
- [ ] Error references `FileComparisonModal.tsx`
- [ ] `<iframe>` elements have `blob:` URLs as `src`
- [ ] Issue occurs when viewing/comparing files
- [ ] Works in older browsers but not Chrome 115+

If you checked all items, **you definitely have this issue!**

---

## 🚀 Next Steps

Now that you've located the issue, see these documents for solutions:

1. **`BLOB_URL_PARTITION_DIAGNOSTIC.md`** - Full technical explanation
2. **`BLOB_URL_PARTITION_FIX.md`** - Implementation solutions
3. **`blob_url_partition_detector.js`** - Diagnostic tool

---

## 💡 Quick Fix Preview

The simplest fix is to **stop using Blob URLs for iframes**:

**Before (Broken):**
```typescript
const blob = await response.blob();
const objectUrl = URL.createObjectURL(blob);  // ❌
return { url: objectUrl, ... };
```

**After (Fixed):**
```typescript
// Option 1: Use direct API URL
return { 
  url: `/pro-mode/files/${processId}/preview`,  // ✅
  ...
};

// Option 2: Use data URL for small files
const arrayBuffer = await response.arrayBuffer();
const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));
return {
  url: `data:${mimeType};base64,${base64}`,  // ✅
  ...
};
```

---

## 📞 Summary

| Question | Answer |
|----------|--------|
| **Where is the issue?** | `FileComparisonModal.tsx` lines 276, 757, 776 |
| **What causes it?** | Blob URL created in main context, used in iframe |
| **Why does it fail?** | Browser blocks cross-partition blob access |
| **How to detect?** | Check console for "Partitioned Blob URL" error |
| **How to verify?** | Run `blob_url_partition_detector.js` script |
| **How to fix?** | Use direct URLs or data URLs instead of Blob URLs |

---

**Status:** ✅ Issue fully located and understood  
**Next:** Implement one of the fix options from `BLOB_URL_PARTITION_FIX.md`

---

*Last Updated: October 16, 2025*
