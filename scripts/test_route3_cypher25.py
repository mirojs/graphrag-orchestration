#!/usr/bin/env python3
"""
Test Route 3 with Cypher 25 Hybrid BM25 + Vector RRF Fusion.

Tests the new _search_chunks_cypher25_hybrid_rrf() method.
"""

import asyncio
import os
import sys

# Add graphrag-orchestration subdirectory to path
graphrag_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                            "graphrag-orchestration")
sys.path.insert(0, graphrag_dir)

from dotenv import load_dotenv

# Load env from graphrag-orchestration subdirectory
load_dotenv(os.path.join(graphrag_dir, ".env"))

# Enable Cypher 25 hybrid RRF
os.environ["ROUTE3_CYPHER25_HYBRID_RRF"] = "1"

from src.worker.hybrid.orchestrator import HybridPipeline
from src.worker.services.graph_service import GraphService
from src.worker.services.llm_service import LLMService


async def test_route3_hybrid():
    """Test Route 3 with hybrid BM25 + Vector search."""
    
    # Test group ID from indexing
    group_id = "test-cypher25-final-1768129960"
    
    # Test queries - thematic/global style
    test_queries = [
        "What are the main themes in these documents?",
        "What compliance topics are covered?",
        "What are the key requirements mentioned?",
    ]
    
    print("=" * 80)
    print("Testing Route 3 with Cypher 25 Hybrid BM25 + Vector RRF Fusion")
    print("=" * 80)
    print(f"Group ID: {group_id}")
    print(f"ROUTE3_CYPHER25_HYBRID_RRF: {os.environ.get('ROUTE3_CYPHER25_HYBRID_RRF', '0')}")
    print()
    
    # Initialize services
    graph_service = GraphService()
    llm_service = LLMService()

    # Initialize orchestrator with configured services
    orchestrator = HybridPipeline(
        neo4j_driver=graph_service.driver,
        llm_client=llm_service.llm,
        embedding_client=llm_service.embed_model,
        group_id=group_id,
    )
    await orchestrator.initialize()

    # First, test the hybrid search method directly
    print("-" * 80)
    print("Direct Test: _search_chunks_cypher25_hybrid_rrf()")
    print("-" * 80)
    
    query = "compliance requirements"
    print(f"Query: {query}")
    
    try:
            # Compute embedding for the query
        embedding = llm_service.embed_model.get_text_embedding(query)

        # Call the hybrid search method
        chunks = await orchestrator._search_chunks_cypher25_hybrid_rrf(
            query_text=query,
            embedding=embedding,
            top_k=10,
            vector_k=30,
            bm25_k=30,
        )

        # Method returns list of (chunk, rrf_score, is_anchor) tuples
        
        print(f"\nFound {len(chunks)} chunks:")
        for i, item in enumerate(chunks):
            chunk, rrf_score, is_anchor = item
            doc_name = chunk.get("document_title") or chunk.get("document_source") or "unknown"
            text_preview = chunk.get("text", "")[:100] + "..." if chunk.get("text") else "N/A"
            anchor_marker = " [ANCHOR]" if is_anchor else ""
            print(f"  {i+1}. rrf_score={rrf_score:.6f}{anchor_marker} | doc={doc_name}")
            print(f"      text: {text_preview}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Now test full Route 3 query
    print()
    print("-" * 80)
    print("Full Route 3 Query Test")
    print("-" * 80)
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * 40)
        
        try:
            result = await orchestrator.query(
                query=query,
                response_type="summary"
            )
            
            # Check which route was used
            route = result.get("route", "unknown")
            response = result.get("response", "")[:500]
            sources = result.get("sources", [])
            
            print(f"Route: {route}")
            print(f"Response: {response}...")
            print(f"Sources: {len(sources)} documents")
            
            # Check for Cypher 25 hybrid RRF in logs
            if "cypher25_hybrid_rrf" in str(result):
                print("[✓] Cypher 25 Hybrid RRF was used")
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    print()
    print("=" * 80)
    print("Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_route3_hybrid())
