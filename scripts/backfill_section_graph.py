#!/usr/bin/env python3
"""Backfill Section graph for existing TextChunks.

This script materializes Section nodes and relationships from the section_path
metadata stored in TextChunk nodes. It's designed for small corpora (dev stage)
where a full re-index is acceptable but a quick backfill is preferred.

Usage:
    python scripts/backfill_section_graph.py --group-id <group_id> [--dry-run]

Environment variables:
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE (optional)

What it creates:
    - (:Section) nodes with id, group_id, doc_id, path_key, title, depth
    - (:Document)-[:HAS_SECTION]->(:Section) for top-level sections
    - (:Section)-[:SUBSECTION_OF]->(:Section) for parent-child hierarchy
    - (:TextChunk)-[:IN_SECTION]->(:Section) for leaf section linkage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Default fallback for chunks without section metadata
DEFAULT_ROOT_SECTION = "[Document Root]"


@dataclass
class SectionInfo:
    """Represents a section to be created."""
    id: str
    group_id: str
    doc_id: str
    path_key: str
    title: str
    depth: int
    parent_path_key: Optional[str] = None


def stable_section_id(group_id: str, doc_id: str, path_key: str) -> str:
    """Generate a stable hash-based section ID."""
    h = hashlib.sha256()
    h.update(group_id.encode("utf-8", errors="ignore"))
    h.update(b"\n")
    h.update(doc_id.encode("utf-8", errors="ignore"))
    h.update(b"\n")
    h.update(path_key.encode("utf-8", errors="ignore"))
    return f"section_{h.hexdigest()[:12]}"


def parse_section_path(metadata: Dict[str, Any]) -> List[str]:
    """Extract section path from chunk metadata.
    
    Handles multiple formats:
    - section_path: List[str] (preferred)
    - di_section_path: str (fallback, may be " > " joined)
    - di_section_part: str (fallback, single section name)
    """
    # Preferred: section_path as list
    section_path = metadata.get("section_path")
    if isinstance(section_path, list) and section_path:
        return [str(s).strip() for s in section_path if str(s).strip()]
    
    # Fallback: di_section_path as string (may be " > " joined)
    di_section_path = metadata.get("di_section_path")
    if isinstance(di_section_path, str) and di_section_path.strip():
        # Split on " > " if present, otherwise treat as single section
        if " > " in di_section_path:
            return [s.strip() for s in di_section_path.split(" > ") if s.strip()]
        return [di_section_path.strip()]
    
    # Fallback: di_section_part as single section
    di_section_part = metadata.get("di_section_part")
    if isinstance(di_section_part, str) and di_section_part.strip():
        return [di_section_part.strip()]
    
    return []


def build_section_hierarchy(
    group_id: str,
    doc_id: str,
    section_path: List[str],
) -> List[SectionInfo]:
    """Build all sections in a hierarchy from a section path.
    
    For path ["A", "B", "C"], creates:
    - Section(path_key="A", depth=0, parent=None)
    - Section(path_key="A > B", depth=1, parent="A")
    - Section(path_key="A > B > C", depth=2, parent="A > B")
    """
    sections: List[SectionInfo] = []
    
    for depth, title in enumerate(section_path):
        path_key = " > ".join(section_path[: depth + 1])
        parent_path_key = " > ".join(section_path[:depth]) if depth > 0 else None
        
        sections.append(
            SectionInfo(
                id=stable_section_id(group_id, doc_id, path_key),
                group_id=group_id,
                doc_id=doc_id,
                path_key=path_key,
                title=title,
                depth=depth,
                parent_path_key=parent_path_key,
            )
        )
    
    return sections


def backfill_section_graph(
    uri: str,
    username: str,
    password: str,
    database: str,
    group_id: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Main backfill logic."""
    
    driver = GraphDatabase.driver(uri, auth=(username, password))
    stats = {
        "chunks_processed": 0,
        "chunks_with_section": 0,
        "chunks_without_section": 0,
        "sections_created": 0,
        "has_section_edges": 0,
        "subsection_of_edges": 0,
        "in_section_edges": 0,
        "errors": [],
    }
    
    try:
        with driver.session(database=database) as session:
            # Step 1: Fetch all TextChunks with their Document
            logger.info(f"Fetching TextChunks for group_id={group_id}...")
            result = session.run(
                """
                MATCH (t:TextChunk {group_id: $group_id})
                OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
                RETURN t.id AS chunk_id, t.metadata AS metadata, d.id AS doc_id
                """,
                group_id=group_id,
            )
            
            chunks: List[Tuple[str, str, Dict[str, Any]]] = []
            for record in result:
                chunk_id = record["chunk_id"]
                doc_id = record["doc_id"] or "unknown_doc"
                raw_metadata = record["metadata"]
                
                # Parse metadata (stored as JSON string)
                if isinstance(raw_metadata, str):
                    try:
                        metadata = json.loads(raw_metadata)
                    except json.JSONDecodeError:
                        metadata = {}
                elif isinstance(raw_metadata, dict):
                    metadata = raw_metadata
                else:
                    metadata = {}
                
                chunks.append((chunk_id, doc_id, metadata))
            
            stats["chunks_processed"] = len(chunks)
            logger.info(f"Found {len(chunks)} TextChunks")
            
            if not chunks:
                logger.warning("No chunks found, nothing to backfill")
                return stats
            
            # Step 2: Collect all unique sections across all chunks
            all_sections: Dict[Tuple[str, str], SectionInfo] = {}  # keyed by (doc_id, path_key)
            chunk_to_leaf_section: Dict[str, str] = {}  # chunk_id -> section_id
            
            for chunk_id, doc_id, metadata in chunks:
                section_path = parse_section_path(metadata)
                
                if not section_path:
                    # Use fallback root section
                    section_path = [DEFAULT_ROOT_SECTION]
                    stats["chunks_without_section"] += 1
                else:
                    stats["chunks_with_section"] += 1
                
                # Build hierarchy
                section_infos = build_section_hierarchy(group_id, doc_id, section_path)
                
                for si in section_infos:
                    key = (si.doc_id, si.path_key)
                    if key not in all_sections:
                        all_sections[key] = si
                
                # Map chunk to its leaf section
                if section_infos:
                    chunk_to_leaf_section[chunk_id] = section_infos[-1].id
            
            logger.info(
                f"Sections to create: {len(all_sections)}, "
                f"Chunks with section: {stats['chunks_with_section']}, "
                f"Chunks without (using fallback): {stats['chunks_without_section']}"
            )
            
            if dry_run:
                logger.info("[DRY RUN] Would create the following sections:")
                for (doc_id, path_key), si in list(all_sections.items())[:10]:
                    logger.info(f"  - {doc_id}: {path_key} (depth={si.depth})")
                if len(all_sections) > 10:
                    logger.info(f"  ... and {len(all_sections) - 10} more")
                return stats
            
            # Step 3: Create Section nodes
            logger.info("Creating Section nodes...")
            section_data = [
                {
                    "id": si.id,
                    "group_id": si.group_id,
                    "doc_id": si.doc_id,
                    "path_key": si.path_key,
                    "title": si.title,
                    "depth": si.depth,
                }
                for si in all_sections.values()
            ]
            
            result = session.run(
                """
                UNWIND $sections AS s
                MERGE (sec:Section {id: s.id})
                SET sec.group_id = s.group_id,
                    sec.doc_id = s.doc_id,
                    sec.path_key = s.path_key,
                    sec.title = s.title,
                    sec.depth = s.depth,
                    sec.updated_at = datetime()
                RETURN count(sec) AS count
                """,
                sections=section_data,
            )
            record = result.single()
            stats["sections_created"] = record["count"] if record else 0
            logger.info(f"Created/updated {stats['sections_created']} Section nodes")
            
            # Step 4: Create HAS_SECTION edges (Document -> top-level Section)
            logger.info("Creating HAS_SECTION edges...")
            top_level_sections = [
                {"doc_id": si.doc_id, "section_id": si.id}
                for si in all_sections.values()
                if si.depth == 0
            ]
            
            result = session.run(
                """
                UNWIND $edges AS e
                MATCH (d:Document {id: e.doc_id, group_id: $group_id})
                MATCH (s:Section {id: e.section_id})
                MERGE (d)-[:HAS_SECTION]->(s)
                RETURN count(*) AS count
                """,
                edges=top_level_sections,
                group_id=group_id,
            )
            record = result.single()
            stats["has_section_edges"] = record["count"] if record else 0
            logger.info(f"Created {stats['has_section_edges']} HAS_SECTION edges")
            
            # Step 5: Create SUBSECTION_OF edges (child -> parent)
            logger.info("Creating SUBSECTION_OF edges...")
            subsection_edges = []
            for si in all_sections.values():
                if si.parent_path_key:
                    parent_key = (si.doc_id, si.parent_path_key)
                    parent_si = all_sections.get(parent_key)
                    if parent_si:
                        subsection_edges.append({
                            "child_id": si.id,
                            "parent_id": parent_si.id,
                        })
            
            if subsection_edges:
                result = session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (child:Section {id: e.child_id})
                    MATCH (parent:Section {id: e.parent_id})
                    MERGE (child)-[:SUBSECTION_OF]->(parent)
                    RETURN count(*) AS count
                    """,
                    edges=subsection_edges,
                )
                record = result.single()
                stats["subsection_of_edges"] = record["count"] if record else 0
            logger.info(f"Created {stats['subsection_of_edges']} SUBSECTION_OF edges")
            
            # Step 6: Create IN_SECTION edges (TextChunk -> leaf Section)
            logger.info("Creating IN_SECTION edges...")
            in_section_edges = [
                {"chunk_id": chunk_id, "section_id": section_id}
                for chunk_id, section_id in chunk_to_leaf_section.items()
            ]
            
            # Batch in groups of 1000 to avoid memory issues
            batch_size = 1000
            total_in_section = 0
            for i in range(0, len(in_section_edges), batch_size):
                batch = in_section_edges[i : i + batch_size]
                result = session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (t:TextChunk {id: e.chunk_id})
                    MATCH (s:Section {id: e.section_id})
                    MERGE (t)-[:IN_SECTION]->(s)
                    RETURN count(*) AS count
                    """,
                    edges=batch,
                )
                record = result.single()
                total_in_section += record["count"] if record else 0
            
            stats["in_section_edges"] = total_in_section
            logger.info(f"Created {stats['in_section_edges']} IN_SECTION edges")
            
    finally:
        driver.close()
    
    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill Section graph for existing TextChunks")
    parser.add_argument("--group-id", required=True, help="Group ID to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"), help="Neo4j URI")
    parser.add_argument("--username", default=os.getenv("NEO4J_USERNAME", "neo4j"), help="Neo4j username")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""), help="Neo4j password")
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"), help="Neo4j database")
    
    args = parser.parse_args()
    
    if not args.password:
        logger.error("NEO4J_PASSWORD is required (set via env or --password)")
        sys.exit(1)
    
    logger.info(f"Starting Section graph backfill for group_id={args.group_id}")
    logger.info(f"Neo4j URI: {args.uri}, Database: {args.database}")
    
    if args.dry_run:
        logger.info("[DRY RUN MODE]")
    
    stats = backfill_section_graph(
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
        group_id=args.group_id,
        dry_run=args.dry_run,
    )
    
    logger.info("=" * 60)
    logger.info("Backfill complete. Stats:")
    for k, v in stats.items():
        logger.info(f"  {k}: {v}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
