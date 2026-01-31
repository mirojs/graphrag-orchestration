"""NLP-based Entity Deduplication using embeddings and rules.

This module provides a **deterministic** post-extraction deduplication pass that:
1. Collects all extracted entities with their embeddings
2. Clusters entities by embedding similarity (cosine > threshold)
3. Applies rule-based alias detection (acronyms, abbreviations)
4. Returns a merge map for entity consolidation

Design Principles:
- **Deterministic**: Same entities + embeddings → same merge decisions
- **Auditable**: Every merge has a reason ("cosine=0.97" or "acronym match")
- **Efficient**: O(n²) pairwise comparisons, but fast numpy operations
- **No LLM calls**: Uses pre-computed embeddings from text-embedding-3-large

This replaces the LLM-based approach for better repeatability in audit-grade systems.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import structlog

logger = structlog.get_logger(__name__)


# Try to use numpy for fast vector operations, fall back to pure Python
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    logger.warning("numpy not available, using pure Python for cosine similarity (slower)")


@dataclass
class EntityMergeResult:
    """Result of entity deduplication analysis."""

    # Maps variant name → canonical name
    # e.g., {"MSFT": "Microsoft", "Microsoft Corporation": "Microsoft"}
    merge_map: Dict[str, str] = field(default_factory=dict)

    # Canonical entities with their variants
    # e.g., {"Microsoft": ["MSFT", "Microsoft Corporation"]}
    canonical_to_variants: Dict[str, List[str]] = field(default_factory=dict)

    # Merge reasons for auditability
    # e.g., {"MSFT": {"reason": "embedding_similarity", "score": 0.97}}
    merge_reasons: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Stats
    total_entities: int = 0
    unique_after_merge: int = 0
    merge_groups: int = 0
    embedding_merges: int = 0
    rule_merges: int = 0


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    if HAS_NUMPY:
        a = np.array(vec1)
        b = np.array(vec2)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    else:
        # Pure Python fallback
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)


def _is_acronym_match(name1: str, name2: str) -> bool:
    """
    Check if one name is an acronym of the other.
    
    Examples:
        - "IBM" ↔ "International Business Machines" → True
        - "MSFT" ↔ "Microsoft" → False (MSFT is stock ticker, not acronym)
        - "UN" ↔ "United Nations" → True
    """
    n1 = name1.strip()
    n2 = name2.strip()
    
    if not n1 or not n2:
        return False
    
    # Identify which might be the acronym (shorter, all caps)
    if len(n1) < len(n2) and n1.isupper() and len(n1) <= 6:
        acronym, full = n1, n2
    elif len(n2) < len(n1) and n2.isupper() and len(n2) <= 6:
        acronym, full = n2, n1
    else:
        return False
    
    # Extract initials from full name
    words = re.findall(r'\b[A-Za-z]+', full)
    if not words:
        return False
    
    # Check if acronym matches initials
    initials = ''.join(w[0].upper() for w in words if w)
    
    return acronym.upper() == initials


def _is_abbreviation_match(name1: str, name2: str) -> bool:
    """
    Check if one name is an abbreviation/variant of the other.
    
    Examples:
        - "Dr. Smith" ↔ "Doctor Smith" → True
        - "J. Smith" ↔ "John Smith" → True (initial match)
        - "Int'l" ↔ "International" → True
    """
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    
    if not n1 or not n2:
        return False
    
    # Common abbreviation mappings
    abbrev_map = {
        "dr": "doctor",
        "mr": "mister",
        "mrs": "missus",
        "ms": "miss",
        "prof": "professor",
        "int'l": "international",
        "intl": "international",
        "corp": "corporation",
        "inc": "incorporated",
        "ltd": "limited",
        "co": "company",
        "dept": "department",
        "gov": "government",
        "govt": "government",
        "mgmt": "management",
        "mgt": "management",
        "assoc": "association",
        "natl": "national",
        "nat'l": "national",
    }
    
    # Expand abbreviations in both names
    def expand(text: str) -> str:
        words = text.split()
        expanded = []
        for w in words:
            w_clean = re.sub(r'[^\w]', '', w.lower())
            expanded.append(abbrev_map.get(w_clean, w_clean))
        return ' '.join(expanded)
    
    exp1 = expand(n1)
    exp2 = expand(n2)
    
    # Check if expanded forms match
    if exp1 == exp2:
        return True
    
    # Check initial match (J. Smith ↔ John Smith)
    words1 = n1.split()
    words2 = n2.split()
    
    if len(words1) == len(words2) and len(words1) >= 2:
        match_count = 0
        for w1, w2 in zip(words1, words2):
            w1_clean = re.sub(r'[^\w]', '', w1.lower())
            w2_clean = re.sub(r'[^\w]', '', w2.lower())
            
            # Exact match
            if w1_clean == w2_clean:
                match_count += 1
            # Initial match (J ↔ John)
            elif len(w1_clean) == 1 and w2_clean.startswith(w1_clean):
                match_count += 1
            elif len(w2_clean) == 1 and w1_clean.startswith(w2_clean):
                match_count += 1
        
        # Most words match
        if match_count >= len(words1) - 1 and match_count >= len(words1) * 0.7:
            return True
    
    return False


def _normalize_for_comparison(name: str) -> str:
    """Normalize entity name for comparison."""
    s = (name or "").strip().lower()
    # Remove punctuation except alphanumeric and spaces
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


class EntityDeduplicationService:
    """Service for NLP-based entity deduplication using embeddings and rules."""

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.95,
        min_entities_for_dedup: int = 10,
        enable_acronym_detection: bool = True,
        enable_abbreviation_detection: bool = True,
    ):
        """
        Initialize the deduplication service.

        Args:
            similarity_threshold: Cosine similarity threshold for merging (0.95 = very conservative)
            min_entities_for_dedup: Skip dedup if fewer entities than this
            enable_acronym_detection: Whether to apply acronym matching rules
            enable_abbreviation_detection: Whether to apply abbreviation matching rules
        """
        self.similarity_threshold = similarity_threshold
        self.min_entities = min_entities_for_dedup
        self.enable_acronyms = enable_acronym_detection
        self.enable_abbreviations = enable_abbreviation_detection

    def deduplicate_entities(
        self,
        entities: List[Dict[str, Any]],
        *,
        group_id: str = "",
    ) -> EntityMergeResult:
        """
        Analyze entities and return merge recommendations.

        Args:
            entities: List of entity dicts with {"name": str, "embedding": List[float], ...}
            group_id: For logging

        Returns:
            EntityMergeResult with merge map and stats
        """
        result = EntityMergeResult(total_entities=len(entities))

        # Skip if too few entities
        if len(entities) < self.min_entities:
            logger.info(
                "entity_dedup_skipped_too_few",
                group_id=group_id,
                entity_count=len(entities),
                threshold=self.min_entities,
            )
            result.unique_after_merge = len(entities)
            return result

        # Build entity list with embeddings
        entity_data: List[Tuple[str, List[float], str]] = []  # (name, embedding, normalized)
        seen_normalized: Set[str] = set()

        for ent in entities:
            name = str(ent.get("name") or "").strip()
            if not name:
                continue
            
            normalized = _normalize_for_comparison(name)
            if normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            
            embedding = ent.get("embedding") or []
            if isinstance(embedding, list) and len(embedding) > 0:
                entity_data.append((name, embedding, normalized))
            else:
                # No embedding - can still use rule-based matching
                entity_data.append((name, [], normalized))

        if len(entity_data) < self.min_entities:
            logger.info(
                "entity_dedup_skipped_unique_below_threshold",
                group_id=group_id,
                unique_count=len(entity_data),
                threshold=self.min_entities,
            )
            result.unique_after_merge = len(entity_data)
            return result

        # Union-Find structure for clustering
        parent: Dict[str, str] = {name: name for name, _, _ in entity_data}
        
        def find(x: str) -> str:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px != py:
                # Always use the shorter/simpler name as canonical
                if len(px) <= len(py):
                    parent[py] = px
                else:
                    parent[px] = py

        merge_reasons: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Pairwise comparisons
        n = len(entity_data)
        logger.info(
            "entity_dedup_starting",
            group_id=group_id,
            entity_count=n,
            comparisons=n * (n - 1) // 2,
        )

        for i in range(n):
            name_i, emb_i, norm_i = entity_data[i]
            
            for j in range(i + 1, n):
                name_j, emb_j, norm_j = entity_data[j]
                
                # Skip if already in same cluster
                if find(name_i) == find(name_j):
                    continue
                
                should_merge = False
                reason: Dict[str, Any] = {}
                
                # 1. Embedding similarity (if both have embeddings)
                if emb_i and emb_j:
                    sim = _cosine_similarity(emb_i, emb_j)
                    if sim >= self.similarity_threshold:
                        should_merge = True
                        reason = {"type": "embedding_similarity", "score": round(sim, 4)}
                        result.embedding_merges += 1
                
                # 2. Rule-based: Acronym detection
                if not should_merge and self.enable_acronyms:
                    if _is_acronym_match(name_i, name_j):
                        should_merge = True
                        reason = {"type": "acronym_match"}
                        result.rule_merges += 1
                
                # 3. Rule-based: Abbreviation detection
                if not should_merge and self.enable_abbreviations:
                    if _is_abbreviation_match(name_i, name_j):
                        should_merge = True
                        reason = {"type": "abbreviation_match"}
                        result.rule_merges += 1
                
                if should_merge:
                    union(name_i, name_j)
                    # Store reason for the pair
                    merge_reasons[(name_i, name_j)] = reason

        # Build result from clusters
        clusters: Dict[str, List[str]] = {}
        for name, _, _ in entity_data:
            canonical = find(name)
            if canonical not in clusters:
                clusters[canonical] = []
            if name != canonical:
                clusters[canonical].append(name)

        # Populate result
        for canonical, variants in clusters.items():
            if not variants:
                continue  # Single-entity cluster, no merge needed
            
            result.merge_groups += 1
            result.canonical_to_variants[canonical] = variants
            
            for variant in variants:
                result.merge_map[variant] = canonical
                # Find the reason for this merge
                for (n1, n2), reason in merge_reasons.items():
                    if (n1 == variant and find(n2) == canonical) or (n2 == variant and find(n1) == canonical):
                        result.merge_reasons[variant] = reason
                        break

        # Calculate unique count after merge
        result.unique_after_merge = len(clusters)

        logger.info(
            "entity_dedup_complete",
            group_id=group_id,
            total_entities=result.total_entities,
            unique_before=len(entity_data),
            unique_after=result.unique_after_merge,
            merge_groups=result.merge_groups,
            entities_merged=len(result.merge_map),
            embedding_merges=result.embedding_merges,
            rule_merges=result.rule_merges,
        )

        return result


def apply_merge_map(
    entities: List[Dict[str, Any]],
    relationships: List[Dict[str, Any]],
    merge_result: EntityMergeResult,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Apply entity merge map to entities and relationships.

    Args:
        entities: Original entity list
        relationships: Original relationship list
        merge_result: Result from deduplicate_entities()

    Returns:
        (merged_entities, updated_relationships)
    """
    merge_map = merge_result.merge_map

    if not merge_map:
        return entities, relationships

    # Merge entities
    seen_canonical: Set[str] = set()
    merged_entities: List[Dict[str, Any]] = []

    for ent in entities:
        name = str(ent.get("name") or "").strip()
        canonical = merge_map.get(name, name)
        canonical_lower = canonical.lower()

        if canonical_lower in seen_canonical:
            # Skip duplicate
            continue

        seen_canonical.add(canonical_lower)

        # Update entity with canonical name
        merged_ent = dict(ent)
        if name != canonical:
            merged_ent["name"] = canonical
            merged_ent["original_names"] = merged_ent.get("original_names", []) + [name]
            # Add merge reason for auditability
            if name in merge_result.merge_reasons:
                merged_ent["merge_reason"] = merge_result.merge_reasons[name]

        merged_entities.append(merged_ent)

    # Update relationships to use canonical names
    updated_rels: List[Dict[str, Any]] = []
    seen_rels: Set[str] = set()

    for rel in relationships:
        source = str(rel.get("source") or rel.get("source_id") or "").strip()
        target = str(rel.get("target") or rel.get("target_id") or "").strip()

        # Map to canonical names
        canonical_source = merge_map.get(source, source)
        canonical_target = merge_map.get(target, target)

        # Create updated relationship
        updated_rel = dict(rel)
        if "source" in rel:
            updated_rel["source"] = canonical_source
        if "source_id" in rel:
            updated_rel["source_id"] = canonical_source
        if "target" in rel:
            updated_rel["target"] = canonical_target
        if "target_id" in rel:
            updated_rel["target_id"] = canonical_target

        # Dedupe relationships (same source/target/type)
        rel_type = str(rel.get("type") or rel.get("label") or "RELATED_TO")
        rel_key = f"{canonical_source.lower()}|{rel_type}|{canonical_target.lower()}"

        if rel_key not in seen_rels:
            seen_rels.add(rel_key)
            updated_rels.append(updated_rel)

    return merged_entities, updated_rels


# Convenience function for quick deduplication
def deduplicate_entities_quick(
    entities: List[Dict[str, Any]],
    *,
    similarity_threshold: float = 0.95,
    group_id: str = "",
) -> EntityMergeResult:
    """
    Quick entity deduplication with default settings.
    
    Args:
        entities: List of entity dicts with {"name": str, "embedding": List[float], ...}
        similarity_threshold: Cosine similarity threshold (default 0.95 = conservative)
        group_id: For logging
    
    Returns:
        EntityMergeResult
    """
    service = EntityDeduplicationService(similarity_threshold=similarity_threshold)
    return service.deduplicate_entities(entities, group_id=group_id)
