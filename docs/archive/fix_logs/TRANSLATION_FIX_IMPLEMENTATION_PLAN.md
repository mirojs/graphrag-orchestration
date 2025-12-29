# Translation Fix Implementation Plan

## Summary

**Found:** FilesTab.tsx and PredictionTab.tsx have `useTranslation()` imported and `const { t } = useTranslation()` declared, but **NEVER use the `t()` function**.

All text is hardcoded in English.

---

## FilesTab.tsx - Strings to Replace

### Priority 1: User-Visible Text (High Priority)

| Line | Current (Hardcoded) | Should Be | Translation Key |
|------|---------------------|-----------|-----------------|
| 711 | `Upload` | `{t('proMode.files.upload')}` | proMode.files.upload |
| 895 | `Upload` | `{t('proMode.files.upload')}` | proMode.files.upload |
| 702 | `Input Files (...)` | `{t('proMode.files.inputFiles')} (...)` | proMode.files.inputFiles |
| 716 | `"Input Files Table"` | `{t('proMode.files.inputFiles')}` | proMode.files.inputFiles |
| 749 | `Uploaded` | `{t('proMode.files.uploaded')}` | proMode.files.uploaded |
| 929 | `Uploaded` | `{t('proMode.files.uploaded')}` | proMode.files.uploaded |
| 854 | `No input files uploaded yet` | `{t('proMode.files.noInputFiles')}` | proMode.files.noInputFiles |
| 856 | `Click "Upload Input Files" to add files...` | `{t('proMode.files.noInputFilesMessage')}` | proMode.files.noInputFilesMessage |
| 1025 | `No reference files uploaded yet` | `{t('proMode.files.noReferenceFiles')}` | proMode.files.noReferenceFiles |
| 1027 | `Click "Upload Reference Files" to add...` | `{t('proMode.files.noReferenceFilesMessage')}` | proMode.files.noReferenceFilesMessage |

### Additional Strings to Check:

- Table headers: Name, Size, Actions
- Button labels: Delete Selected, Download Selected
- Reference Files header
- Input Files header

---

## PredictionTab.tsx - Strings to Replace

Need to search for:
- "Analyze" button
- "Analyzing..." text
- "No prediction results yet"
- "Select Files"
- "Select Schema"
- Table/results headers

---

## Options for Implementation

### Option 1: Automated Fix (Recommended)
I can automatically replace all hardcoded strings with proper `t()` calls in both files.

**Pros:**
- Fast and complete
- Consistent with SchemaTab
- All 7 languages will work immediately

**Cons:**
- Large number of changes
- You won't see each individual change

---

### Option 2: Manual Review
I provide you with a detailed line-by-line change list, and you approve each one.

**Pros:**
- Full control and visibility
- Can verify each change

**Cons:**
- Time-consuming (50+ strings to replace)
- Tedious

---

### Option 3: Show Sample First
I fix a few key strings in FilesTab first, you test, then I fix the rest.

**Pros:**
- Can verify approach works
- Gradual implementation

**Cons:**
- Partial translations until all done
- Multiple deployment cycles

---

## Recommended Approach: Option 1 - Automated Fix

I'll replace all hardcoded strings in both FilesTab.tsx and PredictionTab.tsx with proper translation calls.

**Changes will include:**
1. Replace `"Upload"` → `{t('proMode.files.upload')}`
2. Replace `"Input Files"` → `{t('proMode.files.inputFiles')}`
3. Replace `"Reference Files"` → `{t('proMode.files.referenceFiles')}`
4. Replace `"Uploaded"` → `{t('proMode.files.uploaded')}`
5. Replace `"No input files uploaded yet"` → `{t('proMode.files.noInputFiles')}`
6. And ~40+ more similar changes

---

## Testing After Fix

Once fixed, test with:
1. Switch to Spanish → Should see "Archivos", "Subir", etc.
2. Switch to French → Should see "Fichiers", "Télécharger", etc.
3. All 7 languages should work on Files and Prediction tabs

---

## Decision Point

**What would you like me to do?**

A) Go ahead with automated fix (replace all strings in both files)
B) Show me a sample of the first 5-10 changes
C) Create detailed change list for manual review  
D) Something else

Let me know and I'll proceed!

---

**Estimated Time:**
- Option A (Automated): ~5-10 minutes to implement all changes
- Option B (Sample): ~2 minutes to show sample + feedback loop
- Option C (Manual): ~30 minutes to document + your review time

**Recommended:** Option A for fastest, complete solution
