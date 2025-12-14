#!/bin/bash
# Manual Azure Deployment Script for GraphRAG Service
# Deploys Neo4j + GraphRAG Container App to Azure

set -e

echo "=================================================="
echo "GraphRAG Manual Azure Deployment"
echo "=================================================="

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-graphrag-feature}"
LOCATION="${LOCATION:-swedencentral}"
NEO4J_CONTAINER_NAME="neo4j-graphrag"
GRAPHRAG_APP_NAME="graphrag-orchestration"
CONTAINER_ENV_NAME="graphrag-env"
ACR_NAME="graphragacr${RANDOM}"
NEO4J_PASSWORD="$(openssl rand -base64 24)"

echo ""
echo "Configuration:"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Location: $LOCATION"
echo "  Neo4j Password: (generated securely)"
echo ""

# Step 1: Create Resource Group
echo "=================================================="
echo "Step 1: Creating Resource Group"
echo "=================================================="
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output table

# Step 2: Create Azure Container Registry
echo ""
echo "=================================================="
echo "Step 2: Creating Azure Container Registry"
echo "=================================================="
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true \
  --output table

echo "Waiting for ACR to be ready..."
for i in {1..30}; do
  if nslookup "$ACR_SERVER" > /dev/null 2>&1; then
    echo "✅ ACR DNS ready"
    break
  fi
  echo "  Attempt $i/30: Waiting for DNS propagation..."
  sleep 5
done

echo "Getting ACR credentials..."
ACR_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query "passwords[0].value" -o tsv)

echo "  ACR Server: $ACR_SERVER"

# Step 3: Build and Push Docker Image
echo ""
echo "=================================================="
echo "Step 3: Building and Pushing Docker Image"
echo "=================================================="
echo "⏳ Logging in to ACR..."
echo "$ACR_PASSWORD" | docker login "$ACR_SERVER" --username "$ACR_USERNAME" --password-stdin

echo "⏳ Building image (this may take 1-2 minutes)..."
docker build -t "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest" . 2>&1 | grep -E "^#|^Step|^Successfully|ERROR" || docker build -t "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest" .

echo "⏳ Pushing image to ACR (this may take 1-2 minutes)..."
docker push "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest" 2>&1 | grep -E "Pushing|Pushed|digest|ERROR" || docker push "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest"

echo "✅ Image pushed: $ACR_SERVER/$GRAPHRAG_APP_NAME:latest"

# Save image ID for cleanup after successful deployment
IMAGE_ID=$(docker images "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest" --format "{{.ID}}")
echo "  Image ID: $IMAGE_ID (will cleanup after deployment)"

# Step 4: Deploy Neo4j as Container Instance
echo ""
echo "=================================================="
echo "Step 4: Deploying Neo4j Container Instance"
echo "=================================================="

# Create storage account for Neo4j persistence
STORAGE_ACCOUNT="neo4jstorage${RANDOM}"
echo "Creating storage account: $STORAGE_ACCOUNT"
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --output table

STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query "[0].value" -o tsv)

echo "Creating file share for Neo4j data..."
az storage share create \
  --name neo4j-data \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --output table

echo "Deploying Neo4j container (this may take 2-3 minutes)..."
echo "⏳ Creating container instance..."
az container create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$NEO4J_CONTAINER_NAME" \
  --image neo4j:5.15.0 \
  --os-type Linux \
  --cpu 2 \
  --memory 4 \
  --ports 7474 7687 \
  --dns-name-label "${NEO4J_CONTAINER_NAME}-${RANDOM}" \
  --environment-variables \
    NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
    NEO4J_PLUGINS='["apoc", "graph-data-science"]' \
  --azure-file-volume-account-name "$STORAGE_ACCOUNT" \
  --azure-file-volume-account-key "$STORAGE_KEY" \
  --azure-file-volume-share-name neo4j-data \
  --azure-file-volume-mount-path /data \
  --output table &

CONTAINER_PID=$!
while kill -0 $CONTAINER_PID 2>/dev/null; do
  echo "  ⏳ Still deploying Neo4j container..."
  sleep 10
done
wait $CONTAINER_PID

NEO4J_FQDN=$(az container show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$NEO4J_CONTAINER_NAME" \
  --query ipAddress.fqdn -o tsv)

NEO4J_URI="bolt://${NEO4J_FQDN}:7687"
echo "✅ Neo4j deployed at: $NEO4J_URI"
echo "   Username: neo4j"
echo "   Password: $NEO4J_PASSWORD"

# Step 5: Create Container Apps Environment
echo ""
echo "=================================================="
echo "Step 5: Creating Container Apps Environment"
echo "=================================================="
echo "⏳ Creating environment (this may take 3-5 minutes)..."
az containerapp env create \
  --name "$CONTAINER_ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output table &

ENV_PID=$!
while kill -0 $ENV_PID 2>/dev/null; do
  echo "  ⏳ Still creating Container Apps environment..."
  sleep 15
done
wait $ENV_PID
echo "✅ Environment created"

# Step 6: Get Azure OpenAI Endpoint (from existing deployment)
echo ""
echo "=================================================="
echo "Step 6: Retrieving Azure OpenAI Configuration"
echo "=================================================="

# Try to get from existing resource group
OPENAI_ENDPOINT=$(az cognitiveservices account list \
  --resource-group rg-knowledgegraph \
  --query "[?kind=='OpenAI'].properties.endpoint | [0]" -o tsv 2>/dev/null || echo "")

if [ -z "$OPENAI_ENDPOINT" ]; then
  echo "⚠️  No Azure OpenAI found in rg-knowledgegraph"
  echo "   You'll need to configure this manually after deployment"
  OPENAI_ENDPOINT="https://placeholder.openai.azure.com/"
else
  echo "✅ Found Azure OpenAI: $OPENAI_ENDPOINT"
fi

# Get Cosmos DB endpoint (from existing deployment)
COSMOS_ENDPOINT=$(az cosmosdb list \
  --resource-group rg-knowledgegraph \
  --query "[0].documentEndpoint" -o tsv 2>/dev/null || echo "")

if [ -z "$COSMOS_ENDPOINT" ]; then
  echo "⚠️  No Cosmos DB found in rg-knowledgegraph"
  COSMOS_ENDPOINT=""
else
  echo "✅ Found Cosmos DB: $COSMOS_ENDPOINT"
  COSMOS_KEY=$(az cosmosdb keys list \
    --resource-group rg-knowledgegraph \
    --name $(az cosmosdb list --resource-group rg-knowledgegraph --query "[0].name" -o tsv) \
    --query primaryMasterKey -o tsv)
fi

# Step 7: Deploy GraphRAG Container App
echo ""
echo "=================================================="
echo "Step 7: Deploying GraphRAG Container App"
echo "=================================================="
echo "⏳ Creating container app (this may take 2-3 minutes)..."

az containerapp create \
  --name "$GRAPHRAG_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$CONTAINER_ENV_NAME" \
  --image "$ACR_SERVER/$GRAPHRAG_APP_NAME:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
    "AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT" \
    "AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4" \
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002" \
    "NEO4J_URI=$NEO4J_URI" \
    "NEO4J_USERNAME=neo4j" \
    "NEO4J_PASSWORD=$NEO4J_PASSWORD" \
    "VECTOR_STORE_TYPE=lancedb" \
    "LANCEDB_PATH=/app/data/lancedb" \
    "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
    "COSMOS_DATABASE_NAME=content-processor" \
    "ENABLE_GROUP_ISOLATION=true" \
  --output table

GRAPHRAG_URL=$(az containerapp show \
  --name "$GRAPHRAG_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

GRAPHRAG_URL="https://$GRAPHRAG_URL"

# Step 8: Configure Managed Identity (for Azure OpenAI)
echo ""
echo "=================================================="
echo "Step 8: Configuring Managed Identity"
echo "=================================================="

echo "Enabling system-assigned identity..."
az containerapp identity assign \
  --name "$GRAPHRAG_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --system-assigned \
  --output table

IDENTITY_PRINCIPAL_ID=$(az containerapp identity show \
  --name "$GRAPHRAG_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query principalId -o tsv)

echo "✅ Identity Principal ID: $IDENTITY_PRINCIPAL_ID"

if [ -n "$COSMOS_ENDPOINT" ]; then
  echo "Granting Cosmos DB access..."
  COSMOS_ACCOUNT=$(az cosmosdb list --resource-group rg-knowledgegraph --query "[0].name" -o tsv)
  az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT" \
    --resource-group rg-knowledgegraph \
    --role-definition-id "00000000-0000-0000-0000-000000000002" \
    --principal-id "$IDENTITY_PRINCIPAL_ID" \
    --scope "/" \
    --output table || echo "⚠️  Cosmos DB role assignment may already exist"
fi

# Save deployment info
echo ""
echo "=================================================="
echo "Saving Deployment Configuration"
echo "=================================================="

cat > deployment-info.env << EOF
# GraphRAG Deployment Information
# Generated: $(date)

RESOURCE_GROUP=$RESOURCE_GROUP
LOCATION=$LOCATION

# Neo4j
NEO4J_URI=$NEO4J_URI
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=$NEO4J_PASSWORD
NEO4J_BROWSER_URL=http://${NEO4J_FQDN}:7474

# GraphRAG Service
GRAPHRAG_URL=$GRAPHRAG_URL
GRAPHRAG_APP_NAME=$GRAPHRAG_APP_NAME
IDENTITY_PRINCIPAL_ID=$IDENTITY_PRINCIPAL_ID

# Azure Resources
ACR_NAME=$ACR_NAME
ACR_SERVER=$ACR_SERVER
STORAGE_ACCOUNT=$STORAGE_ACCOUNT
AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT
COSMOS_ENDPOINT=$COSMOS_ENDPOINT

# For Cosmos DB access, also set:
# COSMOS_KEY=$COSMOS_KEY
EOF

echo "✅ Deployment info saved to: deployment-info.env"

# Summary
echo ""
echo "=================================================="
echo "🎉 Deployment Complete!"
echo "=================================================="
echo ""
echo "GraphRAG Service URL:"
echo "  $GRAPHRAG_URL"
echo ""
echo "Neo4j Browser:"
echo "  http://${NEO4J_FQDN}:7474"
echo "  Username: neo4j"
echo "  Password: $NEO4J_PASSWORD"
echo ""
echo "Test the service:"
echo "  curl -H 'X-Group-ID: test' $GRAPHRAG_URL/health"
echo ""
echo "View logs:"
echo "  az containerapp logs show --name $GRAPHRAG_APP_NAME --resource-group $RESOURCE_GROUP --follow"
echo ""
echo "Next steps:"
if [ "$OPENAI_ENDPOINT" = "https://placeholder.openai.azure.com/" ]; then
  echo "  1. Configure Azure OpenAI endpoint in Container App environment variables"
fi
echo "  2. Run integration tests: ./run_integration_tests.sh"
echo "  3. Access deployment info: cat deployment-info.env"
echo ""
echo "=================================================="

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
