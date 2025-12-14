# GraphRAG Invoice-Contract Verification Results

**Date**: December 4, 2025  
**Branch**: `feature/graphrag-neo4j-integration`  
**Group ID**: `invoice-contract-verification`

## Executive Summary

Successfully tested the GraphRAG system's ability to detect inconsistencies across multiple business documents (invoice, contract, purchase order). The system found **11 potential inconsistencies**, of which **6 are definitively real**, **3 are questionable/partial**, and **2 are false positives**.

**Accuracy Rate**: ~55-82% (6-9 valid out of 11)

---

## Test Setup

### Documents Analyzed
- **Invoice**: #INV-2024-0542 (issued March 15, 2024, due April 15, 2024)
- **Purchase Order**: #PO-2024-0312 (total: $8,700.00)
- **Contract**: #CNT-2024-001 (Master Purchase Contract)

### Entities Extracted
- 54 entities total
- 12 communities built via Leiden clustering
- Key entities: TechCorp Inc. (buyer), Acme Supplies LLC (vendor), Widget Models A/B, Installation Service

### Query Methods Used
- `global_summary_query()` - For general information extraction
- `comparison_query()` - For inconsistency/discrepancy detection

---

## Verified Inconsistencies

### ✅ REAL INCONSISTENCIES (6 Confirmed)

| # | Field | Document 1 | Document 2 | Discrepancy |
|---|-------|-----------|------------|-------------|
| 1 | **Payment Terms** | Invoice: `Net 45 days` | Contract: `Net 30 days` | 15-day difference |
| 2 | **Early Payment Discount** | Invoice: `1% if paid within 15 days` | Contract: `2% discount` | 1% difference |
| 3 | **Order Total** | Invoice subtotal: `$9,450.00` | PO total: `$8,700.00` | $750 difference |
| 4 | **Tax on Tax-Exempt Customer** | Invoice charges: `$800.33 tax` | Customer has: `TX-EXEMPT-12345` | Should be $0 tax |
| 5 | **Shipping on Large Order** | Invoice charges: `$250.00` | Free shipping threshold: `$5,000` | Should be free ($9,450 > $5,000) |
| 9 | **Tax Calculation Error** | Invoice tax: `$800.33` | Expected (8.25% × $9,450): `$779.63` | Off by $20.70 |

### ⚠️ QUESTIONABLE/PARTIAL (3)

| # | Claim | Analysis | Verdict |
|---|-------|----------|---------|
| 6 | Delivery date missing from Invoice/PO | Date exists (`March 20, 2024`) but not directly linked to invoice/PO | Partial - data linkage issue |
| 8 | Installation hours 9.33 is non-standard | $1,400 ÷ $150/hr = 9.33 hours | Could be valid (9h 20m) |
| 10 | Widget A quantity 106.67 is fractional | $4,800 ÷ $45 = 106.67 units | Inferred, not explicit in data |

### ❌ FALSE POSITIVES (2)

| # | Claim | Reality |
|---|-------|---------|
| 7 | Contract reference mismatch | Both reference same contract: `Contract #CNT-2024-001` vs `CNT-2024-001` (format difference only) |
| 11 | Widget B quantity inconsistent | LLM correctly noted this IS consistent (50 units exactly) |

---

## Key Technical Findings

### Why GraphRAG Works for Cross-Document Comparison

1. **Global Query Pattern**: The `comparison_query()` method queries ALL community summaries, not just entity-matched ones
2. **LLM Reasoning**: The prompt explicitly asks the LLM to find "contradictions" and "values that don't match"
3. **Community Summaries**: Even though entities from different documents end up in different communities, the LLM can compare across summaries

### Cookbook Pattern Analysis

From the LlamaIndex GraphRAG v2 cookbook:
- `custom_query()`: Filters to communities matching queried entities → may miss relevant communities
- `comparison_query()` (our implementation): Uses ALL community summaries → LLM can compare everything

```python
# Cookbook pattern for comparison queries
def comparison_query(self, query_str: str) -> str:
    community_summaries = self.graph_store.get_community_summaries()
    # Use ALL summaries, not just entity-matched ones
    all_summaries = '\n\n'.join([
        f"=== Community {cid} ===\n{summary}" 
        for cid, summary in community_summaries.items()
    ])
    # Prompt LLM to find differences across communities
```

### Community Distribution

The 12 communities contained:
- Community 0: Business relationships (TechCorp, Acme Supplies)
- Community 5: Invoice details (dates, amounts, payment terms - Net 45)
- Community 7: Purchase Order payment terms (Net 30)
- Community 11: Contract payment terms (Net 30 days)
- Others: Product pricing, tax info, shipping thresholds, etc.

---

## Neo4j Data Reference

### Key Relationships Stored
```
INVOICE #INV-2024-0542 --[payment terms]--> Net 45 days
INVOICE #INV-2024-0542 --[sales tax]--> $800.33
INVOICE #INV-2024-0542 --[subtotal]--> $9,450.00
INVOICE #INV-2024-0542 --[shipping cost]--> $250.00
INVOICE #INV-2024-0542 --[early payment discount]--> 1% if paid within 15 days

Payment --[terms]--> Net 30
Payment --[includes]--> 2% discount for early payment

$8,700.00 --[total cost of]--> PURCHASE ORDER #PO-2024-0312

TechCorp Inc. --[Holds]--> Certificate #TX-EXEMPT-12345
Tax --[exempt per]--> TX-EXEMPT-12345

Free shipping --[Threshold]--> $5,000
Sales tax --[Rate]--> 8.25%
```

---

## Areas for Improvement

### 1. Entity Resolution
- "Net 30 days" and "Net 45 days" are separate unconnected entities
- Could benefit from normalization to "PaymentTerms" parent concept

### 2. Cross-Document Linking
- Invoice and Contract payment terms end up in different communities
- Could add explicit relationships: `Invoice --[SHOULD_MATCH]--> Contract.paymentTerms`

### 3. Quantity Extraction
- No explicit quantity field was extracted from documents
- LLM inferred quantities from price × total calculations

### 4. False Positive Reduction
- Contract reference format difference flagged as inconsistency
- Could add normalization for document IDs

---

## How to Reproduce

```python
from app.services.graphrag_store import GraphRAGStore
from app.services.graphrag_query_engine import GraphRAGQueryEngine
from app.core.config import settings
from llama_index.llms.azure_openai import AzureOpenAI

GROUP_ID = 'invoice-contract-verification'

store = GraphRAGStore(
    group_id=GROUP_ID,
    username=settings.NEO4J_USERNAME,
    password=settings.NEO4J_PASSWORD,
    url=settings.NEO4J_URI,
)

llm = AzureOpenAI(
    model='gpt-4o',
    deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    temperature=0.0,
)

store.build_communities()

query_engine = GraphRAGQueryEngine(
    graph_store=store,
    llm=llm,
    similarity_top_k=20,
)

# Run comparison query
result = query_engine.comparison_query(
    'Find all inconsistencies between the contract, invoice, and purchase order'
)
print(result)
```

---

## Next Steps (Tomorrow)

1. **Improve entity linking** - Connect related concepts across documents
2. **Add entity resolution** - Normalize similar entity names
3. **Test with more document sets** - Verify consistency of results
4. **Reduce false positives** - Better prompt engineering for comparison queries
5. **Add confidence scores** - Rank inconsistencies by severity/certainty

---

## Files Modified/Created

- `app/services/graphrag_store.py` - GraphRAG store with Leiden clustering
- `app/services/graphrag_query_engine.py` - Query engine with `comparison_query()`
- `app/services/graphrag_extractor.py` - Entity/relationship extraction with embeddings
- `test_graphrag_5doc_benchmark.py` - Benchmark tests

---

## Conclusion

The GraphRAG system successfully demonstrates the ability to detect cross-document inconsistencies using the Microsoft GraphRAG pattern (Leiden clustering + community summaries + LLM reasoning). With 6 definitively confirmed real inconsistencies out of 11 reported, the system shows promise for document verification use cases but has room for improvement in reducing false positives and better entity linking.
