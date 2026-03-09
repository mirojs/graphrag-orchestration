"""Triple Embedding Store + Recognition Memory Filter for HippoRAG 2.

Implements key HippoRAG 2 innovations:

1. **Query-to-triple linking**: At index time, all KG triples (subject, predicate,
   object) are loaded from Neo4j and embedded as concatenated strings. At query time,
   the query embedding is matched against triple embeddings via cosine similarity to
   find the top-K most relevant triples. This replaces HippoRAG 1's NER-to-node
   linking.

2. **MMR diversity filter** (default): Selects a diverse subset of reranked triples
   using Maximal Marginal Relevance — balancing relevance scores against inter-triple
   similarity to eliminate redundant facts (e.g., five variants of "warrants 90 days").

3. **Recognition memory filter** (legacy): An LLM filters the top-K retrieved triples,
   keeping only those judged relevant to the query. Inspired by human recognition
   memory. Selectable via ROUTE7_RECOGNITION_MEMORY_MODE=llm.

Reference: HippoRAG 2 (ICML '25) — https://arxiv.org/abs/2502.14802
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
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
        group_ids: Optional[List[str]] = None,
    ) -> None:
        """Load triples from Neo4j, embed with Voyage, cache in memory.

        Args:
            neo4j_driver: Sync Neo4j driver instance.
            group_id: Multi-tenant group ID (primary).
            voyage_service: VoyageEmbedService instance for embedding.
            group_ids: List of group IDs for multi-group retrieval.
                       Defaults to [group_id] if not provided.
        """
        effective_group_ids = group_ids or [group_id, "__global__"]
        t0 = time.perf_counter()

        # Fetch all RELATED_TO triples from Neo4j
        triples = await asyncio.to_thread(
            self._fetch_triples_sync, neo4j_driver, effective_group_ids
        )

        if not triples:
            logger.warning("triple_store_no_triples", group_id=group_id)
            self._loaded = True
            return

        # Check if triples have pre-computed embeddings from indexing
        precomputed_count = sum(1 for t in triples if t.embedding is not None)
        all_precomputed = precomputed_count == len(triples) and precomputed_count > 0

        if all_precomputed:
            # Use pre-computed embeddings — skip Voyage API call entirely
            self._triples = triples
            self._embeddings_matrix = np.array(
                [t.embedding for t in triples], dtype=np.float32
            )
            logger.info(
                "triple_store_using_precomputed_embeddings",
                group_id=group_id,
                triple_count=len(triples),
            )
        else:
            # Batch-embed triple texts with Voyage (legacy / first-time path)
            triple_texts = [t.triple_text for t in triples]
            embeddings = await asyncio.to_thread(
                voyage_service.embed_documents, triple_texts
            )
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
        self, neo4j_driver: Any, group_ids: List[str]
    ) -> List[Triple]:
        """Fetch all RELATED_TO triples from Neo4j (synchronous).

        If triples have pre-computed embeddings (embedding_v2 property stored
        during indexing), those are loaded directly — avoiding a Voyage API
        call at query time.
        """
        cypher = """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE e1.group_id IN $group_ids AND e2.group_id IN $group_ids
              AND r.description IS NOT NULL AND r.description <> ''
        RETURN e1.id AS subj_id, e1.name AS subj_name,
               r.description AS predicate,
               e2.id AS obj_id, e2.name AS obj_name,
               r.embedding_v2 AS embedding
        """
        triples: List[Triple] = []
        with retry_session(neo4j_driver) as session:
            result = session.run(cypher, group_ids=group_ids)
            for record in result:
                subj_name = record["subj_name"] or ""
                predicate = record["predicate"] or ""
                obj_name = record["obj_name"] or ""
                triple_text = f"{subj_name} {predicate} {obj_name}"
                embedding = record["embedding"]
                triples.append(
                    Triple(
                        subject_id=record["subj_id"],
                        subject_name=subj_name,
                        predicate=predicate,
                        object_id=record["obj_id"],
                        object_name=obj_name,
                        triple_text=triple_text,
                        embedding=list(embedding) if embedding else None,
                    )
                )
        logger.debug(
            "triple_store_fetched",
            group_ids=group_ids,
            count=len(triples),
            precomputed=sum(1 for t in triples if t.embedding is not None),
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


def mmr_diversity_filter(
    candidate_triples: List[Tuple[Triple, float]],
    max_facts: int | None = None,
    lambda_param: float | None = None,
) -> List[Tuple[Triple, float]]:
    """Maximal Marginal Relevance filter — replaces LLM recognition memory.

    Selects a diverse subset of triples that balances relevance (reranker score)
    against redundancy (cosine similarity to already-selected triples).

    At each step, picks the triple maximizing:
        score(t) = λ × relevance(t) − (1−λ) × max_sim(t, selected)

    This naturally deduplicates near-identical triples (e.g., five variants of
    "warrants labor for 90 days") while keeping the most relevant diverse facts.

    Args:
        candidate_triples: List of (Triple, score) from reranker, sorted desc.
        max_facts: Maximum triples to select. Defaults to ROUTE7_RECOGNITION_MEMORY_MAX_FACTS.
        lambda_param: Relevance vs diversity tradeoff (0–1). Higher = more relevance.
                      Defaults to ROUTE7_MMR_LAMBDA (0.7).

    Returns:
        List of (Triple, score) tuples, length ≤ max_facts.
    """
    if not candidate_triples:
        return []

    if max_facts is None:
        max_facts = int(os.getenv("ROUTE7_RECOGNITION_MEMORY_MAX_FACTS", "7"))
    if lambda_param is None:
        lambda_param = float(os.getenv("ROUTE7_MMR_LAMBDA", "0.7"))

    # Build embedding matrix from candidate triples
    embeddings = []
    for triple, _ in candidate_triples:
        if triple.embedding is not None:
            embeddings.append(triple.embedding)
        else:
            # Fallback: zero vector (triple will be scored purely on relevance)
            embeddings.append([0.0] * 2048)

    emb_matrix = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    emb_matrix = emb_matrix / norms

    # Normalize relevance scores to [0, 1]
    scores = np.array([s for _, s in candidate_triples], dtype=np.float32)
    s_min, s_max = scores.min(), scores.max()
    if s_max > s_min:
        norm_scores = (scores - s_min) / (s_max - s_min)
    else:
        norm_scores = np.ones_like(scores)

    # Greedy MMR selection
    n = len(candidate_triples)
    selected_indices: List[int] = []
    remaining = set(range(n))

    for _ in range(min(max_facts, n)):
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            relevance = norm_scores[idx]

            if selected_indices:
                # Max cosine similarity to any already-selected triple
                sims = emb_matrix[idx] @ emb_matrix[selected_indices].T
                max_sim = float(np.max(sims))
            else:
                max_sim = 0.0

            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx < 0:
            break

        selected_indices.append(best_idx)
        remaining.discard(best_idx)

    result = [candidate_triples[i] for i in selected_indices]

    logger.info(
        "mmr_diversity_filter",
        candidates=len(candidate_triples),
        selected=len(result),
        max_facts=max_facts,
        lambda_param=lambda_param,
        top_triple=result[0][0].triple_text[:60] if result else "",
    )
    return result


async def recognition_memory_filter(
    llm_client: Any,
    query: str,
    candidate_triples: List[Tuple[Triple, float]],
    max_facts: int | None = None,
) -> List[Tuple[Triple, float]]:
    """LLM-based recognition memory filter — upstream DSPy few-shot aligned.

    Uses the same prompt structure as upstream HippoRAG 2's DSPyFilter:
    - System prompt describing a high-stakes QA filtering task
    - Few-shot demonstrations from the upstream optimized prompt
    - Structured JSON output: {"fact": [["s","p","o"], ...]}
    - difflib fuzzy matching to map generated facts back to candidates

    Reference: OSU-NLP-Group/HippoRAG rerank.py + filter_default_prompt.py

    Args:
        llm_client: LLM client with ``acomplete(prompt)`` method.
        query: The user query.
        candidate_triples: List of (Triple, score) from TripleEmbeddingStore.search().
        max_facts: Maximum facts to select. Defaults to env ROUTE7_RECOGNITION_MEMORY_MAX_FACTS (4).

    Returns:
        List of (Triple, score) tuples that survived filtering. May be empty.
    """
    if not candidate_triples:
        return []

    if max_facts is None:
        max_facts = int(os.getenv("ROUTE7_RECOGNITION_MEMORY_MAX_FACTS", "7"))

    # Build fact list in upstream format: {"fact": [["s","p","o"], ...]}
    fact_list = []
    triple_text_to_item: Dict[str, Tuple[Triple, float]] = {}
    for triple, score in candidate_triples:
        parts = [triple.subject_name.lower(), triple.predicate.lower(), triple.object_name.lower()]
        fact_list.append(parts)
        triple_text_to_item[str(parts)] = (triple, score)

    fact_before_filter = json.dumps({"fact": fact_list})

    # All 10 upstream DSPy-optimized demonstrations (from filter_default_prompt.py)
    _DEMOS = [
        {
            "q": "Are Imperial River (Florida) and Amaradia (Dolj) both located in the same country?",
            "before": '{"fact": [["imperial river", "is located in", "florida"], ["imperial river", "is a river in", "united states"], ["imperial river", "may refer to", "south america"], ["amaradia", "flows through", "ro ia de amaradia"], ["imperial river", "may refer to", "united states"]]}',
            "after": '{"fact":[["imperial river","is located in","florida"],["imperial river","is a river in","united states"],["amaradia","flows through","ro ia de amaradia"]]}',
        },
        {
            "q": "When is the director of film The Ancestor's birthday?",
            "before": '{"fact": [["jean jacques annaud", "born on", "1 october 1943"], ["tsui hark", "born on", "15 february 1950"], ["pablo trapero", "born on", "4 october 1971"], ["the ancestor", "directed by", "guido brignone"], ["benh zeitlin", "born on", "october 14  1982"]]}',
            "after": '{"fact":[["the ancestor","directed by","guido brignone"]]}',
        },
        {
            "q": "In what geographic region is the country where Teafuone is located?",
            "before": '{"fact": [["teafuaniua", "is on the", "east"], ["motuloa", "lies between", "teafuaniua"], ["motuloa", "lies between", "teafuanonu"], ["teafuone", "is", "islet"], ["teafuone", "located in", "nukufetau"]]}',
            "after": '{"fact":[["teafuone","is","islet"],["teafuone","located in","nukufetau"]]}',
        },
        {
            "q": "When did the director of film S.O.B. (Film) die?",
            "before": '{"fact": [["allan dwan", "died on", "28 december 1981"], ["s o b", "written and directed by", "blake edwards"], ["robert aldrich", "died on", "december 5  1983"], ["robert siodmak", "died on", "10 march 1973"], ["bernardo bertolucci", "died on", "26 november 2018"]]}',
            "after": '{"fact":[["s o b","written and directed by","blake edwards"]]}',
        },
        {
            "q": "Do both films: Gloria (1980 Film) and A New Life (Film) have the directors from the same country?",
            "before": '{"fact": [["sebasti n lelio watt", "received acclaim for directing", "gloria"], ["gloria", "is", "1980 american thriller crime drama film"], ["a brand new life", "is directed by", "ounie lecomte"], ["gloria", "written and directed by", "john cassavetes"], ["a new life", "directed by", "alan alda"]]}',
            "after": '{"fact":[["gloria","is","1980 american thriller crime drama film"],["gloria","written and directed by","john cassavetes"],["a new life","directed by","alan alda"]]}',
        },
        {
            "q": "What is the date of death of the director of film The Old Guard (1960 Film)?",
            "before": '{"fact": [["the old guard", "is", "1960 french comedy film"], ["gilles grangier", "directed", "the old guard"], ["the old guard", "directed by", "gilles grangier"], ["the old fritz", "directed by", "gerhard lamprecht"], ["oswald albert mitchell", "directed", "old mother riley series of films"]]}',
            "after": '{"fact":[["the old guard","is","1960 french comedy film"],["gilles grangier","directed","the old guard"],["the old guard","directed by","gilles grangier"]]}',
        },
        {
            "q": "When is the composer of film Aulad (1968 Film)'s birthday?",
            "before": '{"fact": [["aulad", "has music composed by", "chitragupta shrivastava"], ["aadmi sadak ka", "has music by", "ravi"], ["ravi shankar sharma", "composed music for", "hindi films"], ["gulzar", "was born on", "18 august 1934"], ["aulad", "is a", "1968 hindi language drama film"]]}',
            "after": '{"fact":[["aulad","has music composed by","chitragupta shrivastava"],["aulad","is a","1968 hindi language drama film"]]}',
        },
        {
            "q": "How many households were in the city where Angelical Tears located?",
            "before": '{"fact": [["dow city", "had", "219 households"], ["tucson", "had", "229 762 households"], ["atlantic city", "has", "15 504 households"], ["angelical tears", "located in", "oklahoma city"], ["atlantic city", "had", "15 848 households"]]}',
            "after": '{"fact": [["angelical tears", "located in", "oklahoma city"]]}',
        },
        {
            "q": "Did the movies In The Pope's Eye and Virgin Mountain, originate from the same country?",
            "before": '{"fact": [["virgin mountain", "released in", "icelandic cinemas"], ["virgin mountain", "directed by", "dagur k ri"], ["virgin mountain", "icelandic title is", "f si"], ["virgin mountain", "won", "2015 nordic council film prize"], ["virgin mountain", "is a", "2015 icelandic drama film"]]}',
            "after": '{"fact": [["virgin mountain", "released in", "icelandic cinemas"], ["virgin mountain", "directed by", "dagur k ri"], ["virgin mountain", "icelandic title is", "f si"], ["virgin mountain", "won", "2015 nordic council film prize"], ["virgin mountain", "is a", "2015 icelandic drama film"]]}',
        },
        {
            "q": "Which film has the director who died earlier, The Virtuous Model or Bulldog Drummond's Peril?",
            "before": '{"fact": [["the virtuous model", "is", "1919 american silent drama film"], ["bulldog drummond s peril", "directed by", "james p  hogan"], ["the virtuous model", "directed by", "albert capellani"], ["bulldog drummond s revenge", "directed by", "louis king"], ["bulldog drummond s peril", "is", "american film"]]}',
            "after": '{"fact": [["the virtuous model", "is", "1919 american silent drama film"], ["bulldog drummond s peril", "directed by", "james p  hogan"], ["the virtuous model", "directed by", "albert capellani"], ["bulldog drummond s peril", "is", "american film"]]}',
        },
    ]

    # Build messages in upstream DSPy-optimized format (from filter_default_prompt.py)
    _SYS = (
        "Your input fields are:\n"
        "1. `question` (str): Query for retrieval\n"
        "2. `fact_before_filter` (str): Candidate facts to be filtered\n"
        "\n"
        "Your output fields are:\n"
        '1. `fact_after_filter` (Fact): Filtered facts in JSON format\n'
        "\n"
        "All interactions will be structured in the following way, with the appropriate values filled in.\n"
        "\n"
        "[[ ## question ## ]]\n"
        "{question}\n"
        "\n"
        "[[ ## fact_before_filter ## ]]\n"
        "{fact_before_filter}\n"
        "\n"
        "[[ ## fact_after_filter ## ]]\n"
        '{fact_after_filter}        # note: the value you produce must be pareseable according to the following JSON schema: '
        '{"type": "object", "properties": {"fact": {"type": "array", "description": "A list of facts, each fact is a list of 3 strings: [subject, predicate, object]", '
        '"items": {"type": "array", "items": {"type": "string"}}, "title": "Fact"}}, "required": ["fact"], "title": "Fact"}\n'
        "\n"
        "[[ ## completed ## ]]\n"
        "\n"
        "In adhering to this structure, your objective is: \n"
        "        You are a critical component of a high-stakes question-answering system used by top researchers and "
        "decision-makers worldwide. Your task is to filter facts based on their relevance to a given query, ensuring "
        "that the most crucial information is presented to these stakeholders. The query requires careful analysis and "
        "possibly multi-hop reasoning to connect different pieces of information. You must select up to {max_facts} relevant facts "
        "from the provided candidate list that have a strong connection to the query, aiding in reasoning and providing "
        'an accurate answer. The output should be in JSON format, e.g., {"fact": [["s1", "p1", "o1"], ["s2", "p2", "o2"]]}, '
        'and if no facts are relevant, return an empty list, {"fact": []}. The accuracy of your response is paramount, '
        "as it will directly impact the decisions made by these high-level stakeholders. You must only use facts from the "
        "candidate list and not generate new facts. The future of critical decision-making relies on your ability to "
        "accurately filter and present relevant information."
    )

    _INPUT_TPL = "[[ ## question ## ]]\n{question}\n\n[[ ## fact_before_filter ## ]]\n{fact_before_filter}\n\nRespond with the corresponding output fields, starting with the field `[[ ## fact_after_filter ## ]]`, and then ending with the marker for `[[ ## completed ## ]]`."
    _OUTPUT_TPL = "[[ ## fact_after_filter ## ]]\n{fact_after_filter}\n\n[[ ## completed ## ]]"

    # Build the full prompt: system + few-shot demos + current query
    messages_parts = [_SYS.replace("{max_facts}", str(max_facts)), ""]
    for demo in _DEMOS:
        messages_parts.append(_INPUT_TPL.format(question=demo["q"], fact_before_filter=demo["before"]))
        messages_parts.append(_OUTPUT_TPL.format(fact_after_filter=demo["after"]))
    messages_parts.append(_INPUT_TPL.format(question=query, fact_before_filter=fact_before_filter))

    prompt = "\n\n".join(messages_parts)

    try:
        response = await llm_client.acomplete(prompt, temperature=0)
        text = response.text.strip()

        # Parse upstream structured format: look for [[ ## fact_after_filter ## ]]
        parsed_facts = []
        if "[[ ## fact_after_filter ## ]]" in text:
            after_section = text.split("[[ ## fact_after_filter ## ]]")[1]
            if "[[ ## completed ## ]]" in after_section:
                after_section = after_section.split("[[ ## completed ## ]]")[0]
            after_section = after_section.strip()
        else:
            after_section = text

        # Try to parse as JSON
        try:
            parsed = json.loads(after_section)
            if isinstance(parsed, dict) and "fact" in parsed:
                parsed_facts = parsed["fact"]
        except json.JSONDecodeError:
            # Try to extract JSON from the text
            json_match = re.search(r'\{[^{}]*"fact"\s*:\s*\[.*?\]\s*\}', after_section, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    parsed_facts = parsed.get("fact", [])
                except json.JSONDecodeError:
                    pass

        if not parsed_facts:
            logger.info(
                "recognition_memory_all_filtered",
                query=query[:60],
                candidates=len(candidate_triples),
            )
            return []

        # Fuzzy match generated facts back to candidates (upstream uses difflib)
        surviving: List[Tuple[Triple, float]] = []
        seen_keys: set = set()
        candidate_strs = [str(f) for f in fact_list]

        for gen_fact in parsed_facts:
            gen_str = str(gen_fact)
            matches = difflib.get_close_matches(gen_str, candidate_strs, n=1, cutoff=0.0)
            if matches:
                matched_str = matches[0]
                if matched_str not in seen_keys and matched_str in triple_text_to_item:
                    seen_keys.add(matched_str)
                    surviving.append(triple_text_to_item[matched_str])

        logger.info(
            "recognition_memory_filter",
            query=query[:60],
            candidates=len(candidate_triples),
            surviving=len(surviving),
            generated_facts=len(parsed_facts),
        )
        return surviving

    except Exception as e:
        logger.warning(
            "recognition_memory_filter_failed",
            error=str(e),
            query=query[:60],
        )
        # On failure, pass through all candidates (conservative fallback)
        return list(candidate_triples)
