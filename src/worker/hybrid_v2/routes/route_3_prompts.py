"""Route 3 v3: Map-Reduce prompts for sentence-enriched global search.

These prompts implement a hybrid synthesis strategy:
  MAP  — One LLM call per community: extract claims relevant to the query.
  REDUCE_WITH_EVIDENCE — One LLM call total: synthesize community claims
           AND direct sentence evidence into a coherent global answer.

v3 improvement: REDUCE now receives two evidence streams:
  1. Community claims (thematic structure from graph summaries)
  2. Sentence evidence (direct vector search on source sentences)

This eliminates coverage gaps where themes are present in sentences
but not surfaced through community abstraction layers.
"""

# ─────────────────────────────────────────────────────────────────
# MAP PROMPT
# ─────────────────────────────────────────────────────────────────
# Input variables: {query}, {community_title}, {community_summary},
#                  {entity_names}
# Expected output: numbered list of claims, or "NO RELEVANT CLAIMS"

MAP_PROMPT = """\
You are an analytical assistant performing the MAP phase of a global search.

**Task**: Extract specific, factual claims from the community summary below
that are relevant to the user's query. Each claim must be self-contained
(understandable without reading the summary) and cite the community as source.

**Query**: {query}

**Community**: {community_title}
**Key Entities**: {entity_names}
**Summary**:
{community_summary}

**Instructions**:
1. Read the summary carefully.
2. List up to {max_claims} claims that help answer the query.
3. Each claim must:
   - State a specific fact, relationship, or provision (not a vague theme).
   - Be a complete sentence.
   - Include entity names, amounts, dates, or conditions where present.
4. If NOTHING in the summary is relevant, respond with exactly:
   NO RELEVANT CLAIMS
5. Do NOT invent information not present in the summary.

**Output format** (numbered list):
1. [First factual claim]
2. [Second factual claim]
...
"""

# ─────────────────────────────────────────────────────────────────
# REDUCE PROMPT
# ─────────────────────────────────────────────────────────────────
# Input variables: {query}, {response_type}, {all_claims}
# Expected output: final synthesized response

REDUCE_PROMPT = """\
You are an analytical assistant performing the REDUCE phase of a global search.

**Task**: Synthesize the extracted claims below into a coherent {response_type}
that answers the user's query. The claims were extracted from community
summaries of a knowledge graph built from the user's document corpus.

**Query**: {query}

**Extracted Claims**:
{all_claims}

**Instructions**:
1. Organize the claims thematically — group related facts together.
2. Resolve any contradictions by noting them explicitly.
3. Preserve specific details: entity names, amounts, dates, conditions.
4. If claims come from different communities (marked with [Community: ...]),
   note cross-document patterns and differences.
5. If no claims were extracted (empty input), respond with:
   "The requested information was not found in the available documents."
6. Do NOT add information beyond what the claims state.

**Response Type**: {response_type}
- "summary": Concise overview (3-5 paragraphs)
- "detailed_report": Comprehensive structured report with headings
- "bullet_points": Organized bullet-point list
- Otherwise: Adapt to the requested format

**Response**:
"""

# ─────────────────────────────────────────────────────────────────
# REDUCE WITH EVIDENCE PROMPT (v3)
# ─────────────────────────────────────────────────────────────────
# Input variables: {query}, {response_type}, {community_claims},
#                  {sentence_evidence}
# Expected output: final synthesized response

REDUCE_WITH_EVIDENCE_PROMPT = """\
You are an analytical assistant performing the REDUCE phase of a global search.

**Task**: Synthesize TWO sources of evidence into a coherent {response_type}
that comprehensively answers the user's query.

**Query**: {query}

---

**SOURCE 1 — Community Claims** (extracted from knowledge graph community summaries):
{community_claims}

---

**SOURCE 2 — Direct Sentence Evidence** (retrieved from source documents via semantic search):
{sentence_evidence}

---

**Instructions**:
1. Use BOTH sources to build the most complete answer possible.
2. Community claims provide thematic structure — use them to organize topics.
3. Sentence evidence provides direct factual content from source documents.
   If a fact appears in sentence evidence but NOT in community claims,
   you MUST still include it in your response.
4. Organize thematically — group related facts together under clear headings
   or logical sections.
5. Preserve specific details: entity names, amounts, dates, percentages,
   conditions, section references.
6. If sources provide different levels of detail on the same topic, use
   the more specific/detailed version.
7. Note cross-document patterns and differences when applicable.
8. If BOTH sources are empty, respond with:
   "The requested information was not found in the available documents."
9. Do NOT add information beyond what the evidence states.
10. Do NOT mention or reference the two-source methodology in your response.
    Write as if all information comes from a single comprehensive analysis.

**Response Type**: {response_type}
- "summary": Concise overview (3-5 paragraphs)
- "detailed_report": Comprehensive structured report with headings
- "bullet_points": Organized bullet-point list
- Otherwise: Adapt to the requested format

**Response**:
"""

# ─────────────────────────────────────────────────────────────────
# REDUCE WITH EVIDENCE — CONCISE (v3.2, default)
# ─────────────────────────────────────────────────────────────────
# Ablation-proven: gpt-4.1 + concise = 100% theme coverage.
# Shorter prompt → faster TTFT, less output bloat.
# Input variables: {query}, {response_type}, {community_claims},
#                  {sentence_evidence}

REDUCE_WITH_EVIDENCE_PROMPT_CONCISE = """\
You are a document analysis assistant. Answer the query using the evidence below.

**Query**: {query}

**Community Claims**:
{community_claims}

**Document Sentences**:
{sentence_evidence}

**Rules**:
1. Use ALL evidence. Every obligation, requirement, duty, or provision found in ANY
   document sentence must appear in your answer — even if it appears in only one
   sentence from one document.
2. Organize using the structure the query implies (e.g. per-obligation type,
   per-document, per-party). Use clear headings.
3. Keep specific details: names, amounts, dates, conditions.
4. Completeness takes priority over brevity. Do not drop any item to save space.
   Be concise within each item, but include all items.
5. Do not mention methodology or sources.
6. If no evidence, say: "The requested information was not found in the available documents."

**Answer**:
"""
