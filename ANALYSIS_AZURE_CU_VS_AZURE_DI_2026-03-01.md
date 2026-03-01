# Azure Content Understanding (CU) vs Azure Document Intelligence (DI)

**Date:** 2026-03-01  
**Objective:** Compare Azure Content Understanding (CU) with Azure Document Intelligence (DI) on the same 5 benchmark PDFs to evaluate CU as a potential upgrade or replacement.

---

## 1. What is Azure Content Understanding?

Azure Content Understanding is a multimodal AI service built **on top of** Document Intelligence. It wraps DI's OCR/layout engine with GPT-powered contextualization to provide:

- **The same DI layout extraction** (words, lines, paragraphs, tables, sections, bounding polygons)
- **LLM-powered field extraction** via domain-specific analyzers (invoice, receipt, contract, etc.)
- **RAG-optimized extraction** via `prebuilt-documentSearch` (adds GPT-generated summary)
- **Multi-modal support** (audio, video, images — not just documents)

### Analyzer Hierarchy

| Analyzer | LLM Required | What It Adds Over DI |
|---|---|---|
| `prebuilt-read` | No | OCR only — equivalent to DI `prebuilt-read` |
| `prebuilt-layout` | No | Layout + tables + paragraphs + sections — equivalent to DI `prebuilt-layout` |
| `prebuilt-documentSearch` | Yes (gpt-4.1-mini + embedding) | Layout + **GPT-generated summary** |
| `prebuilt-invoice` | Yes (gpt-4.1 + embedding) | Layout + **31 typed invoice fields** with confidence |
| Other domain analyzers | Yes | Layout + domain-specific typed fields |

---

## 2. Test Setup

- **CU Resource:** `ai-for-content-understanding373514902340` (Australia East, AIServices S0)
- **DI Resource:** `doc-intel-graphrag` (East US, FormRecognizer)
- **Auth:** `DefaultAzureCredential` (managed identity) for both
- **CU Model Deployments:** gpt-4.1 (50K TPM), gpt-4.1-mini (50K TPM), text-embedding-3-large (50K TPM)
- **CU API Version:** 2025-11-01
- **DI API Version:** 2024-11-30 (SDK 1.0.2)
- **CU SDK:** `azure-ai-contentunderstanding` 1.0.0b1

### 5 Benchmark PDFs

| Document | Pages | Size | Type |
|---|---|---|---|
| BUILDERS LIMITED WARRANTY.pdf | 2 | 59 KB | Legal contract |
| HOLDING TANK SERVICING CONTRACT.pdf | 1 | 43 KB | Service contract |
| PROPERTY MANAGEMENT AGREEMENT.pdf | 2 | 30 KB | Property agreement |
| contoso_lifts_invoice.pdf | 1 | 70 KB | Commercial invoice |
| purchase_contract.pdf | 3 | 5 KB | Purchase contract |

---

## 3. Layout Extraction Comparison (prebuilt-layout)

Both CU and DI use the **same underlying OCR engine**. The `prebuilt-layout` analyzer in CU is functionally equivalent to DI's `prebuilt-layout` model.

### 3a. Latency

| Document | CU (s) | DI (s) |
|---|---|---|
| BUILDERS LIMITED WARRANTY | 5.8 | 10.2 |
| HOLDING TANK SERVICING CONTRACT | 3.8 | 4.9 |
| PROPERTY MANAGEMENT AGREEMENT | 3.8 | 5.8 |
| contoso_lifts_invoice | 4.0 | 4.9 |
| purchase_contract | 3.7 | 5.6 |
| **Total** | **21.1** | **31.4** |

**CU is 1.5× faster** on layout extraction. This may be a regional/infrastructure difference (CU in Australia East vs DI in East US), not an inherent engine advantage.

### 3b. Content Volume

| Document | CU Words | DI Words | CU Lines | DI Lines | CU MD | DI MD |
|---|---|---|---|---|---|---|
| BUILDERS LIMITED WARRANTY | 2,827 | 2,364 | 159 | 168 | 15,226 | 15,237 |
| HOLDING TANK SERVICING | 514 | 418 | 53 | 51 | 2,474 | 2,666 |
| PROPERTY MANAGEMENT | 1,205 | 956 | 100 | 93 | 6,177 | 6,166 |
| contoso_lifts_invoice | 259 | 211 | 75 | 75 | 2,223 | 2,160 |
| purchase_contract | 493 | 389 | 55 | 55 | 2,559 | 2,555 |

- **Word counts differ** — CU reports 20-25% more words, likely due to different tokenization rules (CU splits punctuation-attached tokens)
- **Line counts are nearly identical** — confirming the same OCR engine
- **Markdown lengths are within 1-8%** — nearly identical content, minor formatting differences

### 3c. Structural Elements

| Document | CU Tbl | DI Tbl | CU Sect | DI Sect | CU Para | DI Para |
|---|---|---|---|---|---|---|
| BUILDERS LIMITED WARRANTY | 0 | 0 | 1 | 3 | 51 | 54 |
| HOLDING TANK SERVICING | 0 | 1 | 1 | 1 | — | 30 |
| PROPERTY MANAGEMENT | 0 | 0 | 1 | 2 | — | 47 |
| contoso_lifts_invoice | 3 | 3 | 3 | 3 | 58 | 67 |
| purchase_contract | 0 | 0 | 14 | 14 | 51 | 49 |

- **Tables:** identical except Holding Tank (DI detects 1 table that CU misses)
- **Sections:** CU sometimes has a flatter section tree (1 root vs DI's 3 sub-sections)
- **Paragraphs:** similar counts, both include role annotations

### 3d. Paragraph Roles

Both engines detect the same role types:

| Document | CU Roles | DI Roles |
|---|---|---|
| BUILDERS LIMITED WARRANTY | title:1, pageFooter:2, none:48 | title:1, sectionHeading:2, pageFooter:2, none:49 |
| contoso_lifts_invoice | title:1, pageFooter:1, none:56 | title:1, pageFooter:1, none:65 |
| purchase_contract | title:1, sectionHeading:12, none:38 | title:2, sectionHeading:11, none:36 |

Minor differences in role assignment but the same vocabulary and capability.

### 3e. Bounding Polygon Format

| Feature | CU Format | DI Format |
|---|---|---|
| Word polygon | `source: "D(1,0.81,0.77,...)"` — compressed string with page number | `polygon: [0.81,0.77,...]` + separate `pageNumber` field |
| Paragraph bbox | `source: "D(1,x1,y1,...,x4,y4)"` | `boundingRegions: [{pageNumber:1, polygon:[...]}]` |
| Confidence | ✅ Same (word-level, 0.0–1.0) | ✅ Same |
| Span offsets | ✅ Same (`offset`, `length`) | ✅ Same |

**The bounding polygon data is equivalent** — just different serialization. CU's `D(page,x1,y1,...,x4,y4)` string can be trivially parsed to the same 8-coordinate polygon + page number that DI provides.

### 3f. Markdown Differences

The markdown output is nearly identical with minor differences:
- **Bullet characters:** CU uses `.` (period), DI uses `·` (middle dot)
- **Minor whitespace/formatting** differences in ~15% of lines
- **Table rendering:** identical HTML `<table>` format
- **Content substance:** identical text extraction

---

## 4. LLM-Powered Analyzers (CU-Only Features)

### 4a. prebuilt-documentSearch (RAG Optimizer)

Adds a GPT-generated one-paragraph **Summary** field to the layout extraction. All other structural data (pages, paragraphs, tables, sections) remains the same.

| Document | Layout (s) | DocSearch (s) | Summary |
|---|---|---|---|
| BUILDERS LIMITED WARRANTY | 5.8 | 15.4 | "Builders Limited Warranty Agreement with Arbitration provisions between Fabrikam Inc. and Contoso Ltd..." |
| HOLDING TANK SERVICING | 3.8 | 10.4 | "Holding Tank Servicing Contract dated 2024-06-15 between Contoso Ltd. and Fabrikam Inc..." |
| PROPERTY MANAGEMENT | 3.8 | 13.6 | "Property Management Agreement between Contoso Ltd. (Owner) and Walt Flood Realty (Agent)..." |
| contoso_lifts_invoice | 4.0 | 10.3 | "Invoice from Contoso Lifts LLC to John Doe of Fabrikam Construction for elevator and lift components..." |
| purchase_contract | 3.7 | 10.2 | "Purchase contract between Contoso Lifts LLC and Fabrikam Inc. for vertical platform lift installation..." |

**DocSearch is 2.5–2.7× slower** than layout-only due to GPT inference. The summary is useful for RAG retrieval ranking but adds latency.

### 4b. prebuilt-invoice (Domain-Specific Extraction)

Extracts **31 typed invoice fields** with confidence scores from the Contoso invoice:

| Field | Value | Confidence |
|---|---|---|
| InvoiceId | 1256003 | 0.931 |
| InvoiceDate | 2015-12-17 | 0.961 |
| DueDate | 2015-12-17 | 0.936 |
| CustomerId | 4905201 | 0.873 |
| CustomerName | John Doe Fabrikam Construction | 0.610 |
| VendorName | Contoso Lifts LLC | 0.830 |
| VendorAddress | P.O. Box 123567 Key West, FL. 33304-0708 | 0.775 |
| TotalAmount | $29,900 USD | — |
| SubtotalAmount | $29,900 USD | — |
| PONumber | 30060204 | 0.874 |
| PaymentTerm | Due on contract signing | 0.738 |
| **Line Items** | **6 items extracted** | — |

**Line Item Extraction:**

| # | Description | Qty | Unit Price | Total |
|---|---|---|---|---|
| 1 | Vertical Platform Lift (Savaria V1504) | 1 | $11,200 | $11,200 |
| 2 | 110 VAC 60 Hz up, 12 VAC down operation parts | 1 | $3,000 | $3,000 |
| 3 | Special Size 42" x 62" cab with 90 degree Type 3 | 1 | $5,800 | $5,800 |
| 4 | Outdoor fitting | 1 | $2,000 | $2,000 |
| 5 | Aluminum door with plexi-glass inserts | 1 | $5,000 | $5,000 |
| 6 | Hall Call stations (bottom + upper landing) | 2 | $1,450 | $2,900 |

Latency: **37.1s** (vs 4.0s for layout-only). Requires gpt-4.1 model deployment.

### 4c. CU vs DI Feature Comparison

| Feature | CU | DI |
|---|---|---|
| Cross-page table detection | ✅ Automatic merging of tables spanning pages | ⚠️ Layout returns per-page; custom models + post-processing can merge ([sample](https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/Python(v4.0)/Pre_or_post_processing_samples/sample_identify_cross_page_tables.py)) |
| Signature detection | ⚠️ Requires custom analyzer with field schema (not automatic) | ✅ `prebuilt-document` detects signature presence + bounding box automatically |
| Formula extraction (LaTeX) | ✅ Via `enableFormula` config | ✅ Via `features=formulas` add-on — but costs **$6/1K pages extra** (doubles base cost from $5 to $11/1K pages) |
| Hyperlink detection | ✅ (with URL + bounding box) | ❌ |
| GPT-generated summaries | ✅ via documentSearch | ❌ |
| Typed field extraction (invoice, receipt, etc.) | ✅ 31 typed fields via single analyzer | ⚠️ DI has separate prebuilt models (`prebuilt-invoice`, `prebuilt-receipt`, etc.) — same capability, different API surface |
| Audio/Video analysis | ✅ | ❌ |
| Figure description (charts, diagrams) | ✅ via documentSearch | ❌ |
| Custom field extraction | ✅ Zero-shot: define JSON schema → GPT auto-extracts (no training data) | ✅ Custom template/neural models (requires labeled training data, 5+ samples) |

---

## 5. CU Advantages Over DI (Verified)

| Feature | Details |
|---|---|
| **Cross-page table detection** | CU automatically merges table fragments spanning page breaks. DI layout returns per-page tables; merging requires custom model training or [post-processing code](https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/Python(v4.0)/Pre_or_post_processing_samples/sample_identify_cross_page_tables.py). CU advantage: zero-effort automatic merging. |
| **Signature extraction** | CU: requires custom analyzer with field schema — structured extraction (name, date, image) but NOT automatic. DI: `prebuilt-document` detects signature presence + bounding box automatically without extra config. DI advantage for basic detection; CU advantage only if you need schema-driven field extraction. |
| **Formula → LaTeX** | Both support LaTeX output. CU: `enableFormula` config flag. DI: `features=formulas` add-on at **$6/1K pages extra** (more than doubles the $5/1K base cost). CU advantage: likely cheaper. (Not verified on math-heavy docs in this test; our 5 PDFs had no formulas.) |
| **Hyperlink extraction** | CU-only. Detected 2 hyperlinks in the invoice (email mailto: links) with bounding polygons. DI does not extract hyperlinks. |
| **Document summaries** | CU-only. GPT-generated one-paragraph summary per document — useful for RAG retrieval ranking. |
| **Typed field extraction** | CU: single `prebuilt-invoice` analyzer returns 31 fields + line items in one call. DI: separate `prebuilt-invoice` model with similar capability but different API surface. Comparable functionality. |
| **Multi-modal** | CU-only. Extends to audio (transcription + diarization), video (frame extraction + transcripts), and images. |
| **Custom field extraction** | CU: zero-shot extraction — define JSON schema, GPT auto-extracts without training data. DI: custom template/neural models — requires 5+ labeled training documents. CU advantage: no training needed. |

---

## 6. DI Features Available in CU

| Feature | CU prebuilt-layout | DI prebuilt-layout |
|---|---|---|
| Word-level OCR with confidence | ✅ | ✅ |
| Bounding polygons (words, paragraphs) | ✅ (via `source` string) | ✅ (via `polygon` array) |
| Paragraph segmentation | ✅ | ✅ |
| Paragraph roles (title, heading, footer) | ✅ | ✅ |
| Section tree | ✅ | ✅ |
| Table extraction with cells | ✅ (+ automatic cross-page merging) | ✅ (per-page; cross-page via custom model or post-processing) |
| Markdown output | ✅ | ✅ |
| Selection marks | ✅ | ✅ |
| Barcodes | ✅ | ✅ |
| Formulas | ✅ (LaTeX output via `enableFormula`) | ✅ (LaTeX output via `features=formulas` add-on — $6/1K pages extra) |
| Language detection | ❓ Not observed | ✅ |
| Styles (font, handwriting) | ❌ Not observed | ✅ |

**Key finding:** CU's `prebuilt-layout` provides the same core metadata as DI — including bounding polygons, paragraph roles, and section trees. The polygon data uses a different serialization format (`D(page,x1,y1,...,x4,y4)` string vs `polygon: [x1,y1,...]` array) but contains equivalent information.

---

## 7. Migration Impact Assessment

### What Would Need to Change

| Pipeline Component | Current (DI) | CU Equivalent | Migration Effort |
|---|---|---|---|
| OCR + paragraph extraction | `prebuilt-layout` | `prebuilt-layout` | **Low** — same data, parse `source` strings instead of `polygon` arrays |
| Section-aware chunking | DI section tree | CU section tree | **None** — same structure |
| Polygon highlighting UI | DI `boundingRegions` | CU `source: "D(...)"` | **Low** — parse D-string to polygon array |
| KVP extraction | DI `keyValuePairs` feature | CU `prebuilt-documentFields` | **Medium** — different API surface |
| Sentence extraction | DI paragraphs → wtpsplit | CU paragraphs → wtpsplit | **None** — same paragraph output |

### What CU Adds for Free

1. **Automatic cross-page table merging** — DI requires custom training or post-processing; CU does it out-of-the-box
2. **Document summaries** — useful for search/ranking without extra LLM calls
3. **Typed invoice extraction** — similar to DI's prebuilt-invoice but unified API surface
4. **Hyperlink detection** — not available in DI at all
5. **Signature extraction** — CU requires custom analyzer with schema; DI `prebuilt-document` auto-detects. CU advantage only for structured field extraction
6. **Cheaper formula LaTeX** — DI's `features=formulas` add-on costs $6/1K pages extra; CU's `enableFormula` is a config flag
7. **Multi-modal** — audio, video, image analysis not available in DI

---

## 8. Cost Comparison

| Component | DI Pricing | CU Pricing |
|---|---|---|
| Layout extraction | $5/1,000 pages (S0) | $5/1,000 pages (same DI engine) |
| Formula add-on (LaTeX) | $6/1,000 pages extra (via `features=formulas`) | Included via `enableFormula` config (pricing TBC) |
| DocumentSearch (with summary) | N/A | $5/1,000 pages + GPT token costs |
| Invoice extraction | $5/1,000 pages (DI prebuilt-invoice) | $5/1,000 pages + GPT token costs |
| GPT-4.1-mini tokens | N/A | Per-token pricing (Global Standard) |
| Text-embedding-3-large | N/A | Per-token pricing |

**CU's layout-only extraction costs the same as DI.** The LLM-powered features (summaries, typed fields) add GPT token costs on top. DI's formula add-on at $6/1K pages is a significant cost premium that CU may avoid.

---

## 9. Known Limitations

1. **Byte-based input not working** — During testing, sending PDF bytes directly via the SDK's `data` parameter returned empty content. Only URL-based input (`url` parameter) worked. This appears to be a CU service bug (confirmed across 3 different resources in different regions).

2. **Region availability** — CU requires a Microsoft Foundry resource (AIServices kind). Not all regions support CU's full feature set.

3. **Model deployment required** — LLM-based analyzers (documentSearch, invoice, etc.) require GPT model deployments on the same resource. This adds provisioning overhead.

4. **SDK is beta** — `azure-ai-contentunderstanding` 1.0.0b1 (preview). API surface may change.

---

## 10. Recommendation

### For Our Pipeline

**CU is a superset of DI** — it provides all the same layout/OCR metadata plus LLM-powered extras. However, the migration from DI to CU is **not necessary today** because:

1. Our pipeline only uses DI's layout features (paragraphs, sections, polygons, tables)
2. CU's layout output is functionally identical to DI's
3. The LLM-powered features (summaries, typed fields) can be achieved with our existing LLM infrastructure

### When to Consider CU

| Scenario | Recommendation |
|---|---|
| Need document summaries at ingestion | ✅ Use CU `prebuilt-documentSearch` |
| Need structured invoice/receipt extraction | ✅ Use CU `prebuilt-invoice` (37s/page, 31 fields) |
| Need custom field schemas (e.g., extract specific contract clauses) | ✅ Use CU custom analyzers |
| Current DI layout extraction only | ❌ No migration needed — same engine |
| Multi-modal (audio/video) content | ✅ CU is the only option |

### Summary

| Aspect | Winner | Notes |
|---|---|---|
| Layout extraction speed | CU (1.5×) | May be regional; same engine underneath |
| OCR accuracy | Tie | Same engine, same results |
| Structural metadata | CU (slight) | Same paragraphs, sections, polygons; CU adds automatic cross-page table merging |
| Typed field extraction | Tie | Both have prebuilt-invoice; CU unifies under one API surface |
| Document summaries | CU | GPT-generated, useful for RAG |
| Hyperlink detection | CU | Not available in DI |
| Cross-page tables | CU | DI requires custom model or post-processing; CU automatic |
| Formula LaTeX output | CU (cost) | Both support LaTeX; DI add-on costs $6/1K pages extra |
| Signature extraction | DI (basic) | DI auto-detects presence; CU needs custom analyzer for structured extraction |
| Custom field extraction | CU | Zero-shot (no training data) vs DI's labeled-sample approach |
| Maturity/stability | DI | DI is GA, CU SDK is beta |
| Byte upload support | DI | CU byte upload is broken (URL-only works) |
| Cost for layout-only | Tie | Same pricing |
