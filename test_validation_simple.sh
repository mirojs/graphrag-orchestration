#!/bin/bash

# Simple Validation Testing - NO redeployments
# Changes max_triplets in code, deploys ONCE, then runs both tests

set -e

echo "🧪 Simple Validation Testing (max_triplets 20, 40)"
echo "Strategy: Deploy once with test config, run all tests, restore"
echo ""

# Test both values in sequence WITHOUT redeploying
TRIPLETS_VALUES=(20 40)
API_BASE="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# For storing results
declare -A RESULTS

for TRIPLETS in "${TRIPLETS_VALUES[@]}"; do
    TIMESTAMP=$(date +%s)
    GROUP_ID="simple-validation-${TRIPLETS}triplets-${TIMESTAMP}"
    
    echo ""
    echo "=================================================="
    echo "Testing max_triplets=$TRIPLETS"
    echo "=================================================="
    
    # 1. Update code
    echo "📝 Updating max_triplets to $TRIPLETS..."
    sed -i "s/max_triplets_per_pass=[0-9]\+/max_triplets_per_pass=$TRIPLETS/" graphrag-orchestration/app/v3/services/indexing_pipeline.py
    
    # 2. Deploy (creates new identity, need to wait for permissions)
    echo "🚀 Deploying..."
    cd graphrag-orchestration && ./deploy-simple.sh 2>&1 | grep -E "✅|Managed identity:" | tail -5 && cd ..
    
    # 3. CRITICAL: Wait for RBAC propagation (permissions can take 2-5 minutes)
    echo "⏳ Waiting 180s for RBAC propagation (Azure can be slow)..."
    sleep 180
    
    # 4. Submit documents
    echo "📄 Submitting 5 PDFs with group: $GROUP_ID"
    python3 - "$GROUP_ID" << 'EOFPYTHON'
import sys
import requests
group_id = sys.argv[1]
api_base = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
storage = "neo4jstorage21224"

for i in range(5):
    url = f"https://{storage}.blob.core.windows.net/test-docs/test-{i+1}.pdf"
    try:
        response = requests.post(
            f"{api_base}/graphrag/v3/index",
            json={"documents": [url]},
            headers={"x-group-id": group_id},
            timeout=30
        )
        if response.status_code in [200, 201, 202]:
            print(f"  ✅ Submitted test-{i+1}.pdf")
        else:
            print(f"  ⚠️  test-{i+1}.pdf: HTTP {response.status_code}")
    except Exception as e:
        print(f"  ❌ test-{i+1}.pdf: {e}")
EOFPYTHON
    
    # 5. Wait for processing
    echo "⏳ Waiting 180s for processing..."
    sleep 180
    
    # 6. Check results
    echo "📊 Querying Neo4j..."
    RESULT=$(python3 - "$GROUP_ID" << 'EOFPYTHON'
import sys
from neo4j import GraphDatabase

group_id = sys.argv[1]
driver = GraphDatabase.driver(
    "neo4j+s://a86dcf63.databases.neo4j.io",
    auth=("neo4j", "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI")
)

with driver.session() as session:
    entities = session.run("MATCH (e:Entity {group_id: $g}) RETURN count(*) as cnt", g=group_id).single()['cnt']
    print(entities)

driver.close()
EOFPYTHON
)
    
    echo "   Result: $RESULT entities"
    RESULTS[$TRIPLETS]=$RESULT
done

# Restore original
echo ""
echo "🔄 Restoring max_triplets to 60..."
sed -i "s/max_triplets_per_pass=[0-9]\+/max_triplets_per_pass=60/" graphrag-orchestration/app/v3/services/indexing_pipeline.py

# Summary
echo ""
echo "=================================================="
echo "VALIDATION COMPARISON"
echo "=================================================="
echo ""
echo "WITHOUT validation (baseline from earlier tests):"
echo "  20 → 365 entities"
echo "  40 → 522 entities"
echo "  60 → 669 entities"
echo ""
echo "WITH validation (0.7):"
echo "  20 → ${RESULTS[20]:-0} entities"
echo "  40 → ${RESULTS[40]:-0} entities"
echo "  60 → 449 entities (already tested)"
echo ""

# Calculate filtering if we got results
if [ "${RESULTS[20]}" -gt 0 ]; then
    python3 -c "
baseline_20 = 365
validated_20 = ${RESULTS[20]}
filter_pct = ((baseline_20 - validated_20) / baseline_20 * 100)
print(f'Filtering rate at 20 triplets: {filter_pct:.1f}%')
"
fi

if [ "${RESULTS[40]}" -gt 0 ]; then
    python3 -c "
baseline_40 = 522
validated_40 = ${RESULTS[40]}
filter_pct = ((baseline_40 - validated_40) / baseline_40 * 100)
print(f'Filtering rate at 40 triplets: {filter_pct:.1f}%')
"
fi

echo ""
echo "✅ Testing complete!"
