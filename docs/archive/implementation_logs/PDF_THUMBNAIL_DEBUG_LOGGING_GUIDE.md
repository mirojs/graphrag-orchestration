# PDF Thumbnail Debugging - Console Logging Added

**Date:** January 21, 2025  
**Status:** 🔍 Debug logging active - Ready for manual testing  
**Build Status:** ✅ Passing

## Problem Report

User reports that PDF thumbnails are **still showing** despite our consolidation and `pagemode=none` fixes. User suspects the issue may be related to **Pro Mode theming changes** applied to the UI.

## Root Cause Analysis

The user is correct — deleting the duplicate `ProModeDocumentViewer.tsx` file alone wouldn't fix the thumbnail visibility issue if:
1. The `getPdfUrl()` function isn't being called
2. Something is overriding the URL after it's set
3. Theme-related CSS or configuration is forcing the PDF sidebar open
4. The browser is caching old iframe src values

## Debug Logging Added

I've added comprehensive console logging to track PDF URL generation at three critical points:

### 1. ProModeDocumentViewer.getPdfUrl() ✅
**File:** `src/ContentProcessorWeb/src/ProModeComponents/ProModeDocumentViewer.tsx`
**Lines:** ~42-64

```typescript
const getPdfUrl = (url: string) => {
    // Always hide the sidebar/thumbnail panel by default
    const params = ['pagemode=none'];
    
    // Add zoom parameter if fitToWidth is enabled
    if (fitToWidth) {
        params.push('zoom=page-width');
    }
    
    // If URL already has fragment parameters, append our parameters
    let finalUrl: string;
    if (url.includes('#')) {
        // URL already has fragments (e.g., #page=5), append our params
        finalUrl = `${url}&${params.join('&')}`;
    } else {
        finalUrl = `${url}#${params.join('&')}`;
    }
    
    console.log('[ProModeDocumentViewer] getPdfUrl:', {
        input: url,
        output: finalUrl,
        fitToWidth,
        hasPriorFragment: url.includes('#')
    });
    
    return finalUrl;
};
```

**What to look for in console:**
- ✅ `input`: Should be the blob URL (e.g., `blob:https://...`)
- ✅ `output`: Should include `#pagemode=none` at minimum
- ✅ `fitToWidth`: Should match the UI setting
- ❌ **If this log doesn't appear** → `getPdfUrl()` is NOT being called (major clue!)

### 2. FileComparisonModal Auto-jump URL ✅
**File:** `src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.tsx`
**Lines:** ~759-764

```typescript
const finalUrl = `${baseUrl}#${params.join('&')}`;
console.log('[FileComparisonModal] Auto-jump URL:', {
    blobUrl: blob.url,
    firstDifferencePage,
    finalUrl,
    params
});
return finalUrl;

// OR if no auto-jump:
console.log('[FileComparisonModal] No auto-jump, using blob URL:', blob.url);
return blob.url;
```

**What to look for in console:**
- ✅ Check if auto-jump triggered (has `firstDifferencePage`)
- ✅ `finalUrl` should include `page=X&pagemode=none`
- ✅ `params` array should contain `pagemode=none`
- ⚠️ **If "No auto-jump" appears** → URL will be passed to `ProModeDocumentViewer` without fragments, and `getPdfUrl()` should add them

### 3. FileComparisonModal Jump Button Click ✅
**File:** `src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.tsx`
**Lines:** ~729-736

```typescript
const newUrl = `${baseUrl}#${params.join('&')}`;
console.log('[FileComparisonModal] Jump button click:', {
    jumpPage,
    blobUrl: blob.url,
    newUrl,
    params,
    iframeIndex: index,
    currentSrc: (iframes[index] as HTMLIFrameElement).src
});
(iframes[index] as HTMLIFrameElement).src = newUrl;
```

**What to look for in console:**
- ✅ `newUrl` should include `page=X&pagemode=none`
- ✅ `currentSrc` shows what iframe had before the jump
- ❌ **If thumbnails still appear after jump** → Browser may be ignoring the `pagemode` parameter

---

## Manual Testing Instructions

### Prerequisites
1. Build completed successfully ✅ (already done)
2. Browser console open (F12 → Console tab)
3. Clear browser cache/hard refresh recommended

### Step-by-Step Test Plan

#### Test 1: Files Tab (Pro Mode) PDF Preview
1. Start dev server:
   ```bash
   cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
   yarn start
   ```

2. Navigate to **Pro Mode → Files Tab**

3. Select a **PDF file** from the list

4. **Open browser console** (F12)

5. **Expected console output:**
   ```
   [ProModeDocumentViewer] getPdfUrl: {
     input: "blob:https://.../<uuid>",
     output: "blob:https://.../<uuid>#pagemode=none",
     fitToWidth: false,
     hasPriorFragment: false
   }
   ```

6. **Visual check:**
   - ✅ PDF should load **without** thumbnail sidebar
   - ❌ **If sidebar appears:** Note the console output and check:
     - Does the log appear?
     - Does `output` include `pagemode=none`?
     - Check iframe src in DevTools (Elements → find iframe → check `src` attribute)

#### Test 2: Analysis Tab Case Editing (Pro Mode)
1. Navigate to **Pro Mode → Analysis Tab**

2. Click to **edit/view a case** with PDF attachments

3. **Expected console output:**
   ```
   [ProModeDocumentViewer] getPdfUrl: {
     input: "blob:https://.../<uuid>",
     output: "blob:https://.../<uuid>#pagemode=none",
     ...
   }
   ```

4. **Visual check:**
   - ✅ PDF should load **without** thumbnail sidebar

#### Test 3: Compare Popup (Pro Mode) - Initial Load
1. Navigate to **Pro Mode → Analysis Tab**

2. Click **"Compare"** button for documents with differences

3. **Expected console output:**
   ```
   [FileComparisonModal] Auto-jump URL: {
     blobUrl: "blob:https://.../<uuid>",
     firstDifferencePage: 3,
     finalUrl: "blob:https://.../<uuid>#page=3&pagemode=none",
     params: ["page=3", "pagemode=none"]
   }
   
   [ProModeDocumentViewer] getPdfUrl: {
     input: "blob:https://.../<uuid>#page=3&pagemode=none",
     output: "blob:https://.../<uuid>#page=3&pagemode=none&pagemode=none",
     hasPriorFragment: true,
     ...
   }
   ```

   **⚠️ IMPORTANT BUG SPOTTED:**  
   Notice the **double `pagemode=none`** in the output! This happens because:
   - FileComparisonModal adds `#page=3&pagemode=none`
   - Then ProModeDocumentViewer sees `#` exists and appends `&pagemode=none` again

   **This won't break functionality** (browser will use the first one), but it's redundant.

4. **Visual check:**
   - ✅ PDF should load at the difference page **without** thumbnail sidebar

#### Test 4: Compare Popup - Jump Button Click
1. In the Compare popup, click **"Jump to page X"** button

2. **Expected console output:**
   ```
   [FileComparisonModal] Jump button click: {
     jumpPage: 5,
     blobUrl: "blob:https://.../<uuid>",
     newUrl: "blob:https://.../<uuid>#page=5&pagemode=none",
     params: ["page=5", "pagemode=none"],
     iframeIndex: 0,
     currentSrc: "blob:https://.../<uuid>#page=3&pagemode=none&pagemode=none"
   }
   ```

3. **Visual check:**
   - ✅ PDF should jump to page 5 **without** showing thumbnail sidebar

---

## Potential Issues to Watch For

### Issue 1: `getPdfUrl()` not called
**Symptom:** No `[ProModeDocumentViewer] getPdfUrl:` log in console

**Possible causes:**
- Component not rendering the PDF case (wrong mimeType check)
- `urlWithSasToken` is undefined/null
- Theme changes broke the component lifecycle

**Action:** Check which case is being rendered in `getContentComponent()`

### Issue 2: Double `pagemode=none`
**Symptom:** Output shows `#page=X&pagemode=none&pagemode=none`

**Cause:** FileComparisonModal pre-adds fragment with `pagemode`, then ProModeDocumentViewer sees `#` and appends again

**Fix needed:** Update FileComparisonModal to NOT pass `pagemode=none` when calling ProModeDocumentViewer, let the viewer add it consistently

### Issue 3: Browser ignores `pagemode=none`
**Symptom:** Logs show correct URL with `pagemode=none`, but sidebar still appears

**Possible causes:**
- Browser PDF viewer doesn't support the parameter (unlikely with Chrome/Firefox)
- CSP or iframe sandbox restrictions
- Theme CSS overriding iframe behavior
- Cached iframe state

**Actions to try:**
- Hard refresh (Ctrl+Shift+R / Cmd+Shift+R)
- Test in incognito/private window
- Test in different browser
- Check iframe attributes in DevTools (sandbox, allow, etc.)

### Issue 4: Theme-related CSS interference
**Symptom:** Sidebar appears only after theme changes, logs show correct URLs

**Check:**
- Any global CSS targeting `iframe` elements
- FluentUI theme tokens affecting iframe borders/sizing
- Z-index or overlay issues hiding content
- Check for any CSS that might be injected into the PDF viewer iframe

**Locations to inspect:**
```
src/ContentProcessorWeb/src/ProModeComponents/promode-selection-styles.css
src/ContentProcessorWeb/src/ProModeComponents/ProModeThemeProvider.tsx
src/ContentProcessorWeb/src/index.tsx (FluentProvider theme setup)
```

---

## Quick Reference: What Each Log Means

| Log Prefix | Component | What it Shows | When it Appears |
|------------|-----------|---------------|-----------------|
| `[ProModeDocumentViewer] getPdfUrl:` | ProModeDocumentViewer.tsx | URL transformation (input → output with `#pagemode=none`) | Every time a PDF iframe is rendered |
| `[FileComparisonModal] Auto-jump URL:` | FileComparisonModal.tsx | Initial URL with auto-jump to first difference page | Compare popup opens with PDFs that have differences |
| `[FileComparisonModal] No auto-jump, using blob URL:` | FileComparisonModal.tsx | Fallback when no auto-jump needed | Compare popup opens, no differences found or not a PDF |
| `[FileComparisonModal] Jump button click:` | FileComparisonModal.tsx | Manual page jump via button click | User clicks "Jump to page X" button in Compare popup |

---

## Next Steps

### 1. Run Manual Tests ⏳
Follow the test plan above and collect console logs for each scenario.

### 2. Report Findings 📋
For each location where thumbnails still appear, provide:
- ✅ Which location (Files tab, Analysis tab, Compare popup)
- ✅ Console logs (copy/paste)
- ✅ Screenshot of iframe `src` attribute from DevTools
- ✅ Browser/version being used

### 3. Identify Root Cause 🔍
Based on logs, we can determine:
- Is `getPdfUrl()` being called? → If no, component lifecycle issue
- Does URL include `pagemode=none`? → If no, logic bug
- Does URL reach the iframe? → Check DevTools Elements tab
- Does browser respect the parameter? → Browser/CSP issue

### 4. Apply Targeted Fix 🔧
Once we know the root cause, we can apply the correct fix:
- Component lifecycle → Verify component rendering logic
- Logic bug → Fix URL construction
- Double parameters → Remove redundant `pagemode` addition from FileComparisonModal
- Browser/CSP → Add workaround or PDF.js fallback
- Theme CSS → Remove interfering styles

---

## Known Issue: Double pagemode=none

**Current behavior:**  
FileComparisonModal passes `blob.url#page=3&pagemode=none` to ProModeDocumentViewer, which then sees `#` exists and appends `&pagemode=none` again, resulting in:
```
blob:https://...#page=3&pagemode=none&pagemode=none
```

**Impact:** No functional issue (browser uses first parameter), but redundant and messy.

**Recommended fix:**
Update FileComparisonModal to pass blob URL WITHOUT `pagemode=none`, and rely on ProModeDocumentViewer's `getPdfUrl()` to add it consistently.

**Files to change:**
- `FileComparisonModal.tsx` lines ~750-765 (auto-jump URL builder)

**Change:**
```typescript
// Current (adds pagemode):
if (!params.some(p => p.startsWith('pagemode='))) {
  params.push('pagemode=none');
}

// Proposed (remove pagemode addition, let viewer handle it):
// Remove the pagemode check entirely, only add page= and zoom=
```

This will make FileComparisonModal responsible for page jumping and zoom, while ProModeDocumentViewer is solely responsible for `pagemode=none`.

---

## Browser Console Commands

Useful debugging commands to run in browser console after PDFs load:

### Check all iframe sources
```javascript
Array.from(document.querySelectorAll('iframe')).map((iframe, i) => ({
  index: i,
  src: iframe.src,
  hasPagemode: iframe.src.includes('pagemode')
}))
```

### Check specific iframe (e.g., index 0)
```javascript
document.querySelectorAll('iframe')[0].src
```

### Manually test pagemode parameter
```javascript
// Get first iframe
const iframe = document.querySelectorAll('iframe')[0];
// Get current src
const currentSrc = iframe.src;
// Add pagemode=none if not present
if (!currentSrc.includes('pagemode')) {
  iframe.src = currentSrc + (currentSrc.includes('#') ? '&' : '#') + 'pagemode=none';
  console.log('Added pagemode=none, new src:', iframe.src);
}
```

---

## Files Modified (Debug Logging)

| File | Changes | Lines |
|------|---------|-------|
| `ProModeDocumentViewer.tsx` | Added `console.log` in `getPdfUrl()` | ~42-64 |
| `FileComparisonModal.tsx` | Added `console.log` in auto-jump URL builder | ~759-764 |
| `FileComparisonModal.tsx` | Added `console.log` in jump button handler | ~729-736 |

---

## Expected Outcome

After testing, we should know:
1. ✅ Is the code executing as expected?
2. ✅ Are URLs being generated correctly?
3. ✅ Are iframe `src` attributes set correctly?
4. ❌ If thumbnails still appear despite correct URLs → browser/CSP/theme issue

**Then we can apply a targeted fix instead of guessing.**

---

**Status:** Ready for manual testing  
**Build:** ✅ Passing  
**Next Action:** Run dev server and follow test plan above
