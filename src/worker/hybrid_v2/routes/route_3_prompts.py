"""Route 3 v2: Map-Reduce prompts for LazyGraphRAG global search.

These prompts implement the core LazyGraphRAG insight: synthesize answers
from community summaries (which already encode the full graph structure)
rather than fetching and deduplicating raw chunks.

Two-phase approach:
  MAP  — One LLM call per community: extract claims relevant to the query.
  REDUCE — One LLM call total: synthesize all community claims into a
           coherent global answer.

Token budget: MAP outputs are bounded by max_claims to keep REDUCE input
under control (~4K tokens for 3 communities × 10 claims each).
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
