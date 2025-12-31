#!/bin/bash
# Quick 3-value test: 20, 40, 80
# Takes ~24 minutes

set -e

echo "================================================================="
echo "QUICK MAX_TRIPLETS TEST (3 values: 20, 40, 80)"
echo "Time: ~24 minutes"
echo "================================================================="
echo ""

TEST_VALUES=(20 40 80)
RESULTS_FILE="/tmp/triplets_quick_test_$(date +%s).txt"

echo "value,entities,relationships,group_id" > "$RESULTS_FILE"

for VALUE in "${TEST_VALUES[@]}"; do
    echo ""
    echo "================================================================="
    echo "Testing max_triplets_per_chunk = $VALUE"
    echo "================================================================="
    
    # Update code
    echo "📝 Updating code..."
    sed -i "s/max_triplets_per_chunk=[0-9]\+/max_triplets_per_chunk=$VALUE/" \
        app/v3/services/indexing_pipeline.py
    
    # Verify
    CURRENT=$(grep "max_triplets_per_chunk=" app/v3/services/indexing_pipeline.py | grep -o '[0-9]\+' | head -1)
    if [ "$CURRENT" != "$VALUE" ]; then
        echo "❌ Failed to update!"
        exit 1
    fi
    echo "✅ Updated to $VALUE"
    
    # Deploy
    echo ""
    echo "🚀 Deploying..."
    cd /afh/projects/graphrag-orchestration
    bash deploy-graphrag.sh 2>&1 | tail -5
    echo "✅ Deployed"
    
    # Wait for stabilization
    echo "⏳ Waiting 30s for deployment..."
    sleep 30
    
    # Run test
    echo ""
    echo "🧪 Running test..."
    cd graphrag-orchestration
    GROUP_ID="quick-test-${VALUE}-$(date +%s)"
    
    python3 << EOF
import requests
import time
from neo4j import GraphDatabase
import os
import json

API_BASE = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "$GROUP_ID"

print(f"Group ID: {GROUP_ID}")

# Submit indexing
response = requests.post(
    f"{API_BASE}/graphrag/v3/index",
    headers={"x-group-id": GROUP_ID},
    json={
        "documents": [
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/contoso_lifts_invoice.pdf"},
            {"url": "https://afhazstorage.blob.core.windows.net/source-docs/purchase_contract.pdf"},
        ],
        "ingestion": "document-intelligence"
    }
)

if response.status_code == 200:
    print("✅ Indexing started")
else:
    print(f"❌ Error: {response.status_code}")
    exit(1)

print("⏳ Waiting 120 seconds for indexing...")
time.sleep(120)

# Get stats
driver = GraphDatabase.driver(
    'neo4j+s://a86dcf63.databases.neo4j.io',
    auth=('neo4j', os.environ['NEO4J_PASSWORD'])
)

with driver.session(database='neo4j') as session:
    # Get stats
    result = session.run("""
        MATCH (e:Entity {group_id: \$group_id})
        WITH count(e) as entities
        MATCH (e1:Entity {group_id: \$group_id})-[r]-(e2:Entity {group_id: \$group_id})
        WHERE type(r) <> 'MENTIONS'
        RETURN entities, count(DISTINCT r) as relationships
    """, group_id=GROUP_ID)
    
    record = result.single()
    if record:
        entities = record['entities']
        rels = record['relationships']
        print(f"\n📊 RESULTS:")
        print(f"   Entities: {entities}")
        print(f"   Relationships: {rels}")
        
        # Save results
        with open('$RESULTS_FILE', 'a') as f:
            f.write(f"$VALUE,{entities},{rels},{GROUP_ID}\n")
        
        # Get sample entities for quality check
        print(f"\n🔍 Sample entities (for quality verification):")
        result = session.run("""
            MATCH (e:Entity {group_id: \$group_id})
            RETURN e.name as name, e.type as type, e.description as desc
            ORDER BY rand()
            LIMIT 15
        """, group_id=GROUP_ID)
        
        samples = []
        for rec in result:
            name = rec['name']
            etype = rec['type']
            desc = (rec['desc'] or '')[:80]
            samples.append({"name": name, "type": etype, "desc": desc})
            print(f"   - {name} ({etype})")
            if desc:
                print(f"     {desc}...")
        
        # Save samples for review
        with open(f'/tmp/samples_${VALUE}.json', 'w') as f:
            json.dump(samples, f, indent=2)
    else:
        print("⚠️  No data found")

driver.close()
EOF
    
    echo ""
    echo "✅ Test complete for max_triplets=$VALUE"
    echo "   Sample entities saved to: /tmp/samples_${VALUE}.json"
    echo "================================================================="
    
    # Brief pause between tests
    sleep 10
done

echo ""
echo "================================================================="
echo "QUICK TEST COMPLETE"
echo "================================================================="
echo ""
echo "📊 Results Summary:"
echo ""
printf "%-15s %-12s %-15s\n" "max_triplets" "Entities" "Relationships"
echo "─────────────────────────────────────────────────────────────"
tail -n +2 "$RESULTS_FILE" | while IFS=',' read value entities rels group; do
    printf "%-15s %-12s %-15s\n" "$value" "$entities" "$rels"
done

echo ""
echo "📁 Detailed results: $RESULTS_FILE"
echo "📁 Entity samples: /tmp/samples_*.json"
echo ""
echo "🎯 Next: Review entity samples for quality assessment"
echo "   Check /tmp/samples_*.json files"
