"""
Route 5: Multi-Tier Seed Resolver for Unified HippoRAG PPR.

Orchestrates three seed tiers in parallel:
  Tier 1 — Entity seeds (NER on original query)
  Tier 2 — Structural seeds (derived bottom-up from sentence search results)
  Tier 3 — Thematic seeds (community entity resolution)

Each tier is weighted via a *weight profile* that the router selects.
The resolver emits a ``Dict[str, float]`` mapping entity IDs → PPR
teleportation weights.  A single PPR pass then handles both "global"
and "local" retrieval depending on the weight distribution.

Design principles (from ARCHITECTURE_ROUTE5_UNIFIED_HIPPORAG_2026-02-16):
  • Section nodes have two embeddings:
    - Section.embedding: content-rich (title + path + chunk samples) for SEMANTICALLY_SIMILAR edges.
    - Section.structural_embedding: structure-only (title + path_key) for Source 2 header matching.
  • Structural seeds use Section.structural_embedding for semantic header matching.
  • Weight redistribution when a tier returns empty results.
  • Dynamic damping: 0.70 + 0.20 × w₁ (entity weight).
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.worker.services.async_neo4j_service import AsyncNeo4jService
    from ..pipeline.community_matcher import CommunityMatcher

logger = structlog.get_logger(__name__)


# =========================================================================
# Weight Profiles
# =========================================================================

@dataclass(frozen=True)
class WeightProfile:
    """Immutable seed weight distribution across the three tiers."""

    w1: float  # Entity (NER)
    w2: float  # Structural (section-derived)
    w3: float  # Thematic (community)
    label: str = "custom"

    def __post_init__(self):
        total = self.w1 + self.w2 + self.w3
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.3f} "
                f"(w1={self.w1}, w2={self.w2}, w3={self.w3})"
            )


# Pre-defined profiles — router picks one based on query classification.
WEIGHT_PROFILES: Dict[str, WeightProfile] = {
    "fact_extraction": WeightProfile(w1=0.6, w2=0.3, w3=0.1, label="fact_extraction"),
    "clause_analysis": WeightProfile(w1=0.3, w2=0.5, w3=0.2, label="clause_analysis"),
    "cross_doc_comparison": WeightProfile(w1=0.2, w2=0.3, w3=0.5, label="cross_doc_comparison"),
    "thematic_survey": WeightProfile(w1=0.1, w2=0.2, w3=0.7, label="thematic_survey"),
    "multi_hop": WeightProfile(w1=0.5, w2=0.3, w3=0.2, label="multi_hop"),
    # Default balanced profile
    "balanced": WeightProfile(w1=0.5, w2=0.3, w3=0.2, label="balanced"),
}

DEFAULT_PROFILE = WEIGHT_PROFILES["balanced"]


# =========================================================================
# Tier 2: Structural Seed Derivation (bottom-up)
# =========================================================================

def derive_structural_seeds(
    sentence_evidence: List[Dict[str, Any]],
    min_sentences: int = 2,
) -> List[str]:
    """Derive section-level seeds from sentence search results.

    Instead of embedding section titles (noise-prone), aggregate sentence
    search results by ``section_path``.  Sections with ≥ ``min_sentences``
    matching sentences are treated as structural anchors.

    Returns:
        List of ``section_path`` strings that qualify as anchors.
    """
    section_scores: Dict[str, float] = defaultdict(float)
    section_counts: Dict[str, int] = defaultdict(int)

    for ev in sentence_evidence:
        sp = ev.get("section_path", "")
        if sp:
            section_scores[sp] += ev.get("score", 0)
            section_counts[sp] += 1

    # Sections with multiple matching sentences are structural anchors
    structural_seeds = sorted(
        [
            section
            for section, count in section_counts.items()
            if count >= min_sentences
        ],
        key=lambda s: section_scores[s],
        reverse=True,
    )

    logger.info(
        "structural_seeds_derived",
        total_sections=len(section_counts),
        qualifying_sections=len(structural_seeds),
        top_sections=structural_seeds[:5],
    )
    return structural_seeds


async def resolve_section_entities(
    async_neo4j: "AsyncNeo4jService",
    section_paths: List[str],
    group_id: str,
    max_entities_per_section: int = 10,
    folder_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find entities mentioned in text chunks belonging to matched sections.

    Traversal: Section ← IN_SECTION ← TextChunk → MENTIONS → Entity

    Returns:
        List of dicts with ``id``, ``name``, ``section_path`` keys.
    """
    if not section_paths:
        return []

    folder_filter = ""
    folder_params: Dict[str, Any] = {}
    if folder_id is not None:
        folder_filter = (
            "AND EXISTS { "
            "  MATCH (chunk)-[:PART_OF]->(doc2:Document)-[:IN_FOLDER]->(f:Folder) "
            "  WHERE f.id = $folder_id AND f.group_id = $group_id "
            "} "
        )
        folder_params["folder_id"] = folder_id

    cypher = f"""
    UNWIND $paths AS path
    MATCH (s:Section {{group_id: $group_id}})
    WHERE s.title = path
       OR path CONTAINS s.title
       OR s.title CONTAINS path

    WITH s, path
    MATCH (chunk)-[:IN_SECTION]->(s)
    WHERE chunk.group_id = $group_id
      AND (chunk:Chunk OR chunk:TextChunk OR chunk:`__Node__`)
      {folder_filter}

    MATCH (chunk)-[:MENTIONS]->(e)
    WHERE e.group_id = $group_id
      AND (e:Entity OR e:`__Entity__`)

    WITH path, e, count(chunk) AS mention_count
    ORDER BY mention_count DESC

    WITH path, collect({{id: e.id, name: e.name, mentions: mention_count}})[..{max_entities_per_section}] AS top_entities
    UNWIND top_entities AS te
    RETURN DISTINCT te.id AS id, te.name AS name, path AS section_path
    """

    try:
        async with async_neo4j._get_session() as session:
            result = await session.run(
                cypher,
                paths=section_paths,
                group_id=group_id,
                **folder_params,
            )
            records = await result.data()

        logger.info(
            "section_entities_resolved",
            sections_queried=len(section_paths),
            entities_found=len(records),
        )
        return records

    except Exception as e:
        logger.warning("section_entity_resolution_failed", error=str(e))
        return []


# =========================================================================
# Tier 3: Thematic Seed Resolution (community → entities)
# =========================================================================

async def resolve_thematic_seeds(
    community_matcher: "CommunityMatcher",
    async_neo4j: "AsyncNeo4jService",
    query: str,
    group_id: str,
    top_k_communities: int = 5,
    max_entities_per_community: int = 5,
    folder_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve thematic (community) seeds to entity node IDs.

    Steps:
      1. Community embedding match → top-K communities
      2. Community → BELONGS_TO → Entity (or HUB_ENTITY) resolution

    Returns:
        Tuple of (entity_records, matched_community_data).
        entity_records: List[{id, name, community}]
        matched_community_data: raw community dicts for optional synthesis context
    """
    # Step 1: Community match
    try:
        matched = await community_matcher.match_communities(
            query, top_k=top_k_communities,
        )
    except Exception as e:
        logger.warning("thematic_community_match_failed", error=str(e))
        return [], []

    community_data = [c for c, _ in matched]
    community_scores = [s for _, s in matched]

    if not community_data:
        logger.info("thematic_no_communities_matched")
        return [], []

    # Step 2: Resolve community → entities via Neo4j
    # Communities have ids; entities BELONGS_TO communities
    community_ids = [c.get("id", c.get("community_id", "")) for c in community_data]
    community_ids = [cid for cid in community_ids if cid]

    entity_records: List[Dict[str, Any]] = []

    if community_ids and async_neo4j:
        try:
            folder_filter = ""
            folder_params: Dict[str, Any] = {}
            if folder_id is not None:
                folder_filter = (
                    "AND EXISTS { "
                    "  MATCH (chunk2)-[:MENTIONS]->(e) "
                    "  WHERE (chunk2:Chunk OR chunk2:TextChunk) "
                    "  MATCH (chunk2)-[:PART_OF]->(doc2:Document)-[:IN_FOLDER]->(f:Folder) "
                    "  WHERE f.id = $folder_id AND f.group_id = $group_id "
                    "} "
                )
                folder_params["folder_id"] = folder_id

            cypher = f"""
            UNWIND $community_ids AS cid
            MATCH (c:Community {{group_id: $group_id}})
            WHERE c.id = cid OR c.community_id = cid

            MATCH (e)-[:BELONGS_TO]->(c)
            WHERE e.group_id = $group_id
              AND (e:Entity OR e:`__Entity__`)
              {folder_filter}

            WITH c, e
            ORDER BY coalesce(e.degree, 0) DESC
            WITH c, collect({{id: e.id, name: e.name}})[..{max_entities_per_community}] AS top_entities

            UNWIND top_entities AS te
            RETURN DISTINCT te.id AS id, te.name AS name,
                   c.id AS community_id
            """

            async with async_neo4j._get_session() as session:
                result = await session.run(
                    cypher,
                    community_ids=community_ids,
                    group_id=group_id,
                    **folder_params,
                )
                entity_records = await result.data()

        except Exception as e:
            logger.warning("thematic_entity_resolution_failed", error=str(e))

    logger.info(
        "thematic_seeds_resolved",
        communities_matched=len(community_data),
        top_scores=[round(s, 4) for s in community_scores[:3]],
        entities_resolved=len(entity_records),
    )

    return entity_records, community_data


# =========================================================================
# Unified Seed Builder
# =========================================================================

def build_unified_seeds(
    entity_seeds: List[str],
    structural_entity_ids: List[str],
    thematic_entity_ids: List[str],
    profile: WeightProfile,
) -> Dict[str, float]:
    """Build weighted seed dictionary for PPR teleportation vector.

    Each entity ID is assigned a per-seed weight = tier_weight / tier_size.
    Entities appearing in multiple tiers accumulate weight.
    The resulting dict sums to 1.0 (valid probability distribution for PPR).

    Args:
        entity_seeds: Entity IDs from Tier 1 (NER resolution).
        structural_entity_ids: Entity IDs from Tier 2 (section-derived).
        thematic_entity_ids: Entity IDs from Tier 3 (community-derived).
        profile: Weight profile specifying w1/w2/w3.

    Returns:
        Dict mapping entity_id → teleportation weight.
    """
    # Determine effective weights with redistribution
    w1, w2, w3 = profile.w1, profile.w2, profile.w3

    # Redistribute from empty tiers
    if not structural_entity_ids and not thematic_entity_ids:
        # Only Tier 1 available
        w1 = 1.0
        w2 = w3 = 0.0
    elif not structural_entity_ids:
        # Redistribute w2 to w3
        w3 = w3 + w2
        w2 = 0.0
    elif not thematic_entity_ids:
        # Redistribute w3 proportionally to w1 and w2
        ratio = w1 / (w1 + w2) if (w1 + w2) > 0 else 0.5
        w1 = w1 + w3 * ratio
        w2 = w2 + w3 * (1 - ratio)
        w3 = 0.0

    if not entity_seeds and not structural_entity_ids and not thematic_entity_ids:
        logger.warning("unified_seeds_all_tiers_empty")
        return {}

    # Handle empty Tier 1 — redistribute to remaining tiers
    if not entity_seeds:
        if structural_entity_ids and thematic_entity_ids:
            ratio = w2 / (w2 + w3) if (w2 + w3) > 0 else 0.5
            w2 = w2 + w1 * ratio
            w3 = w3 + w1 * (1 - ratio)
        elif structural_entity_ids:
            w2 = w2 + w1
        else:
            w3 = w3 + w1
        w1 = 0.0

    seeds: Dict[str, float] = {}

    # Tier 1: Entity seeds
    if entity_seeds and w1 > 0:
        per_seed = w1 / len(entity_seeds)
        for eid in entity_seeds:
            seeds[eid] = seeds.get(eid, 0) + per_seed

    # Tier 2: Structural entity seeds
    if structural_entity_ids and w2 > 0:
        per_seed = w2 / len(structural_entity_ids)
        for eid in structural_entity_ids:
            seeds[eid] = seeds.get(eid, 0) + per_seed

    # Tier 3: Thematic entity seeds
    if thematic_entity_ids and w3 > 0:
        per_seed = w3 / len(thematic_entity_ids)
        for eid in thematic_entity_ids:
            seeds[eid] = seeds.get(eid, 0) + per_seed

    # Normalize to sum = 1.0
    total = sum(seeds.values())
    if total > 0:
        seeds = {k: v / total for k, v in seeds.items()}

    logger.info(
        "unified_seeds_built",
        tier1_count=len(entity_seeds),
        tier2_count=len(structural_entity_ids),
        tier3_count=len(thematic_entity_ids),
        effective_weights=f"w1={w1:.2f} w2={w2:.2f} w3={w3:.2f}",
        unique_seeds=len(seeds),
        profile=profile.label,
    )

    return seeds


def compute_dynamic_damping(profile: WeightProfile) -> float:
    """Compute PPR damping factor from weight profile.

    Higher entity weight (w1) → higher damping → tighter around seeds.
    Higher thematic weight (w3) → lower damping → broader exploration.

    Range: 0.72 (global) to 0.90 (local).
    """
    return round(0.70 + 0.20 * profile.w1, 4)


# =========================================================================
# Full Multi-Tier Resolution Orchestrator
# =========================================================================

async def resolve_all_tiers(
    query: str,
    sentence_evidence: List[Dict[str, Any]],
    async_neo4j: "AsyncNeo4jService",
    community_matcher: "CommunityMatcher",
    group_id: str,
    entity_seed_names: List[str],
    profile: WeightProfile = DEFAULT_PROFILE,
    folder_id: Optional[str] = None,
    embed_model: Optional[Any] = None,
) -> Dict[str, Any]:
    """Orchestrate all three seed tiers in parallel and build unified seed dict.

    Returns dict with keys:
        weighted_seeds: Dict[str, float] — the PPR teleportation vector
        damping: float — dynamic damping factor
        tier1_ids: List[str] — resolved Tier 1 entity IDs
        tier2_ids: List[str] — resolved Tier 2 entity IDs
        tier3_ids: List[str] — resolved Tier 3 entity IDs
        profile: WeightProfile — the profile used
        community_data: List[Dict] — matched communities (for optional synthesis context)
        structural_sections: List[str] — section paths used as anchors
    """
    min_sentences = int(os.getenv("ROUTE5_STRUCTURAL_MIN_SENTENCES", "2"))

    # ------------------------------------------------------------------
    # Tier 1: NER → Entity ID resolution  (already have names from caller)
    # ------------------------------------------------------------------
    async def _resolve_tier1() -> List[str]:
        if not entity_seed_names:
            return []
        try:
            result = await async_neo4j.get_entities_by_names(
                group_id=group_id,
                entity_names=entity_seed_names,
                return_unmatched=True,
            )
            if isinstance(result, tuple):
                seed_records, unmatched = result
            else:
                seed_records = result
                unmatched = []

            seed_ids = [r["id"] for r in seed_records]

            # Strategy 6: vector fallback for unmatched seeds
            if unmatched and embed_model:
                for seed in unmatched:
                    try:
                        if hasattr(embed_model, 'get_query_embedding'):
                            embedding = embed_model.get_query_embedding(seed)
                        elif hasattr(embed_model, 'embed_query'):
                            embedding = embed_model.embed_query(seed)
                        else:
                            continue

                        if not embedding:
                            continue

                        index_name = (
                            "entity_embedding_v2"
                            if len(embedding) <= 2048
                            else "entity_embedding"
                        )
                        vector_records = await async_neo4j.get_entities_by_vector_similarity(
                            group_id=group_id,
                            seed_text=seed,
                            seed_embedding=embedding,
                            top_k=3,
                            index_name=index_name,
                        )
                        for rec in vector_records:
                            if rec["id"] not in seed_ids:
                                seed_ids.append(rec["id"])
                    except Exception:
                        continue

            return seed_ids
        except Exception as e:
            logger.warning("tier1_entity_resolution_failed", error=str(e))
            return []

    # ------------------------------------------------------------------
    # Tier 2: Structural seeds (bottom-up from sentence evidence)
    # ------------------------------------------------------------------
    async def _resolve_tier2() -> Tuple[List[str], List[str]]:
        structural_sections = derive_structural_seeds(
            sentence_evidence, min_sentences=min_sentences,
        )
        if not structural_sections:
            return [], []

        records = await resolve_section_entities(
            async_neo4j=async_neo4j,
            section_paths=structural_sections,
            group_id=group_id,
            folder_id=folder_id,
        )
        entity_ids = list({r["id"] for r in records})
        return entity_ids, structural_sections

    # ------------------------------------------------------------------
    # Tier 3: Thematic seeds (community → entities)
    # ------------------------------------------------------------------
    async def _resolve_tier3() -> Tuple[List[str], List[Dict[str, Any]]]:
        entity_records, community_data = await resolve_thematic_seeds(
            community_matcher=community_matcher,
            async_neo4j=async_neo4j,
            query=query,
            group_id=group_id,
            folder_id=folder_id,
        )
        entity_ids = list({r["id"] for r in entity_records})
        return entity_ids, community_data

    # ------------------------------------------------------------------
    # Run Tiers 1, 2, 3 in parallel
    # ------------------------------------------------------------------
    tier1_task = asyncio.create_task(_resolve_tier1())
    tier2_task = asyncio.create_task(_resolve_tier2())
    tier3_task = asyncio.create_task(_resolve_tier3())

    tier1_ids, (tier2_ids, structural_sections), (tier3_ids, community_data) = (
        await asyncio.gather(tier1_task, tier2_task, tier3_task)
    )

    # ------------------------------------------------------------------
    # Build unified weighted seed dict
    # ------------------------------------------------------------------
    weighted_seeds = build_unified_seeds(
        entity_seeds=tier1_ids,
        structural_entity_ids=tier2_ids,
        thematic_entity_ids=tier3_ids,
        profile=profile,
    )

    damping = compute_dynamic_damping(profile)

    logger.info(
        "seed_resolution_complete",
        tier1=len(tier1_ids),
        tier2=len(tier2_ids),
        tier3=len(tier3_ids),
        total_unique_seeds=len(weighted_seeds),
        damping=damping,
        profile=profile.label,
    )

    return {
        "weighted_seeds": weighted_seeds,
        "damping": damping,
        "tier1_ids": tier1_ids,
        "tier2_ids": tier2_ids,
        "tier3_ids": tier3_ids,
        "profile": profile,
        "community_data": community_data,
        "structural_sections": structural_sections,
    }
