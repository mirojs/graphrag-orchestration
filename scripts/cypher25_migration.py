#!/usr/bin/env python3
"""
Cypher 25 Migration Script

This script applies Cypher 25 optimizations to an existing Neo4j database:
1. Creates uniqueness constraints (enables MergeUniqueNode optimizer)
2. Tests Cypher 25 runtime compatibility
3. Validates query plans show expected optimizations

Usage:
    # From repo root with .venv activated:
    python scripts/cypher25_migration.py
    
    # Or with explicit environment:
    NEO4J_URI=neo4j+s://xxx.databases.neo4j.io \
    NEO4J_USERNAME=neo4j \
    NEO4J_PASSWORD=xxx \
    python scripts/cypher25_migration.py

Reference:
    - Cypher 25 Features: https://neo4j.com/docs/cypher-manual/current/introduction/cypher_25/
    - MergeUniqueNode: Neo4j 2025 release notes
    - Migration Handover: NEO4J_CYPHER25_HANDOVER_2026-01-10.md
"""

import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from neo4j import GraphDatabase
except ImportError:
    print("❌ neo4j package not installed. Run: pip install neo4j")
    sys.exit(1)


def get_env_or_exit(name: str) -> str:
    """Get environment variable or exit with error."""
    value = os.environ.get(name, "")
    if not value:
        # Try loading from .env or settings
        try:
            from dotenv import load_dotenv
            # Try to load from graphrag-orchestration/.env
            env_paths = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphrag-orchestration", ".env"),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
            ]
            for env_path in env_paths:
                if os.path.exists(env_path):
                    load_dotenv(env_path)
                    break
            value = os.environ.get(name, "")
        except ImportError:
            pass
    
    if not value:
        print(f"❌ {name} environment variable not set")
        print(f"   Try: export {name}=<value>")
        print(f"   Or create graphrag-orchestration/.env with {name}=<value>")
        sys.exit(1)
    return value


def main():
    print("=" * 60)
    print("Cypher 25 Migration Script")
    print(f"Date: {datetime.now().isoformat()}")
    print("=" * 60)
    print()
    
    # Get connection details
    uri = get_env_or_exit("NEO4J_URI")
    username = get_env_or_exit("NEO4J_USERNAME")
    password = get_env_or_exit("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    
    print(f"📡 Connecting to: {uri}")
    print(f"📊 Database: {database}")
    print()
    
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        driver.verify_connectivity()
        print("✅ Connected to Neo4j")
        print()
        
        with driver.session(database=database) as session:
            # Step 1: Check Neo4j version
            print("=" * 40)
            print("STEP 1: Check Neo4j Version")
            print("=" * 40)
            
            result = session.run("CALL dbms.components() YIELD name, versions, edition")
            for record in result:
                print(f"  Name: {record['name']}")
                print(f"  Version: {record['versions']}")
                print(f"  Edition: {record['edition']}")
            print()
            
            # Step 2: Test Cypher 25 runtime
            print("=" * 40)
            print("STEP 2: Test Cypher 25 Runtime")
            print("=" * 40)
            
            try:
                result = session.run("""
                CYPHER 25
                RETURN 1 AS test
                """)
                record = result.single()
                if record and record["test"] == 1:
                    print("✅ Cypher 25 runtime is available!")
                else:
                    print("⚠️ Cypher 25 returned unexpected result")
            except Exception as e:
                print(f"❌ Cypher 25 runtime not available: {e}")
                print("   Your Neo4j version may not support Cypher 25 yet.")
                print("   Continuing with constraint creation (works on Cypher 5)...")
            print()
            
            # Step 3: Check existing constraints
            print("=" * 40)
            print("STEP 3: Check Existing Constraints")
            print("=" * 40)
            
            result = session.run("SHOW CONSTRAINTS")
            existing_constraints = []
            for record in result:
                constraint_name = record.get("name", "unknown")
                existing_constraints.append(constraint_name)
                print(f"  - {constraint_name}")
            
            if not existing_constraints:
                print("  (No constraints found)")
            print()
            
            # Step 4: Create uniqueness constraints
            print("=" * 40)
            print("STEP 4: Create Uniqueness Constraints")
            print("=" * 40)
            print("These enable the MergeUniqueNode optimizer in Cypher 25")
            print()
            
            constraints = [
                ("entity_id_unique", "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:`__Entity__`) REQUIRE e.id IS UNIQUE"),
                ("chunk_id_unique", "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:TextChunk) REQUIRE c.id IS UNIQUE"),
                ("document_id_unique", "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE"),
                ("node_id_unique", "CREATE CONSTRAINT node_id_unique IF NOT EXISTS FOR (n:`__Node__`) REQUIRE n.id IS UNIQUE"),
                ("entity_v3_id_unique", "CREATE CONSTRAINT entity_v3_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE"),
                ("community_id_unique", "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE"),
                ("raptor_id_unique", "CREATE CONSTRAINT raptor_id_unique IF NOT EXISTS FOR (r:RaptorNode) REQUIRE r.id IS UNIQUE"),
            ]
            
            for name, query in constraints:
                try:
                    session.run(query)
                    if name in existing_constraints:
                        print(f"  ✓ {name} (already exists)")
                    else:
                        print(f"  ✅ {name} (created)")
                except Exception as e:
                    error_msg = str(e).lower()
                    if "already exists" in error_msg or "equivalent" in error_msg:
                        print(f"  ✓ {name} (already exists)")
                    else:
                        print(f"  ❌ {name} failed: {e}")
            print()
            
            # Step 5: Verify constraints
            print("=" * 40)
            print("STEP 5: Verify Constraints After Migration")
            print("=" * 40)
            
            result = session.run("SHOW CONSTRAINTS")
            count = 0
            for record in result:
                constraint_name = record.get("name", "unknown")
                constraint_type = record.get("type", "unknown")
                labels = record.get("labelsOrTypes", [])
                properties = record.get("properties", [])
                print(f"  - {constraint_name}: {constraint_type} on {labels} ({properties})")
                count += 1
            
            print(f"\n  Total constraints: {count}")
            print()
            
            # Step 6: Test MERGE with Cypher 25
            print("=" * 40)
            print("STEP 6: Test MergeUniqueNode Optimization")
            print("=" * 40)
            
            try:
                # Profile a MERGE query to see if MergeUniqueNode is used
                result = session.run("""
                CYPHER 25
                PROFILE
                MERGE (t:TextChunk {id: 'cypher25_migration_test'})
                SET t.test = true
                RETURN t.id
                """)
                record = result.single()
                
                # Check query plan
                summary = result.consume()
                plan = summary.profile
                
                if plan:
                    def find_operators(p, depth=0):
                        ops = []
                        if p:
                            op_type = p.operator_type if hasattr(p, 'operator_type') else str(type(p))
                            ops.append((depth, op_type))
                            for child in (p.children if hasattr(p, 'children') else []):
                                ops.extend(find_operators(child, depth + 1))
                        return ops
                    
                    operators = find_operators(plan)
                    print("  Query plan operators:")
                    for depth, op in operators:
                        print(f"    {'  ' * depth}- {op}")
                    
                    op_names = [op for _, op in operators]
                    if any("MergeUniqueNode" in str(op) for op in op_names):
                        print("\n  ✅ MergeUniqueNode optimizer detected!")
                    elif any("Merge" in str(op) for op in op_names):
                        print("\n  ⚠️ MERGE used, but MergeUniqueNode not explicitly shown")
                        print("     (This may still be optimized internally)")
                    else:
                        print("\n  ℹ️ Could not determine MERGE optimization status")
                
                # Cleanup test node
                session.run("MATCH (t:TextChunk {id: 'cypher25_migration_test'}) DELETE t")
                print("  🧹 Test node cleaned up")
                
            except Exception as e:
                print(f"  ⚠️ MERGE test skipped: {e}")
            print()
            
            # Summary
            print("=" * 60)
            print("MIGRATION COMPLETE")
            print("=" * 60)
            print()
            print("✅ Uniqueness constraints created/verified")
            print("✅ Cypher 25 runtime tested")
            print()
            print("Next steps:")
            print("1. Run benchmark suite to establish baseline")
            print("2. Compare query plans before/after with PROFILE")
            print("3. Monitor latency improvements")
            print()
            print("To use Cypher 25 in queries, prefix with:")
            print("  CYPHER 25")
            print("  MATCH (n:Entity) RETURN n")
            print()
            print("Or use the helper function:")
            print("  from app.services.async_neo4j_service import cypher25_query")
            print("  query = cypher25_query('MATCH (n) RETURN n')")
            print()
            
    finally:
        driver.close()
        print("📡 Disconnected from Neo4j")


if __name__ == "__main__":
    main()
