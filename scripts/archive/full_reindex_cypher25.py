#!/usr/bin/env python3
"""
Complete Reindexing with Cypher 25 + HippoRAG 2

This script performs full reindexing using hybrid directory pipeline:
1. Indexes documents with LazyGraphRAG pipeline (entities, chunks, embeddings)
2. Updates HippoRAG 2 graph for PPR-based retrieval
3. Validates Cypher 25 optimizations work correctly

Note: V3 indexing is deprecated. This uses only hybrid/indexing pipeline.

Usage:
  python scripts/full_reindex_cypher25.py [--group-id GROUP_ID]
"""

import os
import sys
import asyncio
import argparse
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "graphrag-orchestration"))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from dotenv import load_dotenv
env_path = os.path.join(SERVICE_ROOT, '.env')
load_dotenv(env_path)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import after path setup
from src.worker.hybrid.indexing.lazygraphrag_pipeline import (
    LazyGraphRAGIndexingPipeline,
    LazyGraphRAGIndexingConfig
)
from src.worker.hybrid.services.neo4j_store import Neo4jStoreV3
from src.worker.services.llm_service import LLMService
from src.core.config import settings


async def load_test_documents():
    """Load 5 test PDFs from data/input_docs."""
    input_dir = Path(SERVICE_ROOT) / "data" / "input_docs"
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return []
    
    # Find PDFs
    pdfs = list(input_dir.glob("*.pdf"))[:5]
    
    if not pdfs:
        logger.error(f"No PDFs found in {input_dir}")
        return []
    
    logger.info(f"Found {len(pdfs)} PDFs:")
    for pdf in pdfs:
        logger.info(f"  • {pdf.name}")
    
    # Load PDF texts
    documents = []
    for pdf in pdfs:
        try:
            from pypdf import PdfReader
            with open(pdf, 'rb') as f:
                reader = PdfReader(f)
                text = "\n".join(
                    page.extract_text() for page in reader.pages 
                    if page.extract_text()
                )
            
            if text.strip():
                # Note: source and title should be at top level, not in metadata
                # This matches what LazyGraphRAG pipeline expects
                documents.append({
                    "text": text,
                    "source": pdf.name,  # Use filename as source
                    "title": pdf.stem,
                    "content": text,  # LazyGraphRAG expects 'content' or 'text'
                    "metadata": {
                        "file_name": pdf.name,
                        "file_path": str(pdf),
                    }
                })
                logger.info(f"  ✅ Loaded: {pdf.name} ({len(text)} chars)")
            else:
                logger.warning(f"  ⚠️  Empty text: {pdf.name}")
        
        except Exception as e:
            logger.error(f"  ❌ Failed to load {pdf.name}: {e}")
    
    return documents


async def validate_indexing(group_id: str):
    """Validate that indexing created expected nodes."""
    from src.worker.services.graph_service import GraphService
    
    graph_service = GraphService()

    if not graph_service.driver:
        logger.error("GraphService driver not initialized")
        return

    with graph_service.driver.session(database=settings.NEO4J_DATABASE) as session:
        # Check chunks
        record = session.run(
            "MATCH (c:TextChunk {group_id: $group_id}) RETURN count(c) AS count",
            group_id=group_id,
        ).single()
        chunk_count = record["count"] if record else 0

        # Check entities
        record = session.run(
            """
            MATCH (e)
            WHERE e.group_id = $group_id AND (e:Entity OR e:__Entity__)
            RETURN count(e) AS count
            """,
            group_id=group_id,
        ).single()
        entity_count = record["count"] if record else 0

        # Check entity relationships
        record = session.run(
            """
            MATCH (e1)-[r]-(e2)
            WHERE e1.group_id = $group_id AND e2.group_id = $group_id
              AND (e1:Entity OR e1:__Entity__)
              AND (e2:Entity OR e2:__Entity__)
              AND type(r) <> 'MENTIONS'
            RETURN count(r) AS count
            """,
            group_id=group_id,
        ).single()
        rel_count = record["count"] if record else 0

        # Check mentions
        record = session.run(
            """
            MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]-(e)
            WHERE e.group_id = $group_id AND (e:Entity OR e:__Entity__)
            RETURN count(*) AS count
            """,
            group_id=group_id,
        ).single()
        mentions_count = record["count"] if record else 0

        logger.info("=" * 70)
        logger.info("Validation Results:")
        logger.info("=" * 70)
        logger.info(f"  ✅ Chunks indexed: {chunk_count}")
        logger.info(f"  ✅ Entities indexed: {entity_count}")
        logger.info(f"  ✅ Entity relationships: {rel_count}")
        logger.info(f"  ✅ MENTIONS edges: {mentions_count}")

    graph_service.close()


async def test_cypher25_queries(group_id: str):
    """Test Cypher 25 queries work correctly."""
    from src.worker.services.async_neo4j_service import AsyncNeo4jService
    
    logger.info("=" * 70)
    logger.info("Testing Cypher 25 Queries:")
    logger.info("=" * 70)
    
    async with AsyncNeo4jService.from_settings() as service:
        # Test entity retrieval
        entities = await service.get_entities_by_importance(group_id, top_k=10)
        logger.info(f"  ✅ Entity retrieval: {len(entities)} entities")
        
        if entities:
            # Test neighbor expansion
            entity_ids = [e['id'] for e in entities[:3]]
            neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2)
            logger.info(f"  ✅ Neighbor expansion: {len(neighbors)} neighbors")
            
            # Test PPR
            ppr_result = await service.personalized_pagerank_native(
                group_id,
                seed_entity_ids=entity_ids,
                top_k=20
            )
            logger.info(f"  ✅ Personalized PageRank: {len(ppr_result)} nodes")


async def main():
    parser = argparse.ArgumentParser(description="Full reindexing with Cypher 25")
    parser.add_argument(
        "--group-id",
        default=f"test-5pdfs-cypher25-{int(__import__('time').time())}",
        help="Group ID for the indexed documents"
    )
    args = parser.parse_args()
    
    group_id = args.group_id
    
    print("=" * 70)
    print("Complete Reindexing with Cypher 25 + HippoRAG 2")
    print("=" * 70)
    print(f"Group ID: {group_id}")
    print()
    
    # Step 1: Load documents
    logger.info("Step 1: Loading test documents...")
    documents = await load_test_documents()
    
    if not documents:
        logger.error("No documents to index!")
        return 1
    
    print()
    
    # Step 2: Initialize services
    logger.info("Step 2: Initializing services...")
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE
    )
    llm_service = LLMService()
    
    try:
        llm = llm_service.llm
        embedder = llm_service.embed_model
    except Exception as e:
        logger.warning(f"Failed to initialize LLM/embedder: {e}")
        logger.warning("Continuing without entity extraction...")
        llm = None
        embedder = None
    
    print()
    
    # Step 3: Index with LazyGraphRAG pipeline
    logger.info("Step 3: Indexing documents with LazyGraphRAG pipeline...")
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm,
        embedder=embedder,
        config=LazyGraphRAGIndexingConfig(
            chunk_size=512,
            chunk_overlap=64,
            embedding_dimensions=3072
        )
    )
    
    result = await pipeline.index_documents(
        group_id=group_id,
        documents=documents,
        reindex=True
    )
    
    logger.info(f"✅ Indexing complete: {result.get('chunks_created', 0)} chunks created")
    print()
    
    # Step 4: Validate indexing
    logger.info("Step 4: Validating indexed data...")
    await validate_indexing(group_id)
    print()
    
    # Step 5: Test Cypher 25 queries
    logger.info("Step 5: Testing Cypher 25 queries...")
    await test_cypher25_queries(group_id)
    print()
    
    # Summary
    print("=" * 70)
    print("✅ Full Reindexing Complete!")
    print("=" * 70)
    print()
    print(f"Group ID: {group_id}")
    print()
    print("Next Steps:")
    print("  1. Run benchmarks to measure Cypher 25 improvements")
    print(f"     python scripts/run_cypher25_baseline_benchmark.py --phase after --group-id {group_id}")
    print("  2. Test Route 3 (HippoRAG 2 + LazyGraphRAG):")
    print(f"     curl -X POST http://localhost:8000/v3/query -d '{{\"query\": \"What are the payment terms?\", \"group_id\": \"{group_id}\"}}'")
    print()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
