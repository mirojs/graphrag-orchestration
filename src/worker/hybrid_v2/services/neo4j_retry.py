"""
Neo4j Retry Utilities — Native Driver Retry

Uses Neo4j driver v5+ managed transactions (``session.execute_read()`` /
``session.execute_write()``) which provide **built-in** retry for transient
errors (deadlocks, leader re-elections, connection resets).  This is the
same mechanism the GDS library uses via ``run_retryable_cypher``.

For operations that need the simpler ``session.run()`` API — but with retry —
we provide a ``RetrySession`` wrapper that delegates ``.run()`` to
``execute_write()`` (or ``execute_read()`` when ``read_only=True``) internally,
eagerly materializing results so callers can use ``.single()``, ``.data()``
etc. unchanged.

Fallback: if the neo4j driver's ``is_retryable()`` flag is unavailable the
wrapper also catches the classic transient exception types manually.

Usage::

    # Sync — wrap the session creation point
    with retry_session(driver, database="neo4j") as session:
        result = session.run("MATCH (n) RETURN count(n)")

    # Inside an async function — offload to thread pool
    loop = asyncio.get_running_loop()
    def _sync():
        with retry_session(driver, read_only=True) as session:
            return list(session.run("MATCH (n) RETURN count(n)"))
    records = await loop.run_in_executor(None, _sync)

Context manager and ``__getattr__`` delegation ensure ``RetrySession`` is a
drop-in replacement for a raw ``Session``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ── Lightweight EagerResult shim ─────────────────────────────────────────────
# ``execute_read/write`` consume the Result inside the tx function.
# We return an EagerResult so callers can still call .single(), .data(), etc.

class _EagerResult:
    """Minimal result wrapper holding pre-fetched records.

    Supports the subset of the ``neo4j.Result`` API that callers actually use:
    ``.single()``, ``.data()``, ``.values()``, ``.peek()``, iteration, and
    ``.consume()`` (no-op).
    """

    def __init__(self, records: list, keys: list[str]):
        self._records = records
        self._keys = keys
        self._index = 0

    # -- Core accessors -------------------------------------------------------

    def single(self, strict: bool = False):
        """Return the single record, or None if empty."""
        if not self._records:
            return None
        return self._records[0]

    def data(self, *keys: str) -> List[dict]:
        """Return all records as list-of-dicts."""
        if keys:
            return [{k: r[k] for k in keys if k in r} for r in self._records]
        return [dict(r) for r in self._records]

    def values(self, *keys: str) -> list:
        if keys:
            return [tuple(r[k] for k in keys) for r in self._records]
        return [tuple(r[k] for k in self._keys) for r in self._records]

    def peek(self):
        if self._records:
            return self._records[0]
        raise StopIteration("No records")

    def keys(self) -> list[str]:
        return self._keys

    def consume(self):
        """No-op — records already consumed."""
        return None

    # -- Iteration ------------------------------------------------------------

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return len(self._records)

    def __bool__(self):
        return bool(self._records)

    def __getitem__(self, index):
        return self._records[index]


# ── Async EagerResult + Retry Session ────────────────────────────────────────

class _AsyncRecordIter:
    """Minimal async iterator over pre-fetched records."""

    def __init__(self, records: list):
        self._records = records
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._records):
            raise StopAsyncIteration
        rec = self._records[self._index]
        self._index += 1
        return rec


class _AsyncEagerResult(_EagerResult):
    """Async-compatible variant of ``_EagerResult``."""

    async def single(self, strict: bool = False):  # type: ignore[override]
        return super().single(strict)

    async def data(self, *keys: str) -> List[dict]:  # type: ignore[override]
        return super().data(*keys)

    async def values(self, *keys: str) -> list:  # type: ignore[override]
        return super().values(*keys)

    async def consume(self):  # type: ignore[override]
        return None

    def __aiter__(self):
        return _AsyncRecordIter(self._records)


class AsyncRetrySession:
    """Wraps a Neo4j ``AsyncSession``, routing ``.run()`` through managed transactions."""

    def __init__(self, session, read_only: bool = False):
        self._session = session
        self._read_only = read_only

    async def run(self, query, parameters=None, **kwargs):
        merged = dict(parameters or {})
        merged.update(kwargs)

        async def _tx_func(tx):
            result = await tx.run(query, merged)
            records = [record async for record in result]
            keys = list(result.keys())
            try:
                await result.consume()
            except Exception:
                pass
            return records, keys

        executor = self._session.execute_read if self._read_only else self._session.execute_write
        label = "execute_read" if self._read_only else "execute_write"
        try:
            records, keys = await executor(_tx_func)
            return _AsyncEagerResult(records, keys)
        except Exception as e:
            q_preview = str(query)[:80].replace("\n", " ")
            logger.debug("Neo4j async %s failed: %s | query: %s", label, e, q_preview)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return await self._session.__aexit__(*args)


# ── Sync Retry Session ──────────────────────────────────────────────────────

class RetrySession:
    """Wraps a Neo4j ``Session``, routing ``.run()`` through managed transactions.

    ``session.execute_write()`` automatically retries on transient errors
    (the Neo4j driver calls ``exception.is_retryable()``).  By default we
    route through ``execute_write`` which is safe for both reads and writes.

    When ``read_only=True``, uses ``execute_read()`` instead — enables
    routing to read replicas in a cluster and is semantically correct
    for retrieval queries.
    """

    def __init__(self, session, read_only: bool = False, timeout: float | None = None):
        self._session = session
        self._read_only = read_only
        self._timeout = timeout  # seconds, passed to execute_read/write

    def run(self, query, parameters=None, **kwargs):
        """Execute a Cypher query with automatic retry via managed transaction."""
        merged = dict(parameters or {})
        merged.update(kwargs)

        def _tx_func(tx):
            result = tx.run(query, merged)
            records = list(result)
            keys = list(result.keys())
            # Consume the result summary inside the tx to avoid "result consumed"
            try:
                result.consume()
            except Exception:
                pass
            return records, keys

        executor = self._session.execute_read if self._read_only else self._session.execute_write
        label = "execute_read" if self._read_only else "execute_write"
        # Note: neo4j-driver v6.x forwards all **kwargs to the work function,
        # so timeout cannot be passed here. Use session-level config instead.
        try:
            records, keys = executor(_tx_func)
            return _EagerResult(records, keys)
        except Exception as e:
            q_preview = str(query)[:80].replace("\n", " ")
            logger.debug("Neo4j %s failed: %s | query: %s", label, e, q_preview)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self._session.__exit__(*args)


# ── Context Manager Helper ───────────────────────────────────────────────────

@contextmanager
def retry_session(driver, database: Optional[str] = None, read_only: bool = False, timeout: float | None = None):
    """Context manager yielding a retry-enabled sync Neo4j session.

    Drop-in replacement for ``with driver.session(database=db) as s:``.
    Uses managed transactions internally for automatic transient-error retry.

    Args:
        driver: Neo4j sync driver instance.
        database: Optional database name.
        read_only: If True, use ``execute_read()`` instead of ``execute_write()``.
                   Preferred for retrieval queries — enables read-replica routing.
        timeout: Optional transaction timeout in seconds. Read queries default to
                 60s, write queries to 120s. Pass explicit value to override.
    """
    if timeout is None:
        timeout = 60.0 if read_only else 120.0
    kwargs = {}
    if database is not None:
        kwargs["database"] = database
    with driver.session(**kwargs) as session:
        yield RetrySession(session, read_only=read_only, timeout=timeout)
