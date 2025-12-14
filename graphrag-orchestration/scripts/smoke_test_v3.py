#!/usr/bin/env python3
"""
V3 Indexing Pipeline Smoke Test (no external services)

Runs the IndexingPipelineV3 end-to-end using:
- Dummy in-memory Neo4j store (no DB)
- Tiny fake LLM and Embeddings
- Single text document

This validates chunking, LlamaIndex integration wiring, community + RAPTOR flow,
and overall control path without requiring Azure/Neo4j.

Usage:
  python services/graphrag-orchestration/scripts/smoke_test_v3.py
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

"""Preload stubs for unavailable heavy deps (numpy, graspologic)."""
import types

# Minimal numpy stub to satisfy tuple-based indexing and dtype reference
if 'numpy' not in sys.modules:
    numpy_stub = types.ModuleType('numpy')

    class _DummyMat:
        def __init__(self):
            pass
        def __setitem__(self, key, value):
            # Support assignment like adj_matrix[i, j] = value
            return None
        def __getitem__(self, key):
            return 0.0

    def _zeros(shape, dtype=None):
        return _DummyMat()

    numpy_stub.zeros = _zeros
    numpy_stub.float32 = 'float32'
    sys.modules['numpy'] = numpy_stub

# Minimal graspologic.partition stub for hierarchical_leiden
if 'graspologic' not in sys.modules:
    graspologic_stub = types.ModuleType('graspologic')
    partition_stub = types.ModuleType('graspologic.partition')

    class HierarchicalCluster:
        def __init__(self, node: int = 0, level: int = 0, cluster: int = 0, is_final_cluster: bool = True):
            self.node = node
            self.level = level
            self.cluster = cluster
            self.is_final_cluster = is_final_cluster

    def hierarchical_leiden(adj_matrix, resolution: float = 1.0, max_cluster_size: int = 10):
        # Return empty clustering to skip community creation in smoke
        return []

    partition_stub.hierarchical_leiden = hierarchical_leiden
    partition_stub.HierarchicalCluster = HierarchicalCluster
    sys.modules['graspologic'] = graspologic_stub
    sys.modules['graspologic.partition'] = partition_stub

# Minimal llama_index.core stubs used by the pipeline
if 'llama_index' not in sys.modules:
    li_pkg = types.ModuleType('llama_index')
    li_core = types.ModuleType('llama_index.core')
    li_schema = types.ModuleType('llama_index.core.schema')
    li_node_parser = types.ModuleType('llama_index.core.node_parser')
    li_graph_stores = types.ModuleType('llama_index.core.graph_stores')

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
                # simple fixed-size chunking
                i = 0
                idx = 0
                while i < len(text):
                    chunk = text[i:i + self.chunk_size]
                    nodes.append(TextNode(id_=f"{d.id_}_n{idx}", text=chunk, metadata=d.metadata))
                    if self.chunk_overlap > 0:
                        i += max(1, self.chunk_size - self.chunk_overlap)
                    else:
                        i += self.chunk_size
                    idx += 1
            return nodes

    class SimplePropertyGraphStore:
        def __init__(self):
            self._triplets: List[tuple] = []
        def get_triplets(self) -> List[tuple]:
            return list(self._triplets)
        def _add_triplet(self, s: str, r: str, o: str):
            self._triplets.append((s, r, o))

    class PropertyGraphIndex:
        def __init__(self, nodes: List[TextNode], llm: Any, embed_model: Any, property_graph_store: SimplePropertyGraphStore, show_progress: bool = False):
            # Very naive heuristic: add one triplet if certain keywords exist
            texts = " ".join(n.text.lower() for n in nodes)
            if "contract" in texts and "contoso" in texts and "fabrikam" in texts:
                property_graph_store._add_triplet("Contoso", "SIGNED_CONTRACT_WITH", "Fabrikam")

    li_schema.Document = Document
    li_schema.TextNode = TextNode
    li_node_parser.SentenceSplitter = SentenceSplitter
    li_graph_stores.SimplePropertyGraphStore = SimplePropertyGraphStore
    li_core.PropertyGraphIndex = PropertyGraphIndex

    sys.modules['llama_index'] = li_pkg
    sys.modules['llama_index.core'] = li_core
    sys.modules['llama_index.core.schema'] = li_schema
    sys.modules['llama_index.core.node_parser'] = li_node_parser
    sys.modules['llama_index.core.graph_stores'] = li_graph_stores

# Minimal neo4j driver stub to satisfy import in neo4j_store
if 'neo4j' not in sys.modules:
    neo4j_stub = types.ModuleType('neo4j')

    class _DummySession:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def run(self, *args, **kwargs):
            class _Res:
                def single(self_inner):
                    return None
            return _Res()

    class _DummyDriver:
        def verify_connectivity(self):
            return None
        def session(self, database: str = "neo4j"):
            return _DummySession()
        def close(self):
            return None

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            return _DummyDriver()

    class Query(str):
        pass

    neo4j_stub.GraphDatabase = GraphDatabase
    neo4j_stub.Query = Query
    neo4j_stub.Driver = _DummyDriver
    sys.modules['neo4j'] = neo4j_stub

from app.v3.services.indexing_pipeline import IndexingPipelineV3, IndexingConfig
from app.v3.services.neo4j_store import Document, TextChunk, Entity, Relationship, Community, RaptorNode


# ----------------- Minimal in-memory store -----------------

class InMemoryStore:
    def __init__(self):
        self.documents: Dict[str, Document] = {}
        self.text_chunks: List[TextChunk] = []
        self.entities: List[Entity] = []
        self.relationships: List[Relationship] = []
        self.communities: List[Community] = []
        self.raptor_nodes: List[RaptorNode] = []

    # Lifecycle helpers
    def delete_group_data(self, group_id: str) -> Dict[str, int]:
        self.documents.clear()
        self.text_chunks.clear()
        self.entities.clear()
        self.relationships.clear()
        self.communities.clear()
        self.raptor_nodes.clear()
        return {
            "documents": 0,
            "text_chunks": 0,
            "entities": 0,
            "relationships": 0,
            "communities": 0,
            "raptor_nodes": 0,
        }

    # Upserts (no-op persistence)
    def upsert_document(self, group_id: str, document: Document) -> None:
        self.documents[document.id] = document

    def upsert_text_chunks_batch(self, group_id: str, chunks: List[TextChunk]) -> None:
        self.text_chunks.extend(chunks)

    def upsert_entities_batch(self, group_id: str, entities: List[Entity]) -> None:
        self.entities.extend(entities)

    def upsert_relationships_batch(self, group_id: str, relationships: List[Relationship]) -> None:
        self.relationships.extend(relationships)

    def upsert_community(self, group_id: str, community: Community) -> None:
        self.communities.append(community)

    def upsert_raptor_nodes_batch(self, group_id: str, nodes: List[RaptorNode]) -> None:
        self.raptor_nodes.extend(nodes)


# ----------------- Tiny fake LLM/Embeddings -----------------

class FakeEmbedder:
    def __init__(self, dim: int = 128):
        self.dim = dim

    async def aembed(self, text: str) -> List[float]:
        return self._embed(text)

    def embed(self, text: str) -> List[float]:
        return self._embed(text)

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)

    def _embed(self, text: str) -> List[float]:
        # Simple deterministic hash-based vector
        import random
        rnd = random.Random(hash(text) & 0xFFFFFFFF)
        return [rnd.random() for _ in range(self.dim)]


@dataclass
class _LLMResponse:
    text: str
    content: Optional[str] = None


class FakeLLM:
    def __init__(self):
        pass

    async def acomplete(self, prompt: str) -> _LLMResponse:
        return _LLMResponse(text=self._short_resp(prompt))

    def complete(self, prompt: str) -> _LLMResponse:
        return _LLMResponse(text=self._short_resp(prompt))

    async def achat(self, messages: List[Dict[str, str]]) -> _LLMResponse:
        content = messages[-1]["content"] if messages else ""
        txt = self._short_resp(content)
        return _LLMResponse(text=txt, content=txt)

    def _short_resp(self, src: str) -> str:
        return ("Auto-summary: " + src.strip())[:256]


# ----------------- Main -----------------

async def run_smoke() -> Dict[str, Any]:
    group_id = os.getenv("GROUP_ID", "smoke")

    # Minimal pipeline config with smaller vectors for speed
    config = IndexingConfig(
        chunk_size=256,
        chunk_overlap=32,
        raptor_levels=2,
        raptor_summary_max_tokens=200,
        raptor_cluster_size=4,
        embedding_dimensions=128,
        embedding_model="fake-emb",
        llm_model="fake-llm",
    )

    store = InMemoryStore()
    llm = FakeLLM()
    embedder = FakeEmbedder(dim=config.embedding_dimensions)

    pipeline = IndexingPipelineV3(
        neo4j_store=store, llm=llm, embedder=embedder, config=config
    )

    # Single short document
    doc = {
        "id": "doc1",
        "title": "Sample Contract",
        "source": "memory",
        "content": (
            "On Jan 1, 2024, Contoso Ltd. signed a service contract with "
            "Fabrikam for $5,000 per month. Payments are due Net 30."
        ),
    }

    stats = await pipeline.index_documents(group_id=group_id, documents=[doc], reindex=True)
    # Include in-memory tallies for quick visibility
    return {
        **stats,
        "_inmem": {
            "documents": len(store.documents),
            "chunks": len(store.text_chunks),
            "entities": len(store.entities),
            "relationships": len(store.relationships),
            "communities": len(store.communities),
            "raptor_nodes": len(store.raptor_nodes),
        },
    }


def main() -> int:
    stats = asyncio.run(run_smoke())
    print("\n[V3 Smoke Test] Completed.")
    for k, v in stats.items():
        if k == "_inmem":
            print("  In-Memory Tallies:")
            for ik, iv in v.items():
                print(f"    - {ik}: {iv}")
        else:
            print(f"  - {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
