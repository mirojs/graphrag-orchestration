# 🧪 Component Isolation Test - Quick Start Guide

## 🚀 **IMMEDIATE STEPS TO RUN THE TEST**

### **Step 1: Replace SchemaTab temporarily (2 minutes)**

1. **Navigate to your SchemaTab usage location:**
   ```bash
   # Find where SchemaTab is imported
   # Likely in: src/Pages/ProModePage/index.tsx or src/ProModeComponents/ProModeContainer.tsx
   ```

2. **Temporarily replace the import:**
   ```tsx
   // Replace this line:
   import SchemaTab from '../../ProModeComponents/SchemaTab';
   
   // With this:
   import SchemaTab from '../../schema_tab_test_wrapper';
   ```

### **Step 2: Run the isolation test**

1. **Start your development server:**
   ```bash
   npm start
   # or
   yarn start
   ```

2. **Navigate to the Schema tab in your application**

3. **You should see the Component Isolation Test interface**

### **Step 3: Run the tests systematically**

1. **Open browser console** (F12 → Console tab)
2. **Click through each test level** or click "Run All Tests Automatically"
3. **Watch for React Error #300** - note exactly which level it occurs at

---

## 🎯 **WHAT TO LOOK FOR**

### **If Level 1-3 work but Level 4 fails:**
- Basic React hooks work fine
- Issue is likely in state management patterns or conditional rendering

### **If Level 5 fails (Redux):**
- Redux store configuration issue
- Selector accessing undefined state
- **Most likely culprit for Error #300**

### **If Level 6 fails (API):**
- API endpoint issues
- CORS problems
- Data structure mismatches with 2025-05-01-preview

---

## 🔧 **QUICK FIX TESTING**

If you want to test the fixed version immediately:

### **Replace SchemaTab.tsx content with safe version:**

```tsx
// Minimal safe version to test
import React, { useState, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';

const SafeSchemaTab = ({ onSchemaSelected }) => {
  // ALL hooks declared at top level - never conditional
  const dispatch = useDispatch();
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState(null);
  
  // Safe Redux selector
  const reduxState = useSelector((state) => {
    if (!state || !state.schemas) {
      return { schemas: [], loading: false, error: 'Store not ready' };
    }
    return {
      schemas: state.schemas.items || [],
      loading: state.schemas.loading || false,
      error: state.schemas.error || null
    };
  });
  
  // Safe useEffect
  useEffect(() => {
    const init = async () => {
      try {
        // Only dispatch if function exists
        if (dispatch && typeof dispatch === 'function') {
          setIsReady(true);
        }
      } catch (err) {
        setError(err.message);
        setIsReady(true);
      }
    };
    init();
  }, [dispatch]);
  
  // Always return JSX - never conditional hooks
  if (!isReady) {
    return <div style={{ padding: '20px' }}>Loading schema management...</div>;
  }
  
  return (
    <div style={{ padding: '20px' }}>
      <h2>✅ Safe Schema Tab</h2>
      <p>If you see this without errors, the basic structure is fixed!</p>
      <p>Schemas found: {reduxState.schemas.length}</p>
      <p>Loading: {reduxState.loading.toString()}</p>
      <p>Error: {reduxState.error || 'None'}</p>
      
      {error && (
        <div style={{ color: 'red', padding: '10px', border: '1px solid red' }}>
          Component Error: {error}
        </div>
      )}
    </div>
  );
};

export default SafeSchemaTab;
```

---

## 🌐 **API TESTING (If authentication disabled)**

### **Enable API testing in the isolation test:**

```tsx
// In schema_tab_test_wrapper.tsx, change this line:
<SchemaTabIsolationTester enableAPITest={true} />
```

### **Test API endpoints manually:**

```bash
# Test your schema endpoint
curl -X GET "https://your-app-url/api/schemas" \
  -H "Accept: application/json" \
  -H "api-version: 2025-05-01-preview"

# Expected 2025-05-01-preview response:
{
  "@odata.context": "$metadata#contentAnalyzers",
  "@odata.count": 2,
  "value": [
    {
      "id": "analyzer-1",
      "displayName": "Schema Name",
      "description": "Schema description",
      "createdDateTime": "2025-01-01T00:00:00Z",
      "lastModifiedDateTime": "2025-01-01T00:00:00Z",
      "contentAnalyzer": {
        "kind": "documentIntelligence",
        "documentIntelligenceModelId": "model-id"
      }
    }
  ]
}
```

---

## 📊 **EXPECTED RESULTS**

### **✅ Success Path:**
- Level 1-3: ✅ (Basic React works)
- Level 4: ✅ (State management works)  
- Level 5: ✅ (Redux works)
- Level 6: ✅ (API works)

### **❌ Common Failure Points:**
- **Level 5 fails:** Redux store issue → Check store configuration
- **Level 6 fails:** API issue → Check CORS and endpoint structure
- **Any level fails with Error #300:** Conditional hook usage

---

## 🚨 **EMERGENCY BYPASS**

If you need to quickly get the schema tab working:

1. **Replace SchemaTab with the minimal safe version above**
2. **Test basic functionality**  
3. **Gradually add features back one by one**
4. **Use the isolation test to verify each addition**

---

## 📞 **NEXT STEPS AFTER TESTING**

1. **Report which level fails** (if any)
2. **Share browser console errors**
3. **If API testing enabled, share API response structure**
4. **We'll create targeted fixes based on the results**

**Ready to start? Replace the SchemaTab import and refresh your app!** 🚀
