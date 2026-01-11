import asyncio

from app.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGIndexingPipeline
from app.hybrid.services.neo4j_store import TextChunk


def test_nlp_seed_entities_simple():
    pipeline = LazyGraphRAGIndexingPipeline(neo4j_store=None, llm=None, embedder=None)
    chunks = [
        TextChunk(
            id="doc1_chunk_0",
            text="Risk Management and Compliance Review at Acme Corp involves multiple parties and obligations.",
            chunk_index=0,
            document_id="doc1",
            embedding=None,
            tokens=12,
            metadata={},
        )
    ]

    seeds = pipeline._nlp_seed_entities("test-group", chunks)
    assert seeds and len(seeds) >= 1
    assert any("Acme" in e.name or "Risk" in e.name for e in seeds)
