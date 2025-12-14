# File Comparison Feature - Data-Driven Methodology Analysis

## 📊 **Complete Azure Analysis Result Structure**

Based on actual analysis results (`analysis_results.json`), here's what Azure provides:

### **Structure Overview:**
```json
{
  "result": {
    "contents": [
      // INDEX 0: Analysis Results (Fields we defined in schema)
      {
        "fields": {
          "DocumentTypes": {
            "type": "array",
            "valueArray": [
              {
                "type": "object",
                "valueObject": {
                  "DocumentType": { "type": "string", "valueString": "Invoice" },
                  "DocumentTitle": { "type": "string", "valueString": "Contoso Lifts Invoice #1256003" }
                }
              },
              // ... more documents
            ]
          },
          "CrossDocumentInconsistencies": {
            "type": "array",
            "valueArray": [
              {
                "type": "object",
                "valueObject": {
                  "InconsistencyType": { "type": "string", "valueString": "Product Description" },
                  "InvoiceValue": { "type": "string", "valueString": "Vertical Platform Lift (Savaria V1504)" },
                  "ContractValue": { "type": "string", "valueString": "Vertical Platform Lift (AscendPro VPX200)" },
                  "Evidence": { "type": "string", "valueString": "The invoice lists..." }
                }
              }
            ]
          }
        },
        "kind": "document",
        "startPageNumber": 0,
        "endPageNumber": 0
      },
      
      // INDEX 1+: Actual Documents (Full content with markdown, pages, words)
      {
        "markdown": "Contoso Lifts LLC\nYour elevator and lift experts...",
        "kind": "document",
        "startPageNumber": 1,
        "endPageNumber": 1,
        "unit": "inch",
        "pages": [
          {
            "pageNumber": 1,
            "angle": 0.03502651,
            "width": 8.5,
            "height": 11,
            "spans": [...],
            "words": [
              {
                "content": "Contoso",
                "span": { "offset": 0, "length": 7 },
                "confidence": 0.996,
                "source": "D(1,0.8131,0.7724,...)"
              },
              // ... more words with coordinates
            ]
          }
        ]
      },
      // ... more documents
    ]
  }
}
```

## 🎯 **Data Available for File Comparison**

### **1. From CrossDocumentInconsistencies (Our Schema):**
```typescript
interface Inconsistency {
  InconsistencyType: string;    // "Product Description", "Payment Terms"
  InvoiceValue: string;          // "Vertical Platform Lift (Savaria V1504)"
  ContractValue: string;         // "Vertical Platform Lift (AscendPro VPX200)"
  Evidence: string;              // "The invoice lists the lift model as 'Savaria V1504'..."
}
```

**What this tells us:**
- ✅ **InvoiceValue** → Content from Invoice document
- ✅ **ContractValue** → Content from Contract document  
- ✅ **Evidence** → Description of the inconsistency
- ❌ **NO document IDs or filenames**
- ❌ **NO page numbers or locations**

### **2. From DocumentTypes (Our Schema):**
```typescript
interface DocumentType {
  DocumentType: string;      // "Invoice", "Contract", "Warranty"
  DocumentTitle: string;     // "Contoso Lifts Invoice #1256003", "PURCHASE CONTRACT"
}
```

**What this tells us:**
- ✅ **DocumentTitle** → Actual title from document
- ✅ **DocumentType** → Classification (Invoice, Contract, etc.)
- ❌ **NO mapping to uploaded filenames**
- ❌ **NO index or ID to link to contents[] array**

### **3. From contents[] Array (Azure provides):**
```typescript
interface DocumentContent {
  markdown: string;           // Full document text
  kind: "document";
  startPageNumber: number;    // 1, 2, 3, etc.
  endPageNumber: number;
  pages: Page[];              // Detailed page data
}
```

**What this tells us:**
- ✅ **Full document content** in markdown
- ✅ **Page-level data** with word coordinates
- ✅ **Ordered by document** (contents[1] = first doc, contents[2] = second doc, etc.)
- ❌ **NO filename metadata**
- ❌ **NO title field**

## 🔍 **Current Problems**

### **Problem 1: No Direct Filename Mapping**
```
User uploads: "invoice_2024.pdf", "purchase_contract.pdf"
     ↓
Azure analyzes and returns DocumentTypes: 
  - "Contoso Lifts Invoice #1256003"  
  - "PURCHASE CONTRACT"
     ↓
Current code tries to match:
  "Contoso Lifts Invoice #1256003" === "invoice_2024.pdf" ❌ FAILS
     ↓
Result: Falls back to generic "Document 1", "Document 2"
```

### **Problem 2: No Document Identification in Inconsistencies**
```
CrossDocumentInconsistency says:
  InvoiceValue: "Savaria V1504"
  ContractValue: "AscendPro VPX200"

But which document in contents[] is the invoice? Which is the contract?
  - contents[1] could be invoice or contract (no way to know!)
  - contents[2] could be invoice or contract (no way to know!)
  
Current code GUESSES based on pattern matching ❌
```

## ✅ **Methodologically Correct Solution**

### **Strategy: Multi-Level Document Matching**

#### **Level 1: Content-Based Matching (Most Reliable)**
Match inconsistency values to actual document content:

```typescript
function findDocumentByContent(
  inconsistency: Inconsistency,
  documents: DocumentContent[]
): { invoice: DocumentContent | null, contract: DocumentContent | null } {
  
  let invoiceDoc = null;
  let contractDoc = null;
  
  for (const doc of documents) {
    // Search for InvoiceValue in document markdown
    if (doc.markdown?.includes(inconsistency.InvoiceValue)) {
      invoiceDoc = doc;
    }
    
    // Search for ContractValue in document markdown
    if (doc.markdown?.includes(inconsistency.ContractValue)) {
      contractDoc = doc;
    }
  }
  
  return { invoice: invoiceDoc, contract: contractDoc };
}
```

**Reliability: 🟢 HIGH**
- Directly matches the actual content Azure found
- No assumptions about filenames or titles
- Works even if filenames don't match document titles

#### **Level 2: DocumentTypes Cross-Reference**
Use DocumentTypes to identify document by type:

```typescript
function findDocumentsByType(
  documentTypes: DocumentType[],
  documents: DocumentContent[]
): Map<string, DocumentContent> {
  
  const typeToDoc = new Map<string, DocumentContent>();
  
  // Match by searching for DocumentTitle in markdown
  documentTypes.forEach((docType, index) => {
    const matchingDoc = documents.find(doc => 
      doc.markdown?.includes(docType.DocumentTitle.substring(0, 50)) // First 50 chars
    );
    
    if (matchingDoc) {
      typeToDoc.set(docType.DocumentType, matchingDoc);
    }
  });
  
  return typeToDoc;
}
```

**Reliability: 🟡 MEDIUM**
- Assumes DocumentTitle appears in the document
- Requires partial matching (titles might be shortened)
- Can fail if title is not in first page

#### **Level 3: Filename Pattern Matching (Fallback)**
Use uploaded filename patterns as last resort:

```typescript
function matchFileByPattern(
  documentType: string,  // "Invoice" or "Contract"
  uploadedFiles: ProModeFile[]
): ProModeFile | null {
  
  const patterns = {
    invoice: /invoice|inv|bill/i,
    contract: /contract|agreement|purchase/i,
    warranty: /warranty|guarantee/i
  };
  
  const pattern = patterns[documentType.toLowerCase()];
  if (!pattern) return null;
  
  return uploadedFiles.find(file => pattern.test(file.name)) || null;
}
```

**Reliability: 🔴 LOW**
- Assumes users follow naming conventions
- Can mismatch if names are generic
- Fails completely if user uploads "doc1.pdf", "doc2.pdf"

### **Recommended Implementation: Cascading Strategy**

```typescript
function identifyDocumentsForComparison(
  inconsistency: Inconsistency,
  analysisResult: AnalysisResult,
  uploadedFiles: ProModeFile[]
): { invoiceDoc: ProModeFile, contractDoc: ProModeFile } | null {
  
  const documents = analysisResult.contents.slice(1); // Skip index 0 (analysis results)
  
  // STEP 1: Content-based matching (BEST)
  const { invoice: invoiceContent, contract: contractContent } = 
    findDocumentByContent(inconsistency, documents);
  
  if (invoiceContent && contractContent) {
    // Map back to uploaded files by page number or content
    const invoiceFile = findUploadedFileByContent(invoiceContent, uploadedFiles);
    const contractFile = findUploadedFileByContent(contractContent, uploadedFiles);
    
    if (invoiceFile && contractFile) {
      console.log('✅ Matched by content');
      return { invoiceDoc: invoiceFile, contractDoc: contractFile };
    }
  }
  
  // STEP 2: DocumentTypes cross-reference (GOOD)
  const documentTypes = analysisResult.contents[0].fields.DocumentTypes?.valueArray || [];
  const typeMap = findDocumentsByType(documentTypes, documents);
  
  const invoiceDocByType = typeMap.get('Invoice');
  const contractDocByType = typeMap.get('Contract');
  
  if (invoiceDocByType && contractDocByType) {
    const invoiceFile = findUploadedFileByContent(invoiceDocByType, uploadedFiles);
    const contractFile = findUploadedFileByContent(contractDocByType, uploadedFiles);
    
    if (invoiceFile && contractFile) {
      console.log('✅ Matched by document type');
      return { invoiceDoc: invoiceFile, contractDoc: contractFile };
    }
  }
  
  // STEP 3: Filename pattern matching (FALLBACK)
  const invoiceByPattern = matchFileByPattern('invoice', uploadedFiles);
  const contractByPattern = matchFileByPattern('contract', uploadedFiles);
  
  if (invoiceByPattern && contractByPattern) {
    console.log('⚠️ Matched by filename pattern (less reliable)');
    return { invoiceDoc: invoiceByPattern, contractDoc: contractByPattern };
  }
  
  // STEP 4: Give up gracefully
  console.error('❌ Could not identify documents for comparison');
  return null;
}
```

## 🔧 **Enhanced Schema Recommendation**

To make file matching 100% reliable, we should enhance our schema to include **document source tracking**:

```json
{
  "CrossDocumentInconsistenciesEnhanced": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "InconsistencyType": { "type": "string" },
        "InvoiceValue": { "type": "string" },
        "ContractValue": { "type": "string" },
        "Evidence": { "type": "string" },
        
        // NEW: Document identification
        "InvoiceDocumentTitle": {
          "type": "string",
          "description": "The exact title of the invoice document where this value was found"
        },
        "ContractDocumentTitle": {
          "type": "string",
          "description": "The exact title of the contract document where this value was found"
        },
        
        // NEW: Location information
        "InvoiceLocation": {
          "type": "object",
          "properties": {
            "Section": { "type": "string", "description": "Section in invoice (e.g., 'Item Description Table')" },
            "ExactText": { "type": "string", "description": "Exact text snippet from invoice" }
          }
        },
        "ContractLocation": {
          "type": "object",
          "properties": {
            "Section": { "type": "string", "description": "Section in contract" },
            "ExactText": { "type": "string", "description": "Exact text snippet from contract" }
          }
        }
      }
    }
  }
}
```

**With this enhancement:**
- ✅ Azure tells us which document each value came from
- ✅ Can match `InvoiceDocumentTitle` to `DocumentTypes[].DocumentTitle`
- ✅ Can then map to `contents[]` index
- ✅ Can display exact location in each document

## 📋 **Implementation Checklist**

### **Phase 1: Quick Fix (Current Schema)**
- [ ] Implement content-based matching using `InvoiceValue`/`ContractValue`
- [ ] Add DocumentTypes cross-reference logic
- [ ] Fallback to filename pattern matching
- [ ] Show better error messages when matching fails

### **Phase 2: Enhanced Schema (Future)**
- [ ] Add `InvoiceDocumentTitle` and `ContractDocumentTitle` to schema
- [ ] Add location objects (`InvoiceLocation`, `ContractLocation`)
- [ ] Update frontend to use enhanced data
- [ ] Enable precise document highlighting

### **Phase 3: Advanced Features (Optional)**
- [ ] Add page-level highlighting using `pages[].words[]` data
- [ ] Implement "Jump to Location" feature
- [ ] Show side-by-side comparison with exact snippets highlighted
- [ ] Add fuzzy matching for partial content searches

## 🎯 **Immediate Action Items**

1. **Implement cascading document matching** (content → type → filename)
2. **Extract document identification logic** into separate utility function
3. **Add comprehensive logging** to debug matching process
4. **Test with various filename patterns** to verify robustness
5. **Consider schema enhancement** for next iteration

---

**Key Insight:** The issue isn't the React architecture or modal state management. It's that we're trying to guess which document is which without Azure explicitly telling us. The solution is to use the content Azure actually found (InvoiceValue/ContractValue) to search within the document markdown and identify the correct files.
