# Insurance Claims Schema Upgrade Summary

## Overview
Updated `CLEAN_SCHEMA_INSURANCE_CLAIMS_REVIEW_PRO_MODE.json` to incorporate best practices from the single-shot meta-array approach, adapted for insurance claims analysis use case.

## Changes Made

### 1. **Single-Shot Global Consistency Instruction** ✅
**Before:**
```json
"description": "Analyze documents for insurance claim approval strictly according to the provided insurance policy..."
```

**After:**
```json
"description": "Analyze ALL documents comprehensively for insurance claim approval strictly according to the provided insurance policy in ONE unified analysis...IMPORTANT: Maintain consistency of all values (costs, vehicle parts, dates, names) across all line items. If a $5,000 cost appears in one line item, use the SAME $5,000 format in related items. Generate the ENTIRE analysis in ONE pass to ensure global consistency."
```

**Benefit:** 
- AI generates all line items at once with consistent cost formatting
- Prevents using "$5K" in one place and "$5,000" in another
- Ensures all costs can be reliably compared and totaled

### 2. **Enhanced Line Item Array Instructions** ✅
**Before:**
```json
"LineItemCorroboration": {
  "description": "Validation of all of the line items on the claim..."
}
```

**After:**
```json
"LineItemCorroboration": {
  "description": "CRITICAL: Analyze ALL line items on the claim comprehensively in ONE analysis...Use consistent cost formatting across all line items (e.g., if you write '$5,000.00' for one item, use the same format for all items, not '$5K' or '5000'). Generate the ENTIRE array in ONE pass to ensure global consistency of costs and evidence."
}
```

**Benefit:** Clear instructions for value consistency and single-shot analysis

### 3. **Structured Evidence with Document Tracking** ✅
**Before:** String array with loose format
```json
"Evidence": {
  "description": "The evidence for this line item entry, a list of the document with analyzed evidence supporting the claim formatted as <document name>/<evidence>.",
  "items": { "type": "string" },
  "type": "array"
}
```

**After:** Structured object array with metadata
```json
"Evidence": {
  "description": "Array of evidence items supporting or disputing this line item claim...",
  "items": {
    "type": "object",
    "properties": {
      "DocumentName": { "type": "string", "description": "Filename WITHOUT UUID prefix..." },
      "PageNumber": { "type": "number", "description": "Page number (1-based index)..." },
      "Finding": { "type": "string", "description": "Clear description of evidence..." },
      "SupportsClaim": { "type": "boolean", "description": "True if supports, false if disputes..." }
    }
  }
}
```

**Benefits:**
- Structured evidence with page references
- UUID stripping for clean filenames
- Boolean flag for supporting vs contradicting evidence
- Easier frontend rendering and navigation

### 4. **UUID Stripping Instructions** ✅
Added to all document reference fields:
```json
"DocumentName": {
  "description": "...WITHOUT any UUID prefix. If filename in storage is '7543c5b8-903b-466c-95dc-1a920040d10c_insurance_policy.pdf', return ONLY 'insurance_policy.pdf'."
}
```

**Benefit:** Clean, user-friendly filenames in UI

### 5. **Cost Consistency Instructions** ✅
```json
"Cost": {
  "description": "The cost of this line item on the claim. Use consistent formatting across all line items (e.g., if you write '$5,000.00' in one place, use '$5,000.00' everywhere, not '$5K' or '5000'). This ensures costs can be reliably compared and totaled."
}
```

**Benefit:** Frontend can accurately total costs without parsing variations

### 6. **Added Risk Level Field** ✅ NEW
```json
"RiskLevel": {
  "type": "string",
  "description": "Financial and fraud risk level for this line item. High = potential fraud, cost >$5K, or major policy violation. Medium = moderate cost concern or minor policy questions. Low = routine item with clear policy support.",
  "enum": ["High", "Medium", "Low"]
}
```

**Benefits:**
- Adds fraud detection dimension
- Helps prioritize human review
- Separates policy compliance (ClaimStatus) from financial risk (RiskLevel)

### 7. **Added Review Notes Field** ✅ NEW
```json
"ReviewNotes": {
  "type": "string",
  "description": "Optional: Additional notes for human reviewers explaining concerns, policy references, or recommendations. Include specific policy clause numbers or sections when applicable."
}
```

**Benefit:** Provides context for human reviewers on why items were flagged

### 8. **Enhanced Claim Status Descriptions** ✅
**Before:**
```json
"confirmed": "Completely and explicitly corroborated by the policy."
"suspicious": "Only partially verified, questionable, or otherwise uncertain evidence..."
```

**After:**
```json
"confirmed": "Completely and explicitly corroborated by the policy. All evidence supports approval, costs are reasonable, and item is necessary for repair."
"suspicious": "Only partially verified, questionable, or otherwise uncertain evidence to approve automatically. May have cost concerns, unclear policy coverage, or conflicting evidence. Requires human review."
```

**Benefit:** More comprehensive guidance for AI classification decisions

### 9. **Added Claim Summary Object** ✅ NEW
```json
"ClaimSummary": {
  "type": "object",
  "description": "High-level summary of the claim analysis. This can be calculated from the LineItemCorroboration array on the frontend, but AI can also generate it for convenience.",
  "properties": {
    "TotalLineItems": { "type": "number" },
    "TotalClaimAmount": { "type": "number" },
    "ConfirmedAmount": { "type": "number" },
    "SuspiciousAmount": { "type": "number" },
    "UnconfirmedAmount": { "type": "number" },
    "ConfirmedCount": { "type": "number" },
    "SuspiciousCount": { "type": "number" },
    "UnconfirmedCount": { "type": "number" },
    "HighRiskCount": { "type": "number" },
    "OverallRecommendation": { "type": "string" },
    "KeyConcerns": { "type": "string" }
  }
}
```

**Benefits:**
- Executive summary for quick review
- Overall recommendation (Approve/Partial/Review/Deny)
- Financial breakdown by status
- Key concerns highlighted

**Note:** Unlike invoice/contract schema, this allows AI generation OR frontend calculation for flexibility

### 10. **Added Documents Analyzed Tracking** ✅ NEW
```json
"DocumentsAnalyzed": {
  "type": "array",
  "description": "List of all documents that were analyzed for this claim review, with types and relevance.",
  "items": {
    "type": "object",
    "properties": {
      "DocumentName": { "type": "string", "description": "Filename WITHOUT UUID..." },
      "DocumentType": { "type": "string", "description": "'Insurance Policy', 'Claim Form', 'Repair Estimate'..." },
      "RelevanceToAnalysis": { "type": "string", "description": "How this document contributed..." }
    }
  }
}
```

**Benefits:**
- Audit trail of what was reviewed
- Document type classification
- Explains relevance of each document to analysis
- Helps identify missing documents (e.g., "No police report found")

## Schema Structure Comparison

### Before (131 lines)
```
InsuranceClaimsReview
├── CarBrand
├── CarColor
├── CarModel
├── LicensePlate
├── VIN
├── ReportingOfficer
└── LineItemCorroboration[]
    ├── LineItemName
    ├── IdentifiedVehiclePart (enum)
    ├── Cost
    ├── Evidence[] (strings)
    └── ClaimStatus (enum)
```

### After (226 lines)
```
InsuranceClaimsReview
├── CarBrand
├── CarColor
├── CarModel
├── LicensePlate
├── VIN
├── ReportingOfficer
├── LineItemCorroboration[]
│   ├── LineItemName
│   ├── IdentifiedVehiclePart (enum)
│   ├── Cost (with consistency instructions)
│   ├── Evidence[] (structured objects)
│   │   ├── DocumentName (UUID-stripped)
│   │   ├── PageNumber
│   │   ├── Finding
│   │   └── SupportsClaim (boolean)
│   ├── ClaimStatus (enum, enhanced descriptions)
│   ├── RiskLevel (enum) ⭐ NEW
│   └── ReviewNotes ⭐ NEW
├── ClaimSummary ⭐ NEW
│   ├── TotalLineItems
│   ├── TotalClaimAmount
│   ├── ConfirmedAmount
│   ├── SuspiciousAmount
│   ├── UnconfirmedAmount
│   ├── ConfirmedCount
│   ├── SuspiciousCount
│   ├── UnconfirmedCount
│   ├── HighRiskCount
│   ├── OverallRecommendation
│   └── KeyConcerns
└── DocumentsAnalyzed[] ⭐ NEW
    ├── DocumentName (UUID-stripped)
    ├── DocumentType
    └── RelevanceToAnalysis
```

## Breaking Changes

### Structure Changes
- **Evidence field:** Changed from `string[]` to `object[]` with structured properties
  - Old: `["policy.pdf/Section 5 allows bumper replacement", "claim.pdf/Front bumper cost $5,000"]`
  - New: `[{DocumentName: "policy.pdf", PageNumber: 5, Finding: "Section 5 allows bumper replacement", SupportsClaim: true}, ...]`

### Migration Required
**Backend:**
- Update evidence parsing to generate structured objects instead of strings
- Implement UUID stripping for all document names
- Generate ClaimSummary object
- Generate DocumentsAnalyzed array

**Frontend:**
- Update Evidence renderer to handle object array with DocumentName, PageNumber, Finding, SupportsClaim
- Display RiskLevel alongside ClaimStatus
- Show ReviewNotes for flagged items
- Render ClaimSummary dashboard
- Display DocumentsAnalyzed list with types and relevance

## Benefits Summary

### Data Quality ✅
- Consistent cost formatting across all line items
- Clean filenames without UUIDs
- Structured evidence with page references
- Single-shot analysis prevents contradictions

### Fraud Detection ✅
- RiskLevel field separates financial risk from policy compliance
- HighRiskCount in summary for prioritization
- SupportsClaim boolean identifies contradicting evidence

### User Experience ✅
- Executive summary with overall recommendation
- Clear breakdown of confirmed vs suspicious amounts
- Review notes explain why items were flagged
- Document tracking shows what was analyzed

### Auditing & Compliance ✅
- Page number references for evidence
- Policy clause numbers in review notes
- Document type classification
- Clear rationale for each decision

## Frontend Implementation Guide

### 1. Line Item Table
```typescript
interface LineItem {
  LineItemName: string;
  IdentifiedVehiclePart: string;
  Cost: number;
  Evidence: Array<{
    DocumentName: string;
    PageNumber: number | null;
    Finding: string;
    SupportsClaim: boolean;
  }>;
  ClaimStatus: 'confirmed' | 'suspicious' | 'unconfirmed';
  RiskLevel: 'High' | 'Medium' | 'Low';
  ReviewNotes?: string;
}

// Render with status badge + risk badge
<Badge color={getStatusColor(item.ClaimStatus)}>{item.ClaimStatus}</Badge>
<Badge color={getRiskColor(item.RiskLevel)}>{item.RiskLevel} Risk</Badge>
```

### 2. Evidence Panel
```typescript
// Clickable evidence with page navigation
{item.Evidence.map(ev => (
  <div className={ev.SupportsClaim ? 'supports' : 'contradicts'}>
    <a onClick={() => navigateToPage(ev.DocumentName, ev.PageNumber)}>
      {ev.DocumentName} (p. {ev.PageNumber})
    </a>
    <p>{ev.Finding}</p>
    <Badge>{ev.SupportsClaim ? 'Supports' : 'Contradicts'}</Badge>
  </div>
))}
```

### 3. Summary Dashboard
```typescript
// Display ClaimSummary for executive overview
<SummaryCard>
  <h3>Claim Summary</h3>
  <Statistic label="Total Claim" value={formatCurrency(summary.TotalClaimAmount)} />
  <Statistic label="Approved" value={formatCurrency(summary.ConfirmedAmount)} />
  <Statistic label="Under Review" value={formatCurrency(summary.SuspiciousAmount)} />
  <Statistic label="Denied" value={formatCurrency(summary.UnconfirmedAmount)} />
  <Badge color={getRecommendationColor(summary.OverallRecommendation)}>
    {summary.OverallRecommendation}
  </Badge>
  <Alert type="warning">{summary.KeyConcerns}</Alert>
</SummaryCard>
```

### 4. Documents Panel
```typescript
// Show what was analyzed
<DocumentsList>
  {documentsAnalyzed.map(doc => (
    <DocumentCard>
      <Icon type={getDocTypeIcon(doc.DocumentType)} />
      <div>
        <h4>{doc.DocumentName}</h4>
        <Badge>{doc.DocumentType}</Badge>
        <p>{doc.RelevanceToAnalysis}</p>
      </div>
    </DocumentCard>
  ))}
</DocumentsList>
```

## Testing Recommendations

### AI Output Quality
1. **Cost consistency:** Verify all costs formatted identically (e.g., all "$5,000.00", no mix with "$5K")
2. **Evidence structure:** Confirm all evidence items have DocumentName, PageNumber, Finding, SupportsClaim
3. **UUID stripping:** Check all DocumentName fields are clean (no UUIDs)
4. **Risk assessment:** Validate RiskLevel aligns with costs and ClaimStatus
5. **Summary accuracy:** Verify ClaimSummary totals match LineItemCorroboration data

### Business Logic
1. **Status thresholds:** Test that AI correctly classifies confirmed/suspicious/unconfirmed
2. **Risk triggers:** Verify High risk assigned for costs >$5K or potential fraud
3. **Overall recommendation:** Confirm logic: all confirmed → Approve, majority unconfirmed → Deny
4. **Policy references:** Check ReviewNotes include specific policy clauses when applicable

### Edge Cases
1. **Missing documents:** Test with incomplete document sets (no policy, no photos)
2. **Conflicting evidence:** Verify SupportsClaim boolean handles contradictions
3. **Zero amounts:** Test with $0 line items (covered by insurance)
4. **Partial page numbers:** Handle cases where PageNumber is null

## Files Changed
- ✅ `/data/CLEAN_SCHEMA_INSURANCE_CLAIMS_REVIEW_PRO_MODE.json` (131 → 226 lines, +72% enrichment)

## Related Schemas
This schema now follows the same best practices as:
- `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY.json` (document comparison)
- `simple_enhanced_schema_update.json` (invoice/contract verification)
- `GENERIC_SCHEMA_TEMPLATE_V2.json` (generic cross-document analysis)

All schemas now share:
- Single-shot global consistency instructions
- UUID stripping for clean filenames
- Value consistency enforcement
- Structured evidence with page references
- Executive summaries
- Clear severity/risk guidelines
