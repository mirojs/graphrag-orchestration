# Boosters (Selection & Synthesis Guardrails)

This repo uses “boosters” as small, query-class–specific guardrails that improve **recall** and **completeness** in the GraphRAG pipeline without relying on document-specific rules.

A booster is **not stored in Neo4j** (or any database). It is **runtime logic in the orchestrator** (FastAPI service). What *is* stored is the **evidence and summaries** the booster operates on.

## Why boosters exist

RAG/GraphRAG failures commonly come in two flavors:

1) **Selection/recall misses**: the needed fact exists in the corpus, but the pipeline fails to retrieve/select the right community/chunk, so the model never sees it.
2) **Synthesis/compression drops**: the fact is present in retrieved context, but the map/reduce summarization drops a concrete anchor (numbers, deadlines, limits) in the final answer.

Boosters address these failure modes while keeping answers grounded.

## Where boosters live

Boosters live in the V3 orchestration layer, for example:

- graphrag-orchestration/app/v3/routers/graphrag_v3.py

They are deployed with the container image. There is nothing “booster-specific” to persist.

## What boosters read from storage

Boosters operate on data already stored by the indexing pipeline:

- **Neo4j graph store**: community hierarchy/levels, community summaries, and chunk evidence (and group isolation).
- **Vector store (optional, depending on routing/mode)**: embeddings index used for similarity retrieval.

If you run **global/community** mode only, Neo4j can be sufficient. If you also want robust **vector/local/raptor** behavior at scale, you typically also need a vector store.

## Booster types

### 1) Selection-stage recall boost

Goal: ensure the right evidence enters the context window.

Pattern:

- Detect a **query class** by generic signals (keywords/patterns).
- Search a broader candidate set (e.g., all level-0 communities) for summaries that contain concrete anchors relevant to that class.
- Add a small bounded number of extra candidates (e.g., 1–2), then re-rank for the final top_k.

Key properties:

- Bounded expansion (prevents context explosion).
- Uses generic patterns (non-document-specific).
- Still relies on stored summaries/evidence (grounded).

Examples in this repo:

- Insurance/indemnity selection recall augmentation
- Notice/delivery/filings selection recall augmentation

### 2) Post-reduce completeness booster (grounded rewrite)

Goal: if a concrete anchor appears in evidence but is missing from the final answer, force it to be included **verbatim (or near-verbatim)**.

Pattern:

- Extract required anchors from evidence (e.g., money amounts, deadlines like “ten (10) business days”).
- Check whether the synthesized answer includes them.
- If not, run a constrained rewrite that:
  - requires including the anchor(s) verbatim, and
  - forbids inventing new numbers/jurisdictions/deadlines.

Key properties:

- Only fires when evidence already contains the anchor.
- Improves determinism for “hard” facts.
- Preserves grounding.

## Why boosters are reasonable and non-document-specific

A booster is considered reasonable (and not a one-off hack) when:

- It addresses a **generic failure mode** (recall miss or compression drop).
- It’s keyed off **cross-domain contract patterns** (e.g., “N business days”, “certified mail return receipt requested”, currency formats), not document names.
- It’s **bounded** (adds minimal extra context, minimal extra LLM calls).
- It maintains **grounding**: no new facts beyond evidence.

## How to add a new booster safely

1) **Prove the failure mode**
   - If the fact is absent from selected context → selection boost.
   - If present in context but missing from answer → post-reduce completeness boost.

2) **Use generic detectors**
   - Prefer patterns/keywords that generalize across documents.

3) **Keep it bounded**
   - Add a small fixed number of extra candidates.
   - Avoid wide fan-out.

4) **Preserve grounding**
   - Only force inclusion of anchors that are extractable from evidence.

5) **Validate with the question bank**
   - Re-run targeted failing questions first.
   - Then re-run the full suite for the affected engine(s).
