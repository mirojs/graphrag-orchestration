"""
GraphRAG Worker - Background Job Processor

Consumes jobs from Redis queue and processes them using the HybridOrchestrator.
Runs as a separate container from the API Gateway for independent scaling.

Multi-instance Notes:
- Uses BRPOPLPUSH for DLQ-safe job consumption
- Stores results in RedisResultStore for cross-instance visibility
- Implements distributed locking for indexing operations
"""
import asyncio
import json
import os
import signal
import sys
import logging
import threading

# Suppress "None of PyTorch, TensorFlow..." warning from transformers (used by wtpsplit)
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

# Suppress Neo4j advisory notifications (property/label/rel-type doesn't exist yet)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis

from src.worker.hybrid_v2 import HybridPipeline
from src.core.services.usage_tracker import UsageTracker
from src.core.services.redis_service import (
    get_redis_service,
    RedisService,
    RedisJobQueue,
    Job,
    LockAcquisitionError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Worker:
    """Background worker that processes jobs from Redis queue."""
    
    def __init__(self):
        self.redis_service: Optional[RedisService] = None
        self.orchestrator: Optional[HybridPipeline] = None
        self.usage_tracker: Optional[UsageTracker] = None
        self._stop_event = threading.Event()
        self.worker_id = f"worker-{os.getpid()}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
    async def connect(self):
        """Initialize connections to Redis and other services."""
        # Use RedisService for unified state management
        self.redis_service = await get_redis_service()
        logger.info(f"Worker {self.worker_id} connected to Redis")
        
        # Initialize orchestrator
        self.orchestrator = HybridPipeline()
        logger.info("HybridPipeline initialized")
        
        # Initialize usage tracker (uses singleton Cosmos client internally)
        self.usage_tracker = UsageTracker()
        logger.info("UsageTracker initialized")
            
    async def disconnect(self):
        """Clean up connections."""
        if self.redis_service:
            await self.redis_service.close()
            logger.info("Redis connection closed")
            
    async def process_job(self, job_data: dict) -> dict:
        """
        Process a single job from the queue.
        
        Supports both legacy format and new Job dataclass format:
        
        Legacy format:
        {
            "job_id": "uuid",
            "type": "query|index|reindex",
            "group_id": "tenant-group-id",
            ...
        }
        
        New Job format (from RedisJobQueue):
        {
            "id": "uuid",
            "job_type": "query|index|reindex",
            "tenant_id": "tenant-group-id",
            "payload": {...},
            ...
        }
        """
        # Handle both old and new formats
        job_id = job_data.get('id') or job_data.get('job_id', 'unknown')
        job_type = job_data.get('job_type') or job_data.get('type', 'query')
        group_id = job_data.get('tenant_id') or job_data.get('group_id', '')
        user_id = job_data.get('user_id', '')
        payload = job_data.get('payload', {})
        
        logger.info(f"Processing job {job_id} (type={job_type}, group={group_id})")
        start_time = datetime.utcnow()
        
        try:
            if job_type == 'query':
                # Run orchestrator query
                query = payload.get('query', '')
                
                if not self.orchestrator:
                    raise RuntimeError("Orchestrator not initialized")
                    
                result = await self.orchestrator.query(query=query)
                
                # Track LLM usage if available in result
                if self.usage_tracker and result.get('usage'):
                    usage = result['usage']
                    await self.usage_tracker.log_llm_usage(
                        partition_id=group_id,
                        model=usage.get('model', 'unknown'),
                        prompt_tokens=usage.get('prompt_tokens', 0),
                        completion_tokens=usage.get('completion_tokens', 0),
                        user_id=user_id,
                        route=result.get('route', 'unknown'),
                        query_id=job_id
                    )
                    
                return {
                    'job_id': job_id,
                    'status': 'completed',
                    'result': result,
                    'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000
                }
                
            elif job_type == 'index':
                # Document indexing job
                document_id = payload.get('document_id')
                content = payload.get('content')
                metadata = payload.get('metadata', {})
                
                logger.info(f"Indexing document {document_id}")
                
                from src.worker.hybrid_v2.indexing.pipeline_factory import (
                    get_lazygraphrag_indexing_pipeline_v2,
                )
                
                pipeline = get_lazygraphrag_indexing_pipeline_v2()
                doc = {
                    'document_id': document_id,
                    'content': content,
                    **(metadata or {}),
                }
                index_result = await pipeline.index_documents(
                    group_id=group_id,
                    documents=[doc],
                    reindex=payload.get('reindex', False),
                )
                
                return {
                    'job_id': job_id,
                    'status': 'completed',
                    'result': {'document_id': document_id, 'indexed': True, **index_result},
                    'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000
                }

            elif job_type == 'index_folder':
                # Folder analysis job — runs the full indexing pipeline for all
                # files in a folder, with per-file progress and resume support.
                # This decouples the heavy pipeline from the API process.
                return await self._process_index_folder(
                    job_id=job_id,
                    group_id=group_id,
                    payload=payload,
                    start_time=start_time,
                )
                
            else:
                logger.warning(f"Unknown job type: {job_type}")
                return {
                    'job_id': job_id,
                    'status': 'failed',
                    'error': f'Unknown job type: {job_type}'
                }
                
        except Exception as e:
            logger.exception(f"Error processing job {job_id}: {e}")
            return {
                'job_id': job_id,
                'status': 'failed',
                'error': str(e),
                'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000
            }

    async def _process_index_folder(
        self, *, job_id: str, group_id: str, payload: dict, start_time
    ) -> dict:
        """Process an index_folder job: run full pipeline for all files in a folder.

        Payload keys:
            folder_id, folder_name, neo4j_gid, partition_id,
            blobs: [{name, url}, ...]
        """
        import traceback
        from neo4j import GraphDatabase
        from src.core.config import settings
        from src.api_gateway.services.document_sync import DocumentSyncService

        folder_id = payload["folder_id"]
        folder_name = payload["folder_name"]
        neo4j_gid = payload["neo4j_gid"]
        partition_id = payload["partition_id"]
        blobs = payload["blobs"]
        file_count = len(blobs)

        logger.info(f"index_folder_start folder_id={folder_id} files={file_count}")

        # Worker-local Neo4j session helper
        _driver_cache = {}

        def _get_driver():
            if "d" not in _driver_cache or _driver_cache["d"] is None:
                _driver_cache["d"] = GraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
                    max_connection_lifetime=300,
                    max_connection_pool_size=10,
                )
            return _driver_cache["d"]

        def _neo4j_session():
            db = getattr(settings, "NEO4J_DATABASE", None) or "neo4j"
            return _get_driver().session(database=db)

        doc_sync = DocumentSyncService()

        try:
            # ── File-level resume (name-based) ──
            files_done: set = set()
            phase2_complete = False
            with _neo4j_session() as session:
                rec = session.run(
                    "MATCH (f:Folder {id: $fid, group_id: $pid}) "
                    "RETURN f.analysis_files_done AS done, f.analysis_status AS status, "
                    "       f.phase2_complete AS p2",
                    fid=folder_id, pid=partition_id,
                ).single()
                if rec and rec["status"] == "analyzing":
                    raw_done = rec["done"]
                    if raw_done:
                        import json as _json
                        files_done = set(_json.loads(raw_done))
                    phase2_complete = bool(rec["p2"])
                    if files_done:
                        logger.info(f"index_folder_resume done={len(files_done)}/{file_count}")

            # Set total count
            with _neo4j_session() as session:
                session.run(
                    "MATCH (f:Folder {id: $fid, group_id: $pid}) "
                    "SET f.analysis_files_total = $total, f.analysis_files_processed = $processed",
                    fid=folder_id, pid=partition_id, total=file_count, processed=len(files_done),
                )

            # ── Parallel per-file extraction (steps 1-7 only) ──
            # Graph-wide steps (7.5-9: triple embeddings, synonymy edges,
            # KNN, Louvain, communities) are deferred to after all docs are
            # extracted — running them per-doc is wasted work since each
            # subsequent doc deletes and rebuilds them.
            import asyncio as _aio
            import json as _json
            _extract_sem = _aio.Semaphore(int(os.environ.get("INDEX_PARALLEL_DOCS", "3")))
            _progress_lock = _aio.Lock()

            pending_blobs = [b for b in blobs if b["name"] not in files_done]
            if pending_blobs:
                logger.info(f"index_folder_extract pending={len(pending_blobs)} skip={len(files_done)}")

                async def _extract_one(blob: dict) -> None:
                    async with _extract_sem:
                        logger.info(f"index_file_start: {blob['name']}")
                        await doc_sync.on_file_uploaded(
                            group_id=neo4j_gid,
                            filename=blob["name"],
                            blob_url=blob["url"],
                            user_id=partition_id,
                            extraction_only=True,
                        )
                        async with _progress_lock:
                            files_done.add(blob["name"])
                            with _neo4j_session() as session:
                                session.run(
                                    "MATCH (f:Folder {id: $fid, group_id: $pid}) "
                                    "SET f.analysis_files_processed = $processed, "
                                    "    f.analysis_files_done = $done",
                                    fid=folder_id, pid=partition_id,
                                    processed=len(files_done),
                                    done=_json.dumps(sorted(files_done)),
                                )
                        logger.info(f"index_file_done {len(files_done)}/{file_count}: {blob['name']}")

                tasks = [_extract_one(blob) for blob in pending_blobs]
                await _aio.gather(*tasks)
            else:
                logger.info("index_folder_extract all files already done, skipping Phase 1")

            # ── Graph algorithms (steps 7.5-9) — run ONCE on full graph ──
            graph_stats = {}
            graph_errors = []
            if not phase2_complete:
                logger.info(f"index_folder_graph_algorithms group={neo4j_gid} files={file_count}")
                graph_stats = await doc_sync.pipeline.run_graph_algorithms_only(
                    group_id=neo4j_gid,
                )

                # Mark phase 2 complete so resume skips it
                with _neo4j_session() as session:
                    session.run(
                        "MATCH (f:Folder {id: $fid, group_id: $pid}) SET f.phase2_complete = true",
                        fid=folder_id, pid=partition_id,
                    )

                # ── Check for critical failures ──
                graph_errors = graph_stats.get("errors", [])
                graph_success = graph_stats.get("success", True)
                if not graph_success:
                    failed_steps = ", ".join(e["step"] for e in graph_errors if e["step"] in ("triple_embeddings", "gds"))
                    error_details = "; ".join(f'{e["step"]}: {e["error"]}' for e in graph_errors)
                    raise RuntimeError(
                        f"Graph algorithms failed on critical steps ({failed_steps}): {error_details}"
                    )
            else:
                logger.info("index_folder_phase2_already_done, skipping graph algorithms")

            # ── Collect stats ──
            stats_query = """
            OPTIONAL MATCH (e:Entity {group_id: $gid})
            WITH count(e) as entity_count
            OPTIONAL MATCH (c:Community {group_id: $gid})
            WITH entity_count, count(c) as community_count
            OPTIONAL MATCH (sec:Section {group_id: $gid})
            WITH entity_count, community_count, count(sec) as section_count
            OPTIONAL MATCH (sent:Sentence {group_id: $gid})
            WITH entity_count, community_count, section_count, count(sent) as sentence_count
            OPTIONAL MATCH (:Entity {group_id: $gid})-[r:RELATED_TO]->()
            RETURN entity_count, community_count, section_count, sentence_count,
                   count(r) as relationship_count
            """
            entity_count = community_count = section_count = sentence_count = relationship_count = 0
            with _neo4j_session() as session:
                record = session.run(stats_query, gid=neo4j_gid).single()
                if record:
                    entity_count = record["entity_count"]
                    community_count = record["community_count"]
                    section_count = record["section_count"]
                    sentence_count = record["sentence_count"]
                    relationship_count = record["relationship_count"]

            # Log non-critical warnings (synonymy, communities) without failing
            if graph_errors:
                non_critical = [e for e in graph_errors if e["step"] not in ("triple_embeddings", "gds")]
                if non_critical:
                    logger.warning(
                        f"index_folder_non_critical_warnings: "
                        + "; ".join(f'{e["step"]}: {e["error"][:100]}' for e in non_critical)
                    )

            # ── Mark complete ──
            with _neo4j_session() as session:
                session.run(
                    """
                    MATCH (f:Folder {id: $fid, group_id: $pid})
                    OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
                    WITH collect(f) + collect(sub) AS folders
                    UNWIND folders AS fld
                    SET fld.analysis_status = 'analyzed',
                        fld.analyzed_at = datetime(),
                        fld.file_count = $file_count,
                        fld.entity_count = $entity_count,
                        fld.community_count = $community_count,
                        fld.section_count = $section_count,
                        fld.sentence_count = $sentence_count,
                        fld.relationship_count = $relationship_count,
                        fld.analysis_files_total = null,
                        fld.analysis_files_processed = null,
                        fld.analysis_files_done = null,
                        fld.phase2_complete = null,
                        fld.analysis_error = null,
                        fld.updated_at = datetime()
                    """,
                    fid=folder_id, pid=partition_id, file_count=file_count,
                    entity_count=entity_count, community_count=community_count,
                    section_count=section_count, sentence_count=sentence_count,
                    relationship_count=relationship_count,
                )

            logger.info(
                f"index_folder_complete folder_id={folder_id} entities={entity_count} "
                f"sentences={sentence_count} communities={community_count}"
            )
            return {
                'job_id': job_id,
                'status': 'completed',
                'result': {
                    'folder_id': folder_id,
                    'entity_count': entity_count,
                    'community_count': community_count,
                    'section_count': section_count,
                    'sentence_count': sentence_count,
                    'relationship_count': relationship_count,
                },
                'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000,
            }

        except Exception as e:
            logger.exception(f"index_folder_failed folder_id={folder_id}: {e}")
            # Mark folder as stale with error
            try:
                with _neo4j_session() as session:
                    session.run(
                        """
                        MATCH (f:Folder {id: $fid, group_id: $pid})
                        OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
                        WITH collect(f) + collect(sub) AS folders
                        UNWIND folders AS fld
                        SET fld.analysis_status = 'stale',
                            fld.analysis_error = $err,
                            fld.analysis_files_total = null,
                            fld.analysis_files_processed = null,
                            fld.updated_at = datetime()
                        """,
                        fid=folder_id, pid=partition_id, err=str(e)[:500],
                    )
            except Exception:
                pass
            return {
                'job_id': job_id,
                'status': 'failed',
                'error': str(e),
                'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000,
            }
        finally:
            try:
                drv = _driver_cache.get("d")
                if drv:
                    drv.close()
            except Exception:
                pass
            
    async def store_result(self, job_id: str, result: dict):
        """Store job result in Redis for retrieval by API."""
        if not self.redis_service:
            logger.warning(f"Cannot store result for job {job_id}: Redis not connected")
            return
            
        await self.redis_service.results.store(job_id, result)
        logger.debug(f"Stored result for job {job_id}")
        
    async def _redis_op_with_retry(self, coro_fn, description: str, retries: int = 3):
        """Execute a Redis operation with retry on transient errors."""
        for attempt in range(1, retries + 1):
            try:
                return await coro_fn()
            except (Exception) as e:
                is_redis_err = isinstance(e, (
                    aioredis.ConnectionError, aioredis.TimeoutError,
                    OSError, ConnectionResetError, TimeoutError,
                ))
                if is_redis_err and attempt < retries:
                    logger.warning(f"{description} failed (attempt {attempt}/{retries}): {e}")
                    await asyncio.sleep(min(2 ** attempt, 10))
                else:
                    raise

    async def run(self):
        """Main worker loop - consume and process jobs with DLQ support."""
        logger.info(f"Worker {self.worker_id} started, listening for jobs...")
        
        if not self.redis_service:
            logger.error("Cannot run worker: Redis not connected")
            return
        
        queue = self.redis_service.queue
        
        while not self._stop_event.is_set():
            try:
                # Dequeue with BRPOPLPUSH (DLQ-safe)
                job = await queue.dequeue(timeout=5)
                
                if job is None:
                    # Timeout or transient Redis error - continue loop
                    continue
                
                logger.info(f"Processing job {job.id} (type={job.job_type}, tenant={job.tenant_id})")
                
                # Check if indexing job needs a lock
                if job.job_type == 'index' and job.payload.get('graph_id'):
                    graph_id = job.payload['graph_id']
                    lock_key = f"lock:{job.tenant_id}:{graph_id}:write"
                    
                    try:
                        async with self.redis_service.lock(lock_key, ttl_seconds=300):
                            job_result = await self.process_job(job.__dict__)
                    except LockAcquisitionError:
                        # Another worker is indexing this graph - NACK and retry later
                        logger.info(f"Graph {graph_id} locked, re-queuing job {job.id}")
                        await queue.nack(job, requeue=True)
                        continue
                elif job.job_type == 'index_folder' and job.payload.get('neo4j_gid'):
                    gid = job.payload['neo4j_gid']
                    lock_key = f"lock:index_folder:{gid}"
                    try:
                        async with self.redis_service.lock(lock_key, ttl_seconds=600):
                            job_result = await self.process_job(job.__dict__)
                    except LockAcquisitionError:
                        logger.info(f"Folder {gid} locked, re-queuing job {job.id}")
                        await queue.nack(job, requeue=True)
                        continue
                else:
                    # Query jobs don't need locks
                    job_result = await self.process_job(job.__dict__)
                
                # Store result for retrieval by API (with retry)
                await self._redis_op_with_retry(
                    lambda: self.store_result(job.id, job_result),
                    f"store_result({job.id})"
                )
                
                # Acknowledge job completion (with retry)
                await self._redis_op_with_retry(
                    lambda: queue.ack(job),
                    f"ack({job.id})"
                )
                
            except Exception as e:
                logger.exception(f"Error processing job: {e}")
                if 'job' in locals() and job:
                    try:
                        await queue.nack(job, requeue=True)
                    except Exception as nack_err:
                        logger.error(f"Failed to nack job {job.id}: {nack_err}")
                await asyncio.sleep(1)
                
        logger.info(f"Worker {self.worker_id} stopped")
        
    def handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self._stop_event.set()


async def main():
    """Entry point for the worker."""
    worker = Worker()
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, worker.handle_signal)
    signal.signal(signal.SIGINT, worker.handle_signal)
    
    # Retry connection with backoff — don't crash-loop on transient Redis issues
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            await worker.connect()
            break
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed to connect after {max_retries} attempts: {e}")
                return
            wait = min(2 ** attempt, 30)
            logger.warning(f"Connection attempt {attempt}/{max_retries} failed: {e}. Retrying in {wait}s...")
            await asyncio.sleep(wait)
    
    try:
        await worker.run()
    finally:
        await worker.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
