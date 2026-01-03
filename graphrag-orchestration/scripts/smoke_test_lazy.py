#!/usr/bin/env python3
"""LazyGraphRAG indexing pipeline smoke test (no external services).

This validates the dedicated hybrid-owned LazyGraphRAG indexing pipeline wiring:
- document normalization
- chunking via SentenceSplitter
- write calls into a store (in-memory stub)

It intentionally avoids Azure OpenAI, Document Intelligence, and Neo4j.

Usage:
  python graphrag-orchestration/scripts/smoke_test_lazy.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Add service app to path
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

# If llama_index isn't installed in the current environment, stub the minimal bits
# required for chunking.
try:
    import llama_index  # noqa: F401
except Exception:
    import types

    li_pkg = types.ModuleType("llama_index")
    li_core = types.ModuleType("llama_index.core")
    li_schema = types.ModuleType("llama_index.core.schema")
    li_node_parser = types.ModuleType("llama_index.core.node_parser")
    li_indices = types.ModuleType("llama_index.core.indices")
    li_pg = types.ModuleType("llama_index.core.indices.property_graph")

    class Document:
        def __init__(self, text: str, id_: str, metadata: Optional[Dict[str, Any]] = None):
            self.text = text
            self.id_ = id_
            self.metadata = metadata or {}

    class TextNode:
        def __init__(self, id_: str, text: str, metadata: Optional[Dict[str, Any]] = None):
            self.id_ = id_
            self.text = text
            self.metadata = metadata or {}

        def get_content(self) -> str:
            return self.text

    class SentenceSplitter:
        def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 128):
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap

        def get_nodes_from_documents(self, docs: List[Document]) -> List[TextNode]:
            nodes: List[TextNode] = []
            for d in docs:
                text = d.text
                i = 0
                idx = 0
                while i < len(text):
                    chunk = text[i : i + self.chunk_size]
                    nodes.append(TextNode(id_=f"{d.id_}_n{idx}", text=chunk, metadata=d.metadata))
                    step = max(1, self.chunk_size - self.chunk_overlap)
                    i += step
                    idx += 1
            return nodes

    class SchemaLLMPathExtractor:
        def __init__(self, *args, **kwargs):
            pass

        async def acall(self, nodes: List[TextNode]) -> List[TextNode]:
            # No-op: return nodes unchanged.
            return nodes

    li_schema.Document = Document
    li_schema.TextNode = TextNode
    li_node_parser.SentenceSplitter = SentenceSplitter
    li_pg.SchemaLLMPathExtractor = SchemaLLMPathExtractor

    sys.modules["llama_index"] = li_pkg
    sys.modules["llama_index.core"] = li_core
    sys.modules["llama_index.core.schema"] = li_schema
    sys.modules["llama_index.core.node_parser"] = li_node_parser
    sys.modules["llama_index.core.indices"] = li_indices
    sys.modules["llama_index.core.indices.property_graph"] = li_pg


from app.hybrid.indexing.lazygraphrag_pipeline import (
    LazyGraphRAGIndexingConfig,
    LazyGraphRAGIndexingPipeline,
)
from app.v3.services.neo4j_store import Document, Entity, Relationship, TextChunk


class InMemoryStore:
    def __init__(self):
        self.deleted_groups: List[str] = []
        self.documents: Dict[str, Document] = {}
        self.chunks: List[TextChunk] = []
        self.entities: List[Entity] = []
        self.relationships: List[Relationship] = []

    def delete_group_data(self, group_id: str) -> Dict[str, int]:
        self.deleted_groups.append(group_id)
        self.documents.clear()
        self.chunks.clear()
        self.entities.clear()
        self.relationships.clear()
        return {
            "documents": 0,
            "text_chunks": 0,
            "entities": 0,
            "relationships": 0,
        }

    def upsert_document(self, group_id: str, document: Document) -> str:
        self.documents[document.id] = document
        return document.id

    def upsert_text_chunks_batch(self, group_id: str, chunks: List[TextChunk]) -> int:
        self.chunks.extend(chunks)
        return len(chunks)

    async def aupsert_entities_batch(self, group_id: str, entities: List[Entity]) -> int:
        self.entities.extend(entities)
        return len(entities)

    def upsert_relationships_batch(self, group_id: str, relationships: List[Relationship]) -> int:
        self.relationships.extend(relationships)
        return len(relationships)


async def main() -> None:
    group_id = "lazy-smoke-local"

    store = InMemoryStore()

    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=store,  # type: ignore[arg-type]
        llm=None,  # smoke: chunk-only mode
        embedder=None,
        config=LazyGraphRAGIndexingConfig(chunk_size=200, chunk_overlap=40, embedding_dimensions=3072),
    )

    stats = await pipeline.index_documents(
        group_id=group_id,
        documents=[
            {
                "title": "SmokeDoc",
                "source": "local://smoke",
                "content": (
                    "This is a small document for smoke testing the LazyGraphRAG indexing pipeline. "
                    "It should be chunked into multiple text units and stored without external services. "
                    "The quick brown fox jumps over the lazy dog. "
                    "Repeat: The quick brown fox jumps over the lazy dog."
                ),
                "metadata": {"test": True},
            }
        ],
        reindex=True,
        ingestion="none",
        run_community_detection=False,
        run_raptor=False,
    )

    assert stats.get("chunks", 0) > 0, f"Expected chunks > 0, got {stats}"
    assert len(store.documents) == 1, f"Expected 1 document, got {len(store.documents)}"
    assert len(store.chunks) == stats["chunks"], "Chunk count mismatch"

    print("OK")
    print("stats:", stats)


if __name__ == "__main__":
    asyncio.run(main())
