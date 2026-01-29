#!/bin/bash
# Test invoice consistency query on all KNN configurations via curl
# This directly hits the deployed API endpoint

API_URL="https://graphrag-orchestration-container.proudgrass-23d0c91d.eastus.azurecontainerapps.io/hybrid/query"

# Test groups
declare -A GROUPS=(
    ["V2-Baseline"]="test-5pdfs-v2-1769609082:806"
    ["KNN-Disabled"]="test-5pdfs-v2-knn-disabled:0"
    ["KNN-1"]="test-5pdfs-v2-knn-1:268"
    ["KNN-2"]="test-5pdfs-v2-knn-2:476"
    ["KNN-3"]="test-5pdfs-v2-knn-3:444"
)

QUERY="Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"

echo "======================================================================"
echo "Testing Invoice Consistency Query on KNN Configurations"
echo "======================================================================"
echo ""

for name in "V2-Baseline" "KNN-Disabled" "KNN-1" "KNN-2" "KNN-3"; do
    IFS=':' read -r group_id edges <<< "${GROUPS[$name]}"
    
    echo "======================================================================"
    echo "🔬 Testing: $name"
    echo "======================================================================"
    echo "  Group ID: $group_id"
    echo "  KNN Edges: $edges"
    echo ""
    
    # Make API request and save to temp file
    output_file="/tmp/knn_test_${name}.json"
    
    curl -s -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "X-Group-ID: $group_id" \
        -d "{
            \"query\": \"$QUERY\",
            \"force_route\": \"drift_multi_hop\",
            \"response_type\": \"summary\"
        }" > "$output_file" 2>&1
    
    if [ $? -eq 0 ] && [ -s "$output_file" ]; then
        # Extract key info using jq if available, otherwise use grep
        if command -v jq &> /dev/null; then
            echo "✅ Query Complete"
            echo "🛣️  Route: $(jq -r '.route_used // "unknown"' "$output_file")"
            
            # Count inconsistencies in response
            response=$(jq -r '.response // ""' "$output_file")
            inconsistencies=$(echo "$response" | grep -oiE '\b[0-9]+\.' | wc -l)
            echo "📊 Inconsistencies Found: ~$inconsistencies"
            
            # Count citations
            citations=$(jq '.citations | length' "$output_file" 2>/dev/null || echo "0")
            echo "📚 Citations: $citations"
            
            # Show first 800 chars of response
            echo ""
            echo "Response (first 800 chars):"
            echo "$response" | head -c 800
            echo ""
            if [ ${#response} -gt 800 ]; then
                echo "..."
            fi
            
            # Analyze citation relevance
            if [ "$citations" -gt 0 ]; then
                relevant=0
                total=0
                while IFS= read -r preview; do
                    if [ $total -ge 5 ]; then break; fi
                    if echo "$preview" | grep -qiE 'invoice|contract|purchase|agreement'; then
                        ((relevant++))
                    fi
                    ((total++))
                done < <(jq -r '.citations[].text_preview // ""' "$output_file" 2>/dev/null)
                
                if [ $total -gt 0 ]; then
                    relevance_pct=$((relevant * 100 / total))
                    echo ""
                    echo "  Relevance (top 5): $relevant/$total ($relevance_pct%)"
                fi
            fi
        else
            echo "✅ Query Complete (see $output_file for details)"
            head -c 1000 "$output_file"
            echo ""
        fi
    else
        echo "❌ Error: Query failed or no response"
        cat "$output_file" 2>/dev/null
    fi
    
    echo ""
    echo ""
    sleep 3  # Rate limiting
done

echo "======================================================================"
echo "📊 Summary"
echo "======================================================================"
echo "Results saved to /tmp/knn_test_*.json"
echo ""
echo "To view detailed results:"
echo "  cat /tmp/knn_test_V2-Baseline.json | jq ."
echo "  cat /tmp/knn_test_KNN-1.json | jq ."
echo ""
