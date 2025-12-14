# 🔧 Schema Tab React Error #300 - Complete Debugging Guide

## 🎯 **IMMEDIATE ACTION PLAN**

Based on your Minified React error #300, here's a systematic approach to identify and fix the issue:

### **Phase 1: Quick Component Isolation (15 minutes)**

1. **Replace your SchemaTab temporarily with a minimal version:**

```tsx
// Temporary minimal SchemaTab for testing
const MinimalSchemaTab = () => {
  return (
    <div style={{ padding: '20px' }}>
      <h3>Minimal Schema Tab</h3>
      <p>If you see this without errors, the issue is in the full component.</p>
    </div>
  );
};

export default MinimalSchemaTab;
```

2. **If minimal version works, gradually add complexity:**
   - Add useState hooks
   - Add useEffect
   - Add Redux selectors
   - Add conditional rendering

### **Phase 2: Check Redux Store Integration (10 minutes)**

1. **Verify ProMode store is properly configured:**

```bash
# Check if ProModeStores are properly imported in your main store
# Look for store configuration errors
```

2. **Test Redux selectors in isolation:**

```tsx
// Add this to your component temporarily
useEffect(() => {
  console.log('🔍 Redux State Check:', {
    state: store.getState(),
    schemasSlice: store.getState()?.schemas,
    hasProModeStore: !!store.getState()?.schemas
  });
}, []);
```

### **Phase 3: Data Structure Analysis (20 minutes)**

## 🔍 **ROOT CAUSE ANALYSIS**

### **Most Likely Causes of Error #300:**

1. **Conditional Hook Usage** ⚠️ 
   ```tsx
   // ❌ WRONG - This causes error #300
   if (loading) {
     return <Spinner />;
   }
   const [state, setState] = useState(); // Hook after conditional return
   
   // ✅ CORRECT
   const [state, setState] = useState(); // All hooks at top
   if (loading) {
     return <Spinner />;
   }
   ```

2. **Redux Selector Issues** 🔴
   ```tsx
   // ❌ WRONG - Selector accessing undefined state
   const schemas = useSelector(state => state.schemas.items); // crashes if schemas undefined
   
   // ✅ CORRECT
   const schemas = useSelector(state => state?.schemas?.items || []);
   ```

3. **Store Configuration Problems** 🔴
   ```tsx
   // Check if ProModeStore is properly integrated
   // Your main store should include the ProMode slices
   ```

## 🚀 **AZURE STORAGE + COSMOS DB ANALYSIS**

### **Current Architecture Issues:**

1. **Dual Storage Strategy Complexity:**
   - Schema files → Azure Storage
   - Metadata → Cosmos DB
   - This creates potential sync issues

2. **API Call Flow Problems:**
   ```
   Upload Schema → Azure Storage ✅
                → Update Cosmos DB ❌ (potential failure point)
                → Update Redux Store ❌ (depends on above)
   ```

### **Recommended Data Flow Fixes:**

1. **Atomic Operations:**
   ```typescript
   // Ensure both storage operations succeed or both fail
   const uploadSchema = async (file, metadata) => {
     const transaction = await beginTransaction();
     try {
       const azureUrl = await uploadToAzureStorage(file);
       const cosmosDoc = await saveToCosmosDB({...metadata, azureUrl});
       await transaction.commit();
       return { success: true, schema: cosmosDoc };
     } catch (error) {
       await transaction.rollback();
       throw error;
     }
   };
   ```

2. **Error Handling Strategy:**
   ```typescript
   // Handle partial failures gracefully
   const fetchSchemas = async () => {
     try {
       // Try Cosmos DB first (faster)
       const metadata = await fetchFromCosmosDB();
       return metadata.map(doc => ({
         ...doc,
         azureStorageAvailable: true // assume available
       }));
     } catch (error) {
       // Fallback to Azure Storage direct scan
       return await scanAzureStorageSchemas();
     }
   };
   ```

## 🛠️ **IMMEDIATE FIXES TO TRY**

### **Fix #1: Safe Component Pattern**

Replace your current SchemaTab with this safe pattern:

```tsx
const SafeSchemaTab = ({ onSchemaSelected }) => {
  // ALL hooks at the top - never conditional
  const dispatch = useDispatch();
  const [componentReady, setComponentReady] = useState(false);
  const [error, setError] = useState(null);
  
  // Safe selector with fallbacks
  const schemaState = useSelector(state => ({
    items: state?.schemas?.items || [],
    loading: state?.schemas?.loading || false,
    error: state?.schemas?.error || null
  }));
  
  // Safe initialization
  useEffect(() => {
    const init = async () => {
      try {
        await dispatch(fetchSchemasAsync());
        setComponentReady(true);
      } catch (err) {
        setError(err.message);
        setComponentReady(true); // Still show UI
      }
    };
    init();
  }, [dispatch]);
  
  // Always return JSX - never conditional hooks
  if (!componentReady) {
    return <div>Loading...</div>;
  }
  
  if (error) {
    return <div>Error: {error}</div>;
  }
  
  return (
    <div>
      {/* Your schema UI here */}
    </div>
  );
};
```

### **Fix #2: Store Configuration Check**

Add this to your main store configuration:

```typescript
// In your main store file
import { schemasSlice } from './ProModeStores/proModeStore';

const store = configureStore({
  reducer: {
    // ... your existing reducers
    schemas: schemasSlice.reducer, // Make sure this is included
  }
});
```

### **Fix #3: API Error Handling**

Update your API service with better error handling:

```typescript
// In your proModeApiService.ts
export const fetchSchemas = async () => {
  try {
    const response = await fetch('/api/schemas');
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
    
    // Ensure consistent response format
    return {
      schemas: Array.isArray(data.schemas) ? data.schemas : [],
      count: data.count || 0,
      success: true
    };
  } catch (error) {
    console.error('fetchSchemas error:', error);
    // Return safe fallback instead of throwing
    return {
      schemas: [],
      count: 0,
      success: false,
      error: error.message
    };
  }
};
```

## 🧪 **TESTING STRATEGY**

### **Step 1: Component Isolation Test**
1. Use the `schema_tab_isolation_test.tsx` file I created
2. Run each level until you find the breaking point

### **Step 2: API Testing**
1. Test your schema endpoints directly:
   ```bash
   curl -X GET http://your-api/api/schemas
   curl -X POST http://your-api/api/schemas/upload -F "file=@test.json"
   ```

### **Step 3: Redux DevTools**
1. Install Redux DevTools
2. Monitor state changes during schema operations
3. Look for undefined/null states

## 🎯 **PRIORITY ORDER**

1. **HIGHEST:** Fix conditional hook usage (most likely cause)
2. **HIGH:** Verify Redux store configuration  
3. **MEDIUM:** Improve API error handling
4. **LOW:** Optimize data flow architecture

## 📋 **NEXT STEPS**

1. **Implement Fix #1** (Safe Component Pattern) first
2. **Test with minimal data** to isolate the issue
3. **Check browser console** for specific error details
4. **Use React DevTools** to inspect component state
5. **Monitor network tab** for API call failures

The error #300 is almost always related to hook usage patterns, so focus on the component structure first before diving into the data architecture issues.
