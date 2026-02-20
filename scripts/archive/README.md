# Archived Indexing Scripts

These scripts are **no longer in use** and have been moved here to prevent accidental use.

## Why archived

| Script | Pipeline | Problem |
|--------|----------|---------|
| `full_reindex_cypher25.py` | V1 `hybrid` (512-token SentenceSplitter) | Does NOT create `Sentence` nodes or `Sentence→Entity` MENTIONS. Routes 3/4 sentence search and Route 5 semantic addon return empty when indexed with this. |
| `index_with_hybrid_pipeline.py` | V1 `hybrid` | Same V1 pipeline. No sentence skeleton enrichment. |
| `reindex_with_cypher25.py` | Legacy `GraphService` | Pre-hybrid architecture. Obsolete. |
| `index_5pdfs.py` | API client (V1 remote) | Uses old V1 blob URLs and V1 embedding property. |
| `run_reindex.sh` | Shell wrapper | Called `index_with_hybrid_pipeline.py` — wrong pipeline. |
| `run_reindex_correct.sh` | Shell wrapper | Despite the name, called `index_5pdfs.py` — still V1/old. |

## Correct script

Use **`scripts/index_5pdfs_v2_local.py`** for all local indexing.

Requirements:
- `VOYAGE_V2_ENABLED=True`
- `VOYAGE_API_KEY=<key>`
- `SKELETON_ENRICHMENT_ENABLED=True` (default)
- `SKELETON_MIN_SENTENCE_WORDS=3` (default since commit 019e584)

This creates:
- `TextChunk` nodes (section-aware, 1500 tokens)
- `Sentence` nodes with Voyage embeddings (enables Routes 3/4 sentence search)
- `Sentence→Entity` MENTIONS (enables Route 5 semantic addon)
- `TextChunk→Entity` MENTIONS (primary path for all routes)
- `Section` nodes + structural embeddings
