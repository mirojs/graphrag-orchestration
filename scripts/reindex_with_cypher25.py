#!/usr/bin/env python3
"""
Reindex test documents with Cypher 25 optimizations enabled.

This script:
1. Reindexes PDFs via the existing Hybrid indexing endpoint (Azure Document Intelligence)
2. Syncs HippoRAG artifacts via the existing Hybrid sync endpoint
3. Validates that all properties are correctly set
4. Tests Cypher 25 queries on fresh data

Usage:
    python scripts/reindex_with_cypher25.py \
        --base-url https://<your-app> \
        --sas-urls-file /tmp/5pdf_urls.txt
"""

import os
import sys
import asyncio
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "graphrag-orchestration"))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from dotenv import load_dotenv
env_path = os.path.join(SERVICE_ROOT, '.env')
load_dotenv(env_path)

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import after path setup
from app.services.graph_service import GraphService
from app.services.async_neo4j_service import USE_CYPHER_25


async def cleanup_old_group(group_id: str):
    """Delete all nodes and relationships for the old group."""
    logger.info(f"Cleaning up existing group: {group_id}")
    
    graph_service = GraphService()
    await graph_service.async_init()
    
    # Delete all nodes with this group_id
    query = """
    MATCH (n {group_id: $group_id})
    DETACH DELETE n
    """
    
    async with graph_service.async_driver.session() as session:
        result = await session.run(query, group_id=group_id)
        summary = await result.consume()
        logger.info(f"Deleted nodes/relationships for group {group_id}")
    
    await graph_service.close()


async def validate_indexed_data(group_id: str):
    """Validate that indexing created all expected properties."""
    logger.info(f"Validating indexed data for group: {group_id}")
    
    graph_service = GraphService()
    await graph_service.async_init()
    
    async with graph_service.async_driver.session() as session:
        # Check TextChunk properties
        query = """
        MATCH (c:TextChunk {group_id: $group_id})
        RETURN count(c) AS chunk_count,
               count(c.document_title) AS chunks_with_title,
               count(c.document_source) AS chunks_with_source,
               count(c.embedding) AS chunks_with_embedding
        """
        result = await session.run(query, group_id=group_id)
        record = await result.single()
        
        if record:
            logger.info(f"✅ Chunks indexed: {record['chunk_count']}")
            logger.info(f"   - With document_title: {record['chunks_with_title']}")
            logger.info(f"   - With document_source: {record['chunks_with_source']}")
            logger.info(f"   - With embeddings: {record['chunks_with_embedding']}")
        
        # Check Entity properties
        query2 = """
        MATCH (e)
        WHERE (e:Entity OR e:__Entity__) AND e.group_id = $group_id
        RETURN count(e) AS entity_count
        """
        result = await session.run(query2, group_id=group_id)
        record = await result.single()
        
        if record:
            logger.info(f"✅ Entities indexed: {record['entity_count']}")
    
    await graph_service.close()


def _read_sas_urls(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"SAS URLs file not found: {p}")
    urls: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    # De-dup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _http_post_json(url: str, payload: dict, headers: dict[str, str], timeout_s: float = 180.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {getattr(e, 'code', '?')} POST {url} failed: {body or e}")


def _http_get_json(url: str, headers: dict[str, str], timeout_s: float = 60.0) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {getattr(e, 'code', '?')} GET {url} failed: {body or e}")


def _poll_job(base_url: str, group_id: str, job_id: str, timeout_s: float = 1200.0) -> dict:
    headers = {"X-Group-ID": group_id}
    status_url = f"{base_url.rstrip('/')}/hybrid/index/status/{job_id}"
    t0 = time.monotonic()
    last_status: str | None = None
    while True:
        status = _http_get_json(status_url, headers=headers, timeout_s=60.0)
        s = status.get("status")
        progress = status.get("progress")
        if s != last_status:
            logger.info("index_status status=%s progress=%s", s, progress)
            last_status = s

        if s in ("completed", "failed"):
            return status

        if time.monotonic() - t0 > timeout_s:
            raise RuntimeError(f"Timed out waiting for indexing job {job_id} (last status={s}, progress={progress})")

        time.sleep(3)


async def test_cypher25_queries(group_id: str):
    """Test Cypher 25 queries on freshly indexed data."""
    logger.info(f"Testing Cypher 25 queries on group: {group_id}")
    
    from app.services.async_neo4j_service import AsyncNeo4jService
    
    async with AsyncNeo4jService.from_settings() as service:
        # Test entity retrieval
        entities = await service.get_entities_by_importance(group_id, top_k=10)
        logger.info(f"✅ Retrieved {len(entities)} entities")
        
        if entities:
            # Test neighbor expansion
            entity_ids = [e['id'] for e in entities[:3]]
            neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2)
            logger.info(f"✅ Expanded to {len(neighbors)} neighbors")
        
        # Test document field check
        exists, section = await service.check_field_exists_in_document(
            group_id,
            "contract",
            ["payment", "terms"]
        )
        logger.info(f"✅ Field exists check: {exists}")


async def main():
    print("=" * 70)
    print("Reindexing with Cypher 25 Optimizations")
    print("=" * 70)
    print(f"USE_CYPHER_25 = {USE_CYPHER_25}")
    print()
    
    base_url = os.getenv("GRAPHRAG_CLOUD_URL") or os.getenv("BASE_URL") or "http://localhost:8000"
    sas_urls_file = os.getenv("SAS_URLS_FILE")
    group_id = os.getenv("GROUP_ID") or f"test-5pdfs-cypher25-{int(time.time())}"
    hipporag_out = os.getenv("HIPPORAG_OUT") or "./hipporag_index"
    timeout_s = float(os.getenv("INDEX_TIMEOUT_S", "1200"))

    # CLI-lite: allow env-only usage (keeps this script simple to run in CI/ops)
    if len(sys.argv) > 1:
        # Minimal argparse (avoid breaking existing env-based usage)
        import argparse as _argparse

        parser = _argparse.ArgumentParser(description="Reindex with Cypher 25 (Hybrid pipeline + DI)")
        parser.add_argument("--base-url", default=base_url)
        parser.add_argument("--group-id", default=group_id)
        parser.add_argument("--sas-urls-file", default=sas_urls_file)
        parser.add_argument("--hipporag-out", default=hipporag_out)
        parser.add_argument("--timeout-s", type=float, default=timeout_s)
        parser.add_argument("--skip-neo4j-validate", action="store_true")
        args = parser.parse_args()
        base_url = args.base_url
        group_id = args.group_id
        sas_urls_file = args.sas_urls_file
        hipporag_out = args.hipporag_out
        timeout_s = args.timeout_s
        skip_validate = args.skip_neo4j_validate
    else:
        skip_validate = False

    if not sas_urls_file:
        raise RuntimeError("Provide --sas-urls-file or set SAS_URLS_FILE")

    sas_urls = _read_sas_urls(sas_urls_file)
    if not sas_urls:
        raise RuntimeError(f"No SAS URLs found in {sas_urls_file}")

    print("=" * 70)
    print("Step 1: Hybrid index (Azure Document Intelligence)")
    print("=" * 70)
    print(f"Base URL: {base_url}")
    print(f"Group ID: {group_id}")
    print(f"Docs: {len(sas_urls)}")

    headers = {"X-Group-ID": group_id, "Content-Type": "application/json"}
    index_url = f"{base_url.rstrip('/')}/hybrid/index/documents"
    index_payload = {
        "documents": sas_urls,
        "ingestion": "document-intelligence",
        "reindex": True,
        "run_raptor": False,
        "run_community_detection": False,
    }
    resp = _http_post_json(index_url, index_payload, headers=headers, timeout_s=180.0)
    job_id = resp.get("job_id")
    if not job_id:
        raise RuntimeError(f"Index response missing job_id: {resp}")
    print(f"Index job_id: {job_id}")

    status = _poll_job(base_url, group_id, job_id, timeout_s=timeout_s)
    if status.get("status") != "completed":
        raise RuntimeError(f"Indexing failed: {status}")
    print("✅ Indexing completed")

    print("=" * 70)
    print("Step 2: Hybrid sync (HippoRAG artifacts)")
    print("=" * 70)
    sync_url = f"{base_url.rstrip('/')}/hybrid/index/sync"
    sync_payload = {"output_dir": hipporag_out, "dry_run": False}
    sync_resp = _http_post_json(sync_url, sync_payload, headers=headers, timeout_s=300.0)
    print(f"Sync status: {sync_resp.get('status')}")
    if sync_resp.get("status") != "success":
        raise RuntimeError(f"HippoRAG sync failed: {sync_resp}")

    if skip_validate:
        print("✅ Done (skipped Neo4j validation)")
        return

    print("=" * 70)
    print("Step 3: Validate Neo4j + Cypher25 services")
    print("=" * 70)
    await validate_indexed_data(group_id)
    await test_cypher25_queries(group_id)
    print("=" * 70)
    print("✅ Reindex + validation complete")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
