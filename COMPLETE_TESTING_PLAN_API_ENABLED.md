# 🚀 Complete Testing Plan - API Authentication Disabled

## **🎯 PHASE 1: Disable Azure Authentication (5 minutes)**

### **Azure Container Apps - Disable Authentication:**

1. **Go to Azure Portal** → Your Container App
2. **Navigate to Authentication** (in left sidebar)
3. **Disable authentication** temporarily:
   ```
   Settings → Authentication → Require authentication: OFF
   ```
4. **Or via CLI:**
   ```bash
   az containerapp auth config remove --name YOUR_APP_NAME --resource-group YOUR_RG
   ```
5. **Note your app URL:** `https://your-app.azurecontainerapps.io`

---

## **🎯 PHASE 2: Replace SchemaTab for Testing (2 minutes)**

### **Find and Update SchemaTab Import:**

1. **Locate the import** (likely in one of these files):
   - `src/Pages/ProModePage/index.tsx`
   - `src/ProModeComponents/ProModeContainer.tsx`

2. **Replace the import:**
   ```tsx
   // OLD:
   import SchemaTab from '../../ProModeComponents/SchemaTab';
   
   // NEW (temporary):
   import SchemaTab from '../../schema_tab_test_wrapper';
   ```

3. **Save the file**

---

## **🎯 PHASE 3: Run Component + API Tests (10 minutes)**

### **Start Your App:**
```bash
npm start
# or
yarn start
```

### **Navigate to Schema Tab:**
1. **Open your app** in browser
2. **Go to Pro Mode** → **Schema Tab**
3. **You should see the isolation test interface**

### **Run the Tests:**

#### **Test 1: Component Isolation**
1. **Click "Run All Tests Automatically"**
2. **Watch browser console** for errors
3. **Note which level fails** (if any)

#### **Test 2: API Endpoint Testing**  
1. **In Level 6**, click **"Test Schema API"**
2. **Check if APIs return data**
3. **Verify 2025-05-01-preview structure**

---

## **🎯 PHASE 4: Comprehensive API Analysis (5 minutes)**

### **Test All Endpoints:**

1. **Open a new browser tab**
2. **Navigate to:** `https://your-app.azurecontainerapps.io`
3. **Test endpoints manually:**

```bash
# Test these URLs in browser or curl:
https://your-app.azurecontainerapps.io/api/schemas
https://your-app.azurecontainerapps.io/api/content-analyzers  
https://your-app.azurecontainerapps.io/content-analyzers
https://your-app.azurecontainerapps.io/api/promode/schemas
```

### **Expected 2025-05-01-preview Response:**
```json
{
  "@odata.context": "$metadata#contentAnalyzers",
  "@odata.count": 2,
  "value": [
    {
      "id": "string",
      "displayName": "string",
      "description": "string", 
      "createdDateTime": "2025-01-01T00:00:00Z",
      "lastModifiedDateTime": "2025-01-01T00:00:00Z",
      "contentAnalyzer": {
        "kind": "documentIntelligence",
        "documentIntelligenceModelId": "string"
      }
    }
  ]
}
```

---

## **🎯 PHASE 5: Report Results**

### **Gather This Information:**

#### **Component Test Results:**
- ✅ Which levels passed (1-6)
- ❌ Which level failed with React Error #300
- 📋 Browser console error messages
- 🔍 Redux state information (if Level 5 failed)

#### **API Test Results:**
- 🌐 Which endpoints respond successfully
- 📊 Current response format vs 2025-05-01-preview
- ⚠️ Any CORS or network errors
- 🔄 Data structure validation results

#### **Example Report:**
```
COMPONENT TESTS:
✅ Level 1-4: Passed
❌ Level 5: Failed with "useSelector is not defined"
⏳ Level 6: Not reached

API TESTS:  
✅ /api/schemas: Returns legacy format
❌ /api/content-analyzers: 404 Not Found
⚠️ Need to convert to 2025-05-01-preview format

CONSOLE ERRORS:
- "Minified React error #300"
- "Cannot read property 'schemas' of undefined"
```

---

## **🎯 PHASE 6: Quick Fixes Based on Results**

### **If Component Tests Fail at Level 5 (Redux):**
- **Issue:** Redux store not configured properly
- **Fix:** Update store configuration
- **Action:** Replace with safe SchemaTab version

### **If API Tests Show Legacy Format:**
- **Issue:** Not using 2025-05-01-preview structure  
- **Fix:** Update backend to return correct format
- **Action:** Add conversion layer in frontend

### **If No APIs Work:**
- **Issue:** Endpoint paths or CORS
- **Fix:** Check backend routing
- **Action:** Verify API deployment

---

## **🎯 EMERGENCY WORKAROUNDS**

### **If Everything Fails:**

1. **Use Mock Data Mode:**
   ```tsx
   // In schema_tab_test_wrapper.tsx
   const useMockData = true;
   ```

2. **Minimal Safe Component:**
   ```tsx
   const MinimalSchemaTab = () => (
     <div>Schema management temporarily disabled for debugging</div>
   );
   ```

---

## **🔧 CLEANUP (After Testing)**

### **Re-enable Authentication:**
1. **Azure Portal** → Container App → Authentication → **Enable**
2. **Restore original SchemaTab import**
3. **Apply any fixes discovered during testing**

---

## **📞 NEXT STEPS**

After running the tests, provide:
1. **Test results summary**
2. **Console error messages** 
3. **API response examples**
4. **Which approach you'd like to take** for fixes

**Ready to start? Disable authentication and let's test! 🚀**
