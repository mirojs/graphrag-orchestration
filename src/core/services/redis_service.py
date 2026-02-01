"""
Redis Service for Distributed State Management

Provides:
- DistributedLock: Per-graph write locks with TTL and heartbeat renewal
- RedisOperationStore: Job state CRUD (replaces in-memory dicts)
- RedisResultStore: Async job results with TTL
- RedisJobQueue: DLQ-safe job queue with BRPOPLPUSH

Enables multi-instance scaling by moving all state to Redis.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, AsyncIterator

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

def get_redis_url() -> str:
    """Build Redis URL from environment variables."""
    host = os.getenv("REDIS_HOST")
    port = int(os.getenv("REDIS_PORT", "6380"))
    password = os.getenv("REDIS_PASSWORD")
    
    if not host or not password:
        raise ValueError("REDIS_HOST and REDIS_PASSWORD environment variables are required")
    
    return f"rediss://:{password}@{host}:{port}"


# =============================================================================
# Distributed Lock
# =============================================================================

class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired."""
    pass


class DistributedLock:
    """
    Redis-based distributed lock with TTL and heartbeat renewal.
    
    Usage:
        async with DistributedLock(redis, "lock:tenant:graph:write") as lock:
            # Critical section - only one worker can be here per key
            await do_indexing()
    
    Features:
    - Auto-expiry (TTL) prevents zombie locks if holder crashes
    - Heartbeat renewal keeps lock alive during long operations
    - Unique owner ID ensures only holder can release
    """
    
    def __init__(
        self,
        redis_client: aioredis.Redis,
        key: str,
        ttl_seconds: int = 60,
        heartbeat_interval: int = 20,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
    ):
        self.redis = redis_client
        self.key = key
        self.ttl = ttl_seconds
        self.heartbeat_interval = heartbeat_interval
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.owner_id = str(uuid.uuid4())
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._acquired = False
    
    async def acquire(self) -> bool:
        """
        Attempt to acquire the lock.
        
        Returns True if acquired, False if already held by another owner.
        """
        for attempt in range(self.retry_attempts):
            # SET NX EX: Set if Not eXists with EXpiry
            acquired = await self.redis.set(
                self.key,
                self.owner_id,
                nx=True,
                ex=self.ttl
            )
            
            if acquired:
                self._acquired = True
                self._start_heartbeat()
                logger.info(f"Lock acquired: {self.key} (owner={self.owner_id[:8]})")
                return True
            
            # Check who holds the lock (for debugging)
            current_owner = await self.redis.get(self.key)
            logger.debug(f"Lock held by {current_owner[:8] if current_owner else 'unknown'}, retry {attempt + 1}/{self.retry_attempts}")
            
            if attempt < self.retry_attempts - 1:
                await asyncio.sleep(self.retry_delay)
        
        return False
    
    async def release(self) -> bool:
        """
        Release the lock if we own it.
        
        Uses Lua script for atomic check-and-delete.
        """
        if not self._acquired:
            return False
        
        # Stop heartbeat first
        self._stop_heartbeat()
        
        # Atomic: only delete if we still own it
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        
        try:
            result = await self.redis.eval(lua_script, 1, self.key, self.owner_id)
            released = result == 1
            
            if released:
                logger.info(f"Lock released: {self.key}")
            else:
                logger.warning(f"Lock release failed (not owner): {self.key}")
            
            self._acquired = False
            return released
        except Exception as e:
            logger.error(f"Lock release error: {e}")
            self._acquired = False
            return False
    
    def _start_heartbeat(self):
        """Start background task to renew lock TTL."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    
    def _stop_heartbeat(self):
        """Stop heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
    
    async def _heartbeat_loop(self):
        """Periodically renew lock TTL while held."""
        try:
            while self._acquired:
                await asyncio.sleep(self.heartbeat_interval)
                
                if not self._acquired:
                    break
                
                # Atomic: only extend if we still own it
                lua_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("expire", KEYS[1], ARGV[2])
                else
                    return 0
                end
                """
                
                result = await self.redis.eval(lua_script, 1, self.key, self.owner_id, self.ttl)
                
                if result == 1:
                    logger.debug(f"Lock heartbeat: {self.key} extended by {self.ttl}s")
                else:
                    logger.warning(f"Lock heartbeat failed (lost ownership): {self.key}")
                    self._acquired = False
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Lock heartbeat error: {e}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        if not await self.acquire():
            raise LockAcquisitionError(f"Failed to acquire lock: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.release()
        return False  # Don't suppress exceptions


# =============================================================================
# Operation Store (Job State)
# =============================================================================

class OperationStatus(str, Enum):
    """Job status enum."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Operation:
    """Job operation record."""
    id: str
    status: OperationStatus
    created_at: str
    updated_at: str
    tenant_id: str
    operation_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: int = 0  # 0-100


class RedisOperationStore:
    """
    Redis-backed operation state store.
    
    Replaces in-memory dicts to enable multi-instance scaling.
    Operations expire after TTL to prevent unbounded growth.
    """
    
    KEY_PREFIX = "graphrag:operation"
    DEFAULT_TTL = 3600  # 1 hour
    
    def __init__(self, redis_client: aioredis.Redis, ttl_seconds: int = DEFAULT_TTL):
        self.redis = redis_client
        self.ttl = ttl_seconds
    
    def _key(self, operation_id: str) -> str:
        return f"{self.KEY_PREFIX}:{operation_id}"
    
    async def create(
        self,
        operation_id: str,
        tenant_id: str,
        operation_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Operation:
        """Create a new operation record."""
        now = datetime.utcnow().isoformat()
        
        operation = Operation(
            id=operation_id,
            status=OperationStatus.PENDING,
            created_at=now,
            updated_at=now,
            tenant_id=tenant_id,
            operation_type=operation_type,
            metadata=metadata or {}
        )
        
        await self.redis.setex(
            self._key(operation_id),
            self.ttl,
            json.dumps(asdict(operation))
        )
        
        logger.info(f"Operation created: {operation_id} ({operation_type})")
        return operation
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """Get operation by ID."""
        data = await self.redis.get(self._key(operation_id))
        
        if not data:
            return None
        
        obj = json.loads(data)
        obj["status"] = OperationStatus(obj["status"])
        return Operation(**obj)
    
    async def update(
        self,
        operation_id: str,
        status: Optional[OperationStatus] = None,
        progress: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None
    ) -> Optional[Operation]:
        """Update operation fields."""
        operation = await self.get(operation_id)
        
        if not operation:
            logger.warning(f"Operation not found for update: {operation_id}")
            return None
        
        if status:
            operation.status = status
        if progress is not None:
            operation.progress = progress
        if result is not None:
            operation.result = result
        if error is not None:
            operation.error = error
        if metadata_update:
            operation.metadata.update(metadata_update)
        
        operation.updated_at = datetime.utcnow().isoformat()
        
        await self.redis.setex(
            self._key(operation_id),
            self.ttl,
            json.dumps(asdict(operation))
        )
        
        logger.info(f"Operation updated: {operation_id} -> {status}")
        return operation
    
    async def delete(self, operation_id: str) -> bool:
        """Delete operation."""
        result = await self.redis.delete(self._key(operation_id))
        return result > 0
    
    async def list_by_tenant(self, tenant_id: str, limit: int = 100) -> List[Operation]:
        """
        List operations for a tenant.
        
        Note: This scans keys, which is O(N). For production with many operations,
        consider using a sorted set index.
        """
        operations = []
        cursor = 0
        
        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=f"{self.KEY_PREFIX}:*",
                count=100
            )
            
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    obj = json.loads(data)
                    if obj.get("tenant_id") == tenant_id:
                        obj["status"] = OperationStatus(obj["status"])
                        operations.append(Operation(**obj))
                        
                        if len(operations) >= limit:
                            return operations
            
            if cursor == 0:
                break
        
        return operations


# =============================================================================
# Result Store (Async Job Results)
# =============================================================================

class RedisResultStore:
    """
    Redis-backed result store for async job outputs.
    
    Workers write results here; API Gateway reads them.
    Results expire after TTL.
    """
    
    KEY_PREFIX = "graphrag:result"
    DEFAULT_TTL = 3600  # 1 hour
    
    def __init__(self, redis_client: aioredis.Redis, ttl_seconds: int = DEFAULT_TTL):
        self.redis = redis_client
        self.ttl = ttl_seconds
    
    def _key(self, job_id: str) -> str:
        return f"{self.KEY_PREFIX}:{job_id}"
    
    async def store(self, job_id: str, result: Dict[str, Any]) -> None:
        """Store job result."""
        await self.redis.setex(
            self._key(job_id),
            self.ttl,
            json.dumps(result)
        )
        logger.info(f"Result stored: {job_id}")
    
    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job result."""
        data = await self.redis.get(self._key(job_id))
        
        if not data:
            return None
        
        return json.loads(data)
    
    async def delete(self, job_id: str) -> bool:
        """Delete result."""
        result = await self.redis.delete(self._key(job_id))
        return result > 0
    
    async def exists(self, job_id: str) -> bool:
        """Check if result exists."""
        return await self.redis.exists(self._key(job_id)) > 0


# =============================================================================
# Job Queue (DLQ-Safe)
# =============================================================================

@dataclass
class Job:
    """Job queue item."""
    id: str
    tenant_id: str
    job_type: str
    payload: Dict[str, Any]
    created_at: str
    idempotency_key: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3


class RedisJobQueue:
    """
    Redis-backed job queue with Dead Letter Queue support.
    
    Uses BRPOPLPUSH for atomic pop-and-push to processing list.
    If worker crashes, jobs remain in processing list for recovery.
    """
    
    QUEUE_KEY = "graphrag:jobs:pending"
    PROCESSING_KEY = "graphrag:jobs:processing"
    DLQ_KEY = "graphrag:jobs:dlq"
    IDEMPOTENCY_PREFIX = "graphrag:idempotency"
    
    DEFAULT_VISIBILITY_TIMEOUT = 600  # 10 minutes
    
    def __init__(
        self,
        redis_client: aioredis.Redis,
        visibility_timeout: int = DEFAULT_VISIBILITY_TIMEOUT
    ):
        self.redis = redis_client
        self.visibility_timeout = visibility_timeout
    
    async def enqueue(self, job: Job) -> bool:
        """
        Add job to queue.
        
        Returns False if duplicate (idempotency key exists).
        """
        # Check idempotency
        if job.idempotency_key:
            idem_key = f"{self.IDEMPOTENCY_PREFIX}:{job.idempotency_key}"
            
            # Set idempotency key with 24h TTL
            was_set = await self.redis.set(idem_key, "1", nx=True, ex=86400)
            
            if not was_set:
                logger.info(f"Duplicate job rejected: {job.idempotency_key}")
                return False
        
        job_data = json.dumps(asdict(job))
        await self.redis.lpush(self.QUEUE_KEY, job_data)
        
        logger.info(f"Job enqueued: {job.id} ({job.job_type})")
        return True
    
    async def dequeue(self, timeout: int = 0) -> Optional[Job]:
        """
        Pop job from queue atomically.
        
        Uses BRPOPLPUSH: pops from pending, pushes to processing.
        If timeout=0, blocks indefinitely until job available.
        """
        result = await self.redis.brpoplpush(
            self.QUEUE_KEY,
            self.PROCESSING_KEY,
            timeout=timeout
        )
        
        if not result:
            return None
        
        job_data = json.loads(result)
        job_data["attempts"] += 1
        
        # Update in processing list with new attempt count
        # (We'll update when acknowledging)
        
        return Job(**job_data)
    
    async def ack(self, job: Job) -> None:
        """
        Acknowledge job completion.
        
        Removes from processing list.
        """
        job_data = json.dumps(asdict(job))
        await self.redis.lrem(self.PROCESSING_KEY, 1, job_data)
        logger.info(f"Job acknowledged: {job.id}")
    
    async def nack(self, job: Job, requeue: bool = True) -> None:
        """
        Negative acknowledge (job failed).
        
        If requeue=True and attempts < max, puts back in queue.
        Otherwise, moves to DLQ.
        """
        # Remove from processing
        original_data = json.dumps(asdict(job))
        await self.redis.lrem(self.PROCESSING_KEY, 1, original_data)
        
        if requeue and job.attempts < job.max_attempts:
            # Re-queue for retry
            await self.redis.lpush(self.QUEUE_KEY, json.dumps(asdict(job)))
            logger.info(f"Job re-queued: {job.id} (attempt {job.attempts}/{job.max_attempts})")
        else:
            # Move to DLQ
            await self.redis.lpush(self.DLQ_KEY, json.dumps(asdict(job)))
            logger.warning(f"Job moved to DLQ: {job.id} (attempts exhausted)")
    
    async def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        pending = await self.redis.llen(self.QUEUE_KEY)
        processing = await self.redis.llen(self.PROCESSING_KEY)
        dlq = await self.redis.llen(self.DLQ_KEY)
        
        return {
            "pending": pending,
            "processing": processing,
            "dlq": dlq
        }
    
    async def recover_stale_jobs(self, max_age_seconds: int = 600) -> int:
        """
        Recover jobs stuck in processing for too long.
        
        Moves them back to pending queue for retry.
        Call this periodically from a sweeper task.
        """
        # Get all processing jobs
        jobs_data = await self.redis.lrange(self.PROCESSING_KEY, 0, -1)
        recovered = 0
        
        now = datetime.utcnow()
        
        for job_data in jobs_data:
            job_dict = json.loads(job_data)
            created = datetime.fromisoformat(job_dict["created_at"])
            age = (now - created).total_seconds()
            
            if age > max_age_seconds:
                job = Job(**job_dict)
                await self.nack(job, requeue=True)
                recovered += 1
        
        if recovered > 0:
            logger.info(f"Recovered {recovered} stale jobs")
        
        return recovered


# =============================================================================
# Service Factory
# =============================================================================

class RedisService:
    """
    Unified Redis service providing all distributed state management.
    
    Usage:
        service = await RedisService.create()
        
        # Lock for indexing
        async with service.lock(f"lock:{tenant}:{graph}:write"):
            await do_indexing()
        
        # Track operations
        op = await service.operations.create(op_id, tenant, "indexing")
        await service.operations.update(op_id, status=OperationStatus.COMPLETED)
        
        # Store/retrieve results
        await service.results.store(job_id, {"answer": "..."})
        result = await service.results.get(job_id)
        
        # Queue jobs
        await service.queue.enqueue(job)
        job = await service.queue.dequeue()
    """
    
    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self.operations = RedisOperationStore(redis_client)
        self.results = RedisResultStore(redis_client)
        self.queue = RedisJobQueue(redis_client)
    
    @classmethod
    async def create(cls, redis_url: Optional[str] = None) -> "RedisService":
        """Create RedisService with connection."""
        url = redis_url or get_redis_url()
        
        client = aioredis.from_url(
            url,
            decode_responses=True,
            ssl_cert_reqs=None  # Azure Redis uses managed certs
        )
        
        # Test connection
        await client.ping()
        logger.info("Redis connection established")
        
        return cls(client)
    
    @asynccontextmanager
    async def lock(
        self,
        key: str,
        ttl_seconds: int = 60,
        heartbeat_interval: int = 20
    ) -> AsyncIterator[DistributedLock]:
        """
        Acquire a distributed lock.
        
        Usage:
            async with service.lock("lock:tenant:graph:write"):
                # Critical section
        """
        lock = DistributedLock(
            self._redis,
            key,
            ttl_seconds=ttl_seconds,
            heartbeat_interval=heartbeat_interval
        )
        
        try:
            if not await lock.acquire():
                raise LockAcquisitionError(f"Failed to acquire lock: {key}")
            yield lock
        finally:
            await lock.release()
    
    async def close(self):
        """Close Redis connection."""
        await self._redis.close()
        logger.info("Redis connection closed")


# =============================================================================
# Singleton Instance
# =============================================================================

_redis_service: Optional[RedisService] = None


async def get_redis_service() -> RedisService:
    """Get or create singleton RedisService instance."""
    global _redis_service
    
    if _redis_service is None:
        _redis_service = await RedisService.create()
    
    return _redis_service


async def close_redis_service():
    """Close singleton RedisService."""
    global _redis_service
    
    if _redis_service:
        await _redis_service.close()
        _redis_service = None
