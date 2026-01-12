#!/usr/bin/env python3
"""Purge + reindex a tenant, then sync HippoRAG index.

This is the safe operational workflow for strict multi-tenancy:
1) Delete all Neo4j data scoped to `group_id`.
2) Re-index the (small) document set.
3) Export/sync the Neo4j graph into HippoRAG (on-disk) format.

Inputs
- Provide `--sas-urls` (comma-separated) or `--sas-urls-file`.
- Uses Document Intelligence extraction inside the V3 pipeline.

Environment variables (typical)
- GROUP_ID (or pass --group-id)
- NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, optional NEO4J_DATABASE
- AZURE_CONTENT_UNDERSTANDING_ENDPOINT / _API_KEY (if DI is configured)
- AZURE_OPENAI_ENDPOINT and either AZURE_OPENAI_API_KEY or managed identity
- AZURE_OPENAI_DEPLOYMENT_NAME, AZURE_OPENAI_EMBEDDING_DEPLOYMENT

Example:
  python scripts/purge_reindex_and_sync.py \
    --group-id my-tenant \
    --sas-urls-file /tmp/sas_urls.txt \
    --hipporag-out ./hipporag_index
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Ensure service root on sys.path when running as script
THIS_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = THIS_DIR.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.core.config import settings
from app.services.graph_service import GraphService
from app.v3.services.indexing_pipeline import IndexingPipelineV3, IndexingConfig
from app.v3.services.neo4j_store import Neo4jStoreV3
from app.services.llm_service import LLMService
from app.hybrid.indexing.dual_index import DualIndexService


def _parse_sas_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []

    if args.sas_urls:
        urls.extend([u.strip() for u in args.sas_urls.split(",") if u.strip()])

    if args.sas_urls_file:
        p = Path(args.sas_urls_file)
        if not p.exists():
            raise RuntimeError(f"SAS URLs file not found: {p}")
        urls.extend(
            [
                line.strip()
                for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )

    # De-dup while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Purge + reindex a group_id, then sync HippoRAG")
    parser.add_argument("--group-id", default=os.getenv("GROUP_ID", "dev"))
    parser.add_argument("--sas-urls", help="Comma-separated SAS URLs")
    parser.add_argument("--sas-urls-file", help="File with one SAS URL per line")
    parser.add_argument("--hipporag-out", default="./hipporag_index", help="Output directory for HippoRAG index")
    parser.add_argument("--skip-sync", action="store_true", help="Skip HippoRAG sync step")
    parser.add_argument("--no-community", action="store_true", help="Disable community detection during reindex")
    args = parser.parse_args()

    group_id: str = args.group_id

    urls = _parse_sas_urls(args)
    if not urls:
        raise RuntimeError("Provide --sas-urls or --sas-urls-file")

    # Initialize Neo4j store + schema
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "bolt://localhost:7687",
        username=settings.NEO4J_USERNAME or "neo4j",
        password=settings.NEO4J_PASSWORD or "password",
        database=settings.NEO4J_DATABASE or "neo4j",
    )
    neo4j_store.initialize_schema()

    llm_service = LLMService()
    if llm_service.llm is None or llm_service.embed_model is None:
        raise RuntimeError("LLMService is not configured (llm/embed_model missing)")

    pipeline = IndexingPipelineV3(
        neo4j_store=neo4j_store,
        llm=llm_service.llm,
        embedder=llm_service.embed_model,
        config=IndexingConfig(
            chunk_size=512,
            chunk_overlap=64,
            embedding_model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT or "text-embedding-3-large",
            llm_model=settings.AZURE_OPENAI_DEPLOYMENT_NAME or "gpt-4",
        ),
    )

    docs: list[dict[str, Any]] = [{"url": u, "source": u} for u in urls]

    stats = await pipeline.index_documents(
        group_id=group_id,
        documents=docs,
        reindex=True,
        ingestion="document-intelligence",
        run_community_detection=(not args.no_community),
        run_raptor=False,
    )

    print("\n[Index] Done")
    for k, v in stats.items():
        print(f"  - {k}: {v}")

    if args.skip_sync:
        print("\n[HippoRAG] Skipped (per --skip-sync)")
        return 0

    output_dir = str(Path(args.hipporag_out).resolve())

    graph_service = GraphService()
    if not graph_service.driver:
        raise RuntimeError("Neo4j not configured (GraphService.driver is None)")

    dual_index = DualIndexService(
        neo4j_driver=graph_service.driver,
        hipporag_save_dir=output_dir,
        group_id=group_id,
    )
    sync_result = await dual_index.sync_from_neo4j()

    print("\n[HippoRAG] Sync result")
    for k, v in sync_result.items():
        print(f"  - {k}: {v}")

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
