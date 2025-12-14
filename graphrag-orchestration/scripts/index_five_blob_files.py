#!/usr/bin/env python3
"""
Ingest five blob files into the GraphRAG Knowledge Graph (Neo4j).

Flow:
- Generate SAS URLs for existing blobs (no uploads)
- Extract layout-aware Documents via Azure Content Understanding (CU Standard)
- Index entities/relations into Neo4j via PropertyGraphIndex

Environment variables required:
- SAS_URLS: Comma-separated list of SAS URLs (preferred method)
  OR
- SAS_URLS_FILE: Path to file with one SAS URL per line
  OR
- STORAGE_ACCOUNT_NAME, STORAGE_ACCOUNT_KEY, CONTAINER_NAME, BLOB_FILES (legacy)

- GROUP_ID: Tenant/group id for multi-tenancy (default: dev)

- AZURE_CONTENT_UNDERSTANDING_ENDPOINT: CU endpoint (e.g., https://swedencentral.api.cognitive.microsoft.com)
- AZURE_CONTENT_UNDERSTANDING_API_KEY: API key for CU (regional endpoints)

- Neo4j: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

- Azure OpenAI for extraction + embeddings
  AZURE_OPENAI_ENDPOINT, and either AZURE_OPENAI_API_KEY or Azure AD login available
  AZURE_OPENAI_DEPLOYMENT_NAME (llm), AZURE_OPENAI_EMBEDDING_DEPLOYMENT (embeddings)

Usage:
  python services/graphrag-orchestration/scripts/index_five_blob_files.py
"""

from __future__ import annotations

import os
import sys
from typing import List, Dict
from datetime import datetime, timedelta

from azure.storage.blob import generate_blob_sas, BlobSasPermissions

# Add service app to path
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from app.services.indexing_service import IndexingService
from app.services.document_intelligence_service import DocumentIntelligenceService


def env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def generate_sas_urls(
    account_name: str,
    account_key: str,
    container: str,
    blob_names: List[str],
    expiry_hours: int = 2,
) -> List[Dict[str, str]]:
    from urllib.parse import quote

    inputs: List[Dict[str, str]] = []
    expiry = datetime.utcnow() + timedelta(hours=expiry_hours)
    for name in blob_names:
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        # Note: preserve exact blob name; Azure handles spaces in URLs
        url = f"https://{account_name}.blob.core.windows.net/{container}/{quote(name)}?{sas}"
        inputs.append({"url": url})
    return inputs


def main() -> int:
    group_id = os.getenv("GROUP_ID", "dev")
    extraction_only = os.getenv("EXTRACTION_ONLY", "0") in ("1", "true", "True")
    
    # Prefer direct SAS URLs if provided (comma-separated)
    direct_sas_urls = [s.strip() for s in os.getenv("SAS_URLS", "").split(",") if s.strip()]
    sas_urls_file = os.getenv("SAS_URLS_FILE")
    if not direct_sas_urls and sas_urls_file and os.path.exists(sas_urls_file):
        with open(sas_urls_file, "r", encoding="utf-8") as f:
            direct_sas_urls = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    # Storage config (used only when SAS_URLS not provided)
    account_name = os.getenv("STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("STORAGE_ACCOUNT_KEY")
    container = os.getenv("CONTAINER_NAME")

    # Default to the five PDFs used in tests
    default_files = [
        "contoso_lifts_invoice.pdf",
        "purchase_contract.pdf",
        "HOLDING TANK SERVICING CONTRACT.pdf",
        "PROPERTY MANAGEMENT AGREEMENT.pdf",
        "BUILDERS LIMITED WARRANTY.pdf",
    ]
    blob_files = [s.strip() for s in os.getenv("BLOB_FILES", ",".join(default_files)).split(",") if s.strip()]

    print(f"\n[GraphRAG] Group: {group_id}")
    if direct_sas_urls:
        print("[GraphRAG] Using provided SAS URLs:")
        for u in direct_sas_urls:
            print(f"  - {u[:120]}...")
        input_urls = [{"url": u} for u in direct_sas_urls]
    else:
        if not account_name or not account_key or not container:
            raise RuntimeError("Provide SAS_URLS/SAS_URLS_FILE or set STORAGE_ACCOUNT_NAME, STORAGE_ACCOUNT_KEY, CONTAINER_NAME")
        print(f"[GraphRAG] Container: {container}")
        print("[GraphRAG] Files:")
        for f in blob_files:
            print(f"  - {f}")
        # Generate SAS URLs
        print("\n[GraphRAG] Generating SAS URLs...")
        input_urls = generate_sas_urls(account_name, account_key, container, blob_files)

    # Use Document Intelligence SDK for layout-aware text extraction
    print("\n[GraphRAG] Extracting text via Document Intelligence SDK...")
    di_service = DocumentIntelligenceService()
    
    # Extract documents (DocumentIntelligenceService expects list of dicts or URLs)
    documents = __import__("anyio").run(di_service.extract_documents, group_id, input_urls)
    
    print(f"[GraphRAG] Extracted {len(documents)} documents")

    if extraction_only:
        print("[GraphRAG] EXTRACTION_ONLY=1 set; skipping graph indexing.")
        total_chars = sum(len(d.text) for d in documents)
        print(f"[GraphRAG] Extracted characters: {total_chars}")
        for i, doc in enumerate(documents):
            print(f"  Doc {i}: {len(doc.text)} chars")
        print("[GraphRAG] Done.")
        return 0
    else:
        # Index into Neo4j
        print("[GraphRAG] Indexing into Neo4j (PropertyGraphIndex)...")
        svc = IndexingService()
        stats = __import__("anyio").run(
            svc.index_documents,
            group_id,
            documents,
            None,
            None,
            "schema",
        )
        print("\n[GraphRAG] Indexing complete:")
        for k, v in stats.items():
            print(f"  - {k}: {v}")

        print("\n[GraphRAG] Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"\n[GraphRAG] ERROR: {e}")
        raise
