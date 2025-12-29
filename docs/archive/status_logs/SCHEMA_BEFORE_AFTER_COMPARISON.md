# 📊 Schema Evolution: User Intention vs. Before/After API Call

| **User Intention** | **Schema Before API Call** | **Schema After API Call** |
|--------------------|---------------------------|--------------------------|
| **I also want to extract payment due dates and payment terms** | 
- DocumentIdentification (object)
  - InvoiceTitle (string)
  - ContractTitle (string)
  - InvoiceSuggestedFileName (string)
  - ContractSuggestedFileName (string)
- DocumentTypes (array)
  - DocumentType (string)
  - DocumentTitle (string)
- CrossDocumentInconsistencies (array)
- PaymentTermsComparison (object)
- DocumentRelationships (array)
| 
- UserIntentAnalysis (object)
  - PrimaryIntent: add_fields
  - FieldsToAdd: ["PaymentDueDate", "PaymentTerms"]
- EnhancedSchemaDefinition (object)
  - MainFields:
    - DocumentIdentification (object)
    - DocumentTypes (array)
    - CrossDocumentInconsistencies (array)
    - PaymentTermsComparison (object)
    - DocumentRelationships (array)
    - **PaymentInformation (object)**
      - **PaymentDueDate (string)**
      - **PaymentTerms (string)**
      - PaymentMethod (string)
- SchemaComparison (object)
  - AddedFields: ["PaymentDueDate", "PaymentTerms"]
  - ImprovementSummary: Enhanced to extract payment due dates and terms |
| **I don't need contract information anymore, just focus on invoice details** | 
- DocumentIdentification (object)
  - InvoiceTitle (string)
  - ContractTitle (string)
  - InvoiceSuggestedFileName (string)
  - ContractSuggestedFileName (string)
- DocumentTypes (array)
  - DocumentType (string)
  - DocumentTitle (string)
- CrossDocumentInconsistencies (array)
- PaymentTermsComparison (object)
- DocumentRelationships (array)
| 
- UserIntentAnalysis (object)
  - PrimaryIntent: remove_fields, simplify_schema
  - FieldsToRemove: ["ContractTitle", "ContractSuggestedFileName", "ContractValue", "ContractPaymentTerms"]
- EnhancedSchemaDefinition (object)
  - MainFields:
    - DocumentIdentification (object)
      - InvoiceTitle (string)
      - InvoiceSuggestedFileName (string)
    - DocumentTypes (array)
      - DocumentType (string)
      - DocumentTitle (string)
    - PaymentTermsComparison (object)
      - InvoicePaymentTerms (string)
      - Consistent (boolean)
    - DocumentRelationships (array)
  - **Contract-related fields removed**
- SchemaComparison (object)
  - RemovedFields: ["ContractTitle", "ContractSuggestedFileName", "ContractValue", "ContractPaymentTerms"]
  - ImprovementSummary: Simplified schema to focus on invoice details only |

---

**Legend:**
- **Bold** fields indicate new or removed fields as a result of the API enhancement.
- The `UserIntentAnalysis` and `SchemaComparison` sections are AI-generated explanations of what changed and why.

This table visually demonstrates how the schema evolves based on user intent, with the Azure Content Understanding API dynamically adding, removing, or restructuring fields as needed.