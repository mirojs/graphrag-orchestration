#!/usr/bin/env python3
import asyncio
import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
os.chdir(current_dir)

from app.services.async_neo4j_service import AsyncNeo4jService

async def check_structure():
    service = AsyncNeo4jService()
    await service.connect()
    
    group_id = 'test-5pdfs-local-1768899320'
    
    # Check what node types exist
    query = '''
    MATCH (n)
    WHERE n.group_id = $group_id
    RETURN labels(n) AS labels, count(*) AS count
    ORDER BY count DESC
    '''
    result = await service.execute_query(query, {'group_id': group_id})
    print('\n=== Node Types ===')
    for record in result:
        print(f'{record["labels"]}: {record["count"]}')
    
    # Check relationship types
    query = '''
    MATCH (a)-[r]->(b)
    WHERE a.group_id = $group_id
    RETURN type(r) AS rel_type, count(*) AS count
    ORDER BY count DESC
    '''
    result = await service.execute_query(query, {'group_id': group_id})
    print('\n=== Relationship Types ===')
    for record in result:
        print(f'{record["rel_type"]}: {record["count"]}')
    
    # Check for thematic edges specifically
    thematic_edges = ['SEMANTICALLY_SIMILAR', 'SHARES_ENTITY', 'HAS_HUB_ENTITY', 'APPEARS_IN_SECTION', 'IN_SECTION']
    print('\n=== Thematic Edge Check ===')
    for edge_type in thematic_edges:
        query = f'''
        MATCH (a)-[r:{edge_type}]->(b)
        WHERE a.group_id = $group_id
        RETURN count(r) AS count
        '''
        result = await service.execute_query(query, {'group_id': group_id})
        count = result[0]['count'] if result else 0
        status = '✓' if count > 0 else '✗'
        print(f'{status} {edge_type}: {count}')
    
    await service.close()

if __name__ == '__main__':
    asyncio.run(check_structure())
