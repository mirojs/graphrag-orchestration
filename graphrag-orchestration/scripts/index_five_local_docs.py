#!/usr/bin/env python3
"""
Index 5 local PDF documents directly from /data/input_docs

This is a local variant of index_five_blob_files.py that:
- Reads PDFs from /data/input_docs (no Azure Blob Storage needed)
- Uses Azure Document Intelligence to extract text (optional; fallback to PyPDF)
- Indexes entities/relationships into Neo4j via V3 pipeline

Requirements:
- AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT_NAME, AZURE_OPENAI_EMBEDDING_DEPLOYMENT
- NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
- (Optional) AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT, AZURE_DOCUMENT_INTELLIGENCE_KEY

Usage:
  export NEO4J_URI="bolt://localhost:7687" NEO4J_USERNAME="neo4j" NEO4J_PASSWORD="password"
  export AZURE_OPENAI_ENDPOINT="..." AZURE_OPENAI_API_KEY="..." AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4"
  python scripts/index_five_local_docs.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import asyncio
import nest_asyncio
from llama_index.core import Document

nest_asyncio.apply()

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from app.v3.services.indexing_pipeline import IndexingPipelineV3, IndexingConfig
from app.v3.services.neo4j_store import Neo4jStoreV3
from app.services.llm_service import LLMService
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_pdf_text_simple(pdf_path: str) -> str:
    """
    Load PDF text using PyPDF or fallback to placeholder.
    """
    try:
        from pypdf import PdfReader
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
            text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        return text if text.strip() else f"[Binary PDF: {Path(pdf_path).name}]"
    except ImportError:
        logger.warning("PyPDF2 not available; using placeholder")
        return f"[Placeholder: {Path(pdf_path).name}]"
    except Exception as e:
        logger.warning(f"Failed to extract {pdf_path}: {e}")
        return f"[Failed: {Path(pdf_path).name}]"


import argparse
from unittest.mock import MagicMock

# ... imports ...

async def main() -> int:
    parser = argparse.ArgumentParser(description="Index 5 local PDF documents")
    parser.add_argument("--mock-neo4j", action="store_true", help="Mock Neo4j connection for testing")
    args = parser.parse_args()

    group_id = os.getenv("GROUP_ID", "local-test")
    input_dir = Path("data/input_docs").resolve()
    
    if not input_dir.exists():
        # Fallback to relative path if run from scripts/
        input_dir = (Path(__file__).parent.parent / "data/input_docs").resolve()
    
    if not input_dir.exists():
        print(f"[ERROR] Input directory {input_dir} does not exist")
        return 1
    
    # Find PDFs
    pdfs = list(input_dir.glob("*.pdf"))
    if not pdfs:
        print(f"[ERROR] No PDFs found in {input_dir}")
        return 1
    
    print(f"[GraphRAG] Found {len(pdfs)} PDFs:")
    for pdf in pdfs[:5]:
        print(f"  - {pdf.name}")
    
    # Load documents
    print("\n[GraphRAG] Loading PDF texts...")
    documents = []
    for pdf in pdfs[:5]:  # Limit to 5
        text = load_pdf_text_simple(str(pdf))
        documents.append({
            "id": pdf.stem,
            "title": pdf.stem,
            "source": str(pdf),
            "content": text,
        })
        print(f"  Loaded {pdf.name}: {len(text)} chars")
    
    # Initialize V3 pipeline
    print("\n[GraphRAG] Initializing V3 pipeline...")
    
    if args.mock_neo4j:
        print("[GraphRAG] Using MOCK Neo4j store")
        neo4j_store = MagicMock()
        # Setup mock returns if needed
        neo4j_store.upsert_document = MagicMock()
    else:
        try:
            neo4j_store = Neo4jStoreV3(
                uri=settings.NEO4J_URI or "bolt://localhost:7687",
                username=settings.NEO4J_USERNAME or "neo4j",
                password=settings.NEO4J_PASSWORD or "password",
            )
            # Initialize schema (create constraints and vector indexes)
            neo4j_store.initialize_schema()
        except Exception as e:
            print(f"[ERROR] Failed to connect to Neo4j: {e}")
            print("Tip: Use --mock-neo4j to run without a real database connection.")
            return 1

    config = IndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        raptor_levels=2,
        embedding_model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT or "text-embedding-3-large",
        llm_model=settings.AZURE_OPENAI_DEPLOYMENT_NAME or "gpt-4",
    )

    pipeline = IndexingPipelineV3(
        neo4j_store=neo4j_store,
        llm=LLMService().llm,
        embedder=LLMService().embed_model,
        config=config,
    )
    
    try:
        # Index documents
        
        # Index documents
        print(f"\n[GraphRAG] Indexing {len(documents)} documents...")
        stats = await pipeline.index_documents(
            group_id=group_id,
            documents=documents,
            reindex=False,
        )
        
        print("\n[GraphRAG] Indexing complete!")
        print("Statistics:")
        for k, v in stats.items():
            print(f"  - {k}: {v}")
        
        return 0
        
    except Exception as e:
        logger.error(f"[GraphRAG] Indexing failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
