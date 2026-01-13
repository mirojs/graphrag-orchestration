"""
Dual Indexing Service for Hybrid Pipeline

Syncs GraphRAG data with HippoRAG format, maintaining two complementary views:
1. HippoRAG View: Triples (Subject-Predicate-Object) for PageRank
2. LazyGraphRAG View: Text Units and Community hierarchies for synthesis

This module handles:
- Converting Neo4j graph to HippoRAG index format
- Syncing community hierarchies for LazyGraphRAG
- Incremental updates when new documents are indexed
"""

from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json
import asyncio
import structlog

logger = structlog.get_logger(__name__)


class DualIndexService:
    """
    Service for maintaining dual indexes for the Hybrid Pipeline.
    
    The Hybrid Architecture requires two different views of the same data:
    - HippoRAG: Entity triples for PPR-based multi-hop retrieval
    - LazyGraphRAG: Text units linked to entities for synthesis
    """
    
    def __init__(
        self,
        neo4j_driver=None,
        hipporag_save_dir: str = "./hipporag_index",
        group_id: str = "default"
    ):
        """
        Initialize the dual index service.
        
        Args:
            neo4j_driver: Neo4j driver connection
            hipporag_save_dir: Directory to save HippoRAG index
            group_id: Tenant ID for multi-tenancy
        """
        self.driver = neo4j_driver
        self.hipporag_dir = Path(hipporag_save_dir)
        self.group_id = group_id
        
        # Create directories
        self.hipporag_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("dual_index_service_initialized",
                   group_id=group_id,
                   hipporag_dir=str(self.hipporag_dir))
    
    async def sync_from_neo4j(self) -> Dict[str, Any]:
        """
        Sync all data from Neo4j to HippoRAG format.
        
        This is the main synchronization method that:
        1. Extracts entities and relationships from Neo4j
        2. Converts to HippoRAG triple format
        3. Saves the index files
        
        Returns:
            Statistics about the sync operation
        """
        logger.info("sync_from_neo4j_start", group_id=self.group_id)
        
        if not self.driver:
            logger.warning("neo4j_driver_not_configured")
            return {"status": "skipped", "reason": "no_neo4j_driver"}
        
        try:
            # Step 1: Extract entities
            entities = await self._extract_entities()
            logger.info("entities_extracted", count=len(entities))
            
            # Step 2: Extract relationships (triples)
            triples = await self._extract_triples()
            logger.info("triples_extracted", count=len(triples))
            
            # Step 3: Extract text units
            text_units = await self._extract_text_units()
            logger.info("text_units_extracted", count=len(text_units))
            
            # Step 4: Build entity-to-text mappings
            entity_text_map = await self._build_entity_text_mapping()
            logger.info("entity_text_mapping_built", 
                       entities_with_text=len(entity_text_map))
            
            # Step 5: Save HippoRAG index
            await self._save_hipporag_index(entities, triples, entity_text_map)
            
            # Step 6: Save LazyGraphRAG-compatible structures
            await self._save_lazygraphrag_index(text_units, entities)
            
            stats = {
                "status": "success",
                "group_id": self.group_id,
                "entities_indexed": len(entities),
                "triples_indexed": len(triples),
                "text_units_indexed": len(text_units),
                "hipporag_index_path": str(self.hipporag_dir / "hipporag_triples.json"),
                "lazygraphrag_index_path": str(self.hipporag_dir / "lazygraphrag_units.json")
            }
            
            logger.info("sync_from_neo4j_complete", **stats)
            return stats
            
        except Exception as e:
            logger.error("sync_from_neo4j_failed", error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def _extract_entities(self) -> List[Dict[str, Any]]:
        """Extract all entities from Neo4j for this group."""
        if not self.driver:
            return []

        # Schema note: in many deployments entities are labeled :Entity.
        # Keep this query narrow to avoid pulling in documents/chunks.
        query = """
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
        RETURN
            elementId(e) as id,
            labels(e) as labels,
            e.name as name,
            e.description as description,
            properties(e) as properties
        """
        
        entities = []
        with self.driver.session() as session:
            result = session.run(query, group_id=self.group_id)
            for record in result:
                entities.append({
                    "id": record["id"],
                    "labels": record["labels"],
                    "name": record["name"] or record["id"],
                    "description": record["description"],
                    "properties": record["properties"]
                })
        
        return entities
    
    async def _extract_triples(self) -> List[Dict[str, Any]]:
        """
        Extract all relationships as triples (Subject-Predicate-Object).
        
        This is the core format HippoRAG uses for PageRank calculations.
        """
        if not self.driver:
            return []

        query = """
        MATCH (s)-[r]->(o)
        WHERE (s:Entity OR s:__Entity__)
            AND (o:Entity OR o:__Entity__)
            AND s.group_id = $group_id
            AND o.group_id = $group_id
            AND r.group_id = $group_id
        RETURN
            s.name as subject,
            type(r) as predicate,
            o.name as object,
            r.description as rel_description,
            r.weight as weight
        """
        
        triples = []
        with self.driver.session() as session:
            result = session.run(query, group_id=self.group_id)
            for record in result:
                triples.append({
                    "subject": record["subject"],
                    "predicate": record["predicate"],
                    "object": record["object"],
                    "description": record["rel_description"],
                    "weight": record["weight"] or 1.0
                })
        
        return triples
    
    async def _extract_text_units(self) -> List[Dict[str, Any]]:
        """Extract text chunks/units for synthesis."""
        if not self.driver:
            return []

        # Schema note: chunks are typically :TextChunk and linked to :Document via (:TextChunk)-[:PART_OF]->(:Document).
        query = """
        MATCH (c:TextChunk)
        WHERE c.group_id = $group_id
        OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
        RETURN
            elementId(c) as id,
            c.text as text,
            coalesce(d.source, d.title) as source,
            c.chunk_index as chunk_index
        """
        
        text_units = []
        with self.driver.session() as session:
            result = session.run(query, group_id=self.group_id)
            for record in result:
                text_units.append({
                    "id": record["id"],
                    "text": record["text"],
                    "source": record["source"],
                    "chunk_index": record["chunk_index"]
                })
        
        return text_units
    
    async def _build_entity_text_mapping(self) -> Dict[str, List[str]]:
        """
        Build mapping from entities to their source text chunks.
        
        This is critical for Stage 3 (Synthesis) where we need to
        retrieve the raw text that supports each entity.
        """
        if not self.driver:
            return {}
        
        # Schema note: chunks often point to entities via (:TextChunk)-[:MENTIONS]->(:Entity)

        query = """
        MATCH (c)-[m:MENTIONS]-(e)
        WHERE (c:TextChunk OR c:Chunk OR c:__Node__)
            AND (e:Entity OR e:__Entity__)
            AND c.group_id = $group_id
            AND e.group_id = $group_id
            AND m.group_id = $group_id
        RETURN e.name as entity, collect(c.text) as texts
        """
        
        entity_text_map = {}
        with self.driver.session() as session:
            result = session.run(query, group_id=self.group_id)
            for record in result:
                entity_text_map[record["entity"]] = record["texts"]
        
        return entity_text_map
    
    async def _save_hipporag_index(
        self,
        entities: List[Dict[str, Any]],
        triples: List[Dict[str, Any]],
        entity_text_map: Dict[str, List[str]]
    ):
        """
        Save the HippoRAG index files.
        
        HippoRAG expects:
        - entities.json: List of entity names/IDs
        - triples.json: List of (subject, predicate, object) tuples
        - entity_texts.json: Mapping from entity to supporting texts
        """
        group_dir = self.hipporag_dir / self.group_id
        group_dir.mkdir(parents=True, exist_ok=True)
        
        # Save entities
        entities_file = group_dir / "entities.json"
        with open(entities_file, 'w') as f:
            json.dump(entities, f, indent=2, default=str)
        
        # Save triples in HippoRAG format
        triples_file = group_dir / "hipporag_triples.json"
        hipporag_format = [
            [t["subject"], t["predicate"], t["object"]]
            for t in triples
        ]
        with open(triples_file, 'w') as f:
            json.dump(hipporag_format, f, indent=2, default=str)
        
        # Save entity-text mapping
        entity_texts_file = group_dir / "entity_texts.json"
        with open(entity_texts_file, 'w') as f:
            json.dump(entity_text_map, f, indent=2, default=str)
        
        logger.info("hipporag_index_saved",
                   entities_file=str(entities_file),
                   triples_file=str(triples_file))
    
    async def _save_lazygraphrag_index(
        self,
        text_units: List[Dict[str, Any]],
        entities: List[Dict[str, Any]]
    ):
        """
        Save LazyGraphRAG-compatible index structures.
        
        LazyGraphRAG needs:
        - Text units with embeddings (for Iterative Deepening)
        - Entity-to-text mapping (for anchored retrieval)
        """
        group_dir = self.hipporag_dir / self.group_id
        group_dir.mkdir(parents=True, exist_ok=True)
        
        # Save text units
        text_units_file = group_dir / "lazygraphrag_units.json"
        with open(text_units_file, 'w') as f:
            json.dump(text_units, f, indent=2, default=str)
        
        # Save entity index for LazyGraphRAG focal entity lookup
        entity_index_file = group_dir / "entity_index.json"
        entity_index = {
            e["name"]: {
                "id": e["id"],
                "labels": e["labels"],
                "description": e["description"]
            }
            for e in entities if e["name"]
        }
        with open(entity_index_file, 'w') as f:
            json.dump(entity_index, f, indent=2, default=str)
        
        logger.info("lazygraphrag_index_saved",
                   text_units_file=str(text_units_file),
                   entity_index_file=str(entity_index_file))
    
    async def incremental_update(
        self,
        new_entities: List[Dict[str, Any]],
        new_triples: List[Dict[str, Any]],
        new_text_units: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Incrementally update indexes with new data.
        
        Used when new documents are indexed - avoids full re-sync.
        """
        logger.info("incremental_update_start",
                   new_entities=len(new_entities),
                   new_triples=len(new_triples),
                   new_text_units=len(new_text_units))
        
        group_dir = self.hipporag_dir / self.group_id
        
        # Load existing data
        entities_file = group_dir / "entities.json"
        triples_file = group_dir / "hipporag_triples.json"
        text_units_file = group_dir / "lazygraphrag_units.json"
        
        existing_entities = []
        existing_triples = []
        existing_text_units = []
        
        if entities_file.exists():
            with open(entities_file) as f:
                existing_entities = json.load(f)
        
        if triples_file.exists():
            with open(triples_file) as f:
                existing_triples = json.load(f)
        
        if text_units_file.exists():
            with open(text_units_file) as f:
                existing_text_units = json.load(f)
        
        # Merge (deduplicate by ID/name)
        existing_entity_ids = {e.get("id") or e.get("name") for e in existing_entities}
        for entity in new_entities:
            entity_id = entity.get("id") or entity.get("name")
            if entity_id not in existing_entity_ids:
                existing_entities.append(entity)
        
        # Add new triples
        existing_triple_set = {tuple(t) for t in existing_triples}
        for triple in new_triples:
            triple_tuple = (triple["subject"], triple["predicate"], triple["object"])
            if triple_tuple not in existing_triple_set:
                existing_triples.append(list(triple_tuple))
        
        # Add new text units
        existing_unit_ids = {u.get("id") for u in existing_text_units}
        for unit in new_text_units:
            if unit.get("id") not in existing_unit_ids:
                existing_text_units.append(unit)
        
        # Save updated indexes
        group_dir.mkdir(parents=True, exist_ok=True)
        
        with open(entities_file, 'w') as f:
            json.dump(existing_entities, f, indent=2)
        
        with open(triples_file, 'w') as f:
            json.dump(existing_triples, f, indent=2)
        
        with open(text_units_file, 'w') as f:
            json.dump(existing_text_units, f, indent=2)
        
        stats = {
            "status": "success",
            "total_entities": len(existing_entities),
            "total_triples": len(existing_triples),
            "total_text_units": len(existing_text_units),
            "new_entities_added": len(new_entities),
            "new_triples_added": len(new_triples),
            "new_text_units_added": len(new_text_units)
        }
        
        logger.info("incremental_update_complete", **stats)
        return stats
    
    def get_hipporag_config(self) -> Dict[str, Any]:
        """
        Get configuration for initializing HippoRAG with our index.
        
        Returns the paths and settings needed to initialize
        HippoRAG with the synced data.
        """
        group_dir = self.hipporag_dir / self.group_id
        
        return {
            "save_dir": str(group_dir),
            "triples_path": str(group_dir / "hipporag_triples.json"),
            "entities_path": str(group_dir / "entities.json"),
            "entity_texts_path": str(group_dir / "entity_texts.json"),
            "group_id": self.group_id
        }
