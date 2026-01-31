"""
GraphRAG Worker - Background Job Processor

Consumes jobs from Redis queue and processes them using the HybridOrchestrator.
Runs as a separate container from the API Gateway for independent scaling.
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Worker:
    """Background worker that processes jobs from Redis queue."""
    
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.orchestrator: Optional[HybridPipeline] = None
        self.usage_tracker: Optional[UsageTracker] = None
        self.running = True
        self.queue_name = os.getenv('REDIS_QUEUE_NAME', 'graphrag_jobs')
        
    async def connect(self):
        """Initialize connections to Redis and other services."""
        # Redis connection
        redis_host = os.getenv('REDIS_HOST')
        redis_port = int(os.getenv('REDIS_PORT', '6380'))
        redis_password = os.getenv('REDIS_PASSWORD')
        
        if not redis_host or not redis_password:
            logger.error("REDIS_HOST and REDIS_PASSWORD environment variables are required")
            sys.exit(1)
            
        self.redis_client = aioredis.from_url(
            f"rediss://{redis_host}:{redis_port}",
            password=redis_password,
            decode_responses=True,
            ssl_cert_reqs=None  # Azure Redis uses managed certs
        )
        
        # Test connection
        if self.redis_client:
            await self.redis_client.ping()
            logger.info(f"Connected to Redis at {redis_host}:{redis_port}")
        
        # Initialize orchestrator
        self.orchestrator = HybridPipeline()
        logger.info("HybridPipeline initialized")
        
        # Initialize usage tracker (uses singleton Cosmos client internally)
        self.usage_tracker = UsageTracker()
        logger.info("UsageTracker initialized")
            
    async def disconnect(self):
        """Clean up connections."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")
            
    async def process_job(self, job_data: dict) -> dict:
        """
        Process a single job from the queue.
        
        Expected job format:
        {
            "job_id": "uuid",
            "type": "query|index|reindex",
            "group_id": "tenant-group-id",
            "user_id": "user-id", 
            "payload": {
                "query": "...",  # for query type
                "document_id": "...",  # for index/reindex
                ...
            },
            "created_at": "ISO timestamp"
        }
        """
        job_id = job_data.get('job_id', 'unknown')
        job_type = job_data.get('type', 'query')
        group_id = job_data.get('group_id', '')
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
        if not self.redis_client:
            logger.warning(f"Cannot store result for job {job_id}: Redis not connected")
            return
            
        result_key = f"job_result:{job_id}"
        await self.redis_client.setex(
            result_key,
            3600,  # 1 hour TTL
            json.dumps(result)
        )
        logger.debug(f"Stored result for job {job_id}")
        
    async def run(self):
        """Main worker loop - consume and process jobs."""
        logger.info(f"Worker started, listening on queue: {self.queue_name}")
        
        if not self.redis_client:
            logger.error("Cannot run worker: Redis not connected")
            return
        
        while self.running:
            try:
                # BLPOP blocks until a job is available (5 second timeout)
                result = await self.redis_client.blpop(self.queue_name, timeout=5)
                
                if result is None:
                    # Timeout - no jobs available, continue loop
                    continue
                    
                _, job_json = result
                
                try:
                    job_data = json.loads(job_json)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid job JSON: {e}")
                    continue
                    
                # Process the job
                job_result = await self.process_job(job_data)
                
                # Store result for retrieval
                job_id = job_data.get('job_id', 'unknown')
                await self.store_result(job_id, job_result)
                
            except aioredis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")
                await asyncio.sleep(5)  # Wait before reconnecting
                try:
                    await self.connect()
                except Exception:
                    pass
                    
            except Exception as e:
                logger.exception(f"Unexpected error in worker loop: {e}")
                await asyncio.sleep(1)
                
        logger.info("Worker stopped")
        
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
