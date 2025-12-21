#!/bin/bash
# Systematic test of max_triplets_per_chunk values
# Tests 20, 40, 60, 80, 100 to find optimal setting

set -e

API_BASE="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
TEST_VALUES=(20 40 60 80 100)

echo "================================================================="
echo "MAX_TRIPLETS_PER_CHUNK SYSTEMATIC TEST"
echo "================================================================="
echo ""
echo "This will test the following values: ${TEST_VALUES[@]}"
echo "Each test takes ~4 minutes (deploy + index + analyze)"
echo "Total time: ~20 minutes"
echo ""
read -p "Press Enter to start..."

for VALUE in "${TEST_VALUES[@]}"; do
    echo ""
    echo "================================================================="
    echo "Testing max_triplets_per_chunk = $VALUE"
    echo "================================================================="
    
    # Update the code
    echo "📝 Updating indexing_pipeline.py..."
    sed -i "s/max_triplets_per_chunk=[0-9]\+/max_triplets_per_chunk=$VALUE/" \
        app/v3/services/indexing_pipeline.py
    
    # Verify change
    CURRENT=$(grep "max_triplets_per_chunk=" app/v3/services/indexing_pipeline.py | grep -o '[0-9]\+' | head -1)
    echo "   Current value: $CURRENT"
    
    if [ "$CURRENT" != "$VALUE" ]; then
        echo "❌ Failed to update value!"
        exit 1
    fi
    
    # Deploy
    echo ""
    echo "🚀 Deploying..."
    cd /afh/projects/graphrag-orchestration
    bash deploy-graphrag.sh > /dev/null 2>&1
    echo "✅ Deployed"
    
    # Wait for deployment
    echo "⏳ Waiting 30s for deployment to stabilize..."
    sleep 30
    
    # Run test
    echo ""
    echo "🧪 Running test..."
    cd graphrag-orchestration
    python3 << EOF
import requests
import time
from neo4j import GraphDatabase
import os

API_BASE = "$API_BASE"
group_id = f"test-triplets-${VALUE}-{int(time.time())}"

# Cleanup old data
driver = GraphDatabase.driver(
    'neo4j+s://a86dcf63.databases.neo4j.io',
    auth=('neo4j', os.getenv('NEO4J_PASSWORD', 'uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI'))
)
with driver.session(database='neo4j') as session:
    session.run("MATCH (n {group_id: \$group_id}) DETACH DELETE n", group_id=group_id)

# Submit indexing
response = requests.post(
    f"{API_BASE}/graphrag/v3/index",
    headers={"x-group-id": group_id},
    json={
        "documents": [
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/contoso_lifts_invoice.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/purchase_contract.pdf"},
        ],
        "ingestion": "document_intelligence"
    }
)

print(f"✅ Indexing started for group: {group_id}")
print("⏳ Waiting 120 seconds...")
time.sleep(120)

# Get stats
with driver.session(database='neo4j') as session:
    result = session.run("""
        MATCH (e:Entity {group_id: \$group_id})
        WITH count(e) as entities
        MATCH (e1:Entity {group_id: \$group_id})-[r]-(e2:Entity {group_id: \$group_id})
        WHERE type(r) <> 'MENTIONS'
        RETURN entities, count(DISTINCT r) as relationships
    """, group_id=group_id)
    record = result.single()
    if record:
        print(f"")
        print(f"📊 RESULTS for max_triplets=$VALUE:")
        print(f"   Entities: {record['entities']}")
        print(f"   Relationships: {record['relationships']}")
        print(f"   Group: {group_id}")
        
        # Save to file
        with open('/tmp/triplets_test_results.txt', 'a') as f:
            f.write(f"{VALUE},{record['entities']},{record['relationships']},{group_id}\n")

driver.close()
EOF
    
    echo ""
    echo "✅ Test complete for max_triplets=$VALUE"
    echo "================================================================="
    sleep 5
done

echo ""
echo "================================================================="
echo "ALL TESTS COMPLETE"
echo "================================================================="
echo ""
echo "📊 Summary:"
cat /tmp/triplets_test_results.txt | awk -F',' '{printf "max_triplets=%3d → %4d entities, %4d relationships\n", $1, $2, $3}'

echo ""
echo "🎯 Finding optimal value..."
python3 << 'EOF'
import sys

results = []
with open('/tmp/triplets_test_results.txt', 'r') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) >= 3:
            results.append({
                'value': int(parts[0]),
                'entities': int(parts[1]),
                'relationships': int(parts[2])
            })

if results:
    optimal = max(results, key=lambda x: x['entities'])
    print(f"\n✅ OPTIMAL: max_triplets_per_chunk = {optimal['value']}")
    print(f"   Entities: {optimal['entities']}")
    print(f"   Relationships: {optimal['relationships']}")
    
    # Check plateau
    if len(results) >= 3:
        last_three = sorted(results, key=lambda x: x['value'])[-3:]
        entity_values = [r['entities'] for r in last_three]
        variance = max(entity_values) - min(entity_values)
        
        if variance < 100:
            print(f"\n⚠️  Plateau detected (variance: {variance} entities)")
            print(f"   Consider using {last_three[1]['value']} for safety")
EOF

# Clean up
rm -f /tmp/triplets_test_results.txt
