#!/usr/bin/env python3
"""
Standalone PPR Variant Experiment — Query-Biased Teleportation vs Uniform PPR

Compares three PPR variants WITHOUT touching production code:
  A) Uniform PPR (current) — all seeds get equal teleportation weight 1/N
  B) Query-biased teleportation — seeds weighted by cosine(seed_embedding, query_embedding)
  C) PPR + EPIC reranking — uniform PPR output re-scored by cosine(entity_embedding, query_embedding)

Methodology:
  1. Connect to Neo4j directly (same graph the server uses)
  2. For each benchmark question:
     a) Extract entities via LLM NER (same as production)
     b) Resolve entities to graph IDs (same strategies 1-6)
     c) Run PPR variant A, B, C on the resolved seeds
     d) For each variant, collect the top-K entity names → these become the "retrieval set"
  3. Compare: do the retrieved entities (and their linked chunks/sections) cover
     the ground truth better under query-biased teleportation?

Usage:
  cd /afh/projects/graphrag-orchestration
  set -a && source .env.local && set +a
  python scripts/experiment_ppr_variants.py [--top-k 20] [--filter-qid Q-D3]
"""

import asyncio
import json
import os
import sys
import time
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set

import numpy as np

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")

# Azure OpenAI (for LLM NER — same model as production IntentDisambiguator)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
# Production NER uses HYBRID_NER_MODEL = gpt-5.1
AZURE_OPENAI_NER_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.1")


# ---------------------------------------------------------------------------
# Benchmark questions (Q-D1..Q-D10 from QUESTION_BANK_5PDFS_2025-12-24.md)
# ---------------------------------------------------------------------------
BENCHMARK_QUESTIONS = [
    {
        "qid": "Q-D1",
        "query": "If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?",
        "key_entities": ["warranty", "emergency defect", "notification", "builder"],
    },
    {
        "qid": "Q-D2",
        "query": "In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?",
        "key_entities": ["property management agreement", "confirmed reservations", "termination"],
    },
    {
        "qid": "Q-D3",
        "query": "Compare \"time windows\" across the set: list all explicit day-based timeframes.",
        "key_entities": ["time windows", "warranty", "holding tank", "property management", "purchase contract"],
    },
    {
        "qid": "Q-D4",
        "query": "Which documents mention insurance and what limits are specified?",
        "key_entities": ["insurance", "liability", "property damage", "bodily injury"],
    },
    {
        "qid": "Q-D5",
        "query": "In the warranty, explain how the \"coverage start\" is defined and what must happen before coverage ends.",
        "key_entities": ["warranty", "coverage start", "final settlement", "occupancy"],
    },
    {
        "qid": "Q-D6",
        "query": "Do the purchase contract total price and the invoice total match? If so, what is that amount?",
        "key_entities": ["purchase contract", "invoice", "total price", "$29,900"],
    },
    {
        "qid": "Q-D7",
        "query": "Which document has the latest explicit date, and what is it?",
        "key_entities": ["date", "purchase contract", "2025-04-30"],
    },
    {
        "qid": "Q-D8",
        "query": "Across the set, which entity appears in the most different documents: Fabrikam Inc. or Contoso Ltd.?",
        "key_entities": ["Fabrikam Inc.", "Contoso Ltd.", "documents"],
    },
    {
        "qid": "Q-D9",
        "query": "Compare the \"fees\" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?",
        "key_entities": ["fees", "percentage", "installment", "property management", "purchase contract"],
    },
    {
        "qid": "Q-D10",
        "query": "List the three different \"risk allocation\" statements across the set (risk of loss, liability limitations, non-transferability).",
        "key_entities": ["risk allocation", "risk of loss", "liability", "non-transferable"],
    },
]


# ---------------------------------------------------------------------------
# Neo4j async driver wrapper (minimal, standalone)
# ---------------------------------------------------------------------------
class Neo4jClient:
    """Lightweight async Neo4j client for the experiment."""
    
    def __init__(self, uri: str, user: str, password: str):
        from neo4j import AsyncGraphDatabase
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    
    async def close(self):
        await self.driver.close()
    
    async def run(self, query: str, **params) -> list:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return await result.data()


# ---------------------------------------------------------------------------
# Voyage embedding client (minimal, standalone)
# ---------------------------------------------------------------------------
class VoyageEmbedder:
    """Minimal Voyage AI client using contextualized_embed (2048d, matches Neo4j index)."""
    
    def __init__(self, api_key: str, model: str = "voyage-context-3", dim: int = 2048):
        import voyageai
        self.client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self._cache: Dict[str, List[float]] = {}
    
    def embed(self, texts: List[str], input_type: str = "query") -> List[List[float]]:
        """Embed a batch of texts using contextualized_embed (with caching)."""
        uncached = [t for t in texts if t not in self._cache]
        if uncached:
            # contextualized_embed expects inputs=[[chunk1], [chunk2], ...]
            # Each "document" is a list of chunks; for queries, single-chunk docs
            inputs = [[t] for t in uncached]
            result = self.client.contextualized_embed(
                inputs=inputs,
                model=self.model,
                input_type=input_type,
                output_dimension=self.dim,
            )
            for text, doc_result in zip(uncached, result.results):
                self._cache[text] = doc_result.embeddings[0]
        return [self._cache[t] for t in texts]
    
    def embed_one(self, text: str, input_type: str = "query") -> List[float]:
        return self.embed([text], input_type=input_type)[0]


# ---------------------------------------------------------------------------
# LLM NER — mirrors production IntentDisambiguator.disambiguate()
# ---------------------------------------------------------------------------
import re as _re

_GENERIC_SEED_PHRASES = {
    "ach", "wire", "wire transfer", "swift", "swift code", "swift codes",
    "iban", "bic", "vat", "tax id", "tax id number", "routing number",
    "routing numbers", "bank routing number", "bank routing numbers",
    "bank account number",
}

def _normalize_seed(s: str) -> str:
    s = (s or "").strip().casefold()
    s = _re.sub(r"[^a-z0-9]+", " ", s)
    s = _re.sub(r"\s+", " ", s).strip()
    return s

def _is_generic_non_entity_seed(s: str) -> bool:
    ns = _normalize_seed(s)
    if not ns:
        return True
    if ns in _GENERIC_SEED_PHRASES:
        return True
    if any(phrase in ns for phrase in ("swift", "iban", "bic", "ach")) and len(ns) <= 20:
        return True
    return False


async def llm_ner_extract(query: str, top_k: int = 5) -> List[str]:
    """
    Extract seed entities from a query using the same prompt and filters
    as production IntentDisambiguator.disambiguate().
    """
    from openai import AsyncAzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version=AZURE_OPENAI_API_VERSION,
        azure_ad_token_provider=token_provider,
    )

    prompt = f"""You are an expert at identifying specific entities in a knowledge graph.

Given the following user query and the available entity communities in our graph,
identify the top {top_k} specific entity names that this query is referring to.

User Query: "{query}"

Available Communities/Entities:
No community information available. Extract entities directly from the query.

Important:
- Return specific entity-like strings (proper nouns, organizations, document titles, named clauses) likely to exist in the graph.
- Do NOT return generic keywords (e.g., "licensed", "state", "jurisdiction", "payment", "instructions").
- If you are unsure, return nothing.

Return ONLY a markdown list of entity names, one per line. Example:
- Contoso Ltd.
- Purchase Contract
- Warranty Agreement

Do not include any explanation, just the list.
"""

    response = await client.chat.completions.create(
        model=AZURE_OPENAI_NER_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_completion_tokens=256,
    )
    raw_text = (response.choices[0].message.content or "").strip()

    # Parse markdown list (same as production)
    entities: List[str] = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            entities.append(line[2:].strip())
        elif line.startswith("* "):
            entities.append(line[2:].strip())

    # Clean quotes
    def _clean(name: str) -> str:
        cleaned = (name or "").strip()
        while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'", "`"):
            cleaned = cleaned[1:-1].strip()
        return cleaned

    cleaned = [_clean(x) for x in entities if x]
    cleaned = [x for x in cleaned if x]

    # No heuristic filter — pass raw LLM output to graph resolution.
    # The graph itself decides what exists (lexical + vector match).
    return cleaned[:top_k]


# ---------------------------------------------------------------------------
# Entity resolution (mirrors production strategies 1-5 + vector fallback)
# ---------------------------------------------------------------------------
async def resolve_entities(
    neo4j: Neo4jClient,
    group_id: str,
    entity_names: List[str],
    embedder: VoyageEmbedder,
) -> List[Dict]:
    """Resolve entity names to graph IDs using lexical + vector strategies."""
    resolved = []
    unresolved_names = []
    
    for name in entity_names:
        # Strategy 1: Exact match (case-insensitive)
        records = await neo4j.run("""
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`)
              AND e.group_id = $group_id
              AND toLower(e.name) = toLower($name)
            RETURN e.id AS id, e.name AS name
            LIMIT 1
        """, group_id=group_id, name=name)
        
        if records:
            resolved.append(records[0])
            continue
            
        # Strategy 2: Substring match
        records = await neo4j.run("""
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`)
              AND e.group_id = $group_id
              AND (toLower(e.name) CONTAINS toLower($name)
                   OR toLower($name) CONTAINS toLower(e.name))
            RETURN e.id AS id, e.name AS name
            ORDER BY size(e.name) ASC
            LIMIT 1
        """, group_id=group_id, name=name)
        
        if records:
            resolved.append(records[0])
            continue
        
        unresolved_names.append(name)
    
    # Strategy 6: Vector similarity for unresolved
    for name in unresolved_names:
        emb = embedder.embed_one(name, input_type="query")
        records = await neo4j.run("""
            CALL db.index.vector.queryNodes('entity_embedding_v2', 3, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
              AND (node:Entity OR node:`__Entity__`)
            RETURN node.id AS id, node.name AS name, score AS similarity
            LIMIT 1
        """, group_id=group_id, embedding=emb)
        
        if records:
            resolved.append(records[0])
    
    return resolved


# ---------------------------------------------------------------------------
# PPR Variant A: Uniform (current production behavior)
# ---------------------------------------------------------------------------
async def ppr_uniform(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    top_k: int = 20,
) -> List[Tuple[str, float]]:
    """Standard PPR with uniform personalization (current production)."""
    records = await neo4j.run("""
        UNWIND $seed_ids AS seed_id
        MATCH (seed {id: seed_id})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)

        WITH seed, $group_id AS group_id

        // 1-hop
        CALL (seed, group_id) {
            MATCH (seed)-[r1]-(n1)
            WHERE n1.group_id = group_id
                AND (n1:Entity OR n1:`__Entity__`)
                AND NOT (type(r1) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
            WITH n1
            ORDER BY coalesce(n1.degree, 0) DESC
            LIMIT 25
            RETURN collect(n1) AS hop1
        }

        WITH seed, hop1, group_id

        // Flatten all entities
        UNWIND (hop1 + [seed]) AS hop1_node

        // 2-hop
        CALL (hop1_node, group_id) {
            MATCH (hop1_node)-[r2]-(n2)
            WHERE n2.group_id = group_id
                AND (n2:Entity OR n2:`__Entity__`)
                AND NOT (type(r2) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
            WITH n2
            ORDER BY coalesce(n2.degree, 0) DESC
            LIMIT 10
            RETURN collect(n2) AS hop2
        }

        WITH seed, hop1_node, hop2

        UNWIND (hop2 + [hop1_node]) AS entity
        WITH DISTINCT entity, seed,
             CASE
                 WHEN entity.id = seed.id THEN 1.0
                 WHEN entity.id = hop1_node.id THEN 0.85
                 ELSE 0.85 * 0.85
             END AS score
        RETURN entity.id AS id,
               entity.name AS name,
               max(score) AS score
        ORDER BY score DESC
        LIMIT $top_k
    """, seed_ids=seed_ids, group_id=group_id, top_k=top_k)
    
    return [(r["name"], r["score"]) for r in records]


# ---------------------------------------------------------------------------
# PPR Variant B: Query-Biased Teleportation
# ---------------------------------------------------------------------------
async def ppr_query_biased(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    query_embedding: List[float],
    top_k: int = 20,
) -> List[Tuple[str, float]]:
    """
    PPR with query-biased teleportation (single batched Cypher query).
    
    Instead of uniform 1/N per seed, each seed's teleportation weight is
    cosine(seed_embedding, query_embedding). Seeds more semantically aligned
    with the query get higher teleportation probability.
    
    All seeds are processed in one Cypher call via UNWIND — no per-seed loop.
    """
    # Step 1: Get bias weights via cosine similarity (single query)
    bias_records = await neo4j.run("""
        UNWIND $seed_ids AS seed_id
        MATCH (seed {id: seed_id})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)
          AND (seed.embedding_v2 IS NOT NULL OR seed.embedding IS NOT NULL)
        RETURN seed.id AS id,
               seed.name AS name,
               vector.similarity.cosine(
                   COALESCE(seed.embedding_v2, seed.embedding),
                   $query_embedding
               ) AS query_sim
    """, seed_ids=seed_ids, group_id=group_id, query_embedding=query_embedding)
    
    # Build bias map (id → sim), floor at 0.01
    seed_biases = {}
    for r in bias_records:
        seed_biases[r["id"]] = max(r["query_sim"], 0.01)
    
    # Seeds without embeddings get average weight
    avg_bias = np.mean(list(seed_biases.values())) if seed_biases else 0.5
    for sid in seed_ids:
        if sid not in seed_biases:
            seed_biases[sid] = avg_bias
    
    # Normalize to sum=1
    total = sum(seed_biases.values())
    for sid in seed_biases:
        seed_biases[sid] /= total
    
    # Build parallel arrays for Cypher parameters
    bias_ids = list(seed_biases.keys())
    bias_weights = [seed_biases[sid] for sid in bias_ids]
    num_seeds = len(bias_ids)
    
    # Step 2: Single batched expansion with per-seed bias weights
    records = await neo4j.run("""
        // Zip seed IDs with their bias weights
        WITH $bias_ids AS ids, $bias_weights AS weights, $num_seeds AS n
        UNWIND range(0, size(ids) - 1) AS idx
        WITH ids[idx] AS seed_id, weights[idx] AS bias_weight, n

        MATCH (seed {id: seed_id})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)

        WITH seed, bias_weight, n

        // 1-hop
        CALL (seed) {
            MATCH (seed)-[r1]-(n1)
            WHERE n1.group_id = $group_id
                AND (n1:Entity OR n1:`__Entity__`)
                AND NOT (type(r1) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
            WITH n1
            ORDER BY coalesce(n1.degree, 0) DESC
            LIMIT 25
            RETURN collect(n1) AS hop1
        }

        WITH seed, hop1, bias_weight, n

        UNWIND (hop1 + [seed]) AS hop1_node

        // 2-hop
        CALL (hop1_node) {
            MATCH (hop1_node)-[r2]-(n2)
            WHERE n2.group_id = $group_id
                AND (n2:Entity OR n2:`__Entity__`)
                AND NOT (type(r2) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
            WITH n2
            ORDER BY coalesce(n2.degree, 0) DESC
            LIMIT 10
            RETURN collect(n2) AS hop2
        }

        WITH seed, hop1_node, hop2, bias_weight, n
        UNWIND (hop2 + [hop1_node]) AS entity
        WITH DISTINCT entity, seed, hop1_node, bias_weight, n,
             CASE
                 WHEN entity.id = seed.id THEN 1.0
                 WHEN entity.id = hop1_node.id THEN 0.85
                 ELSE 0.85 * 0.85
             END AS raw_score

        // Weighted score: raw_score * bias_weight * num_seeds (to match uniform magnitude)
        WITH entity.id AS id,
             entity.name AS name,
             sum(raw_score * bias_weight * n) AS score

        RETURN id, name, score
        ORDER BY score DESC
        LIMIT $top_k
    """, bias_ids=bias_ids, bias_weights=bias_weights, num_seeds=num_seeds,
         group_id=group_id, top_k=top_k)
    
    return [(r["name"], r["score"]) for r in records]


# ---------------------------------------------------------------------------
# PPR Variant C: Uniform PPR + EPIC Reranking
# ---------------------------------------------------------------------------
async def ppr_epic_rerank(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    query_embedding: List[float],
    top_k: int = 20,
    rerank_pool: int = 50,
) -> List[Tuple[str, float]]:
    """
    Uniform PPR + EPIC-style reranking.
    
    Runs standard PPR to get top-50, then re-scores each entity by
    cosine(entity_embedding, query_embedding). Final score = PPR * cosine.
    """
    # Step 1: Run uniform PPR with larger pool
    ppr_results = await ppr_uniform(neo4j, group_id, seed_ids, top_k=rerank_pool)
    
    if not ppr_results:
        return []
    
    # Step 2: Get entity embeddings for top results and compute cosine with query
    entity_names = [name for name, _ in ppr_results]
    ppr_scores = {name: score for name, score in ppr_results}
    
    records = await neo4j.run("""
        UNWIND $names AS entity_name
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
          AND e.group_id = $group_id
          AND e.name = entity_name
          AND (e.embedding_v2 IS NOT NULL OR e.embedding IS NOT NULL)
        RETURN e.name AS name,
               vector.similarity.cosine(
                   COALESCE(e.embedding_v2, e.embedding),
                   $query_embedding
               ) AS query_sim
    """, names=entity_names, group_id=group_id, query_embedding=query_embedding)
    
    cosine_scores = {r["name"]: r["query_sim"] for r in records}
    
    # Step 3: Combined score = PPR_score * cosine_sim
    combined = []
    for name, ppr_score in ppr_results:
        cos = cosine_scores.get(name, 0.5)  # Default 0.5 if no embedding
        combined_score = ppr_score * cos
        combined.append((name, combined_score, ppr_score, cos))
    
    combined.sort(key=lambda x: x[1], reverse=True)
    
    return [(name, score) for name, score, _, _ in combined[:top_k]]


# ---------------------------------------------------------------------------
# PPR Variant D: Query-Biased Teleportation + EPIC Reranking (both)
# ---------------------------------------------------------------------------
async def ppr_biased_plus_epic(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    query_embedding: List[float],
    top_k: int = 20,
) -> List[Tuple[str, float]]:
    """Combine query-biased teleportation (B) with EPIC reranking (C)."""
    # Get biased PPR results (larger pool)
    biased_results = await ppr_query_biased(neo4j, group_id, seed_ids, query_embedding, top_k=50)
    
    if not biased_results:
        return []
    
    entity_names = [name for name, _ in biased_results]
    biased_scores = {name: score for name, score in biased_results}
    
    # EPIC rerank
    records = await neo4j.run("""
        UNWIND $names AS entity_name
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
          AND e.group_id = $group_id
          AND e.name = entity_name
          AND (e.embedding_v2 IS NOT NULL OR e.embedding IS NOT NULL)
        RETURN e.name AS name,
               vector.similarity.cosine(
                   COALESCE(e.embedding_v2, e.embedding),
                   $query_embedding
               ) AS query_sim
    """, names=entity_names, group_id=group_id, query_embedding=query_embedding)
    
    cosine_scores = {r["name"]: r["query_sim"] for r in records}
    
    combined = []
    for name, biased_score in biased_results:
        cos = cosine_scores.get(name, 0.5)
        combined.append((name, biased_score * cos))
    
    combined.sort(key=lambda x: x[1], reverse=True)
    return combined[:top_k]


# ---------------------------------------------------------------------------
# PPR Variant E: True Matrix PPR (scipy sparse power iteration)
# ---------------------------------------------------------------------------
async def ppr_matrix(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    top_k: int = 20,
    damping: float = 0.85,
    max_iterations: int = 40,
    tol: float = 1e-6,
) -> List[Tuple[str, float]]:
    """
    True Personalized PageRank using scipy sparse matrix power iteration.

    Loads ALL entities + edges for the group, builds a weighted adjacency
    matrix across 5 edge types, runs standard PPR power iteration.
    """
    from scipy import sparse

    # Edge type weights
    W_RELATED = 1.0
    W_SEMANTIC = 0.8
    W_SECTION_BRIDGE = 0.6
    W_HUB = 0.5
    W_SHARES = 0.5

    # --- Step 1: Load all Entity nodes ---
    node_recs = await neo4j.run("""
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
        RETURN e.id AS id, e.name AS name
    """, group_id=group_id)

    if not node_recs:
        return []

    id_to_idx: Dict[str, int] = {}
    idx_to_name: Dict[int, str] = {}
    for i, rec in enumerate(node_recs):
        id_to_idx[rec["id"]] = i
        idx_to_name[i] = rec["name"]
    n = len(node_recs)

    rows: List[int] = []
    cols: List[int] = []
    vals: List[float] = []

    def _add(si: int, di: int, w: float):
        rows.extend([si, di])
        cols.extend([di, si])
        vals.extend([w, w])

    # --- Edge 1: RELATED_TO ---
    for e in await neo4j.run("""
        MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity)
        WHERE a.group_id = $group_id AND b.group_id = $group_id
        RETURN a.id AS src, b.id AS dst
    """, group_id=group_id):
        si, di = id_to_idx.get(e["src"]), id_to_idx.get(e["dst"])
        if si is not None and di is not None:
            _add(si, di, W_RELATED)

    # --- Edge 2: SEMANTICALLY_SIMILAR (entity↔entity) ---
    for e in await neo4j.run("""
        MATCH (a:Entity)-[r:SEMANTICALLY_SIMILAR]->(b:Entity)
        WHERE a.group_id = $group_id AND b.group_id = $group_id
        RETURN a.id AS src, b.id AS dst, coalesce(r.similarity, 0.6) AS sim
    """, group_id=group_id):
        si, di = id_to_idx.get(e["src"]), id_to_idx.get(e["dst"])
        if si is not None and di is not None:
            _add(si, di, W_SEMANTIC * e["sim"])

    # --- Edge 3: Section bridge (entity→section→sim→section→entity) ---
    for e in await neo4j.run("""
        MATCH (a:Entity)-[:APPEARS_IN_SECTION]->(s1:Section)
              -[sim:SEMANTICALLY_SIMILAR]-(s2:Section)
              <-[:APPEARS_IN_SECTION]-(b:Entity)
        WHERE a.group_id = $group_id AND b.group_id = $group_id
          AND a.id <> b.id AND coalesce(sim.similarity, 0.5) >= 0.5
        RETURN DISTINCT a.id AS src, b.id AS dst,
               max(coalesce(sim.similarity, 0.5)) AS sim
    """, group_id=group_id):
        si, di = id_to_idx.get(e["src"]), id_to_idx.get(e["dst"])
        if si is not None and di is not None:
            _add(si, di, W_SECTION_BRIDGE * e["sim"])

    # --- Edge 4: HUB_ENTITY ---
    for e in await neo4j.run("""
        MATCH (a:Entity)-[:APPEARS_IN_SECTION]->(s:Section)
              -[hub:HAS_HUB_ENTITY]->(b:Entity)
        WHERE a.group_id = $group_id AND b.group_id = $group_id
          AND a.id <> b.id
        RETURN DISTINCT a.id AS src, b.id AS dst,
               max(coalesce(hub.mention_count, 1)) / 10.0 AS hw
    """, group_id=group_id):
        si, di = id_to_idx.get(e["src"]), id_to_idx.get(e["dst"])
        if si is not None and di is not None:
            _add(si, di, W_HUB * min(e["hw"], 1.0))

    # --- Edge 5: SHARES_ENTITY cross-document ---
    for e in await neo4j.run("""
        MATCH (a:Entity)-[:APPEARS_IN_SECTION]->(s1:Section)
              -[se:SHARES_ENTITY]-(s2:Section)
              <-[:APPEARS_IN_SECTION]-(b:Entity)
        WHERE a.group_id = $group_id AND b.group_id = $group_id
          AND a.id <> b.id AND coalesce(se.shared_entities, 1) >= 2
        RETURN DISTINCT a.id AS src, b.id AS dst,
               max(coalesce(se.shared_entities, 1)) / 10.0 AS sew
    """, group_id=group_id):
        si, di = id_to_idx.get(e["src"]), id_to_idx.get(e["dst"])
        if si is not None and di is not None:
            _add(si, di, W_SHARES * min(e["sew"], 1.0))

    if not rows:
        return []

    # --- Step 3: Sparse transition matrix ---
    A = sparse.coo_matrix(
        (np.array(vals), (np.array(rows), np.array(cols))),
        shape=(n, n),
    ).tocsr()
    row_sums = np.array(A.sum(axis=1)).flatten()
    row_sums[row_sums == 0] = 1.0
    M = sparse.diags(1.0 / row_sums) @ A

    # --- Step 4: Personalization vector ---
    p = np.zeros(n)
    for sid in seed_ids:
        idx = id_to_idx.get(sid)
        if idx is not None:
            p[idx] = 1.0
    if p.sum() == 0:
        return []
    p /= p.sum()

    # --- Step 5: Power iteration ---
    Mt = M.T.tocsr()
    v = p.copy()
    for _ in range(max_iterations):
        v_new = damping * Mt.dot(v) + (1 - damping) * p
        if np.abs(v_new - v).sum() < tol:
            v = v_new
            break
        v = v_new

    # --- Step 6: Top-K ---
    top_idx = np.argsort(-v)[:top_k]
    return [(idx_to_name[i], float(v[i])) for i in top_idx if v[i] > 0]


# ---------------------------------------------------------------------------
# Ground Truth: which entities SHOULD appear for each question
# ---------------------------------------------------------------------------
async def get_ground_truth_entities(
    neo4j: Neo4jClient,
    group_id: str,
) -> Dict[str, Set[str]]:
    """
    Build ground truth: for each Q-D question, which entities are in the
    source documents that contain the answer?
    
    We use document-level matching: get all entities that appear in the 
    expected source documents.
    """
    # First: discover document_id → doc name mapping from first chunk text
    doc_map_records = await neo4j.run("""
        MATCH (c)
        WHERE (c:Chunk OR c:TextChunk OR c:`__Node__`)
          AND c.group_id = $group_id
          AND c.chunk_index = 0
        RETURN c.document_id AS doc_id, left(toLower(c.text), 200) AS preview
    """, group_id=group_id)
    
    # Classify each doc_id by content
    doc_labels: Dict[str, str] = {}  # doc_id → label
    for r in doc_map_records:
        p = r["preview"]
        if "warranty" in p or "arbitration" in p:
            doc_labels[r["doc_id"]] = "warranty"
        elif "holding tank" in p:
            doc_labels[r["doc_id"]] = "holding_tank"
        elif "property management" in p:
            doc_labels[r["doc_id"]] = "property_management"
        elif "purchase contract" in p:
            doc_labels[r["doc_id"]] = "purchase_contract"
        elif "invoice" in p or "contoso lifts" in p:
            doc_labels[r["doc_id"]] = "invoice"
    
    # Reverse map: label → doc_ids
    label_to_docs: Dict[str, List[str]] = {}
    for doc_id, label in doc_labels.items():
        label_to_docs.setdefault(label, []).append(doc_id)
    
    print(f"    Doc mapping: {', '.join(f'{v}={k[:12]}' for k, v in doc_labels.items())}")
    
    # Map question → source document labels
    DOC_SOURCES = {
        "Q-D1": ["warranty"],
        "Q-D2": ["property_management"],
        "Q-D3": ["warranty", "holding_tank", "property_management", "purchase_contract"],
        "Q-D4": ["property_management"],
        "Q-D5": ["warranty"],
        "Q-D6": ["purchase_contract", "invoice"],
        "Q-D7": ["purchase_contract", "holding_tank", "invoice", "warranty", "property_management"],
        "Q-D8": ["warranty", "holding_tank", "purchase_contract", "property_management"],
        "Q-D9": ["property_management", "purchase_contract"],
        "Q-D10": ["purchase_contract", "property_management", "warranty"],
    }
    
    gt: Dict[str, Set[str]] = {}
    
    for qid, doc_labels_needed in DOC_SOURCES.items():
        entities: Set[str] = set()
        doc_ids = []
        for label in doc_labels_needed:
            doc_ids.extend(label_to_docs.get(label, []))
        
        if doc_ids:
            records = await neo4j.run("""
                MATCH (c)-[:MENTIONS]->(e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND e.group_id = $group_id
                  AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
                  AND c.group_id = $group_id
                  AND c.document_id IN $doc_ids
                RETURN DISTINCT e.name AS name
            """, group_id=group_id, doc_ids=doc_ids)
            for r in records:
                entities.add(r["name"])
        gt[qid] = entities
    
    return gt


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def coverage_score(retrieved: List[str], ground_truth: Set[str]) -> float:
    """What fraction of ground-truth entities are in the retrieved set?"""
    if not ground_truth:
        return 0.0
    retrieved_set = set(retrieved)
    overlap = retrieved_set & ground_truth
    return len(overlap) / len(ground_truth)


def rank_weighted_score(retrieved: List[Tuple[str, float]], ground_truth: Set[str]) -> float:
    """
    Rank-aware metric: higher score if ground-truth entities appear earlier.
    Uses inverse log rank weighting like NDCG.
    """
    if not ground_truth or not retrieved:
        return 0.0
    
    score = 0.0
    max_possible = 0.0
    
    for rank, (name, _) in enumerate(retrieved, 1):
        weight = 1.0 / np.log2(rank + 1)
        if name in ground_truth:
            score += weight
        max_possible += weight
    
    # Perfect score if all top positions are relevant
    ideal = sum(1.0 / np.log2(i + 1) for i in range(1, min(len(ground_truth), len(retrieved)) + 1))
    return score / ideal if ideal > 0 else 0.0


def entity_overlap(list_a: List[str], list_b: List[str]) -> Tuple[int, int, int]:
    """Returns (shared, only_in_a, only_in_b)."""
    set_a, set_b = set(list_a), set(list_b)
    return len(set_a & set_b), len(set_a - set_b), len(set_b - set_a)


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------
async def run_experiment(top_k: int = 20, filter_qid: Optional[str] = None):
    print("=" * 70)
    print("PPR VARIANT EXPERIMENT: Query-Biased Teleportation")
    print("=" * 70)
    print(f"  Neo4j: {NEO4J_URI}")
    print(f"  Group: {GROUP_ID}")
    print(f"  Top-K: {top_k}")
    print()
    
    # Initialize
    neo4j = Neo4jClient(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
    embedder = VoyageEmbedder(VOYAGE_API_KEY)
    
    try:
        # Verify connectivity
        test = await neo4j.run("""
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`)
              AND e.group_id = $group_id
            RETURN count(e) AS cnt
        """, group_id=GROUP_ID)
        print(f"  Entities in graph: {test[0]['cnt']}")
        
        # Build ground truth
        print("\n  Building ground truth...")
        gt = await get_ground_truth_entities(neo4j, GROUP_ID)
        for qid, ents in sorted(gt.items()):
            print(f"    {qid}: {len(ents)} entities in source docs")
        
        # Filter questions
        questions = BENCHMARK_QUESTIONS
        if filter_qid:
            questions = [q for q in questions if q["qid"] == filter_qid]
            if not questions:
                print(f"  ERROR: No question matches '{filter_qid}'")
                return
        
        # Results storage
        results: List[Dict] = []
        
        print("\n" + "=" * 70)
        print("RUNNING EXPERIMENTS")
        print("=" * 70)
        
        for q in questions:
            qid = q["qid"]
            query = q["query"]
            
            print(f"\n{'─' * 70}")
            print(f"  {qid}: {query[:60]}...")
            
            # Step 1: Get query embedding
            t0 = time.perf_counter()
            query_emb = embedder.embed_one(query, input_type="query")
            
            # Step 2: LLM NER (same prompt + filters as production IntentDisambiguator)
            ner_entities = await llm_ner_extract(query, top_k=5)
            print(f"  NER entities: {ner_entities}")
            
            # Step 2b: Resolve NER entities to graph nodes (dedup by node ID)
            resolved = await resolve_entities(neo4j, GROUP_ID, ner_entities, embedder)
            seen_ids: set = set()
            deduped: list = []
            for r in resolved:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    deduped.append(r)
            seed_ids = [r["id"] for r in deduped]
            seed_names = [r["name"] for r in deduped]
            
            print(f"  Seeds: {seed_names}")
            if not seed_ids:
                print(f"  SKIP: no seeds resolved")
                continue
            
            # Step 3: Run all variants
            t_a = time.perf_counter()
            results_a = await ppr_uniform(neo4j, GROUP_ID, seed_ids, top_k=top_k)
            dt_a = time.perf_counter() - t_a
            
            t_b = time.perf_counter()
            results_b = await ppr_query_biased(neo4j, GROUP_ID, seed_ids, query_emb, top_k=top_k)
            dt_b = time.perf_counter() - t_b
            
            t_c = time.perf_counter()
            results_c = await ppr_epic_rerank(neo4j, GROUP_ID, seed_ids, query_emb, top_k=top_k)
            dt_c = time.perf_counter() - t_c
            
            t_d = time.perf_counter()
            results_d = await ppr_biased_plus_epic(neo4j, GROUP_ID, seed_ids, query_emb, top_k=top_k)
            dt_d = time.perf_counter() - t_d
            
            t_e = time.perf_counter()
            results_e = await ppr_matrix(neo4j, GROUP_ID, seed_ids, top_k=top_k)
            dt_e = time.perf_counter() - t_e
            
            # Step 4: Compute metrics
            gt_entities = gt.get(qid, set())
            
            names_a = [n for n, _ in results_a]
            names_b = [n for n, _ in results_b]
            names_c = [n for n, _ in results_c]
            names_d = [n for n, _ in results_d]
            names_e = [n for n, _ in results_e]
            
            cov_a = coverage_score(names_a, gt_entities)
            cov_b = coverage_score(names_b, gt_entities)
            cov_c = coverage_score(names_c, gt_entities)
            cov_d = coverage_score(names_d, gt_entities)
            cov_e = coverage_score(names_e, gt_entities)
            
            rw_a = rank_weighted_score(results_a, gt_entities)
            rw_b = rank_weighted_score(results_b, gt_entities)
            rw_c = rank_weighted_score(results_c, gt_entities)
            rw_d = rank_weighted_score(results_d, gt_entities)
            rw_e = rank_weighted_score(results_e, gt_entities)
            
            # Print per-question results
            print(f"\n  {'Variant':<25} {'Coverage':>10} {'RankScore':>10} {'Time':>8}")
            print(f"  {'─' * 55}")
            print(f"  {'A) Uniform PPR':<25} {cov_a:>10.3f} {rw_a:>10.3f} {dt_a*1000:>7.0f}ms")
            print(f"  {'B) Query-biased teleport':<25} {cov_b:>10.3f} {rw_b:>10.3f} {dt_b*1000:>7.0f}ms")
            print(f"  {'C) Uniform + EPIC':<25} {cov_c:>10.3f} {rw_c:>10.3f} {dt_c*1000:>7.0f}ms")
            print(f"  {'D) Biased + EPIC':<25} {cov_d:>10.3f} {rw_d:>10.3f} {dt_d*1000:>7.0f}ms")
            print(f"  {'E) True Matrix PPR':<25} {cov_e:>10.3f} {rw_e:>10.3f} {dt_e*1000:>7.0f}ms")
            
            # Show ranking differences (E vs A)
            shared, only_a, only_e = entity_overlap(names_a[:10], names_e[:10])
            if only_a > 0 or only_e > 0:
                print(f"\n  Top-10 diff (A vs E): {shared} shared, {only_a} only-cypher, {only_e} only-matrix")
                only_in_e = set(names_e[:10]) - set(names_a[:10])
                if only_in_e:
                    for name in list(only_in_e)[:5]:
                        in_gt = "✓ GT" if name in gt_entities else "  —"
                        print(f"    NEW in matrix PPR: {name} {in_gt}")
            
            # Store result
            results.append({
                "qid": qid,
                "seeds": seed_names,
                "coverage_a": cov_a,
                "coverage_b": cov_b,
                "coverage_c": cov_c,
                "coverage_d": cov_d,
                "coverage_e": cov_e,
                "rank_a": rw_a,
                "rank_b": rw_b,
                "rank_c": rw_c,
                "rank_d": rw_d,
                "rank_e": rw_e,
                "latency_a_ms": int(dt_a * 1000),
                "latency_b_ms": int(dt_b * 1000),
                "latency_c_ms": int(dt_c * 1000),
                "latency_d_ms": int(dt_d * 1000),
                "latency_e_ms": int(dt_e * 1000),
                "top10_a": names_a[:10],
                "top10_b": names_b[:10],
                "top10_c": names_c[:10],
                "top10_d": names_d[:10],
                "top10_e": names_e[:10],
            })
        
        # ===================================================================
        # Summary
        # ===================================================================
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        
        if results:
            avg = lambda key: np.mean([r[key] for r in results])
            
            print(f"\n  {'Variant':<25} {'Avg Coverage':>12} {'Avg RankScore':>14} {'Avg Latency':>12}")
            print(f"  {'─' * 66}")
            print(f"  {'A) Uniform PPR':<25} {avg('coverage_a'):>12.3f} {avg('rank_a'):>14.3f} {avg('latency_a_ms'):>11.0f}ms")
            print(f"  {'B) Query-biased teleport':<25} {avg('coverage_b'):>12.3f} {avg('rank_b'):>14.3f} {avg('latency_b_ms'):>11.0f}ms")
            print(f"  {'C) Uniform + EPIC':<25} {avg('coverage_c'):>12.3f} {avg('rank_c'):>14.3f} {avg('latency_c_ms'):>11.0f}ms")
            print(f"  {'D) Biased + EPIC':<25} {avg('coverage_d'):>12.3f} {avg('rank_d'):>14.3f} {avg('latency_d_ms'):>11.0f}ms")
            print(f"  {'E) True Matrix PPR':<25} {avg('coverage_e'):>12.3f} {avg('rank_e'):>14.3f} {avg('latency_e_ms'):>11.0f}ms")
            
            # Per-question delta table
            print(f"\n  Per-question coverage delta (vs A=Uniform):")
            print(f"  {'QID':<8} {'A':>8} {'B−A':>8} {'C−A':>8} {'D−A':>8} {'E−A':>8}")
            print(f"  {'─' * 46}")
            for r in results:
                da = r["coverage_a"]
                db = r["coverage_b"] - da
                dc = r["coverage_c"] - da
                dd = r["coverage_d"] - da
                de = r["coverage_e"] - da
                print(f"  {r['qid']:<8} {da:>8.3f} {db:>+8.3f} {dc:>+8.3f} {dd:>+8.3f} {de:>+8.3f}")
            
            # Verdict: E vs A
            e_wins = sum(1 for r in results if r["coverage_e"] > r["coverage_a"])
            e_ties = sum(1 for r in results if r["coverage_e"] == r["coverage_a"])
            e_loses = sum(1 for r in results if r["coverage_e"] < r["coverage_a"])
            
            print(f"\n  True Matrix PPR vs Cypher Approximation:")
            print(f"    Wins: {e_wins}, Ties: {e_ties}, Losses: {e_loses}")
            print(f"    Avg coverage delta: {avg('coverage_e') - avg('coverage_a'):+.3f}")
            print(f"    Avg latency delta:  {avg('latency_e_ms') - avg('latency_a_ms'):+.0f}ms")
        
        # Save results
        out_path = Path(f"experiment_ppr_variants_{time.strftime('%Y%m%dT%H%M%SZ')}.json")
        with open(out_path, "w") as f:
            json.dump({"top_k": top_k, "group_id": GROUP_ID, "results": results}, f, indent=2)
        print(f"\n  Results saved to {out_path}")
        
    finally:
        await neo4j.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PPR Variant Experiment")
    parser.add_argument("--top-k", type=int, default=20, help="Top-K entities per variant")
    parser.add_argument("--filter-qid", type=str, default=None, help="Run only this QID")
    args = parser.parse_args()
    
    asyncio.run(run_experiment(top_k=args.top_k, filter_qid=args.filter_qid))
