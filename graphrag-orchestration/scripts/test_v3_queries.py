#!/usr/bin/env python3
"""
Test V3 Query Endpoints

Tests local, global, and DRIFT search against already-indexed documents.
Assumes you've already run index_five_local_docs.py successfully.

Usage:
  export NEO4J_URI="bolt://localhost:7687" NEO4J_USERNAME="neo4j" NEO4J_PASSWORD="password"
  export AZURE_OPENAI_ENDPOINT="..." AZURE_OPENAI_API_KEY="..." AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4"
  python scripts/test_v3_queries.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import asyncio
import nest_asyncio
from typing import List, Dict, Any

nest_asyncio.apply()

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from app.v3.services.neo4j_store import Neo4jStoreV3
from app.v3.services.drift_adapter import DRIFTAdapter
from app.services.llm_service import LLMService
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class QueryTester:
    """Test harness for V3 query endpoints."""
    
    def __init__(self, group_id: str):
        self.group_id = group_id
        
        # Initialize Neo4j store
        self.neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
        
        # Initialize LLM and embedder
        llm_service = LLMService()
        if not llm_service.llm or not llm_service.embed_model:
            raise ValueError("LLM or Embedding model not initialized. Check Azure OpenAI settings.")
            
        self.llm = llm_service.llm
        self.embedder = llm_service.embed_model
        
        # Initialize DRIFT adapter
        self.drift_adapter = DRIFTAdapter(
            neo4j_driver=self.neo4j_store.driver,
            llm=self.llm,
            embedder=self.embedder,
        )
        
        logger.info(f"QueryTester initialized for group: {group_id}")
    
    async def test_local_search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Test local search (entity-focused).
        
        Mimics the /v3/query/local endpoint logic.
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"LOCAL SEARCH: {query}")
        logger.info(f"{'='*70}")
        
        try:
            # Generate query embedding
            query_embedding = self.embedder.get_text_embedding(query)
            
            # Search entities by embedding
            results = self.neo4j_store.search_entities_by_embedding(
                group_id=self.group_id,
                embedding=query_embedding,
                top_k=top_k,
            )
            
            if not results:
                logger.warning("No entities found!")
                return {
                    "query": query,
                    "answer": "No relevant information found.",
                    "confidence": 0.0,
                    "sources": [],
                }
            
            # Build context from entities
            context_parts = []
            entities_used = []
            sources = []
            
            for entity, score in results:
                context_parts.append(f"- {entity.name} ({entity.type}): {entity.description}")
                entities_used.append(entity.name)
                sources.append({
                    "name": entity.name,
                    "type": entity.type,
                    "score": float(score),
                })
                logger.info(f"  Entity: {entity.name} (score: {score:.3f})")
            
            context = "\n".join(context_parts)
            
            # Generate answer
            prompt = f"""Based on the following information, answer the question.

Information:
{context}

Question: {query}

Answer:"""
            
            response = self.llm.complete(prompt)
            answer = response.text if hasattr(response, 'text') else str(response)
            
            result = {
                "query": query,
                "answer": answer,
                "confidence": float(results[0][1]) if results else 0.0,
                "entities_used": entities_used,
                "sources": sources,
            }
            
            logger.info(f"\nANSWER: {answer}")
            logger.info(f"CONFIDENCE: {result['confidence']:.3f}")
            logger.info(f"ENTITIES: {', '.join(entities_used[:5])}")
            
            return result
            
        except Exception as e:
            logger.error(f"Local search failed: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def test_global_search(self, query: str) -> Dict[str, Any]:
        """
        Test global search (community-based).
        
        Mimics the /v3/query/global endpoint logic.
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"GLOBAL SEARCH: {query}")
        logger.info(f"{'='*70}")
        
        try:
            # Get top-level community summaries
            communities = self.neo4j_store.get_communities_by_level(
                group_id=self.group_id,
                level=0
            )
            
            if not communities:
                logger.warning("No communities found!")
                return {
                    "query": query,
                    "answer": "No community summaries available. Please run indexing first.",
                    "confidence": 0.0,
                    "sources": [],
                }
            
            logger.info(f"Found {len(communities)} level-0 communities")
            
            # Build context from community summaries
            context_parts = []
            for i, community in enumerate(communities[:10]):  # Limit to top 10
                context_parts.append(f"{i+1}. {community.summary}")
                logger.info(f"  Community {i+1}: {len(community.entity_ids)} entities")
            
            context = "\n\n".join(context_parts)
            
            # Generate answer
            prompt = f"""Based on the following community summaries, answer the question.

Community Summaries:
{context}

Question: {query}

Provide a comprehensive answer that synthesizes information from multiple communities:"""
            
            response = self.llm.complete(prompt)
            answer = response.text if hasattr(response, 'text') else str(response)
            
            result = {
                "query": query,
                "answer": answer,
                "confidence": 0.85,  # Global search typically high confidence
                "communities_used": len(communities[:10]),
                "sources": [{"id": c.id, "title": c.title} for c in communities[:5]],
            }
            
            logger.info(f"\nANSWER: {answer}")
            logger.info(f"COMMUNITIES USED: {len(communities[:10])}")
            
            return result
            
        except Exception as e:
            logger.error(f"Global search failed: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def test_drift_search(self, query: str, max_iterations: int = 3) -> Dict[str, Any]:
        """
        Test DRIFT search (multi-step reasoning).
        
        Mimics the /v3/query/drift endpoint logic.
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"DRIFT SEARCH: {query}")
        logger.info(f"{'='*70}")
        
        try:
            # Run DRIFT search
            result = await self.drift_adapter.drift_search(
                group_id=self.group_id,
                query=query,
                max_iterations=max_iterations,
                convergence_threshold=0.8,
            )
            
            logger.info(f"\nANSWER: {result['answer']}")
            logger.info(f"ITERATIONS: {result['iterations']}")
            logger.info(f"CONFIDENCE: {result['confidence']:.3f}")
            
            if result.get('reasoning_path'):
                logger.info("\nREASONING PATH:")
                for i, step in enumerate(result['reasoning_path'], 1):
                    logger.info(f"  Step {i}: {step.get('query', 'N/A')}")
            
            return result
            
        except Exception as e:
            logger.error(f"DRIFT search failed: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get indexing statistics for the group."""
        logger.info(f"\n{'='*70}")
        logger.info(f"STATISTICS FOR GROUP: {self.group_id}")
        logger.info(f"{'='*70}")
        
        try:
            stats = self.neo4j_store.get_group_stats(self.group_id)
            
            logger.info(f"Documents: {stats['documents']}")
            logger.info(f"Text Chunks: {stats['text_chunks']}")
            logger.info(f"Entities: {stats['entities']}")
            logger.info(f"Relationships: {stats['relationships']}")
            logger.info(f"Communities: {stats['communities']}")
            logger.info(f"RAPTOR Nodes: {stats['raptor_nodes']}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}", exc_info=True)
            return {"error": str(e)}


async def main():
    """Run comprehensive query tests."""
    group_id = os.getenv("GROUP_ID", "local-test")
    
    tester = QueryTester(group_id)
    
    # First, check stats
    stats = await tester.get_stats()
    
    if stats.get('entities', 0) == 0:
        logger.error("No entities found! Please run index_five_local_docs.py first.")
        return 1
    
    # Define test queries
    test_queries = [
        # Local search queries (entity-focused)
        {
            "type": "local",
            "query": "What insurance companies are mentioned?",
        },
        {
            "type": "local",
            "query": "Who is the claimant?",
        },
        {
            "type": "local",
            "query": "What are the claim amounts?",
        },
        # Global search queries (thematic)
        {
            "type": "global",
            "query": "What are the main themes across all documents?",
        },
        {
            "type": "global",
            "query": "Summarize the types of claims in the dataset",
        },
        # DRIFT search queries (complex reasoning)
        {
            "type": "drift",
            "query": "What is the relationship between the insurance companies and claimants?",
        },
    ]
    
    results = []
    
    # Run tests
    for test_case in test_queries:
        query_type = test_case["type"]
        query = test_case["query"]
        
        if query_type == "local":
            result = await tester.test_local_search(query)
        elif query_type == "global":
            result = await tester.test_global_search(query)
        elif query_type == "drift":
            result = await tester.test_drift_search(query)
        else:
            continue
        
        results.append({
            "type": query_type,
            **result,
        })
        
        # Small delay between queries
        await asyncio.sleep(2)
    
    # Summary
    logger.info(f"\n{'='*70}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*70}")
    
    successful = sum(1 for r in results if "error" not in r)
    failed = len(results) - successful
    
    logger.info(f"Total queries: {len(results)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    
    if failed > 0:
        logger.warning("\nFailed queries:")
        for r in results:
            if "error" in r:
                logger.warning(f"  - {r.get('query', 'Unknown')}: {r['error']}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
