#!/usr/bin/env python3
"""Check if entity aliases are present in Neo4j"""
import asyncio
import sys
import os

# Add app directory to path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app_dir = os.path.join(repo_root, 'graphrag-orchestration')
sys.path.insert(0, app_dir)

from src.core.config import get_settings
from src.worker.hybrid.services.neo4j_store import Neo4jStore

async def check_aliases():
    settings = get_settings()
    store = Neo4jStore(settings)
    
    gid = 'test-5pdfs-1768832399067050900'
    
    # Check total entities
    query = 'MATCH (e:`__Entity__`) WHERE e.group_id = $gid RETURN count(e) as total'
    result = await store.execute_query(query, {'gid': gid})
    total = result[0]['total']
    print(f'Total entities: {total}')
    
    # Check entities with aliases
    query = '''
        MATCH (e:`__Entity__`)
        WHERE e.group_id = $gid AND e.aliases IS NOT NULL AND size(e.aliases) > 0
        RETURN count(e) as with_aliases
    '''
    result = await store.execute_query(query, {'gid': gid})
    with_aliases = result[0]['with_aliases']
    print(f'Entities with aliases: {with_aliases}')
    
    # Show sample entities
    query = '''
        MATCH (e:`__Entity__`)
        WHERE e.group_id = $gid
        RETURN e.name as name, e.aliases as aliases
        ORDER BY e.name
        LIMIT 20
    '''
    result = await store.execute_query(query, {'gid': gid})
    
    print(f'\nSample entities (first 20):')
    for record in result:
        aliases = record['aliases'] if record['aliases'] else []
        alias_str = f'{aliases}' if aliases else '[]'
        print(f'  {record["name"]}: {alias_str}')
    
    await store.close()

if __name__ == '__main__':
    asyncio.run(check_aliases())
