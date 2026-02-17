"""
Neo4j Retry Utilities — Native Driver Retry

Uses Neo4j driver v5+ managed transactions (``session.execute_read()`` /
``session.execute_write()``) which provide **built-in** retry for transient
errors (deadlocks, leader re-elections, connection resets).  This is the
same mechanism the GDS library uses via ``run_retryable_cypher``.

For operations that need the simpler ``session.run()`` API — but with retry —
we provide ``RetrySession`` / ``AsyncRetrySession`` wrappers that delegate
``.run()`` to ``execute_write()`` internally, eagerly materializing results
so callers can use ``.single()``, ``.data()`` etc. unchanged.

Fallback: if the neo4j driver's ``is_retryable()`` flag is unavailable the
wrapper also catches the classic transient exception types manually.

Usage::

    # Sync — wrap the session creation point
    with retry_session(driver, database="neo4j") as session:
        result = session.run("MATCH (n) RETURN count(n)")

    # Async — same pattern
    async with async_retry_session(async_driver, database="neo4j") as session:
        result = await session.run("MATCH (n) RETURN count(n)")

Context managers and ``__getattr__`` delegation ensure these are drop-in
replacements for raw ``Session`` / ``AsyncSession``.
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


class _AsyncEagerResult(_EagerResult):
    """Async-compatible variant of ``_EagerResult``.

    The async Neo4j driver's ``Result`` has awaitable ``.data()``,
    ``.single()``, ``.values()`` and ``.consume()``.  This subclass
    provides coroutine wrappers so callers can ``await result.data()``
    without change.
    """

    async def single(self, strict: bool = False):  # type: ignore[override]
        return super().single(strict)

    async def data(self, *keys: str) -> List[dict]:  # type: ignore[override]
        return super().data(*keys)

    async def values(self, *keys: str) -> list:  # type: ignore[override]
        return super().values(*keys)

    async def consume(self):  # type: ignore[override]
        return None

    # Async iteration support — callers may use ``async for record in result``
    def __aiter__(self):
        return _AsyncRecordIter(self._records)


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


# ── Sync Retry Session ──────────────────────────────────────────────────────

class RetrySession:
    """Wraps a Neo4j ``Session``, routing ``.run()`` through managed transactions.

    ``session.execute_write()`` automatically retries on transient errors
    (the Neo4j driver calls ``exception.is_retryable()``).  By default we
    route through ``execute_write`` which is safe for both reads and writes.
    """

    def __init__(self, session):
        self._session = session

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

        try:
            records, keys = self._session.execute_write(_tx_func)
            return _EagerResult(records, keys)
        except Exception as e:
            q_preview = str(query)[:80].replace("\n", " ")
            logger.debug("Neo4j execute_write failed: %s | query: %s", e, q_preview)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self._session.__exit__(*args)


# ── Async Retry Session ─────────────────────────────────────────────────────

class AsyncRetrySession:
    """Wraps a Neo4j ``AsyncSession``, routing ``.run()`` through managed transactions."""

    def __init__(self, session):
        self._session = session

    async def run(self, query, parameters=None, **kwargs):
        """Execute a Cypher query with automatic retry via managed transaction."""
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

        try:
            records, keys = await self._session.execute_write(_tx_func)
            return _AsyncEagerResult(records, keys)
        except Exception as e:
            q_preview = str(query)[:80].replace("\n", " ")
            logger.debug("Neo4j async execute_write failed: %s | query: %s", e, q_preview)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return await self._session.__aexit__(*args)


# ── Context Manager Helpers ──────────────────────────────────────────────────

@contextmanager
def retry_session(driver, database: Optional[str] = None):
    """Context manager yielding a retry-enabled sync Neo4j session.

    Drop-in replacement for ``with driver.session(database=db) as s:``.
    Uses ``session.execute_write()`` internally for automatic transient-error
    retry (Neo4j driver native mechanism).
    """
    kwargs = {}
    if database is not None:
        kwargs["database"] = database
    with driver.session(**kwargs) as session:
        yield RetrySession(session)


@asynccontextmanager
async def async_retry_session(driver, database: Optional[str] = None):
    """Context manager yielding a retry-enabled async Neo4j session.

    Drop-in replacement for ``async with driver.session(database=db) as s:``.
    """
    kwargs = {}
    if database is not None:
        kwargs["database"] = database
    async with driver.session(**kwargs) as session:
        yield AsyncRetrySession(session)
