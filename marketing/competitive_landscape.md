# Competitive Landscape Analysis

**Date:** 2026-03-14
**Purpose:** Systematic competitive positioning for Evidoc against the document AI market

---

## Market Context

The enterprise knowledge graph market is projected at **$1.84B in 2026** (24.6% CAGR). GraphRAG (Graph Retrieval-Augmented Generation) is becoming the operational standard for compliance-heavy industries. Evidoc is positioned at the intersection of three converging markets: document AI, knowledge graphs, and verifiable AI.

---

## Competitor Segments

### Segment 1: Consumer PDF Chat Tools

These are Evidoc's most visible competitors in the B2C space. Users discover them first.

| Competitor | What They Do Well | Where They Fall Short vs Evidoc |
|---|---|---|
| **ChatPDF** | Fast, free, easy. Growing multi-doc support | No knowledge graph, no entity resolution, generated (not retrieved) answers, page-level citations at best |
| **PDF.ai** | Clean UX, quick single-doc Q&A | Single file only, no cross-document, no click-to-verify on source |
| **AskYourPDF** | Multi-PDF support, Chrome extension | No knowledge graph linking, no inconsistency detection, basic RAG |
| **Adobe Acrobat AI** | Trusted brand, integrated into existing workflows | Single-document focus, summaries not traceable answers, no cross-referencing |
| **Google NotebookLM** | Free, multi-source synthesis, Google ecosystem | Generated answers (not deterministic), no sentence-level polygon highlighting, limited document formats |

**Evidoc's edge:** Cross-document Knowledge Graph + sentence-level click-to-verify citations + inconsistency detection. None of these tools build an entity graph or let you click a citation and see it highlighted on the original page.

---

### Segment 2: Legal AI Tools

Premium, vertical-specific. Evidoc competes on price and breadth.

| Competitor | What They Do Well | Where They Fall Short vs Evidoc |
|---|---|---|
| **Harvey AI** | Deep legal reasoning, large firm deployments, multi-jurisdictional | Bespoke enterprise only ($$$), not self-serve, legal-only vertical |
| **CoCounsel (Casetext / Thomson Reuters)** | Legal-grade citations, case law integration, e-discovery | Locked into Thomson Reuters ecosystem, legal-only, not cross-industry |
| **Luminance** | Anomaly detection in contracts, visual analytics | Legal/M&A focus only, no general Q&A, no user-uploaded doc flexibility |
| **Kira Systems** | Deep clause extraction, custom ML for legal terms | Legal M&A/due diligence only, no conversational Q&A |
| **Robin AI** | End-to-end contract drafting & negotiation | Contract workflow tool, not document intelligence across arbitrary docs |

**Evidoc's edge:** Cross-industry (not legal-only), self-serve pricing from free tier, supports 15+ document formats, 13 languages. Legal tools charge $50K-500K/yr; Evidoc starts free.

---

### Segment 3: Enterprise Knowledge & Search Platforms

Evidoc's most serious B2B competitors. They solve adjacent problems.

| Competitor | What They Do Well | Where They Fall Short vs Evidoc |
|---|---|---|
| **Glean** | Enterprise search across all apps (Slack, Drive, email), strong integrations | Document-level attribution (not sentence-level), no Knowledge Graph reasoning, no inconsistency detection, no PDF polygon highlighting |
| **Vectara** | Per-passage citation, RAG platform, low hallucination | Developer-focused API/platform (not end-user product), no entity resolution, no cross-document inconsistency detection |
| **Hebbia** | Neural search, page/line-level citations, finance & legal focus | Enterprise-only onboarding, no self-serve, no Knowledge Graph entity linking |
| **Lettria GraphRAG** | Hybrid graph+embedding, no-code ontology, compliance-focused | Requires ontology setup, less suited to ad-hoc document Q&A, no click-to-verify PDF highlighting |

**Evidoc's edge:** End-user product (not API/platform), zero-config Knowledge Graph (auto-built from uploads), sentence-level polygon highlighting on original PDFs, both B2C and B2B pricing.

---

### Segment 4: Document Management / QMS Platforms

Evidoc doesn't replace these — it fills the gap they can't.

| Competitor | What They Do Well | Where They Fall Short vs Evidoc |
|---|---|---|
| **MasterControl** | Full QMS for FDA-regulated manufacturing, workflow automation | Stores and manages docs but **cannot answer questions across them with citations** |
| **Veeva Vault** | Pharma/life sciences document management, regulatory submissions | Same — manages docs, doesn't provide cross-doc Q&A or inconsistency detection |
| **Qualio** | Cloud QMS for smaller life sciences companies | Same gap — no intelligent Q&A layer |
| **DocuSign AI** | Contract lifecycle management, e-signatures | Clause extraction within single contracts, no cross-document reasoning |

**Evidoc's edge:** This is the "layer on top" positioning. These tools store documents; Evidoc makes them searchable with verifiable answers. **Complementary, not competitive** — potential integration partners.

---

### Segment 5: General AI Assistants

The "good enough" risk — users may just use what they already have.

| Competitor | What They Do Well | Where They Fall Short vs Evidoc |
|---|---|---|
| **ChatGPT (+ file upload)** | Massive context window, general intelligence, ubiquitous | Generates answers (hallucination risk), no persistent knowledge graph, no sentence-level click-to-verify, no cross-session document memory |
| **Claude (Anthropic)** | 200K+ token context, excellent at deep reading | Same — generated not retrieved, no entity graph, no PDF highlighting, no inconsistency detection |
| **Microsoft Copilot** | Deep Office 365 integration, enterprise-ready | Works within Microsoft ecosystem only, no Knowledge Graph, generated answers, limited citation tracing |

**Evidoc's edge:** Deterministic retrieval vs generation. When ChatGPT says "the contract states X" — you can't verify it without reading the contract yourself. When Evidoc says it — you click and see the highlighted sentence. For high-stakes work, this is the difference between useful and trustworthy.

---

## Positioning Matrix

|  | Single-doc Q&A | Cross-doc Q&A | Knowledge Graph | Sentence-level Citations | Click-to-Verify on PDF | Inconsistency Detection | Self-serve Pricing | Multi-industry |
|---|---|---|---|---|---|---|---|---|
| **Evidoc** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ChatPDF | ✅ | ⚠️ Limited | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Harvey AI | ✅ | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ Legal |
| CoCounsel | ✅ | ✅ | ❌ | ✅ Legal | ❌ | ❌ | ❌ | ❌ Legal |
| Hebbia | ✅ | ✅ | ❌ | ✅ Page/line | ❌ | ❌ | ❌ | ⚠️ |
| Glean | ✅ | ⚠️ | ❌ | ⚠️ Doc-level | ❌ | ❌ | ❌ | ✅ |
| Vectara | ✅ | ✅ | ❌ | ✅ Passage | ❌ | ❌ | ✅ API | ✅ |
| Lettria | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ❌ | ⚠️ |
| ChatGPT | ✅ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| NotebookLM | ✅ | ✅ | ❌ | ⚠️ | ❌ | ❌ | ✅ Free | ✅ |

**No competitor has all 8 columns green.** Evidoc's unique combination: Knowledge Graph + sentence-level click-to-verify on original PDF + cross-document inconsistency detection + self-serve pricing.

---

## The One-Line Positioning

> **"Other AI tools give you answers. We give you answers the auditor will accept."**

Against each segment:
- vs **PDF Chat tools**: "They summarize. We prove."
- vs **Legal AI**: "Same rigor. Any industry. Any budget."
- vs **Enterprise search**: "They find documents. We find the sentence."
- vs **QMS platforms**: "They manage your docs. We make them answerable."
- vs **ChatGPT/Claude**: "They generate text. We retrieve facts."

---

## Competitive Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **ChatGPT adds better citations** | 🔴 High | Deepen Knowledge Graph moat — entity resolution, inconsistency detection are hard to replicate with pure LLM |
| **Google NotebookLM goes cross-doc** | 🔴 High | Speed to market + vertical depth (legal, manufacturing, procurement landing pages) |
| **Hebbia adds self-serve** | 🟡 Medium | Price advantage + multilingual + broader industry focus |
| **Legal AI tools expand to general docs** | 🟡 Medium | They're locked into legal ontology; Evidoc is industry-agnostic by design |
| **Lettria targets same Knowledge Graph + doc AI space** | 🟡 Medium | Lettria requires ontology config; Evidoc is zero-config (auto-builds graph from uploads) |
| **Enterprise sales cycle too long** | 🟡 Medium | B2C self-serve as entry point; bottom-up adoption like Slack/Dropbox |
