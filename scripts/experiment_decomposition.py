#!/usr/bin/env python3
"""
Decomposition Impact Experiment — Does DRIFT sub-question decomposition help?

Compares two NER strategies:
  F) Direct NER: query → NER → resolve → PPR (HippoRAG 2 style)
  G) DRIFT Decompose: query → decompose into sub-questions → NER on original +
     each sub-question → union seeds → resolve → PPR

The PPR variant is always A (uniform, production Cypher 2-hop).
Variant F is identical to variant A from experiment_ppr_variants.py.

Usage:
  cd /afh/projects/graphrag-orchestration
  set -a && source .env.local && set +a
  python scripts/experiment_decomposition.py [--top-k 20] [--filter-qid Q-D3]
"""

import asyncio
import json
import os
import sys
import time
import argparse
from pathlib import Path
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

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_NER_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.1")


# ---------------------------------------------------------------------------
# Benchmark questions (same Q-D1..Q-D10)
# ---------------------------------------------------------------------------
BENCHMARK_QUESTIONS = [
    {"qid": "Q-D1", "query": "If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?"},
    {"qid": "Q-D2", "query": "In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?"},
    {"qid": "Q-D3", "query": "Compare \"time windows\" across the set: list all explicit day-based timeframes."},
    {"qid": "Q-D4", "query": "Which documents mention insurance and what limits are specified?"},
    {"qid": "Q-D5", "query": "In the warranty, explain how the \"coverage start\" is defined and what must happen before coverage ends."},
    {"qid": "Q-D6", "query": "Do the purchase contract total price and the invoice total match? If so, what is that amount?"},
    {"qid": "Q-D7", "query": "Which document has the latest explicit date, and what is it?"},
    {"qid": "Q-D8", "query": "Across the set, which entity appears in the most different documents: Fabrikam Inc. or Contoso Ltd.?"},
    {"qid": "Q-D9", "query": "Compare the \"fees\" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?"},
    {"qid": "Q-D10", "query": "List the three different \"risk allocation\" statements across the set (risk of loss, liability limitations, non-transferability)."},
]


# ---------------------------------------------------------------------------
# Neo4j + Voyage clients (reused from experiment_ppr_variants.py)
# ---------------------------------------------------------------------------
class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        from neo4j import AsyncGraphDatabase
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    
    async def close(self):
        await self.driver.close()
    
    async def run(self, query: str, **params) -> list:
        async with self.driver.session() as session:
            result = await session.run(query, **params)
            return await result.data()


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str = "voyage-context-3", dim: int = 2048):
        import voyageai
        self.client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self._cache: Dict[str, List[float]] = {}
    
    def embed_one(self, text: str, input_type: str = "query") -> List[float]:
        if text not in self._cache:
            inputs = [[text]]
            result = self.client.contextualized_embed(
                inputs=inputs, model=self.model,
                input_type=input_type, output_dimension=self.dim,
            )
            self._cache[text] = result.results[0].embeddings[0]
        return self._cache[text]


# ---------------------------------------------------------------------------
# Azure OpenAI client (shared across NER and decomposition)
# ---------------------------------------------------------------------------
_aoai_client = None

async def _get_aoai():
    global _aoai_client
    if _aoai_client is None:
        from openai import AsyncAzureOpenAI
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        _aoai_client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_ad_token_provider=token_provider,
        )
    return _aoai_client


# ---------------------------------------------------------------------------
# LLM NER — same prompt as production IntentDisambiguator
# ---------------------------------------------------------------------------
async def llm_ner_extract(query: str, top_k: int = 5) -> List[str]:
    """Extract entity seeds from query text using LLM."""
    client = await _get_aoai()

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

    entities: List[str] = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            entities.append(line[2:].strip())

    def _clean(name: str) -> str:
        cleaned = (name or "").strip()
        while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'", "`"):
            cleaned = cleaned[1:-1].strip()
        return cleaned

    cleaned = [_clean(x) for x in entities if x]
    return [x for x in cleaned if x][:top_k]


# ---------------------------------------------------------------------------
# LLM Decomposition — same prompt as production _drift_decompose()
# ---------------------------------------------------------------------------
async def drift_decompose(query: str) -> List[str]:
    """Decompose query into sub-questions using the production DRIFT prompt."""
    client = await _get_aoai()

    prompt = f"""Break down this complex query into specific, answerable sub-questions.

Original Query: "{query}"

Guidelines:
- Each sub-question should focus on identifying specific entities or relationships
- Questions should build on each other (entity discovery → relationship exploration → analysis)
- Generate 2-5 sub-questions depending on complexity
- CRITICAL: Preserve ALL constraints and qualifiers from the original query in EACH sub-question
  (e.g., if original asks for items "above $500", each sub-question must preserve that threshold)
  (e.g., if original asks for "California-specific" clauses, each sub-question must include that geographic constraint)

Format your response as a numbered list:
1. [First sub-question]
2. [Second sub-question]
...

Sub-questions:"""

    response = await client.chat.completions.create(
        model=AZURE_OPENAI_NER_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_completion_tokens=512,
    )
    text = (response.choices[0].message.content or "").strip()

    sub_questions = []
    for line in text.split('\n'):
        line = line.strip()
        if line and line[0].isdigit():
            content = line.split('.', 1)[-1].strip()
            content = content.split(')', 1)[-1].strip()
            if content:
                normalized = content.strip().strip('"').strip("'").strip()
                if normalized in {"?", "-", "—"}:
                    continue
                if len(normalized) < 8:
                    continue
                sub_questions.append(normalized)

    # De-dupe
    seen: set = set()
    deduped: List[str] = []
    for q in sub_questions:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            deduped.append(q)

    return deduped if deduped else [query]


# ---------------------------------------------------------------------------
# Entity resolution (lexical + vector, same as experiment_ppr_variants.py)
# ---------------------------------------------------------------------------
async def resolve_entities(
    neo4j: Neo4jClient,
    group_id: str,
    entity_names: List[str],
    embedder: VoyageEmbedder,
) -> List[Dict]:
    resolved = []
    unresolved_names = []
    
    for name in entity_names:
        # Strategy 1: Exact match
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
    
    # Strategy 6: Vector similarity
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


async def resolve_entities_semantic(
    neo4j: Neo4jClient,
    group_id: str,
    entity_names: List[str],
    embedder: VoyageEmbedder,
    sim_threshold: float = 0.62,
) -> List[Dict]:
    """
    Semantic-first entity resolution:
      1. Exact match (same as before — free, perfect precision)
      2. Vector similarity with threshold (primary non-exact strategy)
         - Fixes transformations: "Insurance Contract" → "insurance policy" not "contract"
         - Filters fabrications below threshold
      3. Substring fallback ONLY if vector returns nothing
         (some entities lack embedding_v2 in the index)
    """
    resolved = []
    
    for name in entity_names:
        # Strategy 1: Exact match (case-insensitive) — precision = 1.0
        records = await neo4j.run("""
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`)
              AND e.group_id = $group_id
              AND toLower(e.name) = toLower($name)
            RETURN e.id AS id, e.name AS name, 1.0 AS similarity
            LIMIT 1
        """, group_id=group_id, name=name)
        if records:
            resolved.append(records[0])
            continue
        
        # Strategy 2: Vector similarity with threshold
        emb = embedder.embed_one(name, input_type="query")
        records = await neo4j.run("""
            CALL db.index.vector.queryNodes('entity_embedding_v2', 3, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
              AND (node:Entity OR node:`__Entity__`)
            RETURN node.id AS id, node.name AS name, score AS similarity
            ORDER BY score DESC
            LIMIT 1
        """, group_id=group_id, embedding=emb)
        
        if records and records[0].get("similarity", 0) >= sim_threshold:
            resolved.append(records[0])
            continue
        
        # Strategy 3: Substring fallback (only if vector returned nothing)
        # This catches entities that lack embedding_v2 in the graph
        if not records:  # vector returned 0 results
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
        # else: vector returned results but below threshold → drop (fabrication)
    
    return resolved


def dedup_resolved(resolved: List[Dict]) -> List[Dict]:
    """Dedup by node ID, preserving order."""
    seen: set = set()
    out: list = []
    for r in resolved:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# PPR: Uniform (production Cypher 2-hop)
# ---------------------------------------------------------------------------
async def ppr_uniform(
    neo4j: Neo4jClient,
    group_id: str,
    seed_ids: List[str],
    top_k: int = 20,
) -> List[Tuple[str, float]]:
    records = await neo4j.run("""
        UNWIND $seed_ids AS seed_id
        MATCH (seed {id: seed_id})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)

        WITH seed, $group_id AS group_id

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
        UNWIND (hop1 + [seed]) AS hop1_node

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
# Ground truth (same as experiment_ppr_variants.py)
# ---------------------------------------------------------------------------
async def get_ground_truth_entities(neo4j: Neo4jClient, group_id: str) -> Dict[str, Set[str]]:
    doc_map_records = await neo4j.run("""
        MATCH (c)
        WHERE (c:Chunk OR c:TextChunk OR c:`__Node__`)
          AND c.group_id = $group_id
          AND c.chunk_index = 0
        RETURN c.document_id AS doc_id, left(toLower(c.text), 200) AS preview
    """, group_id=group_id)
    
    doc_labels: Dict[str, str] = {}
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
    
    label_to_docs: Dict[str, List[str]] = {}
    for doc_id, label in doc_labels.items():
        label_to_docs.setdefault(label, []).append(doc_id)
    
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


def coverage_score(retrieved: List[str], ground_truth: Set[str]) -> float:
    if not ground_truth:
        return 0.0
    return len(set(retrieved) & ground_truth) / len(ground_truth)


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------
async def run_experiment(top_k: int = 20, filter_qid: Optional[str] = None, sim_threshold: float = 0.75):
    print("=" * 78)
    print("DECOMPOSITION × RESOLUTION EXPERIMENT (2×2 matrix)")
    print("  F)  Direct NER  + old resolution (substring + no-threshold vector)")
    print("  Fs) Direct NER  + semantic resolution (vector-first, threshold)")
    print("  G)  Decompose   + old resolution")
    print("  Gs) Decompose   + semantic resolution  ← hypothesis: best combo")
    print("=" * 78)
    print(f"  Neo4j: {NEO4J_URI}")
    print(f"  Group: {GROUP_ID}")
    print(f"  LLM:   {AZURE_OPENAI_NER_DEPLOYMENT}")
    print(f"  Top-K: {top_k}")
    print(f"  Semantic threshold: {sim_threshold}")
    print()
    
    neo4j = Neo4jClient(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
    embedder = VoyageEmbedder(VOYAGE_API_KEY)
    
    try:
        test = await neo4j.run("""
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
            RETURN count(e) AS cnt
        """, group_id=GROUP_ID)
        print(f"  Entities in graph: {test[0]['cnt']}")
        
        print("\n  Building ground truth...")
        gt = await get_ground_truth_entities(neo4j, GROUP_ID)
        for qid, ents in sorted(gt.items()):
            print(f"    {qid}: {len(ents)} entities in source docs")
        
        questions = BENCHMARK_QUESTIONS
        if filter_qid:
            questions = [q for q in questions if q["qid"] == filter_qid]
            if not questions:
                print(f"  ERROR: No question matches '{filter_qid}'")
                return
        
        results: List[Dict] = []
        
        print("\n" + "=" * 78)
        print("RUNNING EXPERIMENTS")
        print("=" * 78)
        
        for q in questions:
            qid = q["qid"]
            query = q["query"]
            
            print(f"\n{'─' * 78}")
            print(f"  {qid}: {query[:65]}...")
            
            # ==============================================================
            # Step 1: LLM NER on original query (shared by F/Fs)
            # ==============================================================
            ner_direct = await llm_ner_extract(query, top_k=5)
            print(f"\n  Direct NER: {ner_direct}")
            
            # ==============================================================
            # Step 2: Decompose + sub-Q NER (shared by G/Gs)
            # ==============================================================
            sub_questions = await drift_decompose(query)
            print(f"  Decompose → {len(sub_questions)} sub-Qs:")
            for i, sq in enumerate(sub_questions, 1):
                print(f"    SQ{i}: {sq[:72]}...")
            
            sq_ner_all: List[List[str]] = []
            for sq in sub_questions:
                sq_ner = await llm_ner_extract(sq, top_k=5)
                sq_ner_all.append(sq_ner)
                print(f"    NER(SQ): {sq_ner}")
            
            # Build union NER list
            seen_lower: set = set()
            union_ner: List[str] = []
            for e in ner_direct:
                k = e.lower()
                if k not in seen_lower:
                    seen_lower.add(k)
                    union_ner.append(e)
            for sq_ner in sq_ner_all:
                for e in sq_ner:
                    k = e.lower()
                    if k not in seen_lower:
                        seen_lower.add(k)
                        union_ner.append(e)
            
            print(f"  Union NER ({len(union_ner)}): {union_ner}")
            
            # ==============================================================
            # Step 3: Resolve seeds under 4 variants
            # ==============================================================
            # F: direct NER + old resolution
            res_f = dedup_resolved(await resolve_entities(neo4j, GROUP_ID, ner_direct, embedder))
            # Fs: direct NER + semantic resolution
            res_fs = dedup_resolved(await resolve_entities_semantic(neo4j, GROUP_ID, ner_direct, embedder, sim_threshold))
            # G: union NER + old resolution
            res_g = dedup_resolved(await resolve_entities(neo4j, GROUP_ID, union_ner, embedder))
            # Gs: union NER + semantic resolution
            res_gs = dedup_resolved(await resolve_entities_semantic(neo4j, GROUP_ID, union_ner, embedder, sim_threshold))
            
            seeds = {
                "F":  ([r["id"] for r in res_f],  [r["name"] for r in res_f]),
                "Fs": ([r["id"] for r in res_fs], [r["name"] for r in res_fs]),
                "G":  ([r["id"] for r in res_g],  [r["name"] for r in res_g]),
                "Gs": ([r["id"] for r in res_gs], [r["name"] for r in res_gs]),
            }
            
            print(f"\n  Resolved seeds:")
            for label, (ids, names) in seeds.items():
                print(f"    {label:>3}: {names}")
            
            # ==============================================================
            # Step 4: Run PPR for each variant
            # ==============================================================
            ppr_results = {}
            for label, (ids, names) in seeds.items():
                if ids:
                    ppr_results[label] = await ppr_uniform(neo4j, GROUP_ID, ids, top_k=top_k)
                else:
                    ppr_results[label] = []
            
            # ==============================================================
            # Step 5: Metrics
            # ==============================================================
            gt_entities = gt.get(qid, set())
            
            coverages = {}
            for label in ["F", "Fs", "G", "Gs"]:
                names_list = [n for n, _ in ppr_results[label]]
                coverages[label] = coverage_score(names_list, gt_entities)
            
            print(f"\n  {'Variant':<40} {'Coverage':>10} {'Seeds':>6}")
            print(f"  {'─' * 60}")
            labels_desc = {
                "F":  "F)  Direct + old resolution",
                "Fs": "Fs) Direct + semantic resolution",
                "G":  "G)  Decompose + old resolution",
                "Gs": "Gs) Decompose + semantic resolution",
            }
            for label in ["F", "Fs", "G", "Gs"]:
                ids, names = seeds[label]
                marker = " ◀ best" if coverages[label] == max(coverages.values()) and coverages[label] > 0 else ""
                print(f"  {labels_desc[label]:<40} {coverages[label]:>10.3f} {len(ids):>6}{marker}")
            
            # Show deltas vs baseline F
            print(f"\n  Deltas vs F:")
            for label in ["Fs", "G", "Gs"]:
                d = coverages[label] - coverages["F"]
                print(f"    {label:>3} − F = {d:+.3f}")
            
            results.append({
                "qid": qid,
                "query": query,
                "ner_direct": ner_direct,
                "sub_questions": sub_questions,
                "sq_ner": sq_ner_all,
                "union_ner": union_ner,
                "seeds_F":  seeds["F"][1],
                "seeds_Fs": seeds["Fs"][1],
                "seeds_G":  seeds["G"][1],
                "seeds_Gs": seeds["Gs"][1],
                "coverage_F":  coverages["F"],
                "coverage_Fs": coverages["Fs"],
                "coverage_G":  coverages["G"],
                "coverage_Gs": coverages["Gs"],
                "num_seeds_F":  len(seeds["F"][0]),
                "num_seeds_Fs": len(seeds["Fs"][0]),
                "num_seeds_G":  len(seeds["G"][0]),
                "num_seeds_Gs": len(seeds["Gs"][0]),
                "top20_F":  [n for n, _ in ppr_results["F"][:20]],
                "top20_Fs": [n for n, _ in ppr_results["Fs"][:20]],
                "top20_G":  [n for n, _ in ppr_results["G"][:20]],
                "top20_Gs": [n for n, _ in ppr_results["Gs"][:20]],
            })
        
        # ===================================================================
        # Summary
        # ===================================================================
        print("\n" + "=" * 78)
        print("SUMMARY")
        print("=" * 78)
        
        if results:
            variants = ["F", "Fs", "G", "Gs"]
            avg_cov = {v: np.mean([r[f"coverage_{v}"] for r in results]) for v in variants}
            avg_seeds = {v: np.mean([r[f"num_seeds_{v}"] for r in results]) for v in variants}
            
            print(f"\n  {'Variant':<40} {'Avg Cov':>8} {'Avg Seeds':>10}")
            print(f"  {'─' * 62}")
            for v in variants:
                print(f"  {labels_desc[v]:<40} {avg_cov[v]:>8.3f} {avg_seeds[v]:>10.1f}")
            
            # Per-question table
            print(f"\n  Per-question coverage:")
            print(f"  {'QID':<8} {'F':>8} {'Fs':>8} {'G':>8} {'Gs':>8}  {'Fs−F':>6} {'Gs−F':>6}")
            print(f"  {'─' * 62}")
            for r in results:
                d_fs = r["coverage_Fs"] - r["coverage_F"]
                d_gs = r["coverage_Gs"] - r["coverage_F"]
                print(f"  {r['qid']:<8} {r['coverage_F']:>8.3f} {r['coverage_Fs']:>8.3f} "
                      f"{r['coverage_G']:>8.3f} {r['coverage_Gs']:>8.3f}  "
                      f"{d_fs:>+6.3f} {d_gs:>+6.3f}")
            
            # Verdict tables
            for comp_label, comp_key in [("Fs vs F", "Fs"), ("Gs vs F", "Gs"), ("Gs vs G", "Gs")]:
                base = "F" if "vs F" in comp_label else "G"
                test = comp_key
                wins = sum(1 for r in results if r[f"coverage_{test}"] > r[f"coverage_{base}"])
                ties = sum(1 for r in results if r[f"coverage_{test}"] == r[f"coverage_{base}"])
                losses = sum(1 for r in results if r[f"coverage_{test}"] < r[f"coverage_{base}"])
                delta = avg_cov[test] - avg_cov[base]
                print(f"\n  {comp_label}: {wins}W / {ties}T / {losses}L, avg delta = {delta:+.3f}")
        
        # Save results
        out_path = Path(f"experiment_decomposition_{time.strftime('%Y%m%dT%H%M%SZ')}.json")
        with open(out_path, "w") as f:
            json.dump({
                "top_k": top_k, "group_id": GROUP_ID,
                "sim_threshold": sim_threshold,
                "results": results,
            }, f, indent=2)
        print(f"\n  Results saved to {out_path}")
        
    finally:
        await neo4j.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decomposition × Resolution Experiment")
    parser.add_argument("--top-k", type=int, default=20, help="Top-K entities per variant")
    parser.add_argument("--filter-qid", type=str, default=None, help="Run only this QID")
    parser.add_argument("--sim-threshold", type=float, default=0.75, help="Semantic similarity threshold")
    args = parser.parse_args()
    
    asyncio.run(run_experiment(top_k=args.top_k, filter_qid=args.filter_qid, sim_threshold=args.sim_threshold))
