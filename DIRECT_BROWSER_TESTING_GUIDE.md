# Direct Browser Testing Guide 🧪

## **Ready-to-Test Schema Files**

I've created three test schema files that are compatible with your unified schema format:

### **1. Invoice Contract Verification Schema**
📁 **File**: `invoice_contract_verification_compatible.json`
🎯 **Purpose**: Simplified version of your original invoice verification schema
✅ **Features**: 
- All Azure API field types: `string`, `date`, `number`, `integer`, `boolean`
- All generation methods: `extract`, `generate`, `classify`
- Practical invoice verification fields
- Compatible with unified format

### **2. Insurance Claims Review Schema**
📁 **File**: `insurance_claims_review_compatible.json`
🎯 **Purpose**: Simplified version of your original insurance claims review schema
✅ **Features**:
- Vehicle damage claim processing fields
- Insurance policy compliance checking
- Fraud detection indicators
- All field types and generation methods
- Real-world insurance workflow compatibility

### **3. Azure API Validation Test Schema**
📁 **File**: `azure_api_validation_test_schema.json`
🎯 **Purpose**: Complete test of all Azure Content Understanding API field types
✅ **Features**:
- Every supported field type: `string`, `date`, `time`, `number`, `integer`, `boolean`, `array`, `object`
- All generation methods: `extract`, `generate`, `classify`
- Designed to test unified format transformations

## **How to Test in Browser**

### **Step 1: Start Your React App**
```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm start
```

### **Step 2: Upload Schema for Testing**
1. Navigate to your schema management page
2. Use the **"Upload Schema"** feature
3. Select one of the test files:
   - `invoice_contract_verification_compatible.json`
   - `insurance_claims_review_compatible.json`
   - `azure_api_validation_test_schema.json`

### **Step 3: What to Verify**
✅ **Upload Success**: Schema uploads without validation errors
✅ **Format Transformation**: Backend format correctly converts to frontend format
✅ **Field Display**: All fields show with correct types and properties
✅ **Generation Methods**: Extract/Generate/Classify methods preserved
✅ **Required Fields**: Required/optional status maintained
✅ **Azure Compliance**: No Azure API validation warnings

### **Step 4: Expected Results**

**✅ Success Indicators:**
- Schema uploads successfully
- All fields display correctly in the UI
- No validation errors or warnings
- Generation methods show properly
- Required/optional fields marked correctly

**❌ Issues to Watch For:**
- Upload validation errors
- Missing or incorrect field types
- Generation method not preserved
- Required status not maintained

## **Testing the Unified Format**

These schemas will test your unified format implementation by:

1. **Upload Testing**: Backend format → Frontend format transformation
2. **Display Testing**: Frontend format rendering in UI
3. **Validation Testing**: Azure Content Understanding API compliance
4. **Round-trip Testing**: Ensure data integrity through transformations

## **Quick Validation Commands**

If you want to test the schemas without uploading, you can also run these Node.js commands in your terminal:

```bash
# Test schema validation
node -e "
const schema = require('./invoice_contract_verification_compatible.json');
console.log('Schema name:', schema.name);
console.log('Field count:', schema.fields.length);
console.log('Field types:', schema.fields.map(f => f.type).join(', '));
console.log('Generation methods:', [...new Set(schema.fields.map(f => f.generationMethod))].join(', '));
"
```

## **Next Steps**

1. **Test Upload**: Upload one of the schemas in your browser
2. **Verify Transformation**: Check that frontend format displays correctly
3. **Test Creation**: Try creating a new schema using the UI
4. **Validate Round-trip**: Upload → Edit → Save → Verify consistency

Your unified schema format implementation should handle these test schemas perfectly! 🎉
