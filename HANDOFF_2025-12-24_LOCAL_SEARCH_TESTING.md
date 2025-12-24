# Handoff — 2025-12-24 — Local Search Testing + Rate-Limit Work

## Goal
Validate **engine correctness** for V3 endpoints, with emphasis on **Local search**:
- Must answer the **10 Local questions** from the question bank correctly.
- Must also answer the **10 Negative questions** with a clear "not specified / not found" style response.

## Current blocker / why we paused
We attempted to run the full Local question-bank suite against the deployed API and hit a harness parsing bug:
- The question bank uses IDs like `Q-L1`, `Q-G10`, etc.
- The parser initially expected `Q-L-1` style IDs.
- Fix applied: parser now accepts `Q-L1` / `Q-L10`.
- Re-run was started but cancelled before completion.

## What was changed today (workspace code)
### 1) Question-bank-driven QA + 429 handling
File: graphrag-orchestration/test_phase1_5docs.py
- Adds robust handling for deployment rate limits:
  - Retries + honors `Retry-After` on HTTP 429
  - Adds pacing between questions via `SLEEP_BETWEEN_QUERIES_SECONDS`
- Adds an **engine correctness** test mode driven by the grounded question bank:
  - Parses QUESTION_BANK_5PDFS_2025-12-24.md
  - Runs 10 positives + 10 negatives per engine
  - Validates positives by extracting strong anchors (primarily backticked terms, plus dates/numbers)
  - Validates negatives by requiring phrases like "not specified", "not mentioned", etc.

Key env flags (harness):
- `RUN_QUESTION_BANK=true`
- `QA_ENGINES=local` (or others)
- `QA_INCLUDE_NEGATIVES=true`
- `SKIP_INDEXING=true` (reuse an existing indexed group)
- `SKIP_NEO4J_VERIFY=true` (skip direct Neo4j metrics if only testing endpoints)

### 2) Force-route support for vector testing
File: graphrag-orchestration/app/v3/routers/graphrag_v3.py
- Adds `force_route` to the unified request model and passes it through to the TripleEngineRetriever.
- This enables deterministic testing of the vector engine without invoking the routing LLM.

### 3) Hallucination reduction for negative tests
Files:
- graphrag-orchestration/app/v3/routers/graphrag_v3.py
- graphrag-orchestration/app/v3/services/triple_engine_retriever.py
- graphrag-orchestration/app/v3/services/drift_adapter.py

Changes:
- Prompts now explicitly instruct: if answer not present in supplied context/summaries/excerpts, respond with:
  - `Not specified in the provided documents.`
- DRIFT wrapper prepends a prefix to all DRIFT LLM calls with the same instruction.

### 4) Speed debugging support (not deployed yet)
File: graphrag-orchestration/app/v3/routers/graphrag_v3.py
- Adds `synthesize: bool = true` to V3QueryRequest.
- When `synthesize=false` for local/global/raptor, endpoint returns retrieval context without LLM synthesis.
- Adds timing logs (embed ms / Neo4j ms / LLM ms / total ms) for local/global/raptor.

Important: This only helps once the backend is redeployed with these changes.

## Known reality about local search speed
Even though it is called "local search", the current V3 implementation does:
1) embedding call (Azure embeddings)
2) Neo4j query
3) synthesis call (GPT-5.2)

The GPT-5.2 synthesis step is the main reason local can feel slow and is also where 429 rate limits show up.

## What is confirmed working
- Phase 1 index readiness polling via `/graphrag/v3/stats/{group_id}` works.
- Question bank file exists and has:
  - 10 Vector questions
  - 10 Local questions
  - 10 Global questions
  - 10 Drift questions
  - 10 RAPTOR questions
  - 10 Negative questions

Question bank:
- QUESTION_BANK_5PDFS_2025-12-24.md

## What to do tomorrow (exact commands)
### A) Re-run Local question-bank correctness against an existing group
Pick a group id that is already indexed (example used during testing):
- `phase1-5docs-1766598810`

Run:
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration \
  && GROUP_ID=phase1-5docs-1766598810 \
  SKIP_INDEXING=true SKIP_NEO4J_VERIFY=true \
  RUN_QUESTION_BANK=true QA_ENGINES=local QA_INCLUDE_NEGATIVES=true \
  LOCAL_QUERY_TIMEOUT_SECONDS=300 LOCAL_QUERY_RETRIES=3 \
  SLEEP_BETWEEN_QUERIES_SECONDS=5 \
  python3 test_phase1_5docs.py
```

### B) If local is still "slow", first prove whether it’s GPT-5.2 vs Neo4j
This requires a backend redeploy to pick up `synthesize=false` and timing logs.
After redeploy, call local endpoint with synthesize disabled and see if it is fast.

### C) Optional: run the full matrix (all engines)
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration \
  && GROUP_ID=phase1-5docs-1766598810 \
  SKIP_INDEXING=true SKIP_NEO4J_VERIFY=true \
  RUN_QUESTION_BANK=true QA_INCLUDE_NEGATIVES=true \
  SLEEP_BETWEEN_QUERIES_SECONDS=5 \
  python3 test_phase1_5docs.py
```

## Notes
- The deployed API is currently:
  - https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- Rate limiting observed is on GPT-5.2 deployment; the harness now paces and retries.
- The repo currently has uncommitted changes (4 files modified).
