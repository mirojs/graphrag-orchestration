# Azure Schema Validation Kickoff

This document is your quick start for tomorrow’s session to validate enhanced schema generation with the real Azure Content Understanding API.

## Where we left off
- Enhanced backend is complete and tested locally.
- A new test harness `backend/test_azure_schema_quality.py` compares baseline vs enhanced schemas and attempts analyzer creation via Azure API.
- DNS resolution fails for the `services.ai.azure.com` host from this environment. We added:
  - Env-based endpoint overrides
  - DNS resolvability checks
  - Automatic fallback to `cognitiveservices.azure.com` when possible
  - Graceful offline behavior (still prints quality metrics)
- Progress log: `AZURE_SCHEMA_TEST_PROGRESS.md` summarizes work and next steps.

## What we need to proceed
- A reachable Content Understanding endpoint, typically of the form:
  - `https://<resource>.cognitiveservices.azure.com`
- The correct API path segment for analyzer creation (we’ll probe if unknown):
  - `/contentunderstanding/analyzers?api-version=2025-05-01-preview`

## Quick start (5–10 minutes)
1. Set endpoint
   ```bash
   export AZURE_CONTENTUNDERSTANDING_ENDPOINT="https://<resource>.cognitiveservices.azure.com"
   ```
2. Verify Azure CLI auth
   ```bash
   az account show --output table
   az account get-access-token --resource https://cognitiveservices.azure.com/ --query accessToken -o tsv | wc -c
   ```
3. Run the test harness
   ```bash
   python backend/test_azure_schema_quality.py
   ```
4. If analyzer creation fails with 404/400, note the response and continue with the Endpoint Probe (below).

## Endpoint Probe (to add)
We plan to add `backend/endpoint_probe.py` to sweep likely endpoints:
- `GET/HEAD /contentunderstanding/analyzers?api-version=2025-05-01-preview`
- `GET/HEAD /contentunderstanding/analyzers?api-version=2024-07-31-preview`
- `GET/HEAD /contentunderstanding/projects?api-version=2025-05-01-preview`

The script will report DNS, TLS, HTTP code, and latency, with bearer auth from `az account get-access-token`.

## Success criteria
- Enhanced schema is accepted by Azure (HTTP 200/201) for analyzer creation.
- Baseline vs enhanced: enhanced quality score ≥ 85, baseline < 70 (on real run).
- Ability to process real documents and produce results matching the gold-standard schema shape.

## Comparison against Gold Standard
- File: `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json`
- Key checks:
  - Unified AllInconsistencies array with Category field
  - Severity and Type classification present and consistent
  - DocumentA/DocumentB provenance pattern with page numbers
  - Summary object (counts, category breakdown, risk assessment)
  - UUID stripping from filenames

## Troubleshooting Checklist
- DNS failure (`HTTP 000` / curl could not resolve host):
  - Confirm network/VPN access; try `nslookup <resource>.cognitiveservices.azure.com`
  - Export `AZURE_CONTENTUNDERSTANDING_ENDPOINT` to a reachable host
- Authentication issues:
  - `az login`
  - Ensure token audience is `https://cognitiveservices.azure.com/`
- API path mismatch (404/400):
  - Try the alternate preview version `2024-07-31-preview`
  - Try `/projects` vs `/analyzers`
- Payload too large or invalid:
  - Check `/tmp/*_payload.json`
  - Trim very long descriptions in `GeneratedSchema` if needed

## Plan after connectivity works
1. Run baseline vs enhanced schema creation and collect acceptance status.
2. Process real invoice + contract; capture extraction output.
3. Score and compare structure vs gold standard.
4. Tune organization & relationship scoring heuristics.
5. Optionally surface metrics in the frontend UI.

## Reference files
- `backend/test_azure_schema_quality.py` – main test harness
- `backend/utils/query_schema_generator.py` – core logic
- `backend/utils/schema_generation_prompt_template.txt` – enhanced Step 3 prompt
- `AZURE_SCHEMA_TEST_PROGRESS.md` – daily log
- `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json` – gold standard

---
Prepared: 2025-11-09
