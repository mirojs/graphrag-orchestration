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
        self.running = True
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
                
                # TODO: Implement indexing via orchestrator
                logger.info(f"Indexing document {document_id}")
                
                return {
                    'job_id': job_id,
                    'status': 'completed',
                    'result': {'document_id': document_id, 'indexed': True},
                    'duration_ms': (datetime.utcnow() - start_time).total_seconds() * 1000
                }
                
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
            
    async def store_result(self, job_id: str, result: dict):
        """Store job result in Redis for retrieval by API."""
        if not self.redis_service:
            logger.warning(f"Cannot store result for job {job_id}: Redis not connected")
            return
            
        await self.redis_service.results.store(job_id, result)
        logger.debug(f"Stored result for job {job_id}")
        
    async def run(self):
        """Main worker loop - consume and process jobs with DLQ support."""
        logger.info(f"Worker {self.worker_id} started, listening for jobs...")
        
        if not self.redis_service:
            logger.error("Cannot run worker: Redis not connected")
            return
        
        queue = self.redis_service.queue
        
        while self.running:
            try:
                # Dequeue with BRPOPLPUSH (DLQ-safe)
                job = await queue.dequeue(timeout=5)
                
                if job is None:
                    # Timeout - no jobs available, continue loop
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
                else:
                    # Query jobs don't need locks
                    job_result = await self.process_job(job.__dict__)
                
                # Store result for retrieval by API
                await self.store_result(job.id, job_result)
                
                # Acknowledge job completion
                await queue.ack(job)
                
            except Exception as e:
                logger.exception(f"Error processing job: {e}")
                if 'job' in locals() and job:
                    await queue.nack(job, requeue=True)
                await asyncio.sleep(1)
                
        logger.info(f"Worker {self.worker_id} stopped")
        
    def handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False


async def main():
    """Entry point for the worker."""
    worker = Worker()
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, worker.handle_signal)
    signal.signal(signal.SIGINT, worker.handle_signal)
    
    try:
        await worker.connect()
        await worker.run()
    finally:
        await worker.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
