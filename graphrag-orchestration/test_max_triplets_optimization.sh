#!/bin/bash

# MAX_TRIPLETS_PER_CHUNK OPTIMIZATION TEST
# Tests: 20, 40, 80 to find optimal value
# Quality target: 95-99% precision (1-5% false entities acceptable)
# Total time: ~30 minutes (6 min per test + 6 min wait)

set -e

TIMESTAMP=$(date +%s)
RESULTS_FILE="/tmp/max_triplets_results_${TIMESTAMP}.txt"

echo "=================================================================" | tee $RESULTS_FILE
echo "MAX_TRIPLETS_PER_CHUNK OPTIMIZATION TEST" | tee -a $RESULTS_FILE
echo "Started: $(date)" | tee -a $RESULTS_FILE
echo "Testing values: 20, 40, 80" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "" | tee -a $RESULTS_FILE

GROUP_IDS=()

# Test each value
for TRIPLETS in 20 40 80; do
    echo "" | tee -a $RESULTS_FILE
    echo "=================================================================" | tee -a $RESULTS_FILE
    echo "Testing max_triplets_per_chunk = $TRIPLETS" | tee -a $RESULTS_FILE
    echo "=================================================================" | tee -a $RESULTS_FILE
    
    # Update code
    echo "📝 Updating code..." | tee -a $RESULTS_FILE
    sed -i "s/max_triplets_per_chunk=[0-9]\+/max_triplets_per_chunk=$TRIPLETS/" app/v3/services/indexing_pipeline.py
    echo "✅ Updated to $TRIPLETS" | tee -a $RESULTS_FILE
    
    # Deploy
    echo "" | tee -a $RESULTS_FILE
    echo "🚀 Deploying..." | tee -a $RESULTS_FILE
    bash deploy.sh 2>&1 | grep -E "(✅|View Swagger|Check application|Run test)" | tee -a $RESULTS_FILE
    echo "✅ Deployed" | tee -a $RESULTS_FILE
    
    # Wait for deployment
    echo "⏳ Waiting 45s for deployment..." | tee -a $RESULTS_FILE
    sleep 45
    
    # Submit indexing
    GROUP_ID="max-triplets-${TRIPLETS}-${TIMESTAMP}"
    GROUP_IDS+=("$GROUP_ID:$TRIPLETS")
    echo "" | tee -a $RESULTS_FILE
    echo "🧪 Submitting indexing request..." | tee -a $RESULTS_FILE
    echo "Group ID: $GROUP_ID" | tee -a $RESULTS_FILE
    
    python3 << EOF
import requests

response = requests.post(
    'https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/graphrag/v3/index',
    headers={'x-group-id': '$GROUP_ID'},
    json={
        'documents': [
            {'url': 'https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf'},
            {'url': 'https://afhazstorage.blob.core.windows.net/source-docs/AZURE%20Data%20Integration%20-%20Whitepaper.pdf'},
            {'url': 'https://afhazstorage.blob.core.windows.net/source-docs/Azure%20Machine%20Learning.pdf'},
            {'url': 'https://afhazstorage.blob.core.windows.net/source-docs/Best%20Practices%20for%20Azure%20Integration%20Services.pdf'},
            {'url': 'https://afhazstorage.blob.core.windows.net/source-docs/Using%20Azure%20Data%20Factory%20Self-Hosted%20Integration%20Runtime.pdf'}
        ],
        'ingestion': 'document-intelligence'
    }
)

if response.status_code == 200:
    print('✅ Indexing started')
else:
    print(f'❌ Error: {response.status_code} - {response.text}')
    exit(1)
EOF
    
    if [ $? -eq 0 ]; then
        echo "✅ Indexing started for max_triplets=$TRIPLETS" | tee -a $RESULTS_FILE
    else
        echo "❌ Failed to start indexing for max_triplets=$TRIPLETS" | tee -a $RESULTS_FILE
        exit 1
    fi
    
    echo "" | tee -a $RESULTS_FILE
done

echo "" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "ALL INDEXING REQUESTS SUBMITTED" | tee -a $RESULTS_FILE
echo "Waiting 6 minutes for all indexing to complete..." | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
sleep 360

echo "" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "COLLECTING RESULTS" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "" | tee -a $RESULTS_FILE

# Collect results
python3 << 'EOFPYTHON'
import sys
from neo4j import GraphDatabase

uri = "neo4j+s://a86dcf63.databases.neo4j.io"
username = "neo4j"
password = "KXa8R-XdLe34_VUxtQr9v8VpzvNTsQxqMw4glTe78Ww"

driver = GraphDatabase.driver(uri, auth=(username, password))

group_data = []
for item in sys.argv[1:]:
    group_id, triplets = item.split(':')
    group_data.append((group_id, triplets))

print(f"{'max_triplets':<15} {'Entities':<12} {'Relationships':<15} {'Communities':<12}")
print("=" * 60)

for group_id, triplets in group_data:
    with driver.session(database="neo4j") as session:
        # Count entities
        result = session.run("""
            MATCH (e:__Entity__ {group_id: $group_id})
            RETURN count(e) as count
        """, group_id=group_id)
        entities = result.single()["count"]
        
        # Count relationships
        result = session.run("""
            MATCH (e1:__Entity__ {group_id: $group_id})-[r]-(e2:__Entity__ {group_id: $group_id})
            RETURN count(distinct r) as count
        """, group_id=group_id)
        relationships = result.single()["count"]
        
        # Count communities
        result = session.run("""
            MATCH (c:__Community__ {group_id: $group_id})
            RETURN count(c) as count
        """, group_id=group_id)
        communities = result.single()["count"]
        
        print(f"{triplets:<15} {entities:<12} {relationships:<15} {communities:<12}")
        
        # Sample 15 entities for quality review
        result = session.run("""
            MATCH (e:__Entity__ {group_id: $group_id})
            RETURN e.name as name, e.description as description
            LIMIT 15
        """, group_id=group_id)
        
        import json
        samples = [dict(record) for record in result]
        with open(f"/tmp/samples_{triplets}.json", "w") as f:
            json.dump(samples, f, indent=2)

driver.close()
EOFPYTHON ${GROUP_IDS[@]} | tee -a $RESULTS_FILE

echo "" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "TEST COMPLETE" | tee -a $RESULTS_FILE
echo "Finished: $(date)" | tee -a $RESULTS_FILE
echo "=================================================================" | tee -a $RESULTS_FILE
echo "" | tee -a $RESULTS_FILE
echo "📊 Results saved to: $RESULTS_FILE" | tee -a $RESULTS_FILE
echo "📁 Entity samples: /tmp/samples_*.json" | tee -a $RESULTS_FILE
echo "" | tee -a $RESULTS_FILE
echo "🎯 NEXT STEPS:" | tee -a $RESULTS_FILE
echo "   1. Review entity samples in /tmp/samples_*.json" | tee -a $RESULTS_FILE
echo "   2. Calculate precision for each value (count false entities)" | tee -a $RESULTS_FILE
echo "   3. Look for quality degradation or plateau" | tee -a $RESULTS_FILE
echo "   4. Select optimal max_triplets_per_chunk value" | tee -a $RESULTS_FILE
echo "   5. If needed: Test intermediate values (30, 50, 60, 100)" | tee -a $RESULTS_FILE
