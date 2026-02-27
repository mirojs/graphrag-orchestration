# Handover: Denoise Filter, Deployment Fixes & Reindex — 2026-02-27

**Date:** 2026-02-27  
**Status:** Refined denoise filter deployed and reindexed (193 sentences); signature block semantic synthesis added; benchmark pending on new index  
**Previous best (pre-denoise):** 56/57 (98.2%) LLM eval — `route7_hipporag2_r4questions_20260226T222346Z` (207 sentences)  
**Current deployed commit:** `cb8320f fix: preserve signed dates and financial totals in denoise filter`

---

## 1. What Was Done Today

### 1.1 V1 OpenAI Embedding Removal (`b2db291`)
- Removed the 3072-dim OpenAI `text-embedding-3-large` fallback from `llm_service.py`
- Removed V1 schema init from `api_gateway/main.py`
- Marked V1 embedding env vars as DEPRECATED in `config.py`
- All embeddings now Voyage `voyage-context-3` (2048-dim) only

### 1.2 Cloud Deployment Fixes
| Commit | Fix | Root Cause |
|--------|-----|------------|
| `e269b82` | HEAD /health support | Azure health probes use HEAD; returned 405 |
| `e7affa6` | Worker Dockerfile fix | `deploy-graphrag.sh` built both images from `Dockerfile.api` instead of `Dockerfile.worker` |
| `66be247` | Thread isolation for indexing | Sync blocking calls (wtpsplit ONNX, Neo4j, Azure DI) blocked the API event loop |
| `e49d5fe` | Pipeline factory init in thread | Factory init also had blocking calls |
| `f7068c6` | `threading.Lock()` → `threading.RLock()` | `get_lazygraphrag_indexing_pipeline_v2()` acquires lock, calls `get_neo4j_store()` which re-acquires same lock → deadlock |

### 1.3 Denoise Filter — Round 1 (`66c202b`)
Enhanced `_is_noise_sentence()` in `sentence_extraction_service.py`:
- Added `PHONE_FAX_RE` — filters phone/fax/emergency number lines
- Added `ADDRESS_ONLY_RE` — filters standalone street + city/state/zip lines
- Added `SUBTOTAL_RE` — filters SUBTOTAL/TOTAL/AMOUNT DUE table rows
- Added multi-line form block detection (3+ lines ≤4 words each, or 2 lines ≤3 words)
- Removed Source D signature party names (By: X, Authorized Representative: X) from extraction
- Changed DI extraction from parallel `asyncio.gather` to sequential loop (OOM fix)
- Added eager wtpsplit model pre-load before DI extraction

**Result:** 207 → 189 sentences (18 filtered)

### 1.4 Benchmark Regression Found
Route 7 benchmark on 189 sentences (`20260227T202248Z`):

| QID | Pre-denoise (207) | Post-denoise (189) | Δ | Issue |
|-----|--------------------|--------------------|-----|-------|
| Q-D5 | 0.85 | 0.93 | +0.08 | ✅ Improved |
| Q-D6 | 0.90 | 0.70 | -0.20 | ❌ Lost SUBTOTAL TOTAL row + "Total contract price $29,900" |
| Q-D7 | 1.00 | 0.65 | -0.35 | ❌ Lost "Signed date: 04/30/2025" (filtered with signature party) |
| Q-D9 | 1.00 | 0.68 | -0.32 | ❌ Possibly entity count change (256→244) or LLM variance |
| **AVG** | **0.87** | **0.77** | **-0.10** | Containment regression |

### 1.5 Denoise Filter — Round 2 (Refined) (`cb8320f`)
Surgical fixes to preserve critical facts while still filtering noise:

1. **Signed dates restored** — Source D now extracts `signed_date` items (e.g., "Signed date: 04/30/2025") with `source="signature_date"`. Party names still skipped.
2. **SUBTOTAL filter tightened** — Only filters rows where the value contains "N/A". Rows with real dollar amounts ($29,900.00, etc.) are preserved.
3. **Multi-line form block exemption** — Blocks containing `$` are exempt from the form-block filter (preserves "Total contract price is $29,900.00..." type sentences).

### 1.6 Reindex Results

| Reindex | Sentences | Entities | Relationships | Elapsed |
|---------|-----------|----------|---------------|---------|
| Pre-denoise (0226 baseline) | 207 | ~256 | ~845 | — |
| Denoise Round 1 (`66c202b`) | 189 | 244 | ~850 | 210s |
| **Denoise Round 2 (`cb8320f`)** | **193** | **260** | **911** | **238s** |

The refined filter correctly brings back 4 sentences that were over-aggressively removed:
- Signed date sentence(s) from Source D
- SUBTOTAL/TOTAL rows with real dollar amounts
- Sentences containing "$" previously caught by multi-line form filter

---

## 2. Current State

### Deployed Infrastructure
- **API:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`
- **Auth:** `az account get-access-token --resource "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817"`
- **Deploy method:** Push to `main` → `.github/workflows/deploy.yml` auto-triggers
- **PDF blob URLs:** `https://neo4jstorage21224.blob.core.windows.net/test-docs/{name}.pdf`

### Git Log (HEAD → main)
```
cb8320f fix: preserve signed dates and financial totals in denoise filter
66c202b fix: enhance sentence denoise filter — 207→189 (remove 18 noise items)
f7068c6 fix: use RLock in pipeline factory to prevent deadlock
e49d5fe fix: move pipeline factory init into thread to prevent event loop blocking
66be247 fix: run indexing pipeline in thread to avoid blocking API event loop
e7affa6 fix: build worker from Dockerfile.worker, add PYTHONUSERBASE
e269b82 fix: add HEAD support to /health for Azure health probes
b2db291 refactor: remove V1 OpenAI embedding fallback, use Voyage V2 only
```

### Neo4j Index State
- **Group:** `test-5pdfs-v2-fix2`
- **193 sentences**, 260 entities, 911 relationships
- GDS community detection returns 0 communities/edges (Neo4j Aura connectivity issue — pipeline gracefully continues)
- KNN edges: 0 (same GDS issue)

---

## 3. Benchmark History

| Benchmark File | Sentences | Avg Cont | Avg F1 | LLM Eval | Notes |
|----------------|-----------|----------|--------|----------|-------|
| `r4questions_20260226T222346Z` | 207 | **0.87** | **0.37** | 56/57 (98.2%) | Pre-denoise baseline (best) |
| `r4questions_20260227T145223Z` | 207 | 0.86 | 0.35 | — | Local re-run (pre-denoise) |
| `r4questions_20260227T165833Z` | 207 | 0.86 | 0.35 | — | Cloud run (pre-denoise) |
| `r4questions_20260227T202248Z` | 189 | 0.77 | 0.32 | — | **Regression** — aggressive denoise |
| *(pending)* | 193 | ? | ? | ? | Refined denoise — needs benchmark |

---

## 4. Key Files Modified

| File | Changes |
|------|---------|
| `src/worker/services/sentence_extraction_service.py` | Denoise filter: PHONE_FAX_RE, ADDRESS_ONLY_RE, SUBTOTAL_RE, multi-line form detection, Source D signed_date preservation |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Sequential DI extraction (OOM fix), eager wtpsplit pre-load |
| `src/worker/hybrid_v2/indexing/pipeline_factory.py` | `threading.Lock()` → `threading.RLock()` |
| `src/api_gateway/routers/hybrid.py` | `asyncio.to_thread()` for indexing pipeline |
| `src/worker/services/llm_service.py` | Removed V1 OpenAI embedding |
| `src/api_gateway/main.py` | Removed V1 schema init |
| `src/api_gateway/routers/health.py` | Added HEAD support |
| `deploy-graphrag.sh` | Fixed to use `Dockerfile.worker` for worker |
| `Dockerfile.worker` | Added PYTHONUSERBASE |

---

## 5. Known Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| GDS community detection returns 0 | Medium | Neo4j Aura connectivity from Azure Container Apps — all cloud reindexes produce 0 communities/KNN edges. Pipeline gracefully degrades. |
| Local 5-PDF reindex OOM | Low | 7.8Gi codespace insufficient for pipeline+wtpsplit (1.56Gi) + VS Code + Copilot. Cloud reindex works fine. |
| Sync endpoint "Unable to retrieve routing information" | Low | Neo4j connection issue from API for sync/hipporag init at startup. Doesn't affect indexing or queries. |
| Q-D10 (2/3) retrieval gap | Low | sent_38 ("warranty terminates if first purchaser sells") not retrieved — single-sentence chunking limitation. Adjacent sentence uses different vocabulary than query. |

---

## 6. TODO List

### Immediate — Verify Denoise Regression Fix

- [ ] **Run Route 7 benchmark on 193-sentence index** — The refined denoise filter (`cb8320f`) has been deployed and reindexed. Need to run benchmark to verify Q-D6, Q-D7, Q-D9 regressions are fixed.
  ```bash
  python3 scripts/benchmark_route7_hipporag2.py \
    --url https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
    --group-id test-5pdfs-v2-fix2 --repeats 1
  ```
- [ ] **Compare per-question scores** against 0226 baseline (containment 0.87, F1 0.37). Target: match or exceed baseline while retaining noise removal.
- [ ] **If Q-D9 still regressed**, run with `--repeats 3` to distinguish LLM variance from genuine regression. Investigate entity count (260 vs 256) impact.

### Carried Over from 2026-02-26 — Route 7 Improvement Plan

#### High Priority — Upstream Alignment
- [ ] **Commit & deploy rerank_top_k=30** — Already in code (`e720c65`), validated locally at 56/57. Needs cloud validation.
- [ ] **OpenIE triple extraction at indexing time** — Dedicated `subject predicate object` extraction with fact embeddings. File: `src/worker/hybrid_v2/indexing/dual_index.py` (`_extract_triples()` stub exists).
- [ ] **Seed ALL passages in PPR (Gap 1)** — Currently only top-20 DPR hits are seeded. Upstream seeds ALL passages. File: `route_7_hipporag2.py` lines 446–454.
- [ ] **Use raw fact scores for entity seeds (Gap 2)** — Currently +1.0 per triple; should use `fact_score / entity_doc_frequency`. File: `route_7_hipporag2.py` lines 414–416.

#### Medium Priority — Retrieval Quality
- [ ] **Sentence window expansion (±1 neighbors)** — When a sentence is retrieved, also fetch adjacent sentences. Fixes Q-D10 gap (sent_37 retrieved but sent_38 missed). File: `route_7_hipporag2.py` `_fetch_chunks_by_ids()`.
- [ ] **Increase PPR passage top-K (Gap 3)** — Upstream uses `retrieval_top_k=200`, Route 7 uses 20. Consider raising to 50–100. File: `route_7_hipporag2.py` line 277.

#### Low Priority — Ablation & Validation
- [ ] **Damping factor ablation (Gap 5)** — Run benchmark sweep {0.5, 0.7, 0.85}.
- [ ] **Verify RELATED_TO edge weights match upstream (Gap 4)** — Check co-occurrence weighting semantics.

### Carried Over from 2026-02-26 — Sentence Extraction Quality

#### Threshold Fixes (Independent of Splitter)
- [ ] **Lower `SKELETON_MIN_SENTENCE_CHARS` 30→20** — Rescues short-but-meaningful legal sentences ("Tenant forfeits deposit.", "All terms are binding."). File: `src/core/config.py:116`.
- [ ] **Tighten ALL_CAPS word threshold 10→6** — Preserves binding legal statements in caps. File: `sentence_extraction_service.py`.
- [ ] **`_is_kvp_label` word threshold 8→10** — Prevents false positives on "Warranty period: One year from completion date." style sentences.
- [ ] **`numeric_only` alpha threshold 10→6** — Recovers "Invoice #1256003", "Total: $29,900".
- [ ] **Whitespace-normalize dedup key** — `re.sub(r'\s+', ' ', text).strip().lower()` to prevent duplicate embeddings.

### Infrastructure
- [ ] **Investigate GDS Aura connectivity** — All cloud reindexes produce 0 communities and 0 KNN edges. Likely Neo4j Aura GDS projection endpoint issue from Azure Container Apps.
- [ ] **Cloud query 500 error investigation** — Some query endpoints returning 500 Internal Server Error intermittently.

---

## 7. Denoise Filter Architecture Reference

Two-layer filtering:

1. **`_is_noise_sentence()`** in `sentence_extraction_service.py` — Filters BEFORE Neo4j storage. This is the layer modified today.
2. **`_classify_sentence()`** in `lazygraphrag_pipeline.py` — Filters for entity extraction only. Sentences still stored in Neo4j even if classified as noise here.

### Patterns in `_is_noise_sentence()` (current state after `cb8320f`)
| Pattern | What it catches | What it preserves |
|---------|----------------|-------------------|
| `PHONE_FAX_RE` | Phone/fax/emergency number lines | — |
| `ADDRESS_ONLY_RE` | Standalone street + city/state/zip | Addresses embedded in prose |
| `SUBTOTAL_RE` (N/A only) | Table rows with "N/A" values | Rows with real dollar amounts |
| Multi-line form (≤4 words × 3+ lines) | Structural form blocks | Blocks containing `$` |
| Source D party names | "By: X", "Authorized Representative: X" | Synthesized into semantic sentence via `_synthesize_signature_sentences()` (source=`signature_block`) |

### 19 Original Noise Items (from 207-sentence audit)
- 4 HTML artifacts (`<table>`, `<!-- PageBreak -->`) — prevented upstream
- 4 signature party names — now synthesized into semantic sentences (not filtered)
- 1 signed date — **preserved** as part of synthesized signature sentence
- 1 SUBTOTAL with N/A — filtered
- 2 SUBTOTAL/TOTAL with real amounts — **preserved** (critical for Q-D6)
- 3 phone/address/form lines — filtered
- 4 multi-line form blocks — filtered (unless containing `$`)

---

## 8. Signature Block Semantic Sentence Synthesis

### Problem
The denoise filter (round 1) dropped signature party names entirely, and round 2 only preserved `"Signed date: 04/30/2025"` as a flat KVP string. This meant party names (who signed), roles (Seller/Buyer), and the date were **not retrievable** via semantic search — a problem when users ask "who signed the contract?" and expect a table with names, roles, and dates.

### Solution (`_synthesize_signature_sentences()`)
Instead of embedding raw signature lines individually (which get caught by noise filters) or discarding them, we now **synthesize a single semantically rich sentence** from the structured `signature_block` metadata that `_extract_signature_block_metadata()` already produces.

**Before:** Only `"Signed date: 04/30/2025"` was embedded (source=`signature_date`).

**After:** A natural-language sentence is synthesized (source=`signature_block`):
- 2 parties + date → `"This document was signed by John Smith as Seller and Jane Doe as Buyer on 04/30/2025."`
- 3 parties + date → `"This document was signed by Alice as Seller, Bob as Buyer and Charlie as Witness on 01/15/2026."`
- 1 party, no date → `"This document was signed by Contoso Ltd. as Authorized Representative."`
- Date only → `"This document was signed on 04/30/2025."`

### Implementation
- New helper: `_synthesize_signature_sentences()` in `sentence_extraction_service.py`
- Updated both code paths (chunk-based Source D and DI-unit-based Source D)
- Source field changed from `"signature_date"` → `"signature_block"`
- **Reindex required** for existing documents to pick up the new sentences

---

## 9. How to Resume

```bash
# 1. Run benchmark on current 193-sentence index
python3 scripts/benchmark_route7_hipporag2.py \
  --url https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-v2-fix2 --repeats 1

# 2. If regression is fixed, run LLM eval
python3 scripts/evaluate_route4_reasoning.py \
  --benchmark-file benchmarks/route7_hipporag2_r4questions_<TIMESTAMP>.md

# 3. To trigger a fresh reindex (if needed)
TOKEN=$(az account get-access-token --resource "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817" --query accessToken -o tsv)
curl -X POST "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"group_id":"test-5pdfs-v2-fix2","documents":[
    {"source":"https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS%20LIMITED%20WARRANTY.pdf"},
    {"source":"https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf"},
    {"source":"https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"},
    {"source":"https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf"},
    {"source":"https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf"}
  ],"reindex":true,"ingestion":"document-intelligence","run_community_detection":true,"run_raptor":false}'
```
