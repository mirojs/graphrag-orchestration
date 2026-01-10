#!/usr/bin/env python3
"""Neo4j capability probe (Aura/self-host).

Purpose:
- Prints Neo4j server version and edition (Aura/non-Aura)
- Verifies availability of vector functions (e.g., vector.similarity.cosine)
- Verifies availability/signatures of vector/fulltext index procedures

This is intentionally read-only and safe to run against production.

Usage:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... \
    python3 scripts/neo4j_capability_probe.py

Optional:
  NEO4J_DATABASE=neo4j
"""

from __future__ import annotations

import os
import sys
from typing import Any

from neo4j import GraphDatabase


def _ensure_repo_root_on_path() -> None:
    """Allow `import app...` when running `python scripts/...`.

    When executing a script by path, Python sets sys.path[0] to the script
    directory (scripts/), which can prevent imports from the repo root.
    """

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _env(name: str, *, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _print_kv(key: str, value: Any) -> None:
    print(f"{key}: {value}")


def main() -> int:
    _ensure_repo_root_on_path()

    uri = _env("NEO4J_URI")
    # Support both NEO4J_USER and NEO4J_USERNAME (repo uses NEO4J_USERNAME)
    user = _env("NEO4J_USER") or _env("NEO4J_USERNAME") or "neo4j"
    password = _env("NEO4J_PASSWORD")
    database = _env("NEO4J_DATABASE") or "neo4j"

    # Fallback: load from app Settings (which loads .env) when env vars aren't present.
    if not uri or not password:
        try:
            from app.core.config import settings  # type: ignore

            uri = uri or getattr(settings, "NEO4J_URI", None)
            user = user or getattr(settings, "NEO4J_USERNAME", None) or "neo4j"
            password = password or getattr(settings, "NEO4J_PASSWORD", None)
            database = database or getattr(settings, "NEO4J_DATABASE", None) or "neo4j"
        except Exception as exc:
            print(f"Warning: failed to load app settings fallback: {exc}", file=sys.stderr)

    if not uri or not password:
        print(
            "Missing Neo4j connection settings. Provide NEO4J_URI and NEO4J_PASSWORD via env vars "
            "or via app/.env settings.",
            file=sys.stderr,
        )
        return 2

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            # Server identity
            components = list(
                session.run(
                    """
                    CALL dbms.components() YIELD name, versions, edition
                    RETURN name, versions, edition
                    """
                )
            )
            if components:
                c0 = components[0]
                _print_kv("dbms.components.name", c0.get("name"))
                _print_kv("dbms.components.versions", c0.get("versions"))
                _print_kv("dbms.components.edition", c0.get("edition"))
            else:
                print("dbms.components: <no rows>")

            # Vector functions existence
            vector_funcs = [
                r["name"]
                for r in session.run(
                    """
                    SHOW FUNCTIONS YIELD name
                    WHERE name STARTS WITH 'vector.'
                    RETURN name
                    ORDER BY name
                    """
                )
            ]
            _print_kv("vector.functions.count", len(vector_funcs))
            if vector_funcs:
                _print_kv("vector.functions.sample", vector_funcs[:15])

            # Fast runtime check of vector.similarity.cosine, if present
            has_cosine = "vector.similarity.cosine" in set(vector_funcs)
            _print_kv("vector.similarity.cosine.present", has_cosine)
            if has_cosine:
                sim = session.run(
                    """
                    RETURN vector.similarity.cosine([1.0, 0.0], [1.0, 0.0]) AS sim
                    """
                ).single()["sim"]
                _print_kv("vector.similarity.cosine.selftest", sim)

            # Index procedures existence + signatures (helps detect metadata-filter support)
            proc_rows = list(
                session.run(
                    """
                    SHOW PROCEDURES YIELD name, signature
                    WHERE name IN [
                      'db.index.vector.queryNodes',
                      'db.index.vector.queryRelationships',
                      'db.index.fulltext.queryNodes',
                      'db.index.fulltext.queryRelationships'
                    ]
                    RETURN name, signature
                    ORDER BY name
                    """
                )
            )

            if not proc_rows:
                print("index.procedures: <none found>")
            else:
                for r in proc_rows:
                    _print_kv(f"proc.{r['name']}.signature", r.get("signature"))

    finally:
        driver.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
