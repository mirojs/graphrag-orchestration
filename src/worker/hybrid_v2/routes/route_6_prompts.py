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

When ROUTE6_COMMUNITY_EXTRACT=1 (default), the community MAP phase
fetches actual source sentences via Community→Entity→MENTIONS→Sentence
graph traversal, aligning with Microsoft's LazyGraphRAG MAP design.

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
1. Use all three sources. Thematic context helps you organize; document evidence provides facts. Document structure is a reference list of section headings — do NOT treat each heading as a separate finding. Thematic context entries are topic clusters, NOT separate documents — never present a community theme as if it were a distinct document.
2. Include facts from document evidence even if they are not mentioned in thematic context.
3. Use thematic context to frame your answer — group related findings under clear headings.
4. Preserve important terminology from evidence labels (e.g. role names, section titles, legal terms).
5. Keep specific details: names, amounts, dates, conditions, section references.
6. Response length — choose based on query type:
   - R6-VIII: For queries asking for ALL, EVERY, COMPLETE LIST, or ENUMERATE: list EVERY item found across ALL documents without truncation. Completeness is mandatory — do not summarize or drop items.
   - For narrative/summary queries: 3-5 focused paragraphs, prioritizing the most important findings.
   - PRECISION OVER PADDING: When the query qualifies items with criteria such as "explicitly described as X", "specifically named", "required Y" — only include items where the source evidence EXPLICITLY uses that characterisation. Do not broaden the criteria to include tangentially related items. Omitting a marginal item is always better than including one that doesn't strictly match. For entity/party listing queries, include only entities that are primary contract parties or named organisations — not every entity mentioned in the text (e.g. omit arbitration bodies, generic references, or inferred names).
7. Cross-document comparison (R6-IX) — for queries asking which document has the latest/earliest/largest/smallest value, or which entity appears most/least:
   a. Extract the relevant value explicitly from EACH document represented in the evidence.
   b. List: "[Document name]: [value found]" for every document.
   c. Then state which is largest/latest/most based only on the extracted values.
   d. If no evidence exists for a document, write "[Document name]: no evidence found" — never guess.
8. Entity counting (R6-XI) — for queries asking which entity appears in more/most/fewer documents: use the Entity-Document Coverage table above as the authoritative source. The coverage table is exact graph data — do not count from passage evidence. For "list all parties/organisations" queries, use the Entity-Document Coverage table as a starting point but supplement with entities clearly named as contract parties in the document evidence. Omit entities that are not genuine parties or organisations (e.g. arbitration bodies, individual persons who are not named parties, generic references).
9. Do not mention methodology, sources, or how the evidence was retrieved.
10. REFUSE for specific lookups where the exact data point is absent:
   - Question asks about a specific term, clause, or concept by name (e.g. "mold damage", "force majeure") but that exact term does NOT appear anywhere in the document evidence → say: "The requested information was not found in the available documents." Do NOT infer that an unnamed concept falls under a broader or related category.
   - If no evidence at all is available, say: "The requested information was not found in the available documents."

**Answer**:
"""

# ─────────────────────────────────────────────────────────────────
# COMMUNITY KEY-POINT EXTRACTION PROMPT  (Microsoft-aligned MAP)
# ─────────────────────────────────────────────────────────────────
# Fetches actual source sentences via Community→Entity→MENTIONS→Sentence
# graph traversal, then extracts query-relevant claims from SOURCE TEXT
# (not from abstract community summaries).
# Input:  {query}, {community_source_text}
# Output: JSON array of key points with importance scores.

COMMUNITY_EXTRACT_PROMPT = """\
You are an analyst. Given the user query and source passages from community-grouped documents, extract ONLY the specific facts, terms, conditions, or data points that are directly relevant to answering the query.

**Query**: {query}

**Source Passages** (grouped by community theme, labelled by document):
{community_source_text}

**Instructions**:
1. Read ALL source passages across ALL communities. Extract specific facts relevant to the query.
2. Each key point must be a concrete, specific fact — not a vague theme description.
3. Preserve exact terminology: names, amounts, dates, legal terms, conditions, section references.
4. Score each point 0-100 for importance to answering the query. Be strict: only score ≥ 50 for facts that DIRECTLY and EXPLICITLY address the query criteria. Score < 30 for tangentially related facts.
5. If a community has no relevant facts for this query, skip it entirely.
6. Include facts from EVERY document that contains relevant information — do not focus on just one.
7. PRECISION: When the query asks for items "explicitly described as X" or "specifically named Y", only extract items where the source text EXPLICITLY uses that characterisation. Do not broaden the criteria.

Respond with ONLY a JSON object:
{{"points": [
    {{"description": "specific fact or detail from source text", "score": importance_0_to_100, "community": "community title"}},
    ...
]}}
"""
