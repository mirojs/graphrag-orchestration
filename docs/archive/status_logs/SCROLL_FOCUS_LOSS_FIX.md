# 🐛 Scroll Focus Loss Issue - Root Cause & Fix

## Problem Description

**User Reports:**
1. Upon clicking case dropdown → page scrolls to top
2. Upon analysis completion → page scrolls to top
3. User loses their view focus

## Root Cause Analysis

### Issue 1: Case Dropdown Selection

**File:** `CaseSelector.tsx` (line 112)
```tsx
const handleCaseSelect = (_event: any, data: any) => {
  const caseId = data.optionValue;
  dispatch(selectCase(caseId || null) as any);  // ← Triggers Redux update
};
```

**Chain Reaction:**
1. User clicks dropdown option
2. `dispatch(selectCase())` updates Redux state
3. Redux update triggers re-render in `PredictionTab.tsx`
4. `useEffect` with `currentCase` dependency fires (line 172)
5. Effect dispatches multiple actions: `setSelectedInputFiles`, `setSelectedReferenceFiles`, `setActiveSchema`
6. Each dispatch causes additional re-renders
7. React reconciliation + browser scroll restoration = **scroll to top**

### Issue 2: Analysis Completion

**File:** `PredictionTab.tsx` (lines 680-700)
```tsx
// After analysis completes:
toast.success(t('proMode.prediction.toasts.analysisCompletedSuccess'));
console.log('[PredictionTab] ✅ Analysis completed successfully...');
return; // ← Function exits, component re-renders
```

**Chain Reaction:**
1. Analysis async thunk completes
2. Redux state updates with results
3. Component re-renders to show results
4. Large DOM changes (new tables, cards rendering)
5. Browser attempts scroll restoration
6. **Scroll to top occurs**

## Technical Deep Dive

### Why Scroll Position Lost

React + Redux re-renders can cause scroll loss due to:

1. **Virtual DOM Reconciliation**
   - Large changes to DOM structure
   - React unmounts/remounts components
   - Browser loses scroll anchor

2. **State Updates Cascade**
   ```
   User Action
     → Redux Dispatch
       → useEffect Fires
         → More Dispatches
           → More useEffects
             → Multiple Re-renders
               → Scroll Lost
   ```

3. **Browser Behavior**
   - Some browsers auto-scroll to focused element
   - Dropdown loses focus after selection
   - Focus moves to document body
   - Body scroll position = 0 (top)

## Solutions

### Fix 1: Preserve Scroll on Case Selection ✅

**File:** `ProModeComponents/PredictionTab.tsx`

**Add scroll preservation to useEffect (line 172):**

```tsx
// 🔄 AUTO-POPULATE FILES AND SCHEMA WHEN CASE IS SELECTED
useEffect(() => {
  if (currentCase) {
    // 🎯 SCROLL FIX: Save current scroll position BEFORE state updates
    const scrollY = window.scrollY;
    const scrollX = window.scrollX;
    
    console.log('[PredictionTab] 📁 Case selected, auto-populating files and schema:', currentCase.case_id);
    console.log('[PredictionTab] 📍 Saving scroll position:', { x: scrollX, y: scrollY });
    
    // Map file names to file IDs
    const inputFileIds = allInputFiles
      .filter((f: any) => currentCase.input_file_names.includes(f.fileName || f.name))
      .map((f: any) => f.id);
    
    const referenceFileIds = allReferenceFiles
      .filter((f: any) => currentCase.reference_file_names.includes(f.fileName || f.name))
      .map((f: any) => f.id);
    
    // Find schema by name
    const schema = allSchemas.find((s: any) => 
      (s.name === currentCase.schema_name) || (s.id === currentCase.schema_name)
    );
    const schemaId = schema?.id || null;
    
    console.log('[PredictionTab] ✅ Auto-populating:', {
      inputFileIds: inputFileIds.length,
      referenceFileIds: referenceFileIds.length,
      schemaId: schemaId
    });
    
    // Dispatch actions to update Redux state
    if (inputFileIds.length > 0) {
      dispatch(setSelectedInputFiles(inputFileIds));
    }
    
    if (referenceFileIds.length > 0) {
      dispatch(setSelectedReferenceFiles(referenceFileIds));
    }
    
    if (schemaId) {
      dispatch(setActiveSchema(schemaId));
    }
    
    toast.success(`Case "${currentCase.case_name}" loaded successfully`, { autoClose: 3000 });
    
    // 🎯 SCROLL FIX: Restore scroll position AFTER all state updates
    // Use requestAnimationFrame to ensure DOM has updated
    requestAnimationFrame(() => {
      window.scrollTo(scrollX, scrollY);
      console.log('[PredictionTab] 📍 Scroll position restored:', { x: scrollX, y: scrollY });
    });
  }
}, [currentCase, allInputFiles, allReferenceFiles, allSchemas, dispatch]);
```

**Why This Works:**
- ✅ Captures scroll position BEFORE any state changes
- ✅ Lets React complete all re-renders
- ✅ Uses `requestAnimationFrame` to restore AFTER DOM updates
- ✅ Preserves exact user position

### Fix 2: Preserve Scroll on Analysis Completion ✅

**File:** `ProModeComponents/PredictionTab.tsx`

**Option A: Simple scroll preservation (RECOMMENDED)**

Add to the end of both analysis handlers before `return`:

**For Standard Analysis (around line 700):**
```tsx
// Results will persist until user starts a new analysis
console.log('[PredictionTab] ✅ Analysis completed successfully. Results will remain visible until next analysis.');

// 🎯 SCROLL FIX: Preserve scroll position after analysis completion
const currentScrollY = window.scrollY;
const currentScrollX = window.scrollX;
requestAnimationFrame(() => {
  window.scrollTo(currentScrollX, currentScrollY);
  console.log('[PredictionTab] 📍 Scroll preserved after analysis completion');
});

return;
```

**For Orchestrated Analysis (around line 935):**
```tsx
console.log('[PredictionTab] ✅ Orchestrated analysis completed successfully. Results will remain visible until next analysis.');

// 🎯 SCROLL FIX: Preserve scroll position after analysis completion
const currentScrollY = window.scrollY;
const currentScrollX = window.scrollX;
requestAnimationFrame(() => {
  window.scrollTo(currentScrollX, currentScrollY);
  console.log('[PredictionTab] 📍 Scroll preserved after orchestrated analysis completion');
});

return;
```

**For Quick Query (around line 316):**
```tsx
console.log('[PredictionTab] ✅ Quick Query analysis completed successfully');

// 🎯 SCROLL FIX: Preserve scroll position after quick query completion
const currentScrollY = window.scrollY;
const currentScrollX = window.scrollX;
requestAnimationFrame(() => {
  window.scrollTo(currentScrollX, currentScrollY);
  console.log('[PredictionTab] 📍 Scroll preserved after quick query completion');
});

return; // Analysis already complete, no polling needed
```

**Option B: Smart scroll to results (ALTERNATIVE)**

Instead of preserving position, scroll to show the NEW results:

```tsx
// 🎯 SMART SCROLL: Show results without losing context
const scrollToResults = () => {
  // Find the results container (adjust selector as needed)
  const resultsContainer = document.querySelector('[data-results-container]');
  if (resultsContainer) {
    resultsContainer.scrollIntoView({ 
      behavior: 'smooth', 
      block: 'start',
      inline: 'nearest'
    });
  }
};

requestAnimationFrame(scrollToResults);
```

### Fix 3: Prevent Dropdown Scroll Loss ✅

**File:** `ProModeComponents/CaseManagement/CaseSelector.tsx`

**Update dropdown to prevent focus loss:**

```tsx
{/* Case Dropdown */}
<Dropdown
  className={styles.dropdown}
  placeholder={t('proMode.prediction.caseManagement.selectCase')}
  value={getSelectedCaseName()}
  onOptionSelect={handleCaseSelect}
  disabled={loading}
  // 🎯 SCROLL FIX: Prevent dropdown from losing focus and causing scroll
  positioning="below"  // Keep dropdown in place
  onOpenChange={(e, data) => {
    // Preserve scroll when dropdown opens/closes
    if (!data.open) {
      const scrollY = window.scrollY;
      const scrollX = window.scrollX;
      requestAnimationFrame(() => {
        window.scrollTo(scrollX, scrollY);
      });
    }
  }}
>
```

## Alternative Solutions

### Global Scroll Preservation Hook

Create a reusable hook for any component:

**File:** `ProModeComponents/hooks/usePreserveScroll.ts` (NEW)

```typescript
import { useEffect, useRef } from 'react';

/**
 * Hook to preserve scroll position during re-renders
 * 
 * Usage:
 * usePreserveScroll([dependency1, dependency2]);
 */
export const usePreserveScroll = (dependencies: any[] = []) => {
  const scrollPos = useRef({ x: 0, y: 0 });
  
  useEffect(() => {
    // Save scroll before render
    scrollPos.current = {
      x: window.scrollX,
      y: window.scrollY
    };
  }, dependencies);
  
  useEffect(() => {
    // Restore scroll after render
    const { x, y } = scrollPos.current;
    requestAnimationFrame(() => {
      window.scrollTo(x, y);
    });
  }, dependencies);
};
```

**Usage in PredictionTab.tsx:**

```tsx
import { usePreserveScroll } from './hooks/usePreserveScroll';

export const PredictionTab: React.FC = () => {
  // ... existing code ...
  
  // 🎯 Preserve scroll on case changes
  usePreserveScroll([currentCase]);
  
  // 🎯 Preserve scroll on analysis updates
  usePreserveScroll([analysisState.isAnalyzing]);
  
  // ... rest of component ...
};
```

### CSS-Only Solution (Partial Fix)

Add to root container:

```tsx
<div 
  style={{ 
    overflowAnchor: 'auto',  // Enable scroll anchoring
    scrollBehavior: 'auto'   // Disable smooth scroll during updates
  }}
>
  {/* Content */}
</div>
```

**Note:** This helps but doesn't fully prevent React-caused scroll loss.

## Implementation Priority

### High Priority (Implement First) 🔴

1. **Fix 1: Case selection scroll preservation** (Lines ~172-214)
   - Impact: Immediate user action
   - Frequency: Every case selection
   - Difficulty: Easy

2. **Fix 2: Analysis completion scroll preservation** (Lines ~700, ~935, ~316)
   - Impact: After every analysis
   - Frequency: Every analysis run
   - Difficulty: Easy

### Medium Priority 🟡

3. **Fix 3: Dropdown focus management** (CaseSelector.tsx)
   - Impact: Dropdown-specific fix
   - Frequency: Every dropdown interaction
   - Difficulty: Medium (Fluent UI API)

### Low Priority (Nice to Have) 🟢

4. **Global scroll hook** (New file)
   - Impact: Reusable solution
   - Benefit: Future-proofing
   - Difficulty: Medium (refactoring)

## Testing Checklist

After implementing fixes, test:

- [ ] Select case from dropdown → Scroll stays in place
- [ ] Select different case → Scroll stays in place
- [ ] Run Quick Query → Scroll stays in place after completion
- [ ] Run Standard Analysis → Scroll stays in place after completion
- [ ] Run Orchestrated Analysis → Scroll stays in place after completion
- [ ] Open dropdown → No scroll jump
- [ ] Close dropdown → No scroll jump
- [ ] Scroll down, then select case → Position maintained
- [ ] Scroll down, then run analysis → Position maintained

## Success Criteria

✅ User can select cases without losing scroll position
✅ User can complete analysis without losing scroll position
✅ Dropdown interactions don't cause page jumps
✅ User maintains visual context throughout workflow

## Code Locations

| Issue | File | Line | Fix Type |
|-------|------|------|----------|
| Case selection | PredictionTab.tsx | ~172 | Add scroll save/restore |
| Quick Query complete | PredictionTab.tsx | ~316 | Add scroll preservation |
| Standard analysis | PredictionTab.tsx | ~700 | Add scroll preservation |
| Orchestrated analysis | PredictionTab.tsx | ~935 | Add scroll preservation |
| Dropdown focus | CaseSelector.tsx | ~129 | Add onOpenChange handler |

## Notes

- **requestAnimationFrame** is critical - ensures DOM has fully updated before scroll restoration
- **Don't use setTimeout** - unreliable timing, can cause flicker
- **Test on multiple browsers** - Chrome, Firefox, Safari have different scroll behaviors
- **Consider mobile** - Touch scrolling behaves differently

## Expected Outcome

**Before Fix:**
```
User at position Y=800px
  ↓ Clicks dropdown
  ↓ Selects case
  ↓ Page jumps to Y=0px ❌
User confused, scrolls back down manually
```

**After Fix:**
```
User at position Y=800px
  ↓ Clicks dropdown
  ↓ Selects case
  ↓ Page stays at Y=800px ✅
User continues workflow smoothly
```

🎯 **Goal:** Seamless user experience with no unexpected scroll jumps!
