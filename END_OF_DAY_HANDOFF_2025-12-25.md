# End-of-day handoff (2025-12-25)

## TL;DR
- Deployment to Azure Container Apps succeeded and is healthy.
- Fresh reindex + Global question bank still has **5 positive failures**.
- Root cause remains: **missing concrete facts are present in `TextChunk`s but absent from `Community.summary`**, so report-driven Global can’t surface them.
- Additional fixes were implemented locally (document-aware excerpt expansion + prompt tweaks) but **NOT deployed yet** (redeploy was canceled).

---

## Environment
- Deployed base URL: `https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`
- Health endpoint: `/health` (returned HTTP 200)
- V3 endpoints (used by QA harness):
  - `/graphrag/v3/index`
  - `/graphrag/v3/stats/{group_id}`
  - `/graphrag/v3/query/global`

## What is deployed vs. what is only local
### Deployed (confirmed)
- Service is deployed and running; image build/push + container app update completed successfully via `deploy-graphrag.sh`.

### Local-only / pending redeploy
These edits exist in the workspace but were not redeployed after the latest QA run:
- `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
  - Document-aware excerpt expansion (pull high-concreteness chunks from the same documents already represented in a community).
  - Expanded concrete fact extraction for:
    - “non-refundable …” spans
    - “start-up fee” phrasing
- `graphrag-orchestration/app/v3/routers/graphrag_v3.py`
  - Prompt tweak: allow partial answers when document attribution is not available in reports/evidence (don’t collapse to “Not specified…”).

---

## Last successful end-to-end run (deployed)
### Group ID
- `phase1-5docs-verify-1766686614`

### Command used
From `graphrag-orchestration/`:
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration \
  && API_URL='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io' \
  GROUP_ID="phase1-5docs-verify-$(date +%s)" \
  WAIT_TIMEOUT_SECONDS=1200 \
  WAIT_POLL_SECONDS=15 \
  RUN_QUESTION_BANK=true \
  QA_ENGINES=global \
  QA_PRINT_ANSWERS=true \
  QA_PRINT_SOURCES=false \
  python test_phase1_5docs.py
 

### Indexing completion signal
`test_phase1_5docs.py` polled `/graphrag/v3/stats/{group_id}` until counts became non-zero.

### Indexing stats observed
- documents: 5
- text chunks: 17
- entities: 228
- relationships: 205
- communities: 22
- raptor nodes: 20

---

## Global question bank result (deployed)
- Ran `QUESTION BANK QA: GLOBAL` with negatives enabled.
- Outcome:
  - **5 failures** (positives)
  - **Negatives passed** (stable; no hallucinated values)

Failures seen:
- Jurisdictions question missing: `State of Idaho`, `Pocatello, Idaho`, `State of Hawaii`
- “Who pays what” missing invoice totals and fee values including `29900.00`
- Named parties question returned `Not specified in the provided documents.` (despite parties being present in community reports)
- Insurance/indemnity missing `$300,000` / `$25,000`
- Non-refundable/start-up fee missing `non-refundable start-up fee` / `$250.00`

---

## Neo4j evidence check (same group)
### Key finding
For `phase1-5docs-verify-1766686614`:
- These terms **exist in TextChunks**:
  - `state of hawaii`
  - `state of idaho`
  - `pocatello`
  - `29900.00`, `subtotal`, `total`, `amount due`
  - `$300,000`, `$25,000`
  - `non-refundable`, `start-up fee`
- Those same terms were **not found in Community summaries** (0 occurrences in `Community.summary` for many of them).

This confirms the remaining gap is still **community report coverage**, not raw ingestion.

---

## Architecture decision (Microsoft-aligned)
We are intentionally keeping Global “report-driven”:
- Query-time Global uses community reports → map → reduce.
- We removed query-time chunk-evidence heuristics so missing facts must be fixed by improving report generation.

Non-canonical but pragmatic guardrails exist:
- “value-like span grounding” + one rewrite attempt when grounding fails (to reduce hallucinated numbers/IDs/URLs).

---

## Tomorrow: exact continuation steps
### Step 1 — Redeploy latest local changes
From repo root:
```bash
cd /afh/projects/graphrag-orchestration && ./deploy-graphrag.sh
```

### Step 2 — Reindex fresh group + rerun global question bank
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration \
  && API_URL='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io' \
  GROUP_ID="phase1-5docs-verify-$(date +%s)" \
  WAIT_TIMEOUT_SECONDS=1200 \
  WAIT_POLL_SECONDS=15 \
  RUN_QUESTION_BANK=true \
  QA_ENGINES=global \
  QA_PRINT_ANSWERS=true \
  QA_PRINT_SOURCES=false \
  python test_phase1_5docs.py
```

### Step 3 — Verify Community summaries now contain the missing concrete facts
- Run a Neo4j scan for the new group:
  - confirm `Community.summary` includes: jurisdiction phrases, invoice total lines, insurance limits, non-refundable fee.

If still missing:
- Next likely levers:
  - Increase excerpt cap or change selection criteria further.
  - Force report sections to include governing law / invoice totals / insurance limits with verbatim chunk headers.

---

## Files touched today
- `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
- `graphrag-orchestration/app/v3/routers/graphrag_v3.py`

## Notes
- Redeploy after the final set of local fixes was canceled, so production is still on the prior deployed revision.
