#!/bin/bash
# Test max_triplets 20 and 40 WITH validation (0.7 threshold)

echo "🧪 Testing max_triplets with Validation (threshold=0.7)"
echo "Current: max_triplets=60 already tested → 449 entities"
echo ""

for TRIPLETS in 20 40; do
    echo "=================================================="
    echo "Testing max_triplets=$TRIPLETS with validation=0.7"
    echo "=================================================="
    
    # Update code
    sed -i "s/max_triplets_per_pass=[0-9]\+/max_triplets_per_pass=$TRIPLETS/" graphrag-orchestration/app/v3/services/indexing_pipeline.py
    
    # Deploy
    echo "🚀 Deploying..."
    cd graphrag-orchestration && ./deploy-simple.sh 2>&1 | grep -E "✅|Building" | head -5 && cd ..
    
    echo "⏳ Waiting 30s for startup..."
    sleep 30
    
    # Test
    GROUP_ID="validation-07-${TRIPLETS}triplets-$(date +%s)"
    echo "📄 Indexing with group: $GROUP_ID"
    
    python3 - << EOFPYTHON
import requests, time
from neo4j import GraphDatabase

response = requests.post(
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/graphrag/v3/index",
    headers={"X-Group-ID": "$GROUP_ID"},
    json={
        "documents": [
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS LIMITED WARRANTY.pdf",
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING TANK SERVICING CONTRACT.pdf",
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY MANAGEMENT AGREEMENT.pdf",
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf"
        ],
        "ingestion": "document-intelligence"
    },
    timeout=300
)

if response.status_code == 200:
    print("✅ Submitted")
    print("⏳ Waiting 180s...")
    time.sleep(180)
    
    driver = GraphDatabase.driver("neo4j+s://a86dcf63.databases.neo4j.io", auth=("neo4j", "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"))
    with driver.session(database="neo4j") as session:
        result = session.run("MATCH (e:Entity) WHERE e.group_id = \$group_id RETURN count(e) as cnt", group_id="$GROUP_ID")
        count = result.single()["cnt"]
        print(f"\n📊 max_triplets=$TRIPLETS → {count} entities (with validation 0.7)")
    driver.close()
else:
    print(f"❌ Failed: {response.status_code}")
EOFPYTHON

    echo ""
done

echo ""
echo "=================================================="
echo "VALIDATION COMPARISON COMPLETE"
echo "=================================================="
echo "WITHOUT validation:"
echo "  20 → 365 entities"
echo "  40 → 522 entities"
echo "  60 → 669 entities"
echo ""
echo "WITH validation (0.7):"
echo "  20 → [see above]"
echo "  40 → [see above]"
echo "  60 → 449 entities"

# Restore to 60
sed -i "s/max_triplets_per_pass=[0-9]\+/max_triplets_per_pass=60/" graphrag-orchestration/app/v3/services/indexing_pipeline.py
echo ""
echo "✅ Restored max_triplets to 60"
