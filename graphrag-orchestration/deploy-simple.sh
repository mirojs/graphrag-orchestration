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
# Use custom IMAGE_TAG if provided, otherwise default to 'latest'
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="$ACR_SERVER/graphrag-orchestration:$IMAGE_TAG"

echo "Building and Pushing Docker Image"
echo "=================================================="
echo "Image tag: $IMAGE_TAG"
echo "⏳ Logging in..."
echo "$ACR_PASSWORD" | docker login "$ACR_SERVER" --username "$ACR_NAME" --password-stdin

echo "⏳ Building..."
docker build -t "$IMAGE_NAME" .

echo "⏳ Pushing..."
docker push "$IMAGE_NAME"

echo "✅ Image: $IMAGE_NAME"

# Save image ID for cleanup after successful deployment
IMAGE_ID=$(docker images "$IMAGE_NAME" --format "{{.ID}}")
echo "  Image ID: $IMAGE_ID (will cleanup after deployment)"

# Use Neo4j Aura (cloud-hosted, always available)
echo ""
echo "=================================================="
echo "Using Neo4j Aura Cloud"
echo "=================================================="
NEO4J_URI="neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_PASSWORD="uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"
echo "✅ Neo4j Aura: $NEO4J_URI"

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
    --image "$IMAGE_NAME" \
    --set-env-vars \
      "NEO4J_URI=$NEO4J_URI" \
      "NEO4J_USERNAME=neo4j" \
      "NEO4J_PASSWORD=$NEO4J_PASSWORD" \
      "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT" \
      "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://doc-intel-graphrag.cognitiveservices.azure.com/" \
      "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
    --output table
else
  echo "⏳ Creating new app..."
  az containerapp create \
    --name graphrag-orchestration \
    --resource-group "$RESOURCE_GROUP" \
    --environment graphrag-env \
    --image "$IMAGE_NAME" \
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
      "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://doc-intel-graphrag.cognitiveservices.azure.com/" \
      "NEO4J_URI=$NEO4J_URI" \
      "NEO4J_USERNAME=neo4j" \
      "NEO4J_PASSWORD=$NEO4J_PASSWORD" \
      "VECTOR_STORE_TYPE=lancedb" \
      "LANCEDB_PATH=/app/data/lancedb" \
      "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
      "COSMOS_DATABASE_NAME=content-processor" \
      "ENABLE_GROUP_ISOLATION=true" \
    --output table
fi

GRAPHRAG_URL=$(az containerapp show --name graphrag-orchestration --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)
GRAPHRAG_URL="https://$GRAPHRAG_URL"

# Configure managed identity and permissions
echo ""
echo "=================================================="
echo "Configuring Managed Identity & Permissions"
echo "=================================================="
echo "⏳ Assigning system managed identity..."
PRINCIPAL_ID=$(az containerapp identity assign \
  --name graphrag-orchestration \
  --resource-group "$RESOURCE_GROUP" \
  --system-assigned \
  --query principalId -o tsv)

if [ -n "$PRINCIPAL_ID" ]; then
  echo "✅ Managed identity: $PRINCIPAL_ID"
  
  echo "⏳ Granting Storage Blob Data Reader..."
  az role assignment create \
    --assignee "$PRINCIPAL_ID" \
    --role "Storage Blob Data Reader" \
    --scope "/subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT" \
    --output none 2>/dev/null || echo "  (Already assigned)"
  
  echo "⏳ Granting Cognitive Services User (Document Intelligence)..."
  az role assignment create \
    --assignee "$PRINCIPAL_ID" \
    --role "Cognitive Services User" \
    --scope "/subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/doc-intel-graphrag" \
    --output none 2>/dev/null || echo "  (Already assigned)"
  
  echo "⏳ Granting Cognitive Services OpenAI User..."
  az role assignment create \
    --assignee "$PRINCIPAL_ID" \
    --role "Cognitive Services OpenAI User" \
    --scope "/subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/graphrag-openai-8476" \
    --output none 2>/dev/null || echo "  (Already assigned)"
  
  echo "✅ All permissions configured"
  echo "⏳ Waiting 60s for RBAC propagation (Azure can be slow)..."
  sleep 60
else
  echo "❌ Failed to get principal ID"
fi

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
