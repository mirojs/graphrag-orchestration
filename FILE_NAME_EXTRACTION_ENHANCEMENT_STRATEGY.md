# File Name Extraction Enhancement Strategy

## 📋 **Current Situation Analysis**

### **How We're Currently Extracting File Names:**

1. **Document Titles** (from content analysis):
   ```typescript
   extractDocumentTitle(content: string) {
     // Looks for: # INVOICE, PURCHASE CONTRACT, etc.
     // Patterns: /^(INVOICE|BILL|PURCHASE\s+CONTRACT|CONTRACT|AGREEMENT)/
     // Fallback: First 50 characters of first line
   }
   ```

2. **Display File Names** (from uploaded files):
   ```typescript
   getDisplayFileName(item: ProModeFile) {
     // Uses: item.name || filename || original_name || originalName
     // Removes: UUIDs, number prefixes, GUIDs
   }
   ```

### **Current Problems:**
- ❌ **Content-based extraction is unreliable** (depends on document formatting)
- ❌ **No direct connection** between API analysis and original file names
- ❌ **Evidence doesn't specify** which document it comes from
- ❌ **File matching is guesswork** based on filename patterns

## 🚀 **Proposed Schema Enhancement Solution**

### **Enhanced Schema Structure:**
```json
{
  "fields": {
    "DocumentIdentification": {
      "type": "object",
      "description": "Identify and classify the documents being analyzed",
      "properties": {
        "InvoiceDocument": {
          "DocumentType": "Invoice/Bill/Receipt",
          "DocumentTitle": "Main title as it appears", 
          "DocumentNumber": "Invoice #1256003",
          "CompanyName": "Contoso Lifts LLC",
          "SuggestedFileName": "Contoso_Invoice_1256003.pdf"
        },
        "ContractDocument": {
          "DocumentType": "Purchase Contract/Agreement",
          "DocumentTitle": "PURCHASE CONTRACT",
          "ContractNumber": "Contract identifier",
          "EffectiveDate": "Contract date",
          "SuggestedFileName": "Fabrikam_Purchase_Contract_2025.pdf"
        }
      }
    }
  }
}
```

### **Enhanced Inconsistency Fields:**
```json
{
  "Evidence": "Detailed evidence text",
  "InvoiceField": "Invoice section/field",
  "ContractField": "Contract section/field", 
  "SourceDocument": "Invoice|Contract",  // 🔑 NEW
  "PageReference": "Page 1, Section 2"   // 🔑 NEW
}
```

## 💡 **Benefits of Enhanced Schema**

### **1. Perfect File Identification:**
- ✅ **API generates exact document titles** instead of content parsing
- ✅ **Suggested filenames** based on document content analysis
- ✅ **Document type classification** (Invoice vs Contract vs Agreement)
- ✅ **Company names and document numbers** for unique identification

### **2. Precise Source Attribution:**
- ✅ **SourceDocument field** tells us exactly which document the evidence comes from
- ✅ **PageReference field** provides exact location information
- ✅ **Separate InvoiceField/ContractField** for precise targeting

### **3. Enhanced User Experience:**
- ✅ **Accurate file display names** using API-generated suggestions
- ✅ **Intelligent file matching** based on content analysis
- ✅ **Clear source indicators** showing which document has the issue

## 🔧 **Implementation Strategy**

### **Phase 1: Schema Update**
1. Add `DocumentIdentification` section to schema
2. Add `SourceDocument` and `PageReference` to inconsistency fields
3. Test schema with existing documents

### **Phase 2: FileComparisonModal Enhancement**
```typescript
// Enhanced extraction using schema data
const extractDocumentTitleEnhanced = (currentAnalysis, documentType) => {
  // Try schema-generated titles first
  const docId = currentAnalysis?.result?.contents?.[0]?.fields?.DocumentIdentification;
  
  if (docId?.InvoiceDocument?.DocumentTitle && documentType === 'invoice') {
    return docId.InvoiceDocument.DocumentTitle;
  }
  
  if (docId?.ContractDocument?.DocumentTitle && documentType === 'contract') {
    return docId.ContractDocument.DocumentTitle;
  }
  
  // Fallback to existing content parsing
  return extractDocumentTitle(content);
};

// Enhanced document assignment using SourceDocument field
const getSourceDocumentInfo = (inconsistencyData) => {
  const sourceDoc = inconsistencyData?.SourceDocument;
  const pageRef = inconsistencyData?.PageReference;
  
  return {
    primaryDocument: sourceDoc, // 'Invoice' or 'Contract'
    pageReference: pageRef,     // 'Page 1, Section 2'
    shouldHighlight: sourceDoc  // Which document to focus highlighting on
  };
};
```

### **Phase 3: UI Enhancement**
- Display **schema-generated document titles** in headers
- Show **suggested filenames** in tooltips
- Add **page reference indicators** for evidence location
- Implement **source document highlighting** based on SourceDocument field

## 📊 **Expected Results**

### **Before (Current):**
```
📄 Invoice Document: "invoice_20241001_final.pdf"
📋 Contract Document: "contract_v2_signed.pdf"
Evidence: "Invoice states 'Due on contract signing'"
→ ❓ Which document should we highlight?
```

### **After (Enhanced Schema):**
```
📄 Contoso Invoice #1256003: "Contoso_Invoice_1256003.pdf"
📋 Fabrikam Purchase Contract: "Fabrikam_Purchase_Contract_2025.pdf"  
Evidence: "Invoice states 'Due on contract signing'"
SourceDocument: "Invoice"
PageReference: "Page 1, Payment Terms Section"
→ ✅ Highlight invoice document, focus on payment terms
```

## 🎯 **Recommendation**

**YES, we should definitely modify the schema!** This would provide:

1. **100% accurate file identification** using API-generated content analysis
2. **Perfect source attribution** with SourceDocument and PageReference fields  
3. **Enhanced user experience** with precise document titles and locations
4. **Elimination of guesswork** in file matching and highlighting

The enhanced schema would make file name extraction and document identification **completely reliable** instead of the current pattern-matching approach.

Should I implement the enhanced schema and update the FileComparisonModal to use it?
