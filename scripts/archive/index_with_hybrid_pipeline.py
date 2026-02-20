#!/usr/bin/env python3
"""
Index documents using Hybrid Pipeline (LazyGraphRAG + HippoRAG 2)

This script uses ONLY the hybrid directory pipeline - no deprecated V3 code.
Optimized for Cypher 25 with native vector indexes.

Usage:
  export GROUP_ID=test-5pdfs-$(date +%s)
  python scripts/index_with_hybrid_pipeline.py
  
Or with custom group:
  python scripts/index_with_hybrid_pipeline.py --group-id my-custom-group
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
load_dotenv(os.path.join(SERVICE_ROOT, '.env'))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import ONLY from hybrid directory (no V3 imports)
from src.worker.hybrid.indexing.lazygraphrag_pipeline import (
    LazyGraphRAGIndexingPipeline,
    LazyGraphRAGIndexingConfig
)
from src.worker.hybrid.services.neo4j_store import Neo4jStoreV3
from src.worker.services.llm_service import LLMService
from src.core.config import settings


def load_pdf_text(pdf_path: Path) -> str:
    """Load PDF text using PyPDF."""
    try:
        from pypdf import PdfReader
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
            text = "\n".join(
                page.extract_text() for page in reader.pages 
                if page.extract_text()
            )
        return text.strip() or f"[Empty PDF: {pdf_path.name}]"
    except ImportError:
        logger.error("pypdf not installed. Run: pip install pypdf")
        return f"[Missing pypdf: {pdf_path.name}]"
    except Exception as e:
        logger.error(f"Failed to load {pdf_path.name}: {e}")
        return f"[Failed: {pdf_path.name}]"


async def main():
    parser = argparse.ArgumentParser(
        description="Index documents with Hybrid Pipeline (LazyGraphRAG + HippoRAG 2)"
    )
    parser.add_argument(
        "--group-id",
        default=os.getenv("GROUP_ID", f"local-{int(__import__('time').time())}"),
        help="Group ID for multi-tenant isolation"
    )
    parser.add_argument(
        "--input-dir",
        default="graphrag-orchestration/data/input_docs",
        help="Directory containing PDF files"
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=5,
        help="Maximum number of documents to index"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run indexing in dry-run/validation mode (do not persist entities/relationships)"
    )
    args = parser.parse_args()
    
    print("=" * 70)
    print("Hybrid Pipeline Indexing (LazyGraphRAG + HippoRAG 2)")
    print("=" * 70)
    print(f"Group ID: {args.group_id}")
    print(f"Cypher 25: ENABLED")
    print()
    
    # Step 1: Load documents
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return 1
    
    pdfs = list(input_dir.glob("*.pdf"))[:args.max_docs]
    if not pdfs:
        logger.error(f"No PDFs found in {input_dir}")
        return 1
    
    logger.info(f"Found {len(pdfs)} PDFs:")
    for pdf in pdfs:
        logger.info(f"  • {pdf.name}")
    print()
    
    # Load PDF texts
    logger.info("Loading PDF texts...")
    documents = []
    for pdf in pdfs:
        text = load_pdf_text(pdf)
        if text and not text.startswith("["):
            documents.append({
                "text": text,
                "title": pdf.stem,  # Top-level title for Document node
                "source": str(pdf),  # Top-level source for Document node
                "metadata": {
                    "file_name": pdf.name,
                }
            })
            logger.info(f"  ✅ {pdf.name}: {len(text):,} chars")
        else:
            logger.warning(f"  ⚠️  {pdf.name}: {text}")
    
    if not documents:
        logger.error("No valid documents to index!")
        return 1
    
    print()
    
    # Step 2: Initialize services
    logger.info("Initializing services...")
    
    # Initialize Neo4j store (hybrid directory, NOT V3)
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE
    )
    
    # Initialize LLM service
    llm_service = LLMService()
    try:
        llm = llm_service.get_indexing_llm() if llm_service.llm is not None else None
        embedder = llm_service.embed_model
        logger.info(f"  ✅ LLM: {settings.AZURE_OPENAI_DEPLOYMENT_NAME}")
        logger.info(f"  ✅ Embedder: {settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")
        logger.info(f"  ✅ LLM is None: {llm is None}")
        logger.info(f"  ✅ Embedder is None: {embedder is None}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM/embedder: {e}")
        return 1
    
    print()
    
    # Step 3: Run indexing pipeline
    logger.info("Running LazyGraphRAG indexing pipeline...")
    
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
    
    try:
        result = await pipeline.index_documents(
            group_id=args.group_id,
            documents=documents,
            reindex=True,
            dry_run=args.dry_run,
        )

        logger.info(f"  ✅ Validation passed: {result.get('validation_passed', False)}")
        logger.info(f"  🔍 Validation details: {result.get('validation_details', {})}")
        if args.dry_run:
            logger.info("  ⚠️ Dry-run mode: no entities/relationships were persisted.")
        
        print()
        logger.info("=" * 70)
        logger.info("✅ Indexing Complete!")
        logger.info("=" * 70)
        logger.info(f"  Chunks created: {result.get('chunks_created', 0)}")
        logger.info(f"  Entities extracted: {result.get('entities_created', 0)}")
        logger.info(f"  Relationships: {result.get('relationships_created', 0)}")
        logger.info(f"  Group ID: {args.group_id}")
        print()
        
        # Step 4: Verify with quick query
        logger.info("Verifying indexed data...")
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        
        with graph_service.driver.session() as session:
            result = session.run(
                """
                MATCH (c:TextChunk {group_id: $group_id})
                RETURN count(c) AS chunks,
                       count(c.embedding) AS with_embeddings
                """,
                group_id=args.group_id
            )
            record = result.single()
            
            if record:
                logger.info(f"  ✅ Chunks in DB: {record['chunks']}")
                logger.info(f"  ✅ With embeddings: {record['with_embeddings']}")
        
        graph_service.close()
        print()
        
        logger.info("Next Steps:")
        logger.info(f"  1. Test queries with group_id: {args.group_id}")
        logger.info("  2. Run benchmarks to measure Cypher 25 performance")
        logger.info("  3. Test HippoRAG 2 PPR queries")
        print()
        
        return 0
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
