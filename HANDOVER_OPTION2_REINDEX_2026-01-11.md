# HANDOVER: Option 2 Indexing & Route 3 Repair — 2026-01-11

**Summary (short)**
- Identified root cause for Route 3 negative detection: missing Entity nodes / MENTIONS relationships in Neo4j for `test-5pdfs-1767429340223041632`.
- Implemented **Option 2**: robust indexing with native + fallback extractors, numeric seeding, and validation gates; reindex committed and Route 3 thematic signals restored.

---

## What I changed (key files)
- **Added / modified**:
  - `app/hybrid/indexing/lazygraphrag_pipeline.py` — added:
    - `dry_run` support and validation thresholds (`min_entities`, `min_mentions`)
    - LlamaIndex fallback extractor `_extract_with_llamaindex_extractor`
    - lightweight NER seeder `_nlp_seed_entities` (regex money/percent seeding)
    - `_validate_and_commit_entities` (commit gate that prevents partial commits)
  - `scripts/index_with_hybrid_pipeline.py` — added `--dry-run` and validation logging
  - `tests/test_indexing_fallback.py` — initial unit test for NLP seeding

## What I ran & findings
- Dry-run indexing (validation only) for `test-5pdfs-1767429340223041632` — verified extraction diagnostics.
- Committed reindex (no `--dry-run`) and verified entities were persisted:
  - **Entities committed:** 101
  - **Relationships committed:** 107
  - **Chunks with embeddings:** 19
- Route 3 Thematic Benchmark (post-commit) → `benchmarks/route3_thematic_20260111T201512Z.json`:
  - Questions: 10/10 successful
  - **Average Score:** 87.6/100
  - **Theme Coverage (avg):** 59%
  - **Evidence threshold met:** 100%
  - **Total citations:** 96 (avg 9.6 / question)
- Noted a specific low coverage case (T-2: payment/fees) — the summary omitted some expected small numeric fees (e.g., `25%`, `$75`, `$50`) despite those phrases existing in the corpus (tokenization / seed selection reasons suspected).

## Immediate plan & next steps (for tomorrow)
- [ ] Implement **numeric-fee seeding** (regex-based money/percent entity seeds) and add them into seed set before PPR/section boost. (Low-risk, high ROI)
- [ ] Add **integration test** for T-2 that asserts presence of `25%|10%|$75|$50` in response or in matched metadata.
- [ ] Re-run `scripts/index_with_hybrid_pipeline.py` (dry-run + commit) after seeding and re-run `scripts/benchmark_route3_thematic.py` to measure improvement.
- [ ] Tune BM25/fulltext merging thresholds if seeding doesn’t fully recover small-fee themes.
- [ ] Monitor production telemetry (success rate, negative detection rate) for 24–48 hours.

## Artifacts & commands
- Benchmark output: `benchmarks/route3_thematic_20260111T201512Z.json`
- Backup used (if needed to restore): `backups/group_backup_test-5pdfs-1767429340223041632_20260111T120127Z.json`
- To re-run benchmark locally:
  ```bash
  python scripts/benchmark_route3_thematic.py --group-id test-5pdfs-1767429340223041632 --url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
  ```
- To re-index (dry-run):
  ```bash
  python scripts/index_with_hybrid_pipeline.py --group-id test-5pdfs-1767429340223041632 --max-docs 5 --dry-run
  ```

## Notes for tomorrow
- Start with numeric-fee seeding + unit/integration test for T-2.
- After tests pass, reindex (dry-run), then commit and re-run benchmark.
- If theme coverage still low, inspect BM25 tokenization/analyzer and consider adjusting fulltext index settings.

---

**Status:** Handover created by GitHub Copilot on 2026-01-11. We'll reconvene tomorrow to finish integration tests and run the next benchmark.
