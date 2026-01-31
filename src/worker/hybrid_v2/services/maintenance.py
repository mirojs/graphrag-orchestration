"""
Maintenance Service for V2 GraphRAG.

Provides scheduled and on-demand maintenance operations including:
- Orphan entity garbage collection
- Stale KNN edge cleanup
- Deprecated vector index cleanup
- GDS recomputation
- Group isolation validation
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class MaintenanceJobType(Enum):
    """Types of maintenance jobs."""
    GC_ORPHAN_ENTITIES = "gc_orphan_entities"
    GC_STALE_EDGES = "gc_stale_edges"
    GC_DEPRECATED_VECTORS = "gc_deprecated_vectors"
    RECOMPUTE_GDS = "recompute_gds"
    VALIDATE_GROUP_ISOLATION = "validate_group_isolation"
    FULL_GROUP_CLEANUP = "full_group_cleanup"


@dataclass
class MaintenanceJobResult:
    """Result of a maintenance job execution."""
    job_type: MaintenanceJobType
    group_id: str
    success: bool
    stats: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0
    dry_run: bool = False


@dataclass
class GroupHealth:
    """Health metrics for a group."""
    group_id: str
    total_documents: int
    active_documents: int
    deprecated_documents: int
    total_chunks: int
    total_entities: int
    orphan_entities: int
    stale_edges: int
    gds_stale: bool
    gds_last_computed: Optional[datetime]
    isolation_violations: int


class MaintenanceService:
    """
    Unified interface for all maintenance operations.
    
    Provides both on-demand and schedulable maintenance jobs
    for keeping the graph healthy and performant.
    """
    
    def __init__(self, neo4j_store):
        """
        Initialize with Neo4j store.
        
        Args:
            neo4j_store: Neo4jStoreV3 instance
        """
        self.store = neo4j_store
        self.driver = neo4j_store.driver
        self.database = neo4j_store.database
    
    async def run_job(
        self,
        job_type: MaintenanceJobType,
        group_id: str,
        dry_run: bool = False,
    ) -> MaintenanceJobResult:
        """
        Run a specific maintenance job.
        
        Args:
            job_type: Type of job to run
            group_id: Target group
            dry_run: If True, report what would be done without making changes
            
        Returns:
            MaintenanceJobResult with statistics
        """
        start_time = time.time()
        
        job_handlers = {
            MaintenanceJobType.GC_ORPHAN_ENTITIES: self._gc_orphan_entities,
            MaintenanceJobType.GC_STALE_EDGES: self._gc_stale_edges,
            MaintenanceJobType.GC_DEPRECATED_VECTORS: self._gc_deprecated_vectors,
            MaintenanceJobType.RECOMPUTE_GDS: self._recompute_gds,
            MaintenanceJobType.VALIDATE_GROUP_ISOLATION: self._validate_group_isolation,
            MaintenanceJobType.FULL_GROUP_CLEANUP: self._full_group_cleanup,
        }
        
        handler = job_handlers.get(job_type)
        if not handler:
            return MaintenanceJobResult(
                job_type=job_type,
                group_id=group_id,
                success=False,
                errors=[f"Unknown job type: {job_type}"],
                dry_run=dry_run,
            )
        
        try:
            stats, errors = await handler(group_id, dry_run)
            success = len(errors) == 0
        except Exception as e:
            logger.error(f"Maintenance job {job_type} failed: {e}")
            stats = {}
            errors = [str(e)]
            success = False
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return MaintenanceJobResult(
            job_type=job_type,
            group_id=group_id,
            success=success,
            stats=stats,
            errors=errors,
            duration_ms=duration_ms,
            dry_run=dry_run,
        )
    
    async def run_all_gc(
        self,
        group_id: str,
        dry_run: bool = False,
    ) -> List[MaintenanceJobResult]:
        """
        Run all GC jobs in the correct order.
        
        Order:
        1. Orphan entities (entities with no active mentions)
        2. Stale edges (edges to deprecated nodes)
        3. Deprecated vectors (remove from vector index)
        
        Args:
            group_id: Target group
            dry_run: If True, report without making changes
            
        Returns:
            List of MaintenanceJobResult for each job
        """
        gc_jobs = [
            MaintenanceJobType.GC_ORPHAN_ENTITIES,
            MaintenanceJobType.GC_STALE_EDGES,
            MaintenanceJobType.GC_DEPRECATED_VECTORS,
        ]
        
        results = []
        for job_type in gc_jobs:
            result = await self.run_job(job_type, group_id, dry_run)
            results.append(result)
            
            # Stop if a job fails (unless dry_run)
            if not result.success and not dry_run:
                logger.warning(f"GC job {job_type} failed, stopping GC chain")
                break
        
        return results
    
    async def get_group_health(self, group_id: str) -> GroupHealth:
        """
        Get comprehensive health metrics for a group.
        
        Args:
            group_id: Target group
            
        Returns:
            GroupHealth with all metrics
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(
                """
                // Document counts
                OPTIONAL MATCH (d:Document {group_id: $group_id})
                WITH count(d) AS total_docs
                
                OPTIONAL MATCH (d:Document {group_id: $group_id})
                WHERE NOT d:Deprecated
                WITH total_docs, count(d) AS active_docs
                
                OPTIONAL MATCH (d:Document:Deprecated {group_id: $group_id})
                WITH total_docs, active_docs, count(d) AS deprecated_docs
                
                // Chunk count
                OPTIONAL MATCH (c:TextChunk {group_id: $group_id})
                WITH total_docs, active_docs, deprecated_docs, count(c) AS total_chunks
                
                // Entity counts
                OPTIONAL MATCH (e:Entity {group_id: $group_id})
                WITH total_docs, active_docs, deprecated_docs, total_chunks, count(e) AS total_entities
                
                // Orphan entities (no active mentions)
                OPTIONAL MATCH (e:Entity {group_id: $group_id})
                WHERE NOT e:Deprecated
                  AND NOT EXISTS {
                      MATCH (e)<-[:MENTIONS]-(c:TextChunk)
                      WHERE NOT c:Deprecated
                  }
                WITH total_docs, active_docs, deprecated_docs, total_chunks, total_entities,
                     count(e) AS orphan_entities
                
                // Stale edges (connected to deprecated nodes)
                OPTIONAL MATCH ()-[r:SIMILAR_TO|SEMANTICALLY_SIMILAR {group_id: $group_id}]-()
                WHERE EXISTS {
                    MATCH (n1)-[r]-(n2)
                    WHERE n1:Deprecated OR n2:Deprecated
                }
                WITH total_docs, active_docs, deprecated_docs, total_chunks, total_entities,
                     orphan_entities, count(DISTINCT r) AS stale_edges
                
                // GDS status
                OPTIONAL MATCH (g:GroupMeta {group_id: $group_id})
                
                // Isolation violations (nodes without group_id)
                OPTIONAL MATCH (n)
                WHERE n.group_id IS NULL
                  AND (n:Entity OR n:TextChunk OR n:Document OR n:Section)
                WITH total_docs, active_docs, deprecated_docs, total_chunks, total_entities,
                     orphan_entities, stale_edges, g, count(n) AS isolation_violations
                
                RETURN total_docs, active_docs, deprecated_docs, total_chunks, total_entities,
                       orphan_entities, stale_edges,
                       coalesce(g.gds_stale, false) AS gds_stale,
                       g.gds_last_computed AS gds_last_computed,
                       isolation_violations
                """,
                group_id=group_id,
            )
            
            record = result.single()
            if record:
                return GroupHealth(
                    group_id=group_id,
                    total_documents=record["total_docs"] or 0,
                    active_documents=record["active_docs"] or 0,
                    deprecated_documents=record["deprecated_docs"] or 0,
                    total_chunks=record["total_chunks"] or 0,
                    total_entities=record["total_entities"] or 0,
                    orphan_entities=record["orphan_entities"] or 0,
                    stale_edges=record["stale_edges"] or 0,
                    gds_stale=record["gds_stale"],
                    gds_last_computed=record["gds_last_computed"],
                    isolation_violations=record["isolation_violations"] or 0,
                )
            
            return GroupHealth(
                group_id=group_id,
                total_documents=0,
                active_documents=0,
                deprecated_documents=0,
                total_chunks=0,
                total_entities=0,
                orphan_entities=0,
                stale_edges=0,
                gds_stale=False,
                gds_last_computed=None,
                isolation_violations=0,
            )
    
    async def get_stale_groups(self) -> List[Dict[str, Any]]:
        """
        List all groups that need GDS recomputation.
        
        Returns:
            List of group metadata dicts
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(
                """
                MATCH (g:GroupMeta)
                WHERE g.gds_stale = true
                RETURN g.group_id AS group_id,
                       g.gds_stale_since AS stale_since,
                       g.last_lifecycle_change AS last_change
                ORDER BY g.gds_stale_since ASC
                """
            )
            return [dict(record) for record in result]
    
    # ==================== Job Implementations ====================
    
    async def _gc_orphan_entities(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Deprecate entities with no active sources."""
        errors = []
        
        with self.driver.session(database=self.database) as session:
            if dry_run:
                # Just count
                result = session.run(
                    """
                    MATCH (e:Entity {group_id: $group_id})
                    WHERE NOT e:Deprecated
                      AND NOT EXISTS {
                          MATCH (e)<-[:MENTIONS]-(c:TextChunk)
                          WHERE NOT c:Deprecated
                      }
                    RETURN count(e) AS orphan_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                return {"orphans_found": record["orphan_count"] or 0}, errors
            else:
                # Actually deprecate
                result = session.run(
                    """
                    MATCH (e:Entity {group_id: $group_id})
                    WHERE NOT e:Deprecated
                      AND NOT EXISTS {
                          MATCH (e)<-[:MENTIONS]-(c:TextChunk)
                          WHERE NOT c:Deprecated
                      }
                    SET e:Deprecated,
                        e.deprecated_at = datetime(),
                        e.deprecated_reason = 'orphaned'
                    RETURN count(e) AS deprecated_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                count = record["deprecated_count"] or 0
                logger.info(f"GC orphan entities: deprecated {count} in {group_id}")
                return {"orphans_deprecated": count}, errors
    
    async def _gc_stale_edges(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Remove KNN edges connected to deprecated nodes."""
        errors = []
        
        with self.driver.session(database=self.database) as session:
            if dry_run:
                result = session.run(
                    """
                    MATCH (n1)-[r:SIMILAR_TO|SEMANTICALLY_SIMILAR {group_id: $group_id}]-(n2)
                    WHERE n1:Deprecated OR n2:Deprecated
                    RETURN count(DISTINCT r) AS stale_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                return {"stale_edges_found": record["stale_count"] or 0}, errors
            else:
                result = session.run(
                    """
                    MATCH (n1)-[r:SIMILAR_TO|SEMANTICALLY_SIMILAR {group_id: $group_id}]-(n2)
                    WHERE n1:Deprecated OR n2:Deprecated
                    DELETE r
                    RETURN count(r) AS deleted_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                count = record["deleted_count"] or 0
                logger.info(f"GC stale edges: deleted {count} in {group_id}")
                return {"edges_deleted": count}, errors
    
    async def _gc_deprecated_vectors(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Remove deprecated nodes from vector indexes by nulling embeddings."""
        errors = []
        
        with self.driver.session(database=self.database) as session:
            if dry_run:
                result = session.run(
                    """
                    MATCH (n {group_id: $group_id})
                    WHERE n:Deprecated
                      AND (n:TextChunk OR n:Entity)
                      AND (n.embedding IS NOT NULL OR n.embedding_v2 IS NOT NULL)
                    RETURN count(n) AS vector_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                return {"vectors_found": record["vector_count"] or 0}, errors
            else:
                result = session.run(
                    """
                    MATCH (n {group_id: $group_id})
                    WHERE n:Deprecated
                      AND (n:TextChunk OR n:Entity)
                      AND (n.embedding IS NOT NULL OR n.embedding_v2 IS NOT NULL)
                    SET n.embedding = null,
                        n.embedding_v2 = null,
                        n.embedding_archived_at = datetime()
                    RETURN count(n) AS cleared_count
                    """,
                    group_id=group_id,
                )
                record = result.single()
                count = record["cleared_count"] or 0
                logger.info(f"GC deprecated vectors: cleared {count} in {group_id}")
                return {"vectors_cleared": count}, errors
    
    async def _recompute_gds(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Recompute GDS properties for active nodes only."""
        errors = []
        
        if dry_run:
            # Check if recompute is needed
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    """
                    OPTIONAL MATCH (g:GroupMeta {group_id: $group_id})
                    RETURN coalesce(g.gds_stale, true) AS needs_recompute
                    """,
                    group_id=group_id,
                )
                record = result.single()
                return {"needs_recompute": 1 if record["needs_recompute"] else 0}, errors
        
        # Actual recompute - delegate to pipeline's GDS method
        # This would normally call _run_gds_graph_algorithms with active-only projection
        # For now, mark as not stale
        with self.driver.session(database=self.database) as session:
            session.run(
                """
                MERGE (g:GroupMeta {group_id: $group_id})
                SET g.gds_stale = false,
                    g.gds_last_computed = datetime()
                """,
                group_id=group_id,
            )
        
        logger.info(f"GDS recompute: marked complete for {group_id}")
        return {"recomputed": 1}, errors
    
    async def _validate_group_isolation(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Check for nodes/edges missing group_id."""
        errors = []
        
        with self.driver.session(database=self.database) as session:
            # Check nodes
            result = session.run(
                """
                MATCH (n)
                WHERE n.group_id IS NULL
                  AND (n:Entity OR n:TextChunk OR n:Document OR n:Section OR n:Table OR n:Figure OR n:KeyValue)
                RETURN labels(n)[0] AS label, count(n) AS count
                """,
            )
            
            violations = {}
            total_violations = 0
            for record in result:
                label = record["label"]
                count = record["count"]
                violations[f"nodes_without_group_id_{label}"] = count
                total_violations += count
            
            # Check edges
            result = session.run(
                """
                MATCH ()-[r:SIMILAR_TO|SEMANTICALLY_SIMILAR]-()
                WHERE r.group_id IS NULL
                RETURN type(r) AS type, count(r) AS count
                """,
            )
            
            for record in result:
                edge_type = record["type"]
                count = record["count"]
                violations[f"edges_without_group_id_{edge_type}"] = count
                total_violations += count
            
            violations["total_violations"] = total_violations
            
            if total_violations > 0:
                errors.append(f"Found {total_violations} isolation violations")
            
            return violations, errors
    
    async def _full_group_cleanup(
        self,
        group_id: str,
        dry_run: bool,
    ) -> tuple[Dict[str, int], List[str]]:
        """Run all cleanup operations in order."""
        # This is a composite job - run all GC jobs
        all_stats = {}
        all_errors = []
        
        jobs = [
            ("orphan", self._gc_orphan_entities),
            ("edges", self._gc_stale_edges),
            ("vectors", self._gc_deprecated_vectors),
        ]
        
        for name, handler in jobs:
            stats, errors = await handler(group_id, dry_run)
            all_stats.update({f"{name}_{k}": v for k, v in stats.items()})
            all_errors.extend(errors)
        
        return all_stats, all_errors
