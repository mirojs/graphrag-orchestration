# End of Day Handoff — 2025-12-27

## What’s green now

### Global QA (community/global)
- ✅ Global question bank reached **0 failures**.
- ✅ Q‑G8 (insurance/indemnity) now returns explicit limits (e.g., “$300,000”, “$25,000”) reliably.
- ✅ Q‑G7 (notice/delivery) now reliably includes “10 business days” (removed nondeterminism tied to `top_k`/bounded boosting).

### DRIFT stability / ergonomics
- ✅ DRIFT no longer crashes on JSON parsing of the MS GraphRAG DRIFT “primer” output.
  - Adapter now enforces JSON-only output more robustly (strip code fences, extract one JSON payload via `raw_decode`, fallback to `json_repair`).
- ✅ “Fallback only for debugging” behavior implemented.
  - New setting: `V3_DRIFT_DEBUG_FALLBACK` (default `False`).
  - When prerequisites are missing (e.g., no communities/relationships):
    - If `V3_DRIFT_DEBUG_FALLBACK=false` → fail fast with a clean **HTTP 422**.
    - If `V3_DRIFT_DEBUG_FALLBACK=true` → allowed to fall back (debug-only behavior).
- ✅ Router fix deployed so **HTTPException (422)** is not wrapped into **500**.

## Current deployment

- Container App URL: https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- Latest revision observed during deployment: `graphrag-orchestration--0000160`

Health check:
- `GET /health` → 200

## DRIFT: current status (the remaining gap)

### 1) Prerequisites behavior is correct

Group tested (missing communities):
- `X-Group-ID: drift-missing-1766862853`

Observed response:
- `POST /graphrag/v3/query/drift` → **HTTP 422**
- Body: `DRIFT prerequisites missing ... Missing: communities ... Reindex with community detection enabled ...`

This confirms the “debug-only fallback” gate + error propagation is working.

### 2) DRIFT answer quality is still not correct for the minimal group

Group tested (communities present):
- `X-Group-ID: drift-ok-1766862426`

Observed response:
- `POST /graphrag/v3/query/drift` → **HTTP 200**
- Body:
  - `answer`: “Not specified in the provided documents.”
  - `sources`: `[]`
  - `iterations`: often > 1 (e.g., 5)

This indicates DRIFT is running but still failing to ground on the indexed text chunks (it is not surfacing sources and is not pulling the expected “10 business days” fact even when present in indexed text).

## Quick reproducible smoke tests

### A) Missing-communities should return 422

```bash
BASE='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'
GROUP='drift-missing-1766862853'

curl -sS -X POST "$BASE/graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: $GROUP" \
  -d '{"query":"What is the notice period?"}' \
  -w '\nHTTP:%{http_code}\n'
```

Expected:
- `HTTP:422`

### B) Communities-present group returns 200 but “Not specified” (current bug)

```bash
BASE='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'
GROUP='drift-ok-1766862426'

curl -sS -X POST "$BASE/graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: $GROUP" \
  -d '{"query":"What is the notice period?"}' \
  -w '\nHTTP:%{http_code}\n'
```

Expected (today):
- `HTTP:200`
- Answer likely: “Not specified in the provided documents.”

### C) Stats sanity checks

```bash
BASE='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'
GROUP='drift-ok-1766862426'

curl -sS "$BASE/graphrag/v3/stats/$GROUP" \
  -H "X-Group-ID: $GROUP" \
  | jq
```

We previously observed non-zero:
- `entities` > 0
- `relationships` > 0
- `communities` > 0
- `text_chunks` > 0

## Code changes involved (for tomorrow’s debugging)

- `graphrag-orchestration/app/v3/services/drift_adapter.py`
  - JSON coercion/repair for DRIFT primer.
  - `DriftPrerequisitesError` + prerequisite checks.
  - Debug-only fallback gate via `settings.V3_DRIFT_DEBUG_FALLBACK`.

- `graphrag-orchestration/app/v3/routers/graphrag_v3.py`
  - DRIFT endpoint maps prerequisites error to HTTP 422.
  - Preserves `HTTPException` so 422 doesn’t get wrapped into 500.

- `graphrag-orchestration/app/core/config.py`
  - Adds `V3_DRIFT_DEBUG_FALLBACK: bool = False`.

## Open questions / likely root causes for the remaining DRIFT gap

The unresolved issue is **DRIFT returning “Not specified…” with empty sources** despite the group having text chunks and communities.

Most likely areas to investigate next:
1. **DRIFT context building:** Are we actually passing text-unit content into the DRIFT iterations, or only graph summaries?
2. **Text-unit retrieval wiring:** Even if chunks exist, does the DRIFT implementation fetch them (and are we mapping the correct field names/IDs)?
3. **Prompt/response contract:** Does the DRIFT “answerer” prompt require citations/sources but the adapter is discarding them?
4. **Graph-to-text linking:** Are entities/communities linked to the right text chunk IDs so DRIFT can retrieve the source passages?

## Suggested next steps for tomorrow

1. Add temporary debug logging (server-side) for one DRIFT request:
   - How many text units are loaded / passed into each iteration.
   - Whether any text chunk contains the literal “10 business days”.
   - Why `sources` is empty (upstream not returning vs. we’re dropping it).

2. Inspect group data relationships in Neo4j for `drift-ok-1766862426`:
   - Verify the chunk nodes exist and are connected to entities/communities.

3. If the DRIFT library expects a specific schema for “text units”, adapt our adapter to match it (so DRIFT can actually quote and cite).

---

If you want, tomorrow we can start by instrumenting DRIFT with a single “debug trace” mode and running it only for `X-Group-ID: drift-ok-1766862426` to avoid noisy logs.
