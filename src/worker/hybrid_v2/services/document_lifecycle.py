"""
Document Lifecycle Management Service for V2 GraphRAG.

Handles document deprecation, restoration, and deletion with proper cascade
to child nodes (chunks, sections, tables, figures, KVPs) and orphan cleanup.

Key Principles:
1. Soft delete first (deprecation via labels), hard delete later
2. Cascade to children but reference-count shared entities
3. GDS recompute triggered after lifecycle changes
4. Vector indexes cleaned up asynchronously
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class DocumentStatus(Enum):
    """Document lifecycle states."""
    ACTIVE = "active"           # Default, no label needed
    DEPRECATED = "deprecated"   # Soft-deleted, :Deprecated label
    ARCHIVED = "archived"       # Cold storage, :Archived label


@dataclass
class DeprecationResult:
    """Result of document deprecation operation."""
    document_id: str
    group_id: str
    success: bool
    children_deprecated: int
    gds_marked_stale: bool
    errors: List[str] = field(default_factory=list)


@dataclass
class RestorationResult:
    """Result of document restoration operation."""
    document_id: str
    group_id: str
    success: bool
    children_restored: int
    errors: List[str] = field(default_factory=list)


@dataclass
class DeletionResult:
    """Result of document hard deletion operation."""
    document_id: str
    group_id: str
    success: bool
    chunks_deleted: int
    sections_deleted: int
    entities_orphaned: int
    edges_deleted: int
    folder_unlinked: bool = False  # True if IN_FOLDER relationship was removed
    vectors_removed: int
    errors: List[str] = field(default_factory=list)


class DocumentLifecycleService:
    """
    Manages document lifecycle in V2 GraphRAG.
    
    Ensures proper cascade of lifecycle changes to child nodes while
    preserving shared entities until they become orphans.
    """
    
    def __init__(self, neo4j_store):
        """
        Initialize with Neo4j store.
        
        Args:
            neo4j_store: Neo4jStoreV3 instance for database operations
        """
        self.store = neo4j_store
        self.driver = neo4j_store.driver
        self.database = neo4j_store.database
    
    # ==================== Real-Time Operations (Tier 1) ====================
    
    async def deprecate_document(
        self,
        group_id: str,
        document_id: str,
        reason: Optional[str] = None,
        deprecated_by: Optional[str] = None,
    ) -> DeprecationResult:
        """
        Deprecate a document and cascade to children (soft delete).
        
        This is the primary "delete" operation for most use cases.
        The document remains in the graph but is excluded from queries.
        
        Args:
            group_id: Tenant identifier
            document_id: Document to deprecate
            reason: Optional reason for deprecation
            deprecated_by: Optional user/system identifier
            
        Returns:
            DeprecationResult with statistics
        """
        logger.info(f"Deprecating document {document_id} in group {group_id}")
        
        errors = []
        children_deprecated = 0
        gds_marked_stale = False
        
        try:
            with self.driver.session(database=self.database) as session:
                # Step 1: Deprecate document and cascade to children
                result = session.run(
                    """
                    // Find and deprecate the document
                    MATCH (d:Document {id: $doc_id, group_id: $group_id})
                    WHERE NOT d:Deprecated
                    SET d:Deprecated,
                        d.deprecated_at = datetime(),
                        d.deprecated_reason = $reason,
                        d.deprecated_by = $deprecated_by
                    
                    // Cascade to direct children (chunks, sections, tables, figures, kvps)
                    WITH d
                    OPTIONAL MATCH (child)-[:PART_OF|IN_DOCUMENT]->(d)
                    WHERE NOT child:Deprecated
                    SET child:Deprecated, 
                        child.deprecated_at = datetime(),
                        child.deprecated_reason = 'parent_deprecated'
                    
                    WITH d, count(child) AS children_count
                    
                    // Also deprecate sections linked via doc_id property
                    OPTIONAL MATCH (s:Section {doc_id: d.id, group_id: $group_id})
                    WHERE NOT s:Deprecated
                    SET s:Deprecated,
                        s.deprecated_at = datetime(),
                        s.deprecated_reason = 'parent_deprecated'
                    
                    WITH d, children_count, count(s) AS sections_count
                    
                    // Mark group as needing GDS refresh
                    MERGE (g:GroupMeta {group_id: $group_id})
                    SET g.gds_stale = true, 
                        g.gds_stale_since = datetime(),
                        g.last_lifecycle_change = datetime()
                    
                    RETURN d.id AS doc_id, 
                           children_count + sections_count AS total_children,
                           true AS gds_stale
                    """,
                    doc_id=document_id,
                    group_id=group_id,
                    reason=reason,
                    deprecated_by=deprecated_by,
                )
                
                record = result.single()
                if record:
                    children_deprecated = record["total_children"]
                    gds_marked_stale = record["gds_stale"]
                    logger.info(
                        f"Deprecated document {document_id}: "
                        f"{children_deprecated} children affected"
                    )
                else:
                    errors.append(f"Document {document_id} not found or already deprecated")
                    
        except Exception as e:
            logger.error(f"Failed to deprecate document {document_id}: {e}")
            errors.append(str(e))
        
        return DeprecationResult(
            document_id=document_id,
            group_id=group_id,
            success=len(errors) == 0,
            children_deprecated=children_deprecated,
            gds_marked_stale=gds_marked_stale,
            errors=errors,
        )
    
    async def restore_document(
        self,
        group_id: str,
        document_id: str,
    ) -> RestorationResult:
        """
        Restore a deprecated document and its children.
        
        Args:
            group_id: Tenant identifier
            document_id: Document to restore
            
        Returns:
            RestorationResult with statistics
        """
        logger.info(f"Restoring document {document_id} in group {group_id}")
        
        errors = []
        children_restored = 0
        
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    """
                    // Find and restore the document
                    MATCH (d:Document:Deprecated {id: $doc_id, group_id: $group_id})
                    REMOVE d:Deprecated
                    SET d.restored_at = datetime(),
                        d.deprecated_at = null,
                        d.deprecated_reason = null,
                        d.deprecated_by = null
                    
                    // Restore children that were deprecated due to parent
                    WITH d
                    OPTIONAL MATCH (child)-[:PART_OF|IN_DOCUMENT]->(d)
                    WHERE child:Deprecated 
                      AND child.deprecated_reason = 'parent_deprecated'
                    REMOVE child:Deprecated
                    SET child.restored_at = datetime(),
                        child.deprecated_at = null,
                        child.deprecated_reason = null
                    
                    WITH d, count(child) AS children_count
                    
                    // Restore sections
                    OPTIONAL MATCH (s:Section:Deprecated {doc_id: d.id, group_id: $group_id})
                    WHERE s.deprecated_reason = 'parent_deprecated'
                    REMOVE s:Deprecated
                    SET s.restored_at = datetime(),
                        s.deprecated_at = null,
                        s.deprecated_reason = null
                    
                    WITH d, children_count, count(s) AS sections_count
                    
                    // Mark group as needing GDS refresh
                    MERGE (g:GroupMeta {group_id: $group_id})
                    SET g.gds_stale = true, 
                        g.gds_stale_since = datetime(),
                        g.last_lifecycle_change = datetime()
                    
                    RETURN d.id AS doc_id, 
                           children_count + sections_count AS total_children
                    """,
                    doc_id=document_id,
                    group_id=group_id,
                )
                
                record = result.single()
                if record:
                    children_restored = record["total_children"]
                    logger.info(
                        f"Restored document {document_id}: "
                        f"{children_restored} children restored"
                    )
                else:
                    errors.append(f"Document {document_id} not found or not deprecated")
                    
        except Exception as e:
            logger.error(f"Failed to restore document {document_id}: {e}")
            errors.append(str(e))
        
        return RestorationResult(
            document_id=document_id,
            group_id=group_id,
            success=len(errors) == 0,
            children_restored=children_restored,
            errors=errors,
        )
    
    async def hard_delete_document(
        self,
        group_id: str,
        document_id: str,
        orphan_cleanup: bool = True,
    ) -> DeletionResult:
        """
        Permanently delete a document and all its data.
        
        WARNING: This is destructive and cannot be undone.
        Consider deprecate_document() for most use cases.
        
        Handles:
        - Cascade deletion to chunks, sections, tables, figures, KVPs
        - Orphan entity cleanup (entities only referenced by this document)
        - Folder relationship cleanup (IN_FOLDER edge removal)
        - GDS staleness marking
        
        Args:
            group_id: Tenant identifier
            document_id: Document to delete
            orphan_cleanup: If True, delete entities that become orphans
            
        Returns:
            DeletionResult with statistics including folder_unlinked
        """
        logger.warning(f"HARD DELETE document {document_id} in group {group_id}")
        
        errors = []
        stats = {
            "chunks_deleted": 0,
            "sections_deleted": 0,
            "entities_orphaned": 0,
            "edges_deleted": 0,
            "vectors_removed": 0,
        }
        folder_unlinked = False
        
        try:
            with self.driver.session(database=self.database) as session:
                if orphan_cleanup:
                    # Complex query with orphan detection and folder tracking
                    result = session.run(
                        """
                        // Step 1: Collect chunk IDs and check folder relationship
                        MATCH (d:Document {id: $doc_id, group_id: $group_id})
                        OPTIONAL MATCH (d)-[folder_rel:IN_FOLDER]->(:Folder)
                        OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
                        WITH d, folder_rel IS NOT NULL AS had_folder, collect(c.id) AS chunk_ids, count(c) AS chunk_count
                        
                        // Step 2: Find entities mentioned ONLY in these chunks
                        OPTIONAL MATCH (orphan_chunk:TextChunk)-[:MENTIONS]->(e:Entity {group_id: $group_id})
                        WHERE orphan_chunk.id IN chunk_ids
                        WITH d, had_folder, chunk_ids, chunk_count, e, orphan_chunk
                        WITH d, had_folder, chunk_ids, chunk_count, e, count(orphan_chunk) AS mentions_in_doc
                        
                        // Count total mentions across ALL chunks
                        OPTIONAL MATCH (all_chunks:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
                        WITH d, had_folder, chunk_ids, chunk_count, e, mentions_in_doc, count(all_chunks) AS total_mentions
                        
                        // Entity is orphaned if all mentions are in deleted chunks
                        WHERE total_mentions = mentions_in_doc
                        WITH d, had_folder, chunk_ids, chunk_count, collect(DISTINCT e) AS orphaned_entities
                        
                        // Step 3: Delete document and chunks
                        OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
                        WITH d, had_folder, chunk_ids, chunk_count, orphaned_entities, collect(c) AS chunks_to_delete
                        
                        // Delete sections
                        OPTIONAL MATCH (s:Section {doc_id: d.id, group_id: $group_id})
                        WITH d, had_folder, chunk_count, orphaned_entities, chunks_to_delete, collect(s) AS sections_to_delete
                        
                        // Delete tables, figures, KVPs linked to document
                        OPTIONAL MATCH (t:Table)-[:IN_DOCUMENT]->(d)
                        OPTIONAL MATCH (f:Figure)-[:IN_DOCUMENT]->(d)
                        OPTIONAL MATCH (k:KeyValue)-[:IN_DOCUMENT]->(d)
                        WITH d, had_folder, chunk_count, orphaned_entities, chunks_to_delete, sections_to_delete,
                             collect(DISTINCT t) AS tables_to_delete,
                             collect(DISTINCT f) AS figures_to_delete,
                             collect(DISTINCT k) AS kvps_to_delete
                        
                        // Count edges to delete
                        OPTIONAL MATCH (oe:Entity)-[r]-() WHERE oe IN orphaned_entities
                        WITH d, had_folder, chunk_count, orphaned_entities, chunks_to_delete, sections_to_delete,
                             tables_to_delete, figures_to_delete, kvps_to_delete, count(DISTINCT r) AS edge_count
                        
                        // Perform deletions (DETACH DELETE removes all relationships including IN_FOLDER)
                        DETACH DELETE d
                        FOREACH (c IN chunks_to_delete | DETACH DELETE c)
                        FOREACH (s IN sections_to_delete | DETACH DELETE s)
                        FOREACH (t IN tables_to_delete | DETACH DELETE t)
                        FOREACH (f IN figures_to_delete | DETACH DELETE f)
                        FOREACH (k IN kvps_to_delete | DETACH DELETE k)
                        FOREACH (oe IN orphaned_entities | DETACH DELETE oe)
                        
                        // Mark group stale
                        MERGE (g:GroupMeta {group_id: $group_id})
                        SET g.gds_stale = true, g.gds_stale_since = datetime()
                        
                        RETURN chunk_count,
                               size(sections_to_delete) AS section_count,
                               size(orphaned_entities) AS orphan_count,
                               edge_count,
                               had_folder AS folder_unlinked
                        """,
                        doc_id=document_id,
                        group_id=group_id,
                    )
                else:
                    # Simple deletion without orphan cleanup
                    result = session.run(
                        """
                        MATCH (d:Document {id: $doc_id, group_id: $group_id})
                        OPTIONAL MATCH (d)-[folder_rel:IN_FOLDER]->(:Folder)
                        OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
                        OPTIONAL MATCH (s:Section {doc_id: d.id, group_id: $group_id})
                        WITH d, folder_rel IS NOT NULL AS had_folder, 
                             count(c) AS chunk_count, count(s) AS section_count, 
                             collect(c) AS chunks, collect(s) AS sections
                        DETACH DELETE d
                        FOREACH (c IN chunks | DETACH DELETE c)
                        FOREACH (s IN sections | DETACH DELETE s)
                        
                        MERGE (g:GroupMeta {group_id: $group_id})
                        SET g.gds_stale = true, g.gds_stale_since = datetime()
                        
                        RETURN chunk_count, section_count, 0 AS orphan_count, 0 AS edge_count, had_folder AS folder_unlinked
                        """,
                        doc_id=document_id,
                        group_id=group_id,
                    )
                
                record = result.single()
                if record:
                    stats["chunks_deleted"] = record["chunk_count"] or 0
                    stats["sections_deleted"] = record["section_count"] or 0
                    stats["entities_orphaned"] = record["orphan_count"] or 0
                    stats["edges_deleted"] = record["edge_count"] or 0
                    folder_unlinked = record.get("folder_unlinked", False)
                    logger.info(f"Hard deleted document {document_id}: {stats}, folder_unlinked={folder_unlinked}")
                else:
                    errors.append(f"Document {document_id} not found")
                    
        except Exception as e:
            logger.error(f"Failed to hard delete document {document_id}: {e}")
            errors.append(str(e))
        
        return DeletionResult(
            document_id=document_id,
            group_id=group_id,
            success=len(errors) == 0,
            errors=errors,
            folder_unlinked=folder_unlinked,
            **stats,
        )
    
    # ==================== Query Operations ====================
    
    async def list_documents(
        self,
        group_id: str,
        status: Optional[DocumentStatus] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List documents in a group, optionally filtered by status.
        
        Args:
            group_id: Tenant identifier
            status: Filter by lifecycle status (None = all)
            limit: Maximum documents to return
            
        Returns:
            List of document metadata dicts
        """
        with self.driver.session(database=self.database) as session:
            if status == DocumentStatus.DEPRECATED:
                query = """
                MATCH (d:Document:Deprecated {group_id: $group_id})
                RETURN d.id AS id, d.title AS title, d.source AS source,
                       d.deprecated_at AS deprecated_at, d.deprecated_reason AS reason
                ORDER BY d.deprecated_at DESC
                LIMIT $limit
                """
            elif status == DocumentStatus.ACTIVE:
                query = """
                MATCH (d:Document {group_id: $group_id})
                WHERE NOT d:Deprecated AND NOT d:Archived
                RETURN d.id AS id, d.title AS title, d.source AS source,
                       d.updated_at AS updated_at
                ORDER BY d.updated_at DESC
                LIMIT $limit
                """
            else:
                query = """
                MATCH (d:Document {group_id: $group_id})
                RETURN d.id AS id, d.title AS title, d.source AS source,
                       d:Deprecated AS is_deprecated, d:Archived AS is_archived,
                       d.updated_at AS updated_at
                ORDER BY d.updated_at DESC
                LIMIT $limit
                """
            
            result = session.run(query, group_id=group_id, limit=limit)
            return [dict(record) for record in result]
    
    async def get_document_impact(
        self,
        group_id: str,
        document_id: str,
    ) -> Dict[str, Any]:
        """
        Preview the impact of deprecating/deleting a document.
        
        Args:
            group_id: Tenant identifier
            document_id: Document to analyze
            
        Returns:
            Dict with impact statistics
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(
                """
                MATCH (d:Document {id: $doc_id, group_id: $group_id})
                
                // Count chunks
                OPTIONAL MATCH (c:TextChunk)-[:PART_OF]->(d)
                WITH d, count(c) AS chunk_count, collect(c.id) AS chunk_ids
                
                // Count sections
                OPTIONAL MATCH (s:Section {doc_id: d.id, group_id: $group_id})
                WITH d, chunk_count, chunk_ids, count(s) AS section_count
                
                // Count entities that would be orphaned
                OPTIONAL MATCH (c:TextChunk)-[:MENTIONS]->(e:Entity {group_id: $group_id})
                WHERE c.id IN chunk_ids
                WITH d, chunk_count, section_count, e
                OPTIONAL MATCH (other:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
                WHERE NOT other.id IN chunk_ids
                WITH d, chunk_count, section_count, e, count(other) AS other_mentions
                WITH d, chunk_count, section_count, 
                     sum(CASE WHEN other_mentions = 0 THEN 1 ELSE 0 END) AS orphan_entities
                
                // Count tables, figures, KVPs
                OPTIONAL MATCH (t:Table)-[:IN_DOCUMENT]->(d)
                OPTIONAL MATCH (f:Figure)-[:IN_DOCUMENT]->(d)
                OPTIONAL MATCH (k:KeyValue)-[:IN_DOCUMENT]->(d)
                
                RETURN d.id AS document_id,
                       d.title AS title,
                       d:Deprecated AS is_deprecated,
                       chunk_count,
                       section_count,
                       orphan_entities,
                       count(DISTINCT t) AS table_count,
                       count(DISTINCT f) AS figure_count,
                       count(DISTINCT k) AS keyvalue_count
                """,
                doc_id=document_id,
                group_id=group_id,
            )
            
            record = result.single()
            if record:
                return dict(record)
            return {"error": f"Document {document_id} not found"}
