#!/usr/bin/env python3
"""
Initialize Neo4j V3 Schema

Creates all constraints and vector indexes needed for V3 queries.
Run this once before using query endpoints.

Usage:
  export NEO4J_URI="bolt://localhost:7687" NEO4J_USERNAME="neo4j" NEO4J_PASSWORD="password"
  python scripts/initialize_neo4j_schema.py
"""

import os
import sys
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from app.v3.services.neo4j_store import Neo4jStoreV3
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """Initialize Neo4j schema."""
    logger.info("Initializing Neo4j V3 schema...")
    
    store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "",
        username=settings.NEO4J_USERNAME or "",
        password=settings.NEO4J_PASSWORD or "",
    )
    
    try:
        store.initialize_schema()
        logger.info("✅ Schema initialized successfully")
        return 0
    except Exception as e:
        logger.error(f"❌ Schema initialization failed: {e}")
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
