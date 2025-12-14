#!/bin/bash
# Simplified GraphRAG Deployment - Reuses Existing Resources

set -e

RESOURCE_GROUP="rg-graphrag-feature"
LOCATION="swedencentral"
ACR_NAME="graphragacr12153"  # Reuse existing
STORAGE_ACCOUNT="neo4jstorage21224"  # Reuse existing

# Priority: 1) ENV var, 2) existing Neo4j container, 3) deployment-info.txt, 4) generate new
if [ -n "$NEO4J_PASSWORD" ]; then
  echo "✅ Using NEO4J_PASSWORD from environment variable"
else
  # Try to get password from running Neo4j container
  EXISTING_NEO4J_PASSWORD=$(az container show --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --query 'containers[0].environmentVariables[?name==`NEO4J_AUTH`].value | [0]' -o tsv 2>/dev/null | cut -d'/' -f2)
  
  if [ -n "$EXISTING_NEO4J_PASSWORD" ]; then
    echo "✅ Reusing password from existing Neo4j container"
    NEO4J_PASSWORD="$EXISTING_NEO4J_PASSWORD"
  elif [ -f "deployment-info.txt" ]; then
    CACHED_PASSWORD=$(grep "Neo4j Password:" deployment-info.txt | awk '{print $3}')
    if [ -n "$CACHED_PASSWORD" ]; then
      echo "✅ Reusing password from deployment-info.txt"
      NEO4J_PASSWORD="$CACHED_PASSWORD"
    else
      echo "⚙️  Generating new Neo4j password"
      NEO4J_PASSWORD=$(openssl rand -base64 24)
    fi
  else
    echo "⚙️  Generating new Neo4j password"
    NEO4J_PASSWORD=$(openssl rand -base64 24)
  fi
fi

echo "=================================================="
echo "Simplified GraphRAG Deployment"
echo "=================================================="
echo "Using existing resources:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  ACR: $ACR_NAME"
echo "  Storage: $STORAGE_ACCOUNT"
echo ""

# Get ACR credentials
echo "Getting ACR credentials..."
ACR_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query "passwords[0].value" -o tsv)

echo "✅ ACR: $ACR_SERVER"

# Build and push image
echo ""
echo "=================================================="
echo "Building and Pushing Docker Image"
echo "=================================================="
echo "⏳ Logging in..."
echo "$ACR_PASSWORD" | docker login "$ACR_SERVER" --username "$ACR_NAME" --password-stdin

echo "⏳ Building..."
docker build -t "$ACR_SERVER/graphrag-orchestration:latest" .

echo "⏳ Pushing..."
docker push "$ACR_SERVER/graphrag-orchestration:latest"

echo "✅ Image: $ACR_SERVER/graphrag-orchestration:latest"

# Save image ID for cleanup after successful deployment
IMAGE_ID=$(docker images "$ACR_SERVER/graphrag-orchestration:latest" --format "{{.ID}}")
echo "  Image ID: $IMAGE_ID (will cleanup after deployment)"

# Check if Neo4j container exists and is running
echo ""
echo "=================================================="
echo "Checking Neo4j Container"
echo "=================================================="

NEO4J_STATE=$(az container show --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --query instanceView.state -o tsv 2>/dev/null || echo "NotFound")

if [ "$NEO4J_STATE" = "Running" ]; then
  echo "✅ Neo4j already running"
  NEO4J_FQDN=$(az container show --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --query ipAddress.fqdn -o tsv)
elif [ "$NEO4J_STATE" = "NotFound" ] || [ "$NEO4J_STATE" = "Failed" ] || [ "$NEO4J_STATE" = "Terminated" ]; then
  echo "⏳ Deploying new Neo4j container..."
  
  # Delete failed container if exists
  if [ "$NEO4J_STATE" != "NotFound" ]; then
    az container delete --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --yes 2>/dev/null || true
  fi
  
  # Get storage key
  STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query "[0].value" -o tsv)
  
  # Ensure file share exists
  az storage share create --name neo4j-data --account-name "$STORAGE_ACCOUNT" --account-key "$STORAGE_KEY" 2>/dev/null || echo "  (File share already exists)"
  
  # Deploy Neo4j
  az container create \
    --resource-group "$RESOURCE_GROUP" \
    --name neo4j-graphrag \
    --image neo4j:5.15.0 \
    --os-type Linux \
    --cpu 2 \
    --memory 4 \
    --ports 7474 7687 \
    --ip-address Public \
    --dns-name-label "neo4j-graphrag-${RANDOM}" \
    --environment-variables \
      NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
      NEO4J_PLUGINS='["apoc","graph-data-science"]' \
    --azure-file-volume-account-name "$STORAGE_ACCOUNT" \
    --azure-file-volume-account-key "$STORAGE_KEY" \
    --azure-file-volume-share-name neo4j-data \
    --azure-file-volume-mount-path /data \
    --no-wait
  
  echo "  ⏳ Waiting for Neo4j to start (30s)..."
  sleep 30
  
  NEO4J_FQDN=$(az container show --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --query ipAddress.fqdn -o tsv)
else
  echo "  Neo4j state: $NEO4J_STATE"
  echo "  ⏳ Waiting for current operation to complete..."
  sleep 20
  NEO4J_FQDN=$(az container show --name neo4j-graphrag --resource-group "$RESOURCE_GROUP" --query ipAddress.fqdn -o tsv)
fi

NEO4J_URI="bolt://${NEO4J_FQDN}:7687"
echo "✅ Neo4j: $NEO4J_URI"

# Get existing Azure resources
echo ""
echo "=================================================="
echo "Getting Azure Service Endpoints"
echo "=================================================="

# Try to find OpenAI endpoint in various resource groups
OPENAI_ENDPOINT=$(az cognitiveservices account list --resource-group rg-graphrag-feature --query "[?kind=='OpenAI' || kind=='AIServices'].properties.endpoint | [0]" -o tsv 2>/dev/null || echo "")
if [ -z "$OPENAI_ENDPOINT" ]; then
  OPENAI_ENDPOINT=$(az cognitiveservices account list --resource-group rg-knowledgegraph --query "[?kind=='OpenAI' || kind=='AIServices'].properties.endpoint | [0]" -o tsv 2>/dev/null || echo "")
fi
COSMOS_ENDPOINT=$(az cosmosdb list --resource-group rg-knowledgegraph --query "[0].documentEndpoint" -o tsv 2>/dev/null || echo "")

if [ -n "$OPENAI_ENDPOINT" ]; then
  echo "✅ Azure OpenAI: $OPENAI_ENDPOINT"
else
  echo "⚠️  No Azure OpenAI found, using known endpoint"
  OPENAI_ENDPOINT="https://graphrag-cu-swedencentral.cognitiveservices.azure.com/"
fi

if [ -n "$COSMOS_ENDPOINT" ]; then
  echo "✅ Cosmos DB: $COSMOS_ENDPOINT"
else
  echo "⚠️  No Cosmos DB found"
fi

# Deploy or update GraphRAG Container App
echo ""
echo "=================================================="
echo "Deploying GraphRAG Container App"
echo "=================================================="

APP_EXISTS=$(az containerapp show --name graphrag-orchestration --resource-group "$RESOURCE_GROUP" 2>/dev/null && echo "yes" || echo "no")

if [ "$APP_EXISTS" = "yes" ]; then
  echo "⏳ Updating existing app..."
  az containerapp update \
    --name graphrag-orchestration \
    --resource-group "$RESOURCE_GROUP" \
    --image "$ACR_SERVER/graphrag-orchestration:latest" \
    --set-env-vars \
      "NEO4J_URI=$NEO4J_URI" \
      "NEO4J_USERNAME=neo4j" \
      "NEO4J_PASSWORD=$NEO4J_PASSWORD" \
      "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT" \
      "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
    --output table
    # Note: Azure Content Understanding endpoint commented out - using Azure Document Intelligence instead
    # "AZURE_CONTENT_UNDERSTANDING_ENDPOINT=https://cu-graphrag-service.cognitiveservices.azure.com/" \
    # "AZURE_CONTENT_UNDERSTANDING_API_KEY=..."
else
  echo "⏳ Creating new app..."
  az containerapp create \
    --name graphrag-orchestration \
    --resource-group "$RESOURCE_GROUP" \
    --environment graphrag-env \
    --image "$ACR_SERVER/graphrag-orchestration:latest" \
    --registry-server "$ACR_SERVER" \
    --registry-username "$ACR_NAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 2 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --env-vars \
      "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT" \
      "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o" \
      "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large" \
      "NEO4J_URI=$NEO4J_URI" \
      "NEO4J_USERNAME=neo4j" \
      "NEO4J_PASSWORD=$NEO4J_PASSWORD" \
      "VECTOR_STORE_TYPE=lancedb" \
      "LANCEDB_PATH=/app/data/lancedb" \
      "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
      "COSMOS_DATABASE_NAME=content-processor" \
      "ENABLE_GROUP_ISOLATION=true" \
    --output table
    # Note: Azure Content Understanding endpoint commented out - using Azure Document Intelligence instead
    # "AZURE_CONTENT_UNDERSTANDING_ENDPOINT=https://cu-graphrag-service.cognitiveservices.azure.com/" \
    # "AZURE_CONTENT_UNDERSTANDING_API_KEY=..."
fi

GRAPHRAG_URL=$(az containerapp show --name graphrag-orchestration --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)
GRAPHRAG_URL="https://$GRAPHRAG_URL"

# Summary
echo ""
echo "=================================================="
echo "🎉 Deployment Complete!"
echo "=================================================="
echo ""
echo "GraphRAG Service:"
echo "  URL: $GRAPHRAG_URL"
echo "  Health: $GRAPHRAG_URL/health"
echo ""
echo "Neo4j:"
echo "  Bolt: $NEO4J_URI"
echo "  Browser: http://${NEO4J_FQDN}:7474"
echo "  Username: neo4j"
echo "  Password: $NEO4J_PASSWORD"
echo ""
echo "Test:"
echo "  curl -H 'X-Group-ID: test' $GRAPHRAG_URL/health"
echo ""
echo "=================================================="

# Save info
cat > deployment-info.txt << EOF
GraphRAG Service: $GRAPHRAG_URL
Neo4j URI: $NEO4J_URI
Neo4j Password: $NEO4J_PASSWORD
Neo4j Browser: http://${NEO4J_FQDN}:7474
EOF

echo "✅ Info saved to: deployment-info.txt"

# Cleanup local Docker image to save space
echo ""
echo "=================================================="
echo "Cleaning up local Docker image"
echo "=================================================="
if [ -n "$IMAGE_ID" ]; then
  echo "⏳ Removing local image $IMAGE_ID..."
  docker rmi -f "$IMAGE_ID" 2>/dev/null || echo "  (Image already removed)"
  echo "✅ Local Docker image cleaned up"
  
  # Show disk space saved
  echo ""
  echo "💾 Disk space check:"
  df -h /var/lib/docker 2>/dev/null || df -h / | grep "/$"
fi
