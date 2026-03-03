# Handover: Deterministic Triple Extraction for Structured Elements

**Date**: 2026-03-03  
**Status**: Design complete, ready to implement

---

## Context

### How Upstream HippoRAG 2 Extracts Triples

The original HippoRAG 2 repo ([OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG)) uses a **two-step LLM process per chunk**:

1. **NER**: Entire chunk text → LLM → JSON list of named entities
2. **Triple Extraction**: Same chunk text + NER output → LLM → `{"triples": [["subject", "predicate", "object"], ...]}`

- Chunks default to **entire passages** (`preprocess_chunk_max_token_size=None`), with optional token-based splitting (128-token overlap ≈ 96 words).
- Both steps use `ThreadPoolExecutor` for parallelism.
- Prompts: `src/hipporag/prompts/templates/ner.py` and `triple_extraction.py`

### How Our System Currently Works

- Documents → Azure DI → spaCy sentence splitting → `:Sentence` nodes in Neo4j
- Sentences classified as `content` / `metadata` / `noise`
- Content sentences batched in groups of 5 → single-step OpenIE LLM call → `(subject, predicate, object)` triples
- Concurrency: 4 parallel LLM calls via `asyncio.Semaphore`
- Code: `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` (`_extract_openie_triples()`)

### Granularity Comparison

Our 5-sentence batches (~75-125 words) are comparable to upstream's ~96-word chunks (128 tokens). The approach is similar in scale; we split on sentence boundaries (linguistically clean), they split on token count (can cut mid-sentence).

---

## Proposal: Hybrid Deterministic + LLM Triple Extraction

### Core Idea

Our DI pipeline already classifies element roles (title, sectionHeading, pageHeader, KVP, signature, etc.) and produces very precise structured data. For these **structured metadata elements**, we should extract triples **deterministically using NLP/rules** instead of sending them to the LLM. Reserve LLM calls for **content sentences** where relationships are implicit and complex.

### What to Extract Deterministically (NLP / Rules)

| Element | Source | Example Triple | Method |
|---------|--------|---------------|--------|
| **KVPs** | Already parsed as key→value | `("PO Number", "is", "4567")` | Direct mapping |
| **Signatures** | Regex/NLP on signature blocks | `("John Smith", "signed_as", "CEO")` | Regex + NLP |
| **Title** | DI role=title | `(doc_title, "is_document_type", "invoice")` | Direct mapping |
| **Table headers** | DI table structure | Column names → entity nodes | Direct mapping |

### What Still Goes to the LLM

| Element | Why LLM is needed |
|---------|-------------------|
| **Content sentences** | Implicit relationships, complex semantics, domain nuance |
| **Table rows** | Cells need predicate inference across columns |

### Why NLP Is Sufficient for Structured Elements

- **Explicit relationships**: KVPs are already `key: value` — no inference needed
- **Deterministic**: Same input always produces same triples (no temperature variance)
- **Cheaper/faster**: ~1ms/sentence vs ~500ms/sentence for LLM
- **More precise**: LLM sometimes hallucinates entities from simple headers; rules won't

### Why NLP Alone Is NOT Sufficient for Content Sentences

- **Implicit relations**: "With over 20 years in renewable energy, SolarTech leads the market." — NLP parsers miss `(SolarTech, has_experience_years, 20)`
- **Coreference**: "The company was founded in 2010. It now operates in 30 countries." — NLP needs separate coref model; LLMs handle natively
- **Complex clauses**: Deep dependency trees produce noisy/incomplete triples
- **Domain nuance**: "Net 30 payment terms" — LLM understands this means payment due within 30 days; NLP doesn't unpack domain semantics

### Section Headers — Special Case

Bare section headers (e.g., "Payment Terms", "Section 3") are more useful as **context metadata on child sentences** than as standalone graph nodes. Recommendation:

- **Do NOT** extract triples from section headers
- **Do** continue using headers as context prefixes for child sentences (which we already do with `doc_title` prefixing)
- This avoids polluting the knowledge graph with low-value structural nodes

---

## Improved LLM Batching: Paragraph-Grouped with Section Title Context

### Current Approach (Batch of 5 Sequential Sentences)

Sentences are batched in groups of 5 sequentially, regardless of which section or paragraph they belong to. This means:
- A batch might mix sentences from "Payment Terms" and "Scope of Work"
- The LLM has no context about what section it's reading
- Cross-sentence coreference can break at arbitrary batch boundaries

### Proposed Approach: Paragraph-Grouped + Section Title

Instead of arbitrary batches of 5, send **all sentences from one paragraph together**, prefixed with the **section title** for context.

**Example prompt:**
```
Section: Payment Terms

[s1]: Payment shall be made within 30 days of invoice date.
[s2]: A 2% discount applies for payment within 10 days.
[s3]: Late payments are subject to 1.5% monthly interest.
```

vs. current (no section context, mixed topics):
```
[s1]: Payment shall be made within 30 days of invoice date.
[s2]: A 2% discount applies for payment within 10 days.
[s3]: Late payments are subject to 1.5% monthly interest.
[s4]: The project was completed in December 2025.        ← leaked from different section
[s5]: SolarTech provided all required documentation.      ← leaked from different section
```

### Why This Is Better

1. **Section title gives framing context** — knowing you're in "Payment Terms" helps the LLM correctly interpret "Net 30" as a payment deadline, not a networking term
2. **Coreference preserved** — "The contractor... They..." stays within one paragraph
3. **Natural semantic units** — paragraphs are how authors organize related ideas
4. **Paragraph size (~3-8 sentences) is naturally close to our current batch of 5** — no real throughput difference

### No Need for Size Caps or Merging

Long paragraphs (10+ sentences, ~200 words) are trivial for the LLM context window (128K+). Upstream HippoRAG 2 sends entire passages with no size cap. More context = better triple quality.

Short paragraphs (1-2 sentences) still work fine — the section title provides sufficient context. Force-merging short paragraphs from different topics would hurt quality by mixing unrelated contexts. Better to send a 1-sentence paragraph with its section title than to pollute it with unrelated neighbors.

**Approach: send each paragraph as-is with its section title. Simple and correct.**

### Headers Should NOT Become Triples or MENTIONS Sources

**Headers are labels, not assertions.** A triple represents a fact/relationship (subject, predicate, object). A header like "Payment Terms" or "Scope of Work" doesn't assert anything — there's no predicate or object. Possible structural triples like `("Payment Terms", "is_section_of", "Invoice")` don't carry knowledge value and would pollute the graph with nodes that PPR can't usefully traverse.

**Header entities are absorbed into child sentence triples.** When the LLM sees:
```
Section: Payment Terms
[s1]: Payment shall be made within 30 days of invoice date.
```
It extracts `("payment", "due_within", "30 days")` — the concept "payment terms" flows into the child triples naturally through the section context prefix.

**MENTIONS edges from headers would be useless.** Even if a header sentence had a MENTIONS edge to a "payment terms" entity, returning the header text ("Payment Terms") as a retrieved passage provides no useful content. The child content sentences already MENTION the same entities and contain the actual answers.

**Summary:** Headers serve one purpose — **context fuel for the LLM prompt**. They improve triple quality in child sentences without needing their own graph presence.

### Data Already Available

Our DI pipeline already tracks:
- Which paragraph each sentence belongs to (paragraph grouping in `_build_section_aware_documents()`)
- Which section each paragraph falls under (section hierarchy in DI output)
- Section titles / headings

No new parsing needed — just restructure how we batch sentences for OpenIE.

---

## Implementation Plan

### Step 1: Deterministic KVP Triple Extraction
- KVPs are already parsed by our DI pipeline
- Create function to convert `{key: value}` pairs into `(key, "is", value)` triples
- Store as `:CONCEPT` entities and `RELATED_TO` edges (same schema as LLM-extracted triples)

### Step 2: Deterministic Signature Triple Extraction
- Signatures are already detected by `_detect_signature_block()`
- Parse name + role using regex patterns (e.g., "Name\nTitle" format)
- Emit triples like `(person_name, "signed_as", role)`, `(person_name, "signed", doc_title)`

### Step 3: Title/Table Header Entity Extraction
- Titles → create entity nodes directly (no triple needed, just the node)
- Table column headers → create entity nodes as anchors for table row triples

### Step 4: Skip Section Headers
- Confirm section headers are excluded from OpenIE LLM calls
- Ensure they continue to be used as context prefixes only

### Step 5: Benchmarking
- Compare triple quality before/after on the standard 5-PDF test set
- Verify no regression in route 7 benchmark scores (baseline: 55/57)
- Measure LLM cost reduction (expect ~30-40% fewer OpenIE calls)

---

## Key Files

- `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` — OpenIE extraction (`_extract_openie_triples`, `_extract_entities_and_relationships`)
- `src/worker/services/document_intelligence_service.py` — DI parsing, role classification, KVP extraction
- `src/worker/services/sentence_extraction_service.py` — Sentence splitting, classification
- `src/worker/hybrid_v2/services/neo4j_store.py` — Entity/relationship upsert to Neo4j
