# 📋 Quick Reference: Azure Content Understanding Data Sources

## 🎯 **TL;DR - Where Does the Data Come From?**

### **Three Information Sources:**

1. **🎨 Your Custom Schema** (`CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION.json`)
   - **Purpose**: Business-specific analysis
   - **Example**: PaymentTermsInconsistencies, ItemInconsistencies
   - **Method**: `"method": "generate"` - AI creates structured analysis

2. **🤖 Azure OCR Engine** (Automatic)
   - **Purpose**: Complete document extraction
   - **Example**: Full text, tables, word coordinates, confidence scores
   - **Method**: Built-in document intelligence

3. **🧠 Azure AI Analysis** (Semantic Understanding)
   - **Purpose**: Cross-document comparison and evidence generation
   - **Example**: "Invoice states X while contract requires Y"
   - **Method**: Machine learning models

---

## 📊 **Response Structure Map**

```json
{
  "contents": [
    {
      "fields": {
        "PaymentTermsInconsistencies": [...] // 🎨 YOUR SCHEMA
      },
      "kind": "document"
    },
    {
      "markdown": "Full document text...",     // 🤖 AZURE OCR
      "pages": [
        {
          "words": [
            {
              "content": "Contoso",           // 🤖 AZURE OCR
              "confidence": 0.996             // 🤖 AZURE OCR
            }
          ]
        }
      ],
      "kind": "document"
    }
  ]
}
```

---

## 🔧 **Frontend Usage**

### **Primary Display (Schema Results)**
```javascript
const inconsistencies = response.contents[0].fields;
// Show structured tables with Evidence and InvoiceField
```

### **Detailed View (Document Content)**
```javascript
const fullText = response.contents[1].markdown;
const wordData = response.contents[1].pages[0].words;
// Show complete document with highlighting
```

---

## 🎯 **Key Benefits**

- **📊 Structured Analysis**: Your custom business logic
- **📝 Complete Content**: Every word extracted with coordinates
- **🧠 AI Evidence**: Explanations for why inconsistencies exist
- **🔍 Interactive Features**: Click inconsistency → highlight source text
- **📈 Rich UI**: Both summary tables AND detailed document viewer

---

## 📚 **Full Documentation**

See `AZURE_CONTENT_UNDERSTANDING_DATA_SOURCES_DOCUMENTATION.md` for:
- Complete technical details
- Frontend implementation examples
- Performance optimization
- Error handling strategies
- Integration code samples

---

*This is why your test results are so rich - you get THREE layers of intelligence in one API call!* 🚀
