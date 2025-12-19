"""
Document Lifecycle Manager for Neo4j GraphRAG

Handles adding, updating, and removing individual documents while maintaining
graph integrity and preventing "orphan" entities.

Key Principles:
1. Traceability: Every entity traces back to source chunks via MENTIONS
2. Cascade Deletion: Removing a document cleans up orphaned entities
3. Safe Updates: Replace old document atomically to avoid partial states
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from neo4j import GraphDatabase, Query
from app.v3.services.neo4j_store import Neo4jStoreV3, Document, TextChunk, Entity

logger = logging.getLogger(__name__)


@dataclass
class DocumentDeletionResult:
    """Result of document deletion operation."""
    document_deleted: bool
    chunks_deleted: int
    entities_orphaned: int
    communities_affected: int
    relationships_deleted: int


class DocumentManager:
    """
    Manages document lifecycle in Neo4j GraphRAG.
    
    Ensures clean addition, update, and removal of documents while maintaining
    graph integrity through orphan cleanup.
    """
    
    def __init__(self, neo4j_store: Neo4jStoreV3):
        self.store = neo4j_store
        self.driver = neo4j_store.driver
        self.database = neo4j_store.database
    
    def delete_document(
        self,
        group_id: str,
        document_id: str,
        orphan_cleanup: bool = True
    ) -> DocumentDeletionResult:
        """
        Delete a document and optionally clean up orphaned entities.
        
        Args:
            group_id: The group/tenant ID
            document_id: The document to delete
            orphan_cleanup: Whether to delete entities that become orphaned
        
        Returns:
            DocumentDeletionResult with deletion statistics
        
        Process:
            1. Find document and all its chunks
            2. Delete document and chunks (CASCADE deletes PART_OF relationships)
            3. Find entities that were ONLY mentioned in those chunks
            4. Delete orphaned entities and their relationships
            5. Find communities that lost all their entities
            6. Delete empty communities
        """
        logger.info(f"Deleting document {document_id} from group {group_id} (orphan_cleanup={orphan_cleanup})")
        
        if orphan_cleanup:
            query = """
            // Step 1: Find and collect chunk IDs before deletion
            MATCH (d:Document {id: $document_id, group_id: $group_id})
            OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
            WITH d, collect(c.id) AS chunk_ids, count(c) AS chunk_count
            
            // Step 2: Find entities mentioned ONLY in these chunks (will be orphaned)
            OPTIONAL MATCH (orphan_chunk:TextChunk)-[:MENTIONS]->(e:Entity {group_id: $group_id})
            WHERE orphan_chunk.id IN chunk_ids
            WITH d, chunk_ids, chunk_count, e, orphan_chunk
            WITH d, chunk_ids, chunk_count, e, count(orphan_chunk) AS mentions_in_doc
            
            // Count total mentions of this entity across ALL chunks
            OPTIONAL MATCH (all_chunks:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
            WITH d, chunk_ids, chunk_count, e, mentions_in_doc, count(all_chunks) AS total_mentions
            
            // Entity is orphaned if all its mentions are in chunks being deleted
            WHERE total_mentions = mentions_in_doc
            WITH d, chunk_ids, chunk_count, collect(DISTINCT e) AS orphaned_entities
            
            // Step 3: Delete document and chunks
            OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
            WITH d, chunk_ids, chunk_count, orphaned_entities, collect(c) AS chunks_to_delete
            DETACH DELETE d
            FOREACH (c IN chunks_to_delete | DETACH DELETE c)
            
            // Step 4: Delete orphaned entities and count their relationships
            WITH chunk_count, orphaned_entities
            OPTIONAL MATCH (oe:Entity)-[r]-()
            WHERE oe IN orphaned_entities
            WITH chunk_count, orphaned_entities, count(DISTINCT r) AS rel_count
            FOREACH (oe IN orphaned_entities | DETACH DELETE oe)
            
            // Step 5: Find and delete communities that lost all their entities
            MATCH (com:Community {group_id: $group_id})
            WHERE NOT EXISTS {
                MATCH (com)<-[:PART_OF_COMMUNITY]-(e:Entity {group_id: $group_id})
            }
            WITH chunk_count, orphaned_entities, rel_count, collect(com) AS empty_communities
            FOREACH (com IN empty_communities | DETACH DELETE com)
            
            RETURN 
                chunk_count,
                size(orphaned_entities) AS orphan_count,
                size(empty_communities) AS community_count,
                rel_count
            """
        else:
            # Simple deletion without orphan cleanup
            query = """
            MATCH (d:Document {id: $document_id, group_id: $group_id})
            OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
            WITH d, count(c) AS chunk_count, collect(c) AS chunks
            DETACH DELETE d
            FOREACH (c IN chunks | DETACH DELETE c)
            RETURN chunk_count, 0 AS orphan_count, 0 AS community_count, 0 AS rel_count
            """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                Query(query),
                document_id=document_id,
                group_id=group_id
            )
            record = result.single()
            
            if record:
                return DocumentDeletionResult(
                    document_deleted=True,
                    chunks_deleted=record["chunk_count"] or 0,
                    entities_orphaned=record["orphan_count"] or 0,
                    communities_affected=record["community_count"] or 0,
                    relationships_deleted=record["rel_count"] or 0
                )
            else:
                logger.warning(f"Document {document_id} not found in group {group_id}")
                return DocumentDeletionResult(
                    document_deleted=False,
                    chunks_deleted=0,
                    entities_orphaned=0,
                    communities_affected=0,
                    relationships_deleted=0
                )
    
    def replace_document(
        self,
        group_id: str,
        document_id: str,
        new_document: Document,
        new_chunks: List[TextChunk],
        new_entities: List[Entity]
    ) -> Dict[str, any]:
        """
        Replace a document atomically.
        
        This is safer than separate delete + add operations because it happens
        in a single transaction. Useful for document updates.
        
        Args:
            group_id: The group/tenant ID
            document_id: The document to replace
            new_document: New document metadata
            new_chunks: New chunks to add
            new_entities: New entities to add
        
        Returns:
            Statistics about the replacement operation
        """
        logger.info(f"Replacing document {document_id} in group {group_id}")
        
        # Step 1: Delete old document (with orphan cleanup)
        deletion_result = self.delete_document(group_id, document_id, orphan_cleanup=True)
        
        # Step 2: Add new document
        self.store.upsert_document(group_id, new_document)
        chunks_added = self.store.upsert_text_chunks_batch(group_id, new_chunks)
        entities_added = self.store.upsert_entities_batch(group_id, new_entities)
        
        return {
            "deleted": {
                "chunks": deletion_result.chunks_deleted,
                "entities": deletion_result.entities_orphaned,
                "communities": deletion_result.communities_affected,
            },
            "added": {
                "chunks": chunks_added,
                "entities": entities_added,
            }
        }
    
    def get_document_impact(self, group_id: str, document_id: str) -> Dict[str, int]:
        """
        Analyze what would be deleted if this document is removed.
        
        Useful for showing users the impact before deletion.
        """
        query = """
        MATCH (d:Document {id: $document_id, group_id: $group_id})
        OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
        WITH d, collect(c.id) AS chunk_ids, count(c) AS chunk_count
        
        // Find entities mentioned in these chunks
        OPTIONAL MATCH (mentioned_chunk:TextChunk)-[:MENTIONS]->(e:Entity {group_id: $group_id})
        WHERE mentioned_chunk.id IN chunk_ids
        WITH chunk_ids, chunk_count, e, count(mentioned_chunk) AS mentions_in_doc
        
        // Count total mentions across all chunks
        OPTIONAL MATCH (all_chunks:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
        WITH chunk_ids, chunk_count, e, mentions_in_doc, count(all_chunks) AS total_mentions
        
        // Would this entity be orphaned?
        WITH chunk_count, 
             count(DISTINCT e) AS total_entities,
             count(DISTINCT CASE WHEN total_mentions = mentions_in_doc THEN e ELSE NULL END) AS orphan_entities
        
        RETURN 
            chunk_count,
            total_entities,
            orphan_entities
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(Query(query), document_id=document_id, group_id=group_id)
            record = result.single()
            
            if record:
                return {
                    "chunks": record["chunk_count"] or 0,
                    "entities_total": record["total_entities"] or 0,
                    "entities_orphaned": record["orphan_entities"] or 0,
                }
            return {"chunks": 0, "entities_total": 0, "entities_orphaned": 0}
    
    def list_documents(self, group_id: str) -> List[Dict[str, any]]:
        """List all documents in a group with statistics."""
        query = """
        MATCH (d:Document {group_id: $group_id})
        OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
        OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
        RETURN 
            d.id AS id,
            d.title AS title,
            d.source AS source,
            d.updated_at AS updated_at,
            count(DISTINCT c) AS chunk_count,
            count(DISTINCT e) AS entity_count
        ORDER BY d.updated_at DESC
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(Query(query), group_id=group_id)
            return [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "source": record["source"],
                    "updated_at": str(record["updated_at"]),
                    "chunk_count": record["chunk_count"] or 0,
                    "entity_count": record["entity_count"] or 0,
                }
                for record in result
            ]
