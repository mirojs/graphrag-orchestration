# Route 3 Negative Guardrails — Status (2026-01-10)

## Known-good deployment (validated)
- Endpoint: https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- Benchmark group id: `test-5pdfs-1767429340223041632`
- Deployed image tag (ACA): `negfix-20260110-promptalign`
- Latest benchmark artifacts (full 20Q run):
  - `benchmarks/route3_global_search_20260110T140816Z.json`
  - `benchmarks/route3_global_search_20260110T140816Z.md`

## What changed (high level)
- Route 3 (global/hybrid) now has deterministic, Neo4j-backed *post-synthesis* validators for a narrow set of “field lookup” negative failure modes.
- If the specific requested field/pattern is not present in Neo4j chunk text (scoped via doc keyword when applicable), Route 3 returns a canonical refusal:
  - "The requested information was not found in the available documents."
- Prompt refusal text was aligned to the same canonical refusal sentence as a secondary (non-authoritative) guardrail.

## Files touched
- `graphrag-orchestration/app/hybrid/orchestrator.py`
  - Added/expanded field-specific negative validation after synthesis.
  - Centralized refusal payload helper for missing fields.
- `graphrag-orchestration/app/services/async_neo4j_service.py`
  - Added `check_pattern_in_docs_by_keyword(...)` for fast existence checks.
- `graphrag-orchestration/app/hybrid/pipeline/synthesis.py`
  - Aligned refusal-only sentence in prompts to the canonical refusal.

## Benchmark outcome
- Route 3 benchmark: all negatives PASS (Q-N1..Q-N10), positives remained acceptable and prior regression (Q-G10) stayed resolved.
