"""
GraphRAG Query Engine - Microsoft GraphRAG Local-to-Global Retrieval.

This implements the query-time logic:
1. Extract entities from query using embeddings
2. Find communities those entities belong to
3. Generate per-community answers
4. Aggregate into final response

Speed Considerations:
- N LLM calls where N = number of relevant communities (typically 1-5)
- Plus 1 aggregation call
- Can parallelize per-community calls for speed
"""

import re
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

from llama_index.core.query_engine import CustomQueryEngine
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core import PropertyGraphIndex
from llama_index.core.bridge.pydantic import Field

from app.services.graphrag_store import GraphRAGStore

logger = logging.getLogger(__name__)


class GraphRAGQueryEngine(CustomQueryEngine):
    """
    Microsoft GraphRAG Query Engine.
    
    Query Flow (aligned with best-quality pipeline discussion):
    1. Step 7: Hybrid Search (Vector + Full-Text) to find seed entities
    2. Look up which communities those entities belong to
    3. For each relevant community, generate an answer from its summary
    4. Aggregate all community answers into final response
    
    This is the "Local-to-Global" retrieval pattern with Neo4j Hybrid Search.
    """
    
    graph_store: GraphRAGStore = Field(description="GraphRAG store with community summaries")
    llm: LLM = Field(description="LLM for answer generation")
    index: Optional[PropertyGraphIndex] = Field(default=None, description="Optional index for entity embedding lookup")
    similarity_top_k: int = Field(default=10, description="Number of similar entities to retrieve")
    include_community_summaries_in_response: bool = Field(default=False, description="Include raw summaries in response metadata")
    use_hybrid_search: bool = Field(default=True, description="Use Neo4j hybrid search (vector + full-text) for entity discovery")
    
    def custom_query(self, query_str: str) -> str:
        """
        Process query using GraphRAG Local-to-Global retrieval.
        
        Args:
            query_str: User's question
            
        Returns:
            Aggregated answer from relevant community summaries
        """
        logger.info(f"GraphRAG query: {query_str[:100]}...")
        
        # Step 1: Find relevant entities
        entities = self._get_entities_from_query(query_str)
        logger.info(f"Found {len(entities)} relevant entities")
        
        if not entities:
            # Fallback: use all communities
            logger.warning("No entities found, using all community summaries")
            community_ids = list(self.graph_store.get_community_summaries().keys())
        else:
            # Step 2: Get communities for those entities
            community_ids = self.graph_store.get_entity_communities(entities)
            logger.info(f"Entities map to {len(community_ids)} communities")
        
        if not community_ids:
            return "I don't have enough information to answer this question based on the available documents."
        
        # Step 3: Get community summaries
        community_summaries = self.graph_store.get_community_summaries()
        
        # Step 4: Generate per-community answers
        community_answers = []
        for community_id in community_ids:
            if community_id in community_summaries:
                summary = community_summaries[community_id]
                answer = self._generate_answer_from_summary(summary, query_str)
                if answer and not self._is_empty_answer(answer):
                    community_answers.append(answer)
        
        logger.info(f"Generated {len(community_answers)} community answers")
        
        if not community_answers:
            return "I couldn't find relevant information in the document communities to answer this question."
        
        # Step 5: Aggregate answers
        final_answer = self._aggregate_answers(community_answers, query_str)
        
        return final_answer
    
    def _get_entities_from_query(self, query_str: str) -> List[str]:
        """
        Find entities relevant to the query using hybrid search.
        
        This implements Step 7 of the best-quality GraphRAG pipeline:
        "LlamaIndex → Neo4j Hybrid Search: Runs Vector + Full-Text search 
        on the target KG's index to find initial seed nodes"
        
        Flow:
        1. Try Neo4j Hybrid Search (Vector + Full-Text) first
        2. Fallback to vector-only search
        3. Fallback to PropertyGraphIndex
        4. Final fallback: LLM-based entity extraction
        """
        # Try Neo4j hybrid search first (best quality per discussion)
        if self.use_hybrid_search:
            try:
                entities = self._hybrid_search_entities(query_str)
                if entities:
                    logger.info(f"Hybrid search found {len(entities)} entities")
                    return entities
            except Exception as e:
                logger.warning(f"Hybrid search failed, falling back to vector-only: {e}")
        
        # Fallback: Vector-only search
        try:
            entities = self._vector_search_entities(query_str)
            if entities:
                return entities
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
        
        # Fallback: Use PropertyGraphIndex if available
        if self.index is not None:
            try:
                retriever = self.index.as_retriever(
                    similarity_top_k=self.similarity_top_k,
                    include_text=False  # Only search entity embeddings
                )
                nodes = retriever.retrieve(query_str)
                
                entities = []
                for node in nodes:
                    # Extract entity name from node
                    if hasattr(node, 'node') and hasattr(node.node, 'metadata'):
                        name = node.node.metadata.get('name', '')
                        if name:
                            entities.append(name)
                    elif hasattr(node, 'text'):
                        entities.append(node.text[:50])
                
                if entities:
                    return list(set(entities))
            except Exception as e:
                logger.warning(f"Index retrieval failed: {e}")
        
        # Final fallback: LLM-based entity extraction with fuzzy matching
        return self._extract_entities_from_text(query_str)
    
    def _hybrid_search_entities(self, query_str: str) -> List[str]:
        """
        Use Neo4j Hybrid Search (Vector + Full-Text) to find entities.
        
        This is the recommended approach per the best-quality GraphRAG discussion:
        Combines semantic similarity (embeddings) with lexical matching (keywords).
        """
        import asyncio
        from app.services.neo4j_hybrid_search import get_hybrid_search_service
        
        hybrid_service = get_hybrid_search_service()
        
        # Run async search in sync context
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        seed_nodes = loop.run_until_complete(
            hybrid_service.find_seed_nodes(
                query=query_str,
                group_id=self.graph_store.group_id,
                top_k=self.similarity_top_k,
                use_rrf=True,  # Use Reciprocal Rank Fusion
            )
        )
        
        # Extract entity names from seed nodes
        entities = []
        for node in seed_nodes:
            name = node.get("name") or node.get("entity_id")
            if name:
                entities.append(name)
                logger.debug(
                    f"Hybrid match: {name} "
                    f"(vec={node.get('vector_score', 0):.3f}, "
                    f"ft={node.get('fulltext_score', 0):.3f}, "
                    f"combined={node.get('combined_score', 0):.3f})"
                )
        
        return entities
    
    def _vector_search_entities(self, query_str: str) -> List[str]:
        """
        Use Neo4j vector index to find similar entities.
        
        This is the fallback method when hybrid search is unavailable.
        Searches entity embeddings stored in Neo4j.
        """
        # Generate embedding for the query using the central LLMService embedder
        from app.services.llm_service import LLMService
        llm_service = LLMService()
        if llm_service.embed_model is None:
            raise RuntimeError("Embedding model not initialized")

        query_embedding = llm_service.embed_model.get_text_embedding(query_str)
        
        # Search Neo4j vector index
        result = self.graph_store.structured_query(
            """
            CALL db.index.vector.queryNodes('entity', $top_k, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
            RETURN node.id AS entity_name, node.name AS name, score
            ORDER BY score DESC
            """,
            param_map={
                "embedding": query_embedding,
                "top_k": self.similarity_top_k,
                "group_id": self.graph_store.group_id
            }
        )
        
        entities = []
        for row in (result or []):
            name = row.get("name") or row.get("entity_name")
            if name:
                entities.append(name)
                logger.debug(f"Vector match: {name} (score: {row.get('score', 'N/A')})")
        
        logger.info(f"Vector search found {len(entities)} entities for query")
        return entities
        
        # Fallback: Extract entities from query using LLM
        return self._extract_entities_from_text(query_str)
    
    def _extract_entities_from_text(self, text: str) -> List[str]:
        """
        Extract entity names from text using LLM.
        """
        prompt = f"""
Extract the key entity names from this query. Return only the entity names, one per line.

Query: {text}

Entities (one per line):
"""
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = self.llm.chat(messages)
            response_text = str(response).strip()
            
            # Parse one entity per line
            entities = [line.strip() for line in response_text.split('\n') if line.strip()]
            
            # Also check against known entities in the graph
            known_entities = list(self.graph_store.entity_info.keys())
            
            # Filter to only entities that exist in our graph
            matched_entities = []
            for entity in entities:
                # Exact match
                if entity in known_entities:
                    matched_entities.append(entity)
                else:
                    # Fuzzy match - check if any known entity contains this text
                    for known in known_entities:
                        if entity.lower() in known.lower() or known.lower() in entity.lower():
                            matched_entities.append(known)
            
            return list(set(matched_entities)) if matched_entities else entities
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []
    
    def _generate_answer_from_summary(self, community_summary: str, query: str) -> str:
        """
        Generate an answer for the query based on a community summary.
        
        Args:
            community_summary: The community's relationship summary
            query: User's question
            
        Returns:
            Answer derived from this community's knowledge
        """
        prompt = (
            f"Given the following community summary from a knowledge graph:\n\n"
            f"{community_summary}\n\n"
            f"Answer this question based ONLY on the information above. "
            f"If the summary doesn't contain relevant information, say 'No relevant information in this community.'\n\n"
            f"Question: {query}"
        )
        
        try:
            messages = [
                ChatMessage(role="system", content="You are a helpful assistant that answers questions based on knowledge graph summaries."),
                ChatMessage(role="user", content=prompt),
            ]
            response = self.llm.chat(messages)
            cleaned_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
            return cleaned_response
        except Exception as e:
            logger.error(f"Failed to generate answer from summary: {e}")
            return ""
    
    def _is_empty_answer(self, answer: str) -> bool:
        """
        Check if an answer indicates no relevant information.
        """
        empty_indicators = [
            "no relevant information",
            "doesn't contain",
            "does not contain",
            "cannot answer",
            "don't have",
            "not mentioned",
            "no information",
        ]
        answer_lower = answer.lower()
        return any(indicator in answer_lower for indicator in empty_indicators)
    
    def _aggregate_answers(self, community_answers: List[str], query: str) -> str:
        """
        Aggregate multiple community answers into a coherent final response.
        
        Args:
            community_answers: List of answers from different communities
            query: Original query for context
            
        Returns:
            Synthesized final answer
        """
        if len(community_answers) == 1:
            return community_answers[0]
        
        # Combine answers for aggregation
        combined_answers = "\n\n---\n\n".join([
            f"Source {i+1}:\n{answer}" 
            for i, answer in enumerate(community_answers)
        ])
        
        prompt = (
            f"You have received multiple answers from different knowledge communities about this question:\n\n"
            f"Question: {query}\n\n"
            f"Answers from different communities:\n{combined_answers}\n\n"
            f"Please synthesize these answers into a single, coherent, comprehensive response. "
            f"Combine the information, remove redundancy, and present a unified answer."
        )
        
        try:
            messages = [
                ChatMessage(
                    role="system", 
                    content="You are a helpful assistant that synthesizes information from multiple sources into coherent answers."
                ),
                ChatMessage(role="user", content=prompt),
            ]
            response = self.llm.chat(messages)
            cleaned_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
            return cleaned_response
        except Exception as e:
            logger.error(f"Failed to aggregate answers: {e}")
            # Fallback: return first answer
            return community_answers[0] if community_answers else "Unable to generate response."

    def global_summary_query(self, query_str: str = None) -> str:
        """
        Generate a comprehensive summary using ALL community summaries.
        
        This is the "Global" retrieval pattern - uses all communities
        rather than just those matching specific entities.
        
        Args:
            query_str: Optional custom question. If None, provides a general summary.
            
        Returns:
            Comprehensive summary synthesized from all community summaries.
        """
        logger.info("Running global summary query (Map-Reduce) across all communities...")

        community_summaries = self.graph_store.get_community_summaries()
        if not community_summaries:
            return "No community summaries available. Please run build_communities() first."

        # Default query for general summarization
        if query_str is None:
            query_str = (
                "Provide a comprehensive summary covering:\n"
                "1. Key organizations and their relationships\n"
                "2. Key people and their roles\n"
                "3. Contracts and agreements\n"
                "4. Financial information\n"
                "5. Important dates and deadlines"
            )

        # MAP: Answer per community in isolation
        community_answers: List[str] = []
        for cid, summary in community_summaries.items():
            try:
                ans = self._generate_answer_from_summary(summary, query_str)
                if ans and not self._is_empty_answer(ans):
                    community_answers.append(ans)
            except Exception as e:
                logger.warning(f"Map step failed for community {cid}: {e}")

        if not community_answers:
            return "No relevant information found in any community."

        # REDUCE: Aggregate intermediate answers
        try:
            final = self._aggregate_answers(community_answers, query_str)
            logger.info(f"Global summary generated from {len(community_summaries)} communities (kept {len(community_answers)} map answers)")
            return final
        except Exception as e:
            logger.error(f"Failed to reduce global summary: {e}")
            return community_answers[0] if community_answers else f"Error generating summary: {str(e)}"

    def comparison_query(self, query_str: str) -> str:
        """
        Find differences and inconsistencies across communities.
        
        This is designed for queries like:
        - "Find inconsistencies between the contract and invoice"
        - "What are the differences between document A and document B?"
        - "Identify discrepancies in the pricing"
        
        Unlike custom_query (which aggregates similar info), this method
        explicitly looks for DIFFERENCES and CONTRADICTIONS across communities.
        
        Args:
            query_str: Query asking for differences/inconsistencies
            
        Returns:
            Detailed list of inconsistencies found
        """
        logger.info(f"Running comparison query: {query_str[:100]}...")
        
        # Get all community summaries
        community_summaries = self.graph_store.get_community_summaries()
        
        if not community_summaries:
            return "No community summaries available. Please run build_communities() first."
        
        # Combine all summaries with clear labels
        all_summaries = '\n\n'.join([
            f"=== Community {cid} ===\n{summary}" 
            for cid, summary in community_summaries.items()
        ])
        
        prompt = f"""You are an expert auditor analyzing a knowledge graph to find INCONSISTENCIES and DISCREPANCIES.

The knowledge graph has been built from multiple documents (contracts, invoices, purchase orders, etc.). 
Each community represents related information that was extracted.

COMMUNITIES AND THEIR SUMMARIES:
{all_summaries}

YOUR TASK: {query_str}

INSTRUCTIONS:
1. Compare information ACROSS communities to find contradictions
2. Look for values that don't match (prices, dates, terms, quantities)
3. Identify missing information that should be present
4. For EACH inconsistency found, provide:
   - The specific field/aspect that is inconsistent
   - What one source says vs what another source says
   - The evidence from the community summaries

OUTPUT FORMAT:
For each inconsistency, provide:
- **Field**: [the field or aspect that is inconsistent]
- **Inconsistency**: [clear description of the contradiction]
- **Evidence**: [quotes from community summaries showing the difference]

If you find NO inconsistencies, explicitly state "No inconsistencies found" and explain why the documents are consistent."""
        
        try:
            messages = [
                ChatMessage(
                    role="system",
                    content="You are an expert document auditor specialized in finding inconsistencies, discrepancies, and contradictions across multiple documents. You are thorough and precise, always citing specific evidence."
                ),
                ChatMessage(role="user", content=prompt),
            ]
            response = self.llm.chat(messages)
            cleaned_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
            logger.info(f"Comparison query completed across {len(community_summaries)} communities")
            return cleaned_response
        except Exception as e:
            logger.error(f"Failed to run comparison query: {e}")
            return f"Error running comparison query: {str(e)}"


class FastGraphRAGQueryEngine(CustomQueryEngine):
    """
    Optimized GraphRAG Query Engine for faster responses.
    
    Optimizations:
    1. Parallel per-community answer generation
    2. Early termination if high-confidence answer found
    3. Caching of community summaries
    4. Reduced LLM calls for simple queries
    """
    
    graph_store: GraphRAGStore = Field(description="GraphRAG store with community summaries")
    llm: LLM = Field(description="LLM for answer generation")
    similarity_top_k: int = Field(default=5, description="Number of entities/communities to check")
    max_communities: int = Field(default=3, description="Maximum communities to query (for speed)")
    parallel: bool = Field(default=True, description="Run community queries in parallel")
    
    def custom_query(self, query_str: str) -> str:
        """
        Fast GraphRAG query with optimizations.
        """
        logger.info(f"FastGraphRAG query: {query_str[:100]}...")
        
        # Get community summaries
        summaries = self.graph_store.get_community_summaries()
        
        if not summaries:
            return "No community summaries available. Please run build_communities() first."
        
        # Limit to max_communities for speed
        community_ids = list(summaries.keys())[:self.max_communities]
        
        if self.parallel and len(community_ids) > 1:
            # Parallel execution
            answers = self._parallel_generate_answers(
                [summaries[cid] for cid in community_ids], 
                query_str
            )
        else:
            # Sequential execution
            answers = [
                self._generate_answer_from_summary(summaries[cid], query_str)
                for cid in community_ids
            ]
        
        # Filter empty answers
        valid_answers = [a for a in answers if a and not self._is_empty_answer(a)]
        
        if not valid_answers:
            return "I couldn't find relevant information to answer this question."
        
        if len(valid_answers) == 1:
            return valid_answers[0]
        
        # Quick aggregation
        return self._quick_aggregate(valid_answers)
    
    def _parallel_generate_answers(self, summaries: List[str], query: str) -> List[str]:
        """
        Generate answers in parallel using ThreadPoolExecutor.
        """
        with ThreadPoolExecutor(max_workers=len(summaries)) as executor:
            futures = [
                executor.submit(self._generate_answer_from_summary, summary, query)
                for summary in summaries
            ]
            return [f.result() for f in futures]
    
    def _generate_answer_from_summary(self, summary: str, query: str) -> str:
        """Generate answer from a single community summary."""
        prompt = f"Based on this summary:\n{summary}\n\nAnswer: {query}"
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = self.llm.chat(messages)
            return str(response).strip()
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return ""
    
    def _is_empty_answer(self, answer: str) -> bool:
        """Check if answer indicates no relevant information."""
        empty_phrases = ["no relevant", "cannot answer", "don't have", "not mentioned"]
        return any(phrase in answer.lower() for phrase in empty_phrases)
    
    def _quick_aggregate(self, answers: List[str]) -> str:
        """Quick aggregation without additional LLM call."""
        # For speed, just concatenate with clear separators
        if len(answers) <= 2:
            return "\n\n".join(answers)
        
        # For more answers, use LLM to aggregate
        combined = "\n---\n".join(answers)
        prompt = f"Combine these answers into one response:\n{combined}"
        
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = self.llm.chat(messages)
            return str(response).strip()
        except:
            return answers[0]
