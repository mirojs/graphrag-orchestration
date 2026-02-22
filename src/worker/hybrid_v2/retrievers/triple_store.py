"""Triple Embedding Store + Recognition Memory Filter for HippoRAG 2.

Implements two key HippoRAG 2 innovations:

1. **Query-to-triple linking**: At index time, all KG triples (subject, predicate,
   object) are loaded from Neo4j and embedded as concatenated strings. At query time,
   the query embedding is matched against triple embeddings via cosine similarity to
   find the top-K most relevant triples. This replaces HippoRAG 1's NER-to-node
   linking.

2. **Recognition memory filter**: An LLM filters the top-K retrieved triples,
   keeping only those judged relevant to the query. This is inspired by human
   recognition memory — "identifying information with the help of external stimuli."

Reference: HippoRAG 2 (ICML '25) — https://arxiv.org/abs/2502.14802
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import structlog

from ..services.neo4j_retry import retry_session

logger = structlog.get_logger(__name__)


@dataclass
class Triple:
    """A knowledge graph triple with its embedding."""

    subject_id: str
    subject_name: str
    predicate: str
    object_id: str
    object_name: str
    triple_text: str  # "{subject_name} {predicate} {object_name}"
    embedding: Optional[List[float]] = None


class TripleEmbeddingStore:
    """In-memory cache of triple embeddings for query-time linking.

    Loads all RELATED_TO edges from Neo4j, concatenates the triple text
    (subject + predicate + object), batch-embeds with Voyage, and caches
    the result as a numpy matrix for fast cosine similarity search.

    The store is lazy-loaded on first use and cached per group_id.
    """

    def __init__(self) -> None:
        self._triples: List[Triple] = []
        self._embeddings_matrix: Optional[np.ndarray] = None  # (N, dim)
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def triple_count(self) -> int:
        return len(self._triples)

    async def load(
        self,
        neo4j_driver: Any,
        group_id: str,
        voyage_service: Any,
    ) -> None:
        """Load triples from Neo4j, embed with Voyage, cache in memory.

        Args:
            neo4j_driver: Sync Neo4j driver instance.
            group_id: Multi-tenant group ID.
            voyage_service: VoyageEmbedService instance for embedding.
        """
        t0 = time.perf_counter()

        # Fetch all RELATED_TO triples from Neo4j
        triples = await asyncio.to_thread(
            self._fetch_triples_sync, neo4j_driver, group_id
        )

        if not triples:
            logger.warning("triple_store_no_triples", group_id=group_id)
            self._loaded = True
            return

        # Batch-embed triple texts with Voyage
        triple_texts = [t.triple_text for t in triples]
        embeddings = await asyncio.to_thread(
            voyage_service.embed_documents, triple_texts
        )

        # Store as numpy matrix for fast cosine search
        self._triples = triples
        self._embeddings_matrix = np.array(embeddings, dtype=np.float32)

        # Normalize for cosine similarity via dot product
        norms = np.linalg.norm(self._embeddings_matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._embeddings_matrix /= norms

        self._loaded = True
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "triple_store_loaded",
            group_id=group_id,
            triple_count=len(triples),
            embedding_dim=self._embeddings_matrix.shape[1],
            elapsed_ms=elapsed_ms,
        )

    def _fetch_triples_sync(
        self, neo4j_driver: Any, group_id: str
    ) -> List[Triple]:
        """Fetch all RELATED_TO triples from Neo4j (synchronous)."""
        cypher = """
        MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
        WHERE r.description IS NOT NULL AND r.description <> ''
        RETURN e1.id AS subj_id, e1.name AS subj_name,
               r.description AS predicate,
               e2.id AS obj_id, e2.name AS obj_name
        """
        triples: List[Triple] = []
        with retry_session(neo4j_driver) as session:
            result = session.run(cypher, group_id=group_id)
            for record in result:
                subj_name = record["subj_name"] or ""
                predicate = record["predicate"] or ""
                obj_name = record["obj_name"] or ""
                triple_text = f"{subj_name} {predicate} {obj_name}"
                triples.append(
                    Triple(
                        subject_id=record["subj_id"],
                        subject_name=subj_name,
                        predicate=predicate,
                        object_id=record["obj_id"],
                        object_name=obj_name,
                        triple_text=triple_text,
                    )
                )
        logger.debug(
            "triple_store_fetched",
            group_id=group_id,
            count=len(triples),
        )
        return triples

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
    ) -> List[Tuple[Triple, float]]:
        """Cosine similarity search against cached triple embeddings.

        Args:
            query_embedding: Query embedding vector (Voyage 2048d).
            top_k: Number of top triples to return.

        Returns:
            List of (Triple, similarity_score) tuples, sorted descending.
        """
        if not self._loaded or self._embeddings_matrix is None:
            return []

        # Normalize query
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q /= q_norm

        # Cosine similarity = dot product (both vectors normalized)
        scores = self._embeddings_matrix @ q  # (N,)

        # Top-K
        k = min(top_k, len(scores))
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        return [
            (self._triples[i], float(scores[i]))
            for i in top_indices
        ]


async def recognition_memory_filter(
    llm_client: Any,
    query: str,
    candidate_triples: List[Tuple[Triple, float]],
) -> List[Triple]:
    """LLM-based recognition memory filter for retrieved triples.

    After the embedding model retrieves the top-K triples by cosine similarity,
    the LLM acts as a "recognition memory" — it examines each triple and judges
    whether it is genuinely relevant to the query. This filters out false
    positives from the embedding search.

    Modeled after HippoRAG 2's recognition memory mechanism (Section 3.2).

    Args:
        llm_client: LLM client with ``acomplete(prompt)`` method.
        query: The user query.
        candidate_triples: List of (Triple, score) from TripleEmbeddingStore.search().

    Returns:
        List of Triple objects that survived filtering. May be empty.
    """
    if not candidate_triples:
        return []

    # Build numbered list of triples for the LLM
    triple_list_lines = []
    triple_map: Dict[int, Triple] = {}
    for i, (triple, score) in enumerate(candidate_triples, 1):
        triple_list_lines.append(f"{i}. {triple.triple_text}")
        triple_map[i] = triple

    prompt = f"""You are filtering knowledge graph facts for relevance to a query.

Query: "{query}"

Here are candidate facts retrieved from the knowledge graph:
{chr(10).join(triple_list_lines)}

Which facts are relevant to answering the query?
Return ONLY the numbers of relevant facts, comma-separated.
If none are relevant, return "NONE".

Example: 1, 3, 5"""

    try:
        response = await llm_client.acomplete(prompt)
        text = response.text.strip()

        if text.upper() == "NONE":
            logger.info(
                "recognition_memory_all_filtered",
                query=query[:60],
                candidates=len(candidate_triples),
            )
            return []

        # Parse comma-separated numbers
        numbers = [int(n) for n in re.findall(r"\d+", text)]
        surviving = [triple_map[n] for n in numbers if n in triple_map]

        logger.info(
            "recognition_memory_filter",
            query=query[:60],
            candidates=len(candidate_triples),
            surviving=len(surviving),
            selected_numbers=numbers,
        )
        return surviving

    except Exception as e:
        logger.warning(
            "recognition_memory_filter_failed",
            error=str(e),
            query=query[:60],
        )
        # On failure, pass through all candidates (conservative fallback)
        return [triple for triple, _ in candidate_triples]
