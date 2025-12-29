# Next Steps - Getting Detailed 422 Error

## Current State

✅ Added enhanced logging to show:
1. Full payload being sent (schemaService.ts)
2. Detailed validation errors (httpUtility.ts)  
3. Enhanced schema structure (SchemaTab.tsx)

## What to Do Next

### 1. Rebuild Frontend
```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm run build
```

### 2. Test in Browser
1. Open Pro Mode
2. Select a schema
3. Click "AI Schema Update"
4. Enter prompt: `"I also want to extract payment due dates and payment terms"`
5. Click "Generate"
6. Wait for modal to appear
7. Click "Save"

### 3. Check Console Output

You should now see **detailed logs** showing:

#### Before the 422 error:
```
[SchemaTab] Converting ProModeSchema to hierarchical format for save...
[SchemaTab] Enhanced schema draft fields: [Array of 7 fields]
[SchemaTab] Hierarchical schema for save: {
  "fieldSchema": {
    "fields": {
      "PaymentTermsInconsistencies": {...},
      ...
    }
  }
}
[schemaService] Sending save-enhanced payload: {
  "baseSchemaId": "...",
  "newName": "Updated Schema_enhanced",
  "description": "",
  "schema": {...},
  "createdBy": "ai_enhancement_ui",
  "overwriteIfExists": false,
  "enhancementSummary": {...}
}
```

#### After the 422 error:
```
[httpUtility] Validation errors: [
  {
    "loc": ["body", "fieldName", "path"],
    "msg": "exact error message",
    "type": "error_type"
  }
]
```

### 4. Share the Output

Copy the **complete console output** including:
- The full payload from `[schemaService] Sending save-enhanced payload:`
- The validation errors from `[httpUtility] Validation errors:`

This will tell us **exactly** what field is causing the 422 error!

## Most Likely Issues

Based on similar cases, the 422 error is probably caused by:

### Possibility 1: `method` field not allowed
Azure AI returns fields with `method: "required"`, but the backend schema validation might not accept this field.

**Fix:** Remove `method` from the hierarchical schema

### Possibility 2: `enhancementSummary` is a string
The frontend might be storing `enhancementSummary` as a JSON string instead of an object.

**Fix:** Parse string to object before sending

### Possibility 3: Field type mismatch
Some field type like `"date"` might not be in the allowed list.

**Fix:** Normalize types to allowed values

## Quick Test Without Rebuilding

If you want to test a theory immediately, you can modify the code and use browser DevTools:

1. Open browser console
2. Before clicking Save, modify the payload in memory:
```javascript
// In console, run this to test without 'method' field:
window.testPayload = {
  newName: "Test_No_Method",
  schema: {
    fieldSchema: {
      fields: {
        "TestField": {
          type: "string",
          description: "Test without method field"
        }
      }
    }
  }
};
```

But the proper way is to rebuild with the logging and see the actual error details!

## After You Get the Error Details

Once you share the console output showing:
```
[httpUtility] Validation errors: [...]
```

I can immediately fix the exact issue! The Pydantic validation errors are very specific and will tell us:
- **loc**: Which field is problematic
- **msg**: What's wrong with it
- **type**: What kind of validation error

Then we can apply the precise fix and test again. 🎯
