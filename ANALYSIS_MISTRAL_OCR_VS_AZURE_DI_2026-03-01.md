# Mistral OCR vs Azure Document Intelligence — Extraction Comparison

**Date:** 2026-03-01  
**Objective:** Evaluate Mistral OCR (`mistral-ocr-latest`) as an alternative to Azure Document Intelligence for the graphrag-orchestration pipeline.  
**See also:** [LLMWhisperer comparison](ANALYSIS_LLMWHISPERER_VS_AZURE_DI_2026-03-01.md)

## Test Setup

- **Documents:** 5 benchmark PDFs (Builders Warranty, Holding Tank Contract, Property Management Agreement, Contoso Invoice, Purchase Contract)
- **Azure DI:** `prebuilt-layout` model, Markdown output, add-on features (KVPs, barcodes, languages), managed identity auth
- **Mistral OCR:** `mistral-ocr-latest` model, 2 configs tested: `table_format=html` and `table_format=markdown`, with `extract_header=True`, `extract_footer=True`
- **Mistral SDK:** `mistralai` 1.12.4 (Python), file upload → signed URL → OCR process

## Results Summary

### Speed & Text Volume

| Document                      | Engine           | Time (s) | Chars  | Lines | Pages | Tables |
|-------------------------------|------------------|----------|--------|-------|-------|--------|
| BUILDERS LIMITED WARRANTY     | Azure DI         | 10.09    | 15,237 | 221   | 2     | 0      |
|                               | Mistral OCR      | 4.78     | 14,889 | 114   | 2     | 0      |
| HOLDING TANK SERVICING        | Azure DI         | 4.92     | 2,666  | 94    | 1     | 1      |
|                               | Mistral OCR      | 3.79     | 1,926  | 26    | 1     | 2      |
| PROPERTY MANAGEMENT AGREEMENT | Azure DI         | 5.81     | 6,166  | 142   | 2     | 0      |
|                               | Mistral OCR      | 3.25     | 6,025  | 70    | 2     | 0      |
| contoso_lifts_invoice         | Azure DI         | 4.91     | 2,160  | 148   | 1     | 3      |
|                               | Mistral OCR      | 3.31     | 802    | 36    | 1     | 3      |
| purchase_contract             | Azure DI         | 5.64     | 2,555  | 120   | 3     | 0      |
|                               | Mistral OCR      | 1.86     | 2,492  | 84    | 3     | 0      |
| **Totals / Averages**         | **Azure DI**     | **31.4** | 28,784 |       | 9     | 4      |
|                               | **Mistral OCR**  | **17.0** | 26,134 |       | 9     | 5      |

**Mistral OCR is ~1.8× faster** on average (17.0s vs 31.4s total across 5 docs).

### Azure DI Extra Structured Metadata (not available from Mistral OCR)

| Document                      | Paragraphs | KVPs | Sections | Bounding Regions |
|-------------------------------|------------|------|----------|------------------|
| BUILDERS LIMITED WARRANTY     | 54         | 16   | 3        | ✅               |
| HOLDING TANK SERVICING        | 30         | 11   | 1        | ✅               |
| PROPERTY MANAGEMENT AGREEMENT | 47         | 13   | 2        | ✅               |
| contoso_lifts_invoice         | 67         | 24   | 3        | ✅               |
| purchase_contract             | 49         | 7    | 14       | ✅               |

## Detailed Findings

### 1. Markdown Quality — Mistral OCR Produces Cleaner Prose

Mistral OCR generates **significantly better-flowing Markdown** than Azure DI:

**Azure DI (Builders Warranty opening):**
```markdown
In consideration of the Agreement for the construction or purchase of a home for the undersigned
Buyer/Owner, this Limited Warranty Agreement is extended by Fabrikam Inc.
,and is accepted and agreed
(the Builder), whose address is 1820 Summit Ridge Dr., Pocatello, ID 83201

to by Contoso Ltd.
(the Buyer/Owner), who is the original
```
- Awkward mid-sentence line breaks inherited from PDF layout
- Parenthetical roles (e.g., "(the Builder)") separated from their antecedents
- Comma misplacement (",and is accepted")

**Mistral OCR (same passage):**
```markdown
In consideration of the Agreement for the construction or purchase of a home for the undersigned
Buyer/Owner, this Limited Warranty Agreement is extended by Fabrikam Inc. (the Builder), whose
address is 1820 Summit Ridge Dr., Pocatello, ID 83201, and is accepted and agreed to by
Contoso Ltd. (the Buyer/Owner), who is the original Buyer/Owner of the property at the
following address: 480 Willow Glen Drive, Chubbuck, ID 83202.
```
- Proper sentence flow with parentheticals kept inline
- No mid-sentence breaks
- Clean paragraph structure

**This pattern is consistent across all 5 documents.** Mistral OCR reconstructs coherent paragraphs from PDF layout, while Azure DI preserves raw line breaks from the visual layout.

### 2. Heading Detection — Both Good, Slightly Different

Both engines detect document headings and produce `#` / `##` Markdown:

| Feature                | Azure DI                          | Mistral OCR                      |
|------------------------|-----------------------------------|----------------------------------|
| Title detection        | `# BUILDERS LIMITED WARRANTY...`  | `# BUILDERS LIMITED WARRANTY...` |
| Section headings       | `## 1. Builder's Limited Warranty` | `## 1. Builder's Limited Warranty.` |
| Numbered sub-items     | Preserved                         | Preserved                        |
| Section numbering      | Sometimes loses (§8–11)           | Sometimes loses (§10–11)         |

### 3. Table Extraction — Comparable Quality

Both engines extract the same tables with identical cell content:

**Invoice tables (both engines produce equivalent HTML):**
```html
<table>
<tr><th>QUANTITY</th><th>DESCRIPTION</th><th>UNIT PRICE</th><th>TOTAL</th></tr>
<tr><td>1</td><td>Vertical Platform Lift (Savaria V1504)</td><td>11200.00</td><td>11200.00</td></tr>
<tr><td>1</td><td>110 VAC 60 Hz up, 12 VAC down operation parts</td><td>3000.00</td><td>3000.00</td></tr>
...
</table>
```

Key differences:
- Azure DI embeds tables inline in the Markdown as `<table>` blocks
- Mistral OCR uses **placeholder references** (`[tbl-0.html](tbl-0.html)`) in the Markdown body and returns table content separately in a `tables` array per page
- Mistral OCR detected 2 tables in the Holding Tank document (form fields + signatures) where Azure DI detected 1 table + a `<figure>` block
- **Invoice char count difference** (-62.9%): Mistral's inline text is only 802 chars because the tables are stored separately; Azure DI's 2,160 chars includes tables inline

### 4. Form Field Handling

| Feature                 | Azure DI                                  | Mistral OCR                                    |
|-------------------------|-------------------------------------------|------------------------------------------------|
| Blank form lines        | Stripped (values extracted as KVPs)        | Shows `☐` checkbox markers                     |
| Filled-in values        | Extracted inline + as KVPs                | Extracted inline                               |
| Key-value pairs         | ✅ 7–24 structured KVPs per document       | ❌ Not available                                |
| Checkbox detection      | Via selection marks feature                | Renders as `☐` in markdown                     |

### 5. Speed

| Metric              | Azure DI   | Mistral OCR | Winner       |
|---------------------|------------|-------------|--------------|
| Total (5 docs)      | 31.4s      | 17.0s       | **Mistral**  |
| Fastest single doc  | 4.91s      | 1.86s       | **Mistral**  |
| Slowest single doc  | 10.09s     | 4.86s       | **Mistral**  |
| Average per doc     | 6.27s      | 3.40s       | **Mistral**  |

Mistral OCR is consistently ~1.8× faster.

### 6. Structural Features Comparison

| Feature                       | Azure DI                         | Mistral OCR                      |
|-------------------------------|----------------------------------|----------------------------------|
| Output format                 | Markdown                         | Markdown                         |
| Headings (`#`, `##`)          | ✅                                | ✅                                |
| Tables                        | ✅ Inline `<table>` HTML          | ✅ Separate `tables[]` array      |
| Key-value pairs               | ✅ 7–24 per doc                   | ❌                                |
| Paragraph bounding boxes      | ✅ Polygon coordinates per para   | ❌                                |
| Image bounding boxes          | ✅                                | ✅                                |
| Page dimensions               | ✅ Width/height/unit              | ✅ Width/height/dpi               |
| Section tree                  | ✅ Hierarchical parent/child      | ❌                                |
| Confidence scores             | ✅ Per-paragraph                  | ❌                                |
| Language detection             | ✅ Per-span                       | ❌                                |
| Barcodes                      | ✅                                | ❌                                |
| Headers/footers extraction    | ✅ `<!-- PageFooter="..." -->`    | ✅ Separate `header`/`footer`     |
| List items                    | `·` bullet characters             | `-` standard Markdown lists      |
| Sentence-level geometry       | ✅ Via word geometry composition  | ❌                                |

### 7. Cost

| Engine                     | Price per page | Free tier              |
|----------------------------|----------------|------------------------|
| Azure DI prebuilt-layout   | $0.01          | 500 pages/month        |
| Mistral OCR                | $0.01 (1K pgs) | Free tier available    |

Pricing is comparable. Mistral charges per 1,000 pages at batch rates.

## Impact on graphrag-orchestration Pipeline

### What would need to change to adopt Mistral OCR

1. **Section-aware chunking** — Currently depends on DI's `sections` tree and `paragraph.role` (title, sectionHeading). Mistral OCR has no section tree, but its cleaner heading detection (`#`, `##`) could be parsed to reconstruct a section hierarchy.

2. **KVP extraction** — DI provides 7–24 structured key-value pairs per document. Mistral OCR does not extract KVPs. Would need a separate LLM-based extraction step.

3. **Polygon highlighting** — DI provides paragraph-level bounding regions used for frontend highlighting. Mistral OCR provides image bounding boxes but not text bounding regions. **This is a blocker for the current UI.**

4. **Sentence extraction** — Current pipeline uses DI's paragraph segmentation as input to wtpsplit. Mistral's better paragraph flow would actually **improve** sentence splitting since there are no mid-sentence line breaks.

5. **Table handling** — Mistral OCR returns tables separately (not inline). Would need to reconcile table placeholders with separate table content, or switch to `table_format=null` to get inline tables.

### Advantages Mistral OCR Would Bring

1. **Better prose quality** — Significantly cleaner paragraph reconstruction. No mid-sentence breaks. This would improve:
   - Entity extraction accuracy (fewer truncated entity mentions)
   - Sentence splitting quality (wtpsplit gets proper paragraphs)
   - LLM synthesis quality (better context for RAG answers)

2. **Faster processing** — 1.8× speed improvement reduces indexing latency.

3. **Standard Markdown lists** — Proper `-` list markers instead of `·` bullets. Better for downstream Markdown parsers.

4. **Checkbox detection** — `☐` markers in text (though DI has more structured selection mark detection).

## Recommendation

**Mistral OCR is the strongest alternative tested so far** (compared to LLMWhisperer which only outputs plain text). For a pure text extraction + Markdown quality perspective, Mistral OCR is **superior to Azure DI**. However, Azure DI provides critical structured metadata that the current pipeline depends on:

| Must-have for current pipeline | Azure DI | Mistral OCR |
|-------------------------------|----------|-------------|
| Paragraph bounding polygons    | ✅       | ❌           |
| Section tree                   | ✅       | ❌           |
| KVP extraction                 | ✅       | ❌           |
| Sentence-level geometry        | ✅       | ❌           |

### Possible Hybrid Strategy

The most promising approach would be a **dual-engine strategy**:
1. **Azure DI** for structural metadata (bounding regions, KVPs, section tree) — used for polygon highlighting and section-aware chunking
2. **Mistral OCR** for the actual text content — used for sentence extraction, entity extraction, and LLM synthesis

This would combine DI's structural richness with Mistral's superior prose quality. The implementation cost is running both engines during indexing (additive latency/cost), but the text quality improvement could meaningfully improve downstream RAG answer quality.

### Cost-only Alternative

If polygon highlighting and KVP extraction are not needed (e.g., a simpler deployment), Mistral OCR could fully replace Azure DI with:
- Heading-based section hierarchy reconstruction (parse `#`/`##` headings)
- No per-paragraph bounding regions (disable highlighting feature)
- External KVP extraction via LLM if needed
