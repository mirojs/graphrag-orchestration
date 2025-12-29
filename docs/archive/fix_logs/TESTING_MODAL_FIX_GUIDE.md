# Testing the Modal Fix - Step-by-Step Guide

## ✅ Current Status

- **Dev Server:** Running successfully on `http://localhost:3000`
- **Compilation:** No errors, webpack compiled successfully
- **Fix Applied:** `_modalId` added to useMemo dependencies in FileComparisonModal.tsx

## 🧪 Testing Options

### Option 1: Port Forwarding (Recommended for VS Code Container)

If you're using VS Code's port forwarding feature:

1. **Check Port Forwarding Panel:**
   - Look for the "PORTS" tab at the bottom of VS Code
   - You should see port 3000 forwarded
   - Click the globe icon or "Open in Browser" link next to port 3000

2. **Access the forwarded URL:**
   - VS Code will give you a URL like: `https://[something].githubpreview.dev` or similar
   - This URL is accessible from your local browser

### Option 2: Direct Browser Access (If Port is Exposed)

If your container exposes port 3000 to your host machine:

1. Open your regular browser (Chrome, Firefox, Safari, Edge)
2. Navigate to: `http://localhost:3000`
3. The React app should load

### Option 3: Test Using Console Logs (No Browser Needed)

Since we added extensive logging to the fix, you can verify it's working by checking browser console logs:

1. **Open Browser DevTools** (F12 or Right-click → Inspect)
2. **Go to Console tab**
3. **Perform the test steps below**
4. **Look for these log messages:**

```
[FileComparisonModal] 🔧 FIX: Evidence extracted: {...}
[FileComparisonModal] 🔧 FIX: Modal opened with unique data: {...}
[ComparisonButton] Compare button clicked for CrossDocumentInconsistencies, row 0!
[PredictionTab] 🔧 FIX: Setting modal state with unique data: {...}
```

### Option 4: Use curl to Test API Endpoints

While you can't fully test the UI this way, you can verify the backend is working:

```bash
# Test if the frontend is serving
curl http://localhost:3000

# Check if backend is accessible (if running separately)
curl http://localhost:8000/health
```

## 📋 Manual Testing Steps

Once you have browser access, follow these steps:

### Step 1: Navigate to Prediction Tab
1. Open the app in browser
2. Click on "Pro Mode" or "Prediction" tab
3. Ensure you have analysis results loaded

### Step 2: Test Compare Buttons - Row 1
1. Find the first "Compare" button in the CrossDocumentInconsistencies table
2. Click it
3. **✅ Expected:** Modal opens showing evidence from Row 1
4. **Note the evidence text** (e.g., "Invoice states 'Due on contract signing'...")
5. Close the modal

### Step 3: Test Compare Buttons - Row 2
1. Find the SECOND "Compare" button (different row)
2. Click it
3. **✅ Expected:** Modal opens showing DIFFERENT evidence from Row 2
4. **❌ Bug would show:** Same evidence as Row 1 (this is what we fixed!)
5. Close the modal

### Step 4: Test Compare Buttons - Row 3
1. Click the third "Compare" button
2. **✅ Expected:** Modal shows unique evidence from Row 3
3. Close modal

### Step 5: Verify Fix with Console
1. Open Browser DevTools Console (F12)
2. Click different Compare buttons
3. **Look for logs showing DIFFERENT `_modalId` values:**

```javascript
// Row 1 click:
[FileComparisonModal] 🔧 FIX: Evidence extracted: {
  modalId: "CrossDocumentInconsistencies-0-1633024800000",
  extracted: "Invoice states 'Due on contract signing'..."
}

// Row 2 click (SHOULD BE DIFFERENT!):
[FileComparisonModal] 🔧 FIX: Evidence extracted: {
  modalId: "CrossDocumentInconsistencies-1-1633024805000",  // ← Different!
  extracted: "Date discrepancy found between..."  // ← Different!
}
```

## ✅ Success Criteria

The fix is working correctly if:

1. **✅ Each Compare button shows unique content**
2. **✅ Console logs show different `_modalId` for each click**
3. **✅ Evidence text changes between different rows**
4. **✅ No "stale data" or "cached content" appears**
5. **✅ Modal re-opens with correct data after closing and reopening**

## ❌ If Bug Still Exists

If all compare buttons still show the same content:

1. **Check console logs** - Are `_modalId` values changing?
2. **Hard refresh** - Clear browser cache (Ctrl+Shift+R or Cmd+Shift+R)
3. **Verify build** - Make sure latest code was compiled:
   ```bash
   # Check terminal output for "webpack compiled successfully"
   # Look for "No issues found"
   ```
4. **Check the fix** - Verify FileComparisonModal.tsx line ~148:
   ```tsx
   }, [inconsistencyData, fieldName, (inconsistencyData as any)?._modalId]);
   ```

## 🔧 Troubleshooting

### "Please reopen the preview" in VS Code Simple Browser

This usually means:
- Port forwarding isn't set up correctly
- Container networking issue
- VS Code Simple Browser limitation in containers

**Solutions:**
1. Use the PORTS panel and click "Open in Browser"
2. Use your regular browser with the forwarded URL
3. If using GitHub Codespaces/similar, use the provided preview URL

### Dev Server Not Responding

```bash
# Check if process is running
ps aux | grep "react-scripts"

# Restart the dev server if needed
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm start
```

### Port 3000 Already in Use

```bash
# Find process using port 3000
lsof -ti:3000

# Kill the process
kill -9 $(lsof -ti:3000)

# Restart dev server
npm start
```

## 🚀 After Testing Successfully

Once you've verified the fix works:

1. **Stop the dev server** (Ctrl+C in the terminal running npm start)
2. **Proceed with deployment:**
   ```bash
   cd ./code/content-processing-solution-accelerator/infra/scripts
   conda deactivate
   ./docker-build.sh
   ```
3. **Or commit and push** if you want to test in a staging environment first

## 📊 Quick Verification Without UI

If you absolutely can't access the browser, you can verify the code fix:

```bash
# Check that the fix was applied
grep -A 2 "}, \[inconsistencyData, fieldName" \
  code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/FileComparisonModal.tsx

# Expected output should include:
# }, [inconsistencyData, fieldName, (inconsistencyData as any)?._modalId]);
```

## 💡 Alternative: Test in Deployed Environment

If local testing is too difficult:
1. Deploy to a dev/staging environment
2. Test there with full browser access
3. If working, promote to production

This is acceptable for small fixes like this, especially with:
- Good logging in place
- Low-risk change (single dependency addition)
- Thoroughly analyzed root cause

---

**Summary:** The fix is ready. Test it by clicking different Compare buttons and verifying each shows unique content. Check browser console logs if you need to verify the `_modalId` is changing correctly.
