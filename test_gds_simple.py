#!/usr/bin/env python3
"""Simple test of GDS session with Aura Serverless Graph Analytics.

Uses the correct gds.graph.project.remote() approach required by Aura Serverless.
"""

import os
import sys
import time
from dotenv import load_dotenv

# Load from inner directory
load_dotenv('/afh/projects/graphrag-orchestration/graphrag-orchestration/.env')

from graphdatascience.session import (
    GdsSessions,
    AuraAPICredentials,
    DbmsConnectionInfo,
    SessionMemory
)

def main():
    print("=" * 60)
    print("GDS Simple Test - Aura Serverless Graph Analytics")
    print("Using gds.graph.project.remote() approach")
    print("=" * 60)
    
    # 1. Check credentials
    client_id = os.getenv('AURA_DS_CLIENT_ID')
    client_secret = os.getenv('AURA_DS_CLIENT_SECRET')
    uri = os.getenv('NEO4J_URI')
    user = os.getenv('NEO4J_USERNAME', 'neo4j')
    pwd = os.getenv('NEO4J_PASSWORD')
    
    if not all([client_id, client_secret, uri, pwd]):
        print("❌ Missing credentials!")
        print(f"  AURA_DS_CLIENT_ID: {'✓' if client_id else '✗'}")
        print(f"  AURA_DS_CLIENT_SECRET: {'✓' if client_secret else '✗'}")
        print(f"  NEO4J_URI: {'✓' if uri else '✗'}")
        print(f"  NEO4J_PASSWORD: {'✓' if pwd else '✗'}")
        return 1
    
    print(f"✅ Credentials loaded")
    
    # 2. Connect to GDS session
    print("\n📊 Connecting to GDS session...")
    try:
        api_creds = AuraAPICredentials(client_id=client_id, client_secret=client_secret)
        sessions = GdsSessions(api_credentials=api_creds)
        
        db_connection = DbmsConnectionInfo(uri=uri, username=user, password=pwd)
        
        gds = sessions.get_or_create(
            session_name='test_session',
            memory=SessionMemory.m_2GB,
            db_connection=db_connection
        )
        print(f"✅ GDS session ready: version {gds.version()}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return 1
    
    # 3. Create projection using gds.graph.project.remote() - correct Aura Serverless approach
    print("\n📊 Creating test projection with gds.graph.project.remote()...")
    timestamp = int(time.time())
    projection_name = f"test_projection_{timestamp}"
    
    try:
        # Single Cypher query with gds.graph.project.remote() - required for Aura Serverless
        projection_query = '''
            CALL () {
                MATCH (n:Entity)
                WHERE n.embedding_v2 IS NOT NULL
                OPTIONAL MATCH (n)-[r:MENTIONS|RELATED_TO|SEMANTICALLY_SIMILAR]->(m:Entity)
                WHERE m.embedding_v2 IS NOT NULL
                RETURN 
                    n AS source, r AS rel, m AS target,
                    n { .embedding_v2 } AS sourceNodeProperties,
                    m { .embedding_v2 } AS targetNodeProperties
                LIMIT 100
            }
            RETURN gds.graph.project.remote(source, target, {
                sourceNodeProperties: sourceNodeProperties,
                targetNodeProperties: targetNodeProperties,
                sourceNodeLabels: labels(source),
                targetNodeLabels: labels(target),
                relationshipType: type(rel)
            })
        '''
        
        G, result = gds.graph.project(projection_name, projection_query)
        print(f"✅ Projection created: {G.name()}")
        print(f"   Nodes: {G.node_count()}")
        print(f"   Relationships: {G.relationship_count()}")
        
        if G.node_count() == 0:
            print("⚠️  No nodes found - check if embedding_v2 exists in database")
            gds.graph.drop(projection_name)
            return 0
        
    except Exception as e:
        print(f"❌ Projection failed: {e}")
        return 1
    
    # 4. Run simple KNN test
    print("\n🔗 Running KNN algorithm...")
    try:
        knn_df = gds.knn.stream(
            G,
            nodeProperties=["embedding_v2"],
            topK=3,
            similarityCutoff=0.5,
            concurrency=2
        )
        
        pairs = len(knn_df)
        print(f"✅ KNN completed: {pairs} similarity pairs found")
        
        if pairs > 0:
            print("\n   Sample results:")
            for i, row in knn_df.head(3).iterrows():
                print(f"   Node {int(row['node1'])} ↔ Node {int(row['node2'])}: similarity={row['similarity']:.3f}")
    
    except Exception as e:
        print(f"❌ KNN failed: {e}")
        gds.graph.drop(projection_name)
        return 1
    
    # 5. Cleanup
    print("\n🧹 Cleaning up...")
    try:
        gds.graph.drop(projection_name)
        print(f"✅ Dropped projection: {projection_name}")
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")
    
    print("\n" + "=" * 60)
    print("✅ GDS Test PASSED - All operations successful!")
    print("=" * 60)
    return 0

if __name__ == '__main__':
    sys.exit(main())
