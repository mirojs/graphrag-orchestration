"""Route 6: Concept Search — Synthesis prompt.

Route 6 restores the LazyGraphRAG insight: community summaries provide
thematic structure.  Unlike Route 3 (MAP-REDUCE), there is NO MAP phase.
Community summaries are passed **directly** to synthesis alongside sentence
evidence, eliminating the lossy claim-extraction step and the N extra LLM
calls that produced +41% latency for +1% containment improvement.

The prompt receives three evidence streams:
  1. Community summaries  — thematic structure from graph communities
  2. Sentence evidence    — direct vector search on source sentences
  3. (Reserved) PPR graph evidence — entity relationships (future)

Design rationale documented in:
  ANALYSIS_ROUTE3_LAZYGRAPHRAG_DEVIATION_AND_ROUTE6_PLAN_2026-02-19.md
"""

# ─────────────────────────────────────────────────────────────────
# CONCEPT SYNTHESIS PROMPT
# ─────────────────────────────────────────────────────────────────
# Input variables: {query}, {community_summaries}, {sentence_evidence}
# Expected output: final synthesized response

CONCEPT_SYNTHESIS_PROMPT = """\
You are a document analysis assistant. Answer the query using the evidence below.

**Query**: {query}

**Thematic Context** (community summaries from knowledge graph):
{community_summaries}

**Document Evidence** (sentences retrieved from source documents):
{sentence_evidence}

**Rules**:
1. Use both sources. Thematic context helps you organize; document evidence provides facts.
2. Include facts from document evidence even if they are not mentioned in thematic context.
3. Use thematic context to frame your answer — group related findings under clear headings.
4. Keep specific details: names, amounts, dates, conditions, section references.
5. 3-5 focused paragraphs maximum — prioritize the most important findings.
6. Do not mention methodology, sources, or how the evidence was retrieved.
7. If no evidence is available, say: "The requested information was not found in the available documents."

**Answer**:
"""
