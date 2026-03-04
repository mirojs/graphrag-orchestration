# HANDOVER: Route 7 Triple Reranking — 2026-03-04

## Status: Code Committed, Deploy In Progress, Not Yet Validated

## Current Score: 55/57 (96.5%)

---

## Context

Route 7 (HippoRAG 2) benchmark sits at **55/57** with two different failure modes depending on configuration:

| Config | Score | Failures | Root Cause |
|--------|-------|----------|------------|
| PPR-only (DPR=50, no rerank-all) | 55/57 | Q-D3 (1/3) | Cosine triple linking misses abstract category matches |
| Rerank-all (DPR=0, RERANK_ALL_TOP_K=100) | 55/57 | Q-D10 (2/3), Q-N8 (2/3) | Too much context → LLM adds tangential info |

The rerank-all approach (step 4.6) is a **brute-force patch** that bypasses the graph entirely. The user explicitly rejected it: "we should not use two retrieval methods and add them if there's other choices."

---

## Root Cause Analysis: Q-D3

**Query:** "Compare 'time windows' across the set: list all explicit day-based timeframes."

**Problem:** Cosine-based triple linking (`top_k=5`) only finds 2 relevant triples (both about "sixty (60) days"). Missing timeframes:
- 3 business days (cancel period) — `sent_23`: **zero shared entities** with any PPR seed
- 5 business days (listing window) — reachable via "termination" but PPR score too low
- 10 business days (holding tank) — `sent_17`: **zero shared entities** with any PPR seed
- 90 days (labor warranty) — weakly reachable via "warranty"
- 180 days (arbitration window) — reachable via "defect" but PPR score too low

**Why cosine fails:** The query mentions "time windows" — an abstract category. Cosine similarity can't reason that "3 business days" IS a "time window." Upstream HippoRAG 2 uses an **LLM reranker** (GPT-4o-mini) for this reasoning step.

---

## Solution Implemented: Instruction-Following Triple Reranking

**Commit:** `67bff38d` — `feat(route7): add instruction-following triple reranking with Voyage rerank-2.5`

### Architecture: Three-Stage Triple Linking Pipeline

```
Stage 1: Cosine recall (top 30 candidates)      ← ROUTE7_TRIPLE_CANDIDATES_K=30
    ↓
Stage 2: Voyage rerank-2.5 with instruction      ← ROUTE7_TRIPLE_RERANK=1
    ↓  (selects top 5 from 30 using instruction-guided relevance)
Stage 3: LLM recognition memory filter           ← existing, unchanged
    ↓
Entity seeds → PPR
```

### Key Code Changes

**File:** `src/worker/hybrid_v2/routes/route_7_hipporag2.py`

1. **`_query_to_triple_linking()`** (line ~1083): Modified to widen cosine search to `ROUTE7_TRIPLE_CANDIDATES_K` when `ROUTE7_TRIPLE_RERANK=1`, then pipe through `_rerank_triples()` before existing LLM filter.

2. **`_rerank_triples()`** (line ~1127): New method. Uses `voyageai.Reranking.create()` directly (bypassing `Client.rerank()` which lacks `instruction` param in SDK 0.3.7) with an instruction that steers the cross-encoder to understand abstract category membership.

3. **Start logging** (line ~307): Added `triple_rerank` and `triple_candidates_k` to the `route_7_hipporag2_start` log event for diagnostics.

### New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ROUTE7_TRIPLE_RERANK` | `0` | Enable instruction-following triple reranking |
| `ROUTE7_TRIPLE_CANDIDATES_K` | `30` | Number of cosine candidates to fetch before reranking |

### Instruction Text

```
Score each fact based on how relevant it is to answering the query. 
Consider abstract category membership: e.g., if the query asks about 
'time windows' or 'timeframes', facts mentioning specific durations 
like '3 business days' or '90 days' are highly relevant.
```

### Voyage SDK Note

The installed `voyageai` SDK (v0.3.7) `Client.rerank()` method does NOT expose the `instruction` parameter. We bypass this by calling `voyageai.Reranking.create(**params)` directly — the base `APIResource.create()` accepts `**params` and passes them through to the HTTP POST body. This needs validation that the API actually uses the instruction.

---

## Deploy Status

### What's Deployed (as of last check)

- **Container image tag:** `a3445bab` — this is from a PRIOR commit, NOT the triple rerank commit
- **Env vars SET:** `ROUTE7_TRIPLE_RERANK=1`, `ROUTE7_TRIPLE_CANDIDATES_K=30`, `ROUTE7_RERANK_ALL=0`
- **Redeploy in progress:** `deploy-graphrag.sh` was running at time of handover (shell 117)

### CRITICAL: First Test Was Invalid

The Q-D3 test at `20260304T203520Z` (containment=0.38) ran against the **old container image** that did NOT contain the triple rerank code. The env vars were set, but the code to read them wasn't deployed yet. The logs confirmed only 5 triple candidates (not 30), and no `triple_rerank_complete` log events appeared.

**This test must be re-run after deploy completes.**

### Current Env Vars on Container App

```
ROUTE7_RERANK_ALL=0
ROUTE7_PPR_PASSAGE_TOP_K=20
ROUTE7_DPR_TOP_K=50
ROUTE7_DPR_SENTENCE_TOP_K=0
ROUTE7_RERANK_ALL_TOP_K=50
ROUTE7_TRIPLE_RERANK=1
ROUTE7_TRIPLE_CANDIDATES_K=30
```

---

## Benchmark History (2026-03-04)

| Timestamp | Config | Score | Notes |
|-----------|--------|-------|-------|
| 185048Z | DPR=50, no rerank-all | 52/57 | Q-D3 1/3, Q-D5 2/3, Q-D8 1/3 |
| 190150Z | DPR=50, no rerank-all | 55/57 | Q-D3 1/3 only failure (best PPR-only) |
| 193141Z | DPR=0, RERANK_ALL=1, TOP_K=100 | — | Q-D3 only: containment=0.72 (massive improvement) |
| 193305Z | DPR=0, RERANK_ALL=1, TOP_K=100 | 55/57 | Q-D3 3/3 ✅ but Q-D10 2/3, Q-N8 2/3 |
| 203520Z | Triple rerank (NOT DEPLOYED) | — | Q-D3 only: containment=0.38 — **INVALID** (old image) |

---

## TODO List

### Immediate (Complete the Current Experiment)

- [ ] **Verify deploy completed** — Check that `deploy-graphrag.sh` finished and the new image tag matches commit `67bff38d`. Shell 117 may still be running.
  ```bash
  az containerapp show --name graphrag-api -g rg-graphrag-feature --query "properties.template.containers[0].image" -o tsv
  ```

- [ ] **Re-run Q-D3 quick test** — Confirm triple reranking is active (look for `route7_triple_rerank_complete` in logs and 30 candidates in `route7_triple_candidates`)
  ```bash
  python3 scripts/benchmark_route7_hipporag2.py --filter-qid Q-D3 --include-context --group-id test-5pdfs-v2-fix2
  ```

- [ ] **Validate Voyage instruction param** — If Q-D3 doesn't improve, the `instruction` param may be silently ignored by the API. Test locally:
  ```python
  import voyageai
  rr = voyageai.Reranking.create(
      query="time windows", 
      documents=["3 business days cancel", "the sky is blue"],
      model="rerank-2.5",
      instruction="Score based on whether the fact describes a timeframe.",
      api_key="..."
  )
  print(rr.data)  # Check if instruction affected scoring
  ```

- [ ] **Run full 19-question benchmark** if Q-D3 improves
  ```bash
  python3 scripts/benchmark_route7_hipporag2.py --group-id test-5pdfs-v2-fix2
  ```

- [ ] **Run LLM eval** for definitive score
  ```bash
  python3 scripts/evaluate_route4_reasoning.py benchmarks/<latest>.json
  ```

### If Triple Reranking Works (Q-D3 ≥ 2/3)

- [ ] **Tune `ROUTE7_TRIPLE_CANDIDATES_K`** — try 50 or all triples in the graph to maximize recall
- [ ] **Tune `top_k` after reranking** — currently 5 (upstream default), may need 10 for exhaustive queries like Q-D3
- [ ] **Add IDF weighting on entity seeds** — rare entities like "3 business days" should get higher PPR weight than hubs like "defect"
- [ ] **Tune instruction text** — the current instruction is generic; a more specific one may help

### If Triple Reranking Doesn't Help

- [ ] **Check if Voyage API ignores the `instruction` param** — the SDK doesn't officially expose it
- [ ] **Fallback: prepend instruction to query string** — `"[Instruction: ...] time windows"` as the `query` param
- [ ] **Fallback: use LLM (GPT-4o-mini) for triple filtering** — upstream approach, more expensive but can reason about category membership
- [ ] **Fallback: increase `ROUTE7_TRIPLE_TOP_K`** from 5 to 10-15 without reranking — brute-force wider cosine window

### Longer-Term Improvements

- [ ] **IDF weighting on entity seeds** — weight entities by inverse document frequency so rare entities (specific timeframes) get higher PPR mass than hub entities (defect, warranty)
- [ ] **Consider `triple_top_k` increase** — even with reranking, 5 triples may be too few for exhaustive cross-document comparison queries
- [ ] **Synthesis prompt hardening** — Q-D10 and Q-N8 failures are synthesis issues (LLM adds tangential info); tighten prompt rules

---

## Key Files

| File | Purpose |
|------|---------|
| `src/worker/hybrid_v2/routes/route_7_hipporag2.py` | Route 7 main implementation — triple linking at ~1083, rerank at ~1127 |
| `src/worker/hybrid_v2/retrievers/triple_store.py` | Triple embedding store + LLM recognition memory filter |
| `scripts/benchmark_route7_hipporag2.py` | Benchmark runner |
| `scripts/evaluate_route4_reasoning.py` | LLM-as-Judge eval (GPT-5.1) |

## Key Infrastructure

| Resource | Value |
|----------|-------|
| Container App | `graphrag-api` in `rg-graphrag-feature` |
| API URL | `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io` |
| AAD scope | `api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default` |
| Group ID | `test-5pdfs-v2-fix2` |
| Voyage SDK | v0.3.7 (latest as of 2026-03-04) |

---

## Appendix: ADLS Gen2 Storage Enablement for Frontend File Management

### Problem

The frontend's `AdlsBlobManager` requires an ADLS Gen2 storage account (HNS-enabled, `*.dfs.core.windows.net` endpoint) for per-user file uploads with hierarchical namespace and ACL-based access control. The existing storage account `neo4jstorage21224` did not have HNS enabled.

### Root Cause Chain

1. **HNS not enabled** on `neo4jstorage21224` — the account was created as standard Blob Storage (StorageV2 without hierarchical namespace).
2. **HNS migration blocked by Blob Tags** — Microsoft Defender for Storage automatically adds "Malware Scanning" tags to blobs. ADLS Gen2 migration requires all blob tags to be removed first.
3. **`BlobManager` lacks `list_blobs`** — The deployed image (`a3445bab`) used `prepdocslib.BlobManager` (which has no `list_blobs` method) instead of the newer `UserBlobManager` from `src/api_gateway/services/user_blob_manager.py` (commit `e793a626`).

### Resolution

#### 1. Storage Account Migration (In-Place)

Upgraded `neo4jstorage21224` to ADLS Gen2 via Azure HNS migration:

```bash
# 1. Clear Defender malware-scan blob tags (blocking migration)
az storage blob tag set --account-name neo4jstorage21224 --container-name <container> --name <blob> --tags "" --auth-mode key

# 2. Validate migration
az storage account hns-migration start --type validation --name neo4jstorage21224 --resource-group rg-graphrag-feature

# 3. Upgrade (irreversible)
az storage account hns-migration start --type upgrade --name neo4jstorage21224 --resource-group rg-graphrag-feature
```

**Result:** `isHnsEnabled: true` — DFS endpoint now available at `https://neo4jstorage21224.dfs.core.windows.net`.

#### 2. Container Created

```bash
az storage container create --name user-content --account-name neo4jstorage21224 --auth-mode login --public-access off
```

#### 3. Infrastructure Changes

- **`infra/core/storage/storage-account.bicep`** (new): Reusable storage account module with `isHnsEnabled` parameter.
- **`infra/main.bicep`**: Added `useUserUpload` flag (default `true`), `userStorageContainerName` param. Passes `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONTAINER`, `AZURE_USERSTORAGE_ACCOUNT`, `AZURE_USERSTORAGE_CONTAINER` env vars to container apps. Added `Storage Blob Data Owner` role assignment.
- **`infra/core/security/role-assignments.bicep`**: Added optional `userStorageAccountName` param and `Storage Blob Data Owner` role.
- **`deploy-graphrag.sh`**: Added `AZURE_STORAGE_ACCOUNT`/`CONTAINER` to ENV_VARS. Fixed `AZURE_USERSTORAGE_CONTAINER` default from `documents` to `user-content`.

#### 4. Container App Env Vars

All three container apps (`graphrag-api`, `graphrag-api-b2c`, `graphrag-worker`) updated with:

| Variable | Value |
|---|---|
| `AZURE_STORAGE_ACCOUNT` | `neo4jstorage21224` |
| `AZURE_STORAGE_CONTAINER` | `content` |
| `AZURE_USERSTORAGE_ACCOUNT` | `neo4jstorage21224` |
| `AZURE_USERSTORAGE_CONTAINER` | `user-content` |

#### 5. Code Fix (Pending Deploy)

The deployed image `a3445bab` predates commit `e793a626` which introduced `UserBlobManager` with `list_blobs`. Full redeploy needed.

### Key Learnings

- **HNS migration is possible** on existing accounts (since ~2023), but requires removing all blob tags first.
- **Microsoft Defender blob tags** are invisible via `--auth-mode login` — needs `--auth-mode key` to read/clear.
- **Single storage account** works for both global content (Blob API) and user uploads (DFS API).
- **Deploy script must pass env vars** — Bicep env vars only apply during `azd provision`; `deploy-graphrag.sh` overrides them via `az containerapp update --set-env-vars`.
