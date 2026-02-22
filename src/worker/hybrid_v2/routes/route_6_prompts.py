"""Route 6: Concept Search — Synthesis prompt.

Route 6 restores the LazyGraphRAG insight: community summaries provide
thematic structure.  Unlike Route 3 (MAP-REDUCE), there is NO MAP phase.
Community summaries are passed **directly** to synthesis alongside sentence
evidence, eliminating the lossy claim-extraction step and the N extra LLM
calls that produced +41% latency for +1% containment improvement.

The prompt receives three evidence streams:
  1. Community summaries  — thematic structure from graph communities
  2. Section headings     — structural heading context (title + summary)
  3. Sentence evidence    — direct vector search on source sentences

Design rationale documented in:
  ANALYSIS_ROUTE3_LAZYGRAPHRAG_DEVIATION_AND_ROUTE6_PLAN_2026-02-19.md
"""

# ─────────────────────────────────────────────────────────────────
# CONCEPT SYNTHESIS PROMPT
# ─────────────────────────────────────────────────────────────────
# Input variables: {query}, {community_summaries}, {section_headings},
#                  {sentence_evidence}, {entity_coverage}
# Expected output: final synthesized response

CONCEPT_SYNTHESIS_PROMPT = """\
You are a document analysis assistant. Answer the query using the evidence below.

**Query**: {query}

**Thematic Context** (community summaries from knowledge graph):
{community_summaries}

**Document Structure** (section headings found in source documents):
{section_headings}

**Document Evidence** (passages from source documents, labelled [Document > Section Header]):
{sentence_evidence}

**Entity-Document Coverage** (which entities appear in which documents — exact graph data):
{entity_coverage}

**Rules**:
1. Use all three sources. Thematic context helps you organize; document evidence provides facts. Document structure is a reference list of section headings — do NOT treat each heading as a separate finding.
2. Include facts from document evidence even if they are not mentioned in thematic context.
3. Use thematic context to frame your answer — group related findings under clear headings.
4. Preserve important terminology from evidence labels (e.g. role names, section titles, legal terms).
5. Keep specific details: names, amounts, dates, conditions, section references.
6. Response length — choose based on query type:
   - R6-VIII: For queries asking for ALL, EVERY, COMPLETE LIST, or ENUMERATE: list EVERY item found across ALL documents without truncation. Completeness is mandatory — do not summarize or drop items.
   - For narrative/summary queries: 3-5 focused paragraphs, prioritizing the most important findings.
7. Cross-document comparison (R6-IX) — for queries asking which document has the latest/earliest/largest/smallest value, or which entity appears most/least:
   a. Extract the relevant value explicitly from EACH document represented in the evidence.
   b. List: "[Document name]: [value found]" for every document.
   c. Then state which is largest/latest/most based only on the extracted values.
   d. If no evidence exists for a document, write "[Document name]: no evidence found" — never guess.
8. Entity counting (R6-XI) — for queries asking which entity appears in more/most/fewer documents: use the Entity-Document Coverage table above as the authoritative source. The coverage table is exact graph data — do not count from passage evidence.
9. Do not mention methodology, sources, or how the evidence was retrieved.
10. If no evidence is available, say: "The requested information was not found in the available documents."

**Answer**:
"""
