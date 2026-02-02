targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

// CRITICAL: Ensure we never accidentally deploy hello-world images
// azd generates parameter names as: service<ServiceName>ImageName
// where ServiceName is PascalCase version of service name
@description('API Gateway container image - handles HTTP requests')
param serviceGraphragOrchestrationImageName string = ''

@description('Worker container image - processes background jobs')
param serviceGraphragWorkerImageName string = ''

@description('API Gateway image name from azd env (fallback)')
param SERVICE_GRAPHRAG_ORCHESTRATION_IMAGE_NAME string = ''

@description('Worker image name from azd env (fallback)')
param SERVICE_GRAPHRAG_WORKER_IMAGE_NAME string = ''

// Resolve image names with explicit fallback to ensure correct images
var apiImageName = !empty(serviceGraphragOrchestrationImageName) ? serviceGraphragOrchestrationImageName : (!empty(SERVICE_GRAPHRAG_ORCHESTRATION_IMAGE_NAME) ? SERVICE_GRAPHRAG_ORCHESTRATION_IMAGE_NAME : '${containerRegistry.name}.azurecr.io/graphrag-orchestration/graphrag-orchestration-default:latest')
var workerImageName = !empty(serviceGraphragWorkerImageName) ? serviceGraphragWorkerImageName : (!empty(SERVICE_GRAPHRAG_WORKER_IMAGE_NAME) ? SERVICE_GRAPHRAG_WORKER_IMAGE_NAME : '${containerRegistry.name}.azurecr.io/graphrag-orchestration/graphrag-worker-default:latest')

@secure()
@description('Neo4j Password')
param neo4jPassword string

@secure()
@description('Voyage API Key for V2 embeddings')
param voyageApiKey string = ''

@description('Azure Document Intelligence Endpoint')
param azureDocumentIntelligenceEndpoint string = 'https://doc-intel-graphrag.cognitiveservices.azure.com/'

// Easy Auth parameters
@description('Enable Easy Auth (Microsoft Entra ID authentication)')
param enableAuth bool = false

@description('Entra ID (Azure AD) Client ID for authentication')
param authClientId string = ''

@description('Authentication mode: B2B (groups claim) or B2C (oid claim)')
@allowed(['B2B', 'B2C'])
param authType string = 'B2B'

// APIM parameters
@description('Enable Azure API Management for external API access')
param enableApim bool = false

@description('Publisher email for APIM (required if enableApim=true)')
param apimPublisherEmail string = ''

@description('Admin API key for version management endpoints')
@secure()
param adminApiKey string = ''

// Tags for all resources
var tags = {
  azd_env_name: environmentName
  app: 'graphrag-orchestration'
}

// Reference existing Resource Group in Sweden Central
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: 'rg-graphrag-feature'
}

// Container Apps Environment - Create with consistent name
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: 'graphrag-env'  // Use fixed name instead of random token
    location: location
    tags: tags
  }
}

// Reference existing Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: 'graphragacr12153'
  scope: rg
}

// Cosmos DB for chat history and usage tracking
module cosmosDb './core/database/cosmos-db.bicep' = {
  name: 'cosmos-db'
  scope: rg
  params: {
    accountName: 'graphrag-cosmos-${uniqueString(rg.id)}'
    location: location
    tags: tags
    databaseName: 'graphrag'
  }
}

// Redis for async job queue
module redis './core/cache/redis.bicep' = {
  name: 'redis-cache'
  scope: rg
  params: {
    cacheName: 'graphrag-redis-${uniqueString(rg.id)}'
    location: location
    tags: tags
    sku: 'Basic'
    capacity: 0
  }
}

// GraphRAG API Gateway Container App
module graphragApi './core/host/container-app.bicep' = {
  name: 'graphrag-orchestration'
  scope: rg
  params: {
    name: 'graphrag-orchestration'
    location: location
    tags: union(tags, {
      'azd-service-name': 'graphrag-orchestration'
    })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    containerName: 'graphrag-orchestration'
    // API Gateway image - handles HTTP requests
    containerImage: apiImageName
    targetPort: 8000
    // Easy Auth configuration
    enableAuth: enableAuth
    authClientId: authClientId
    authTenantId: subscription().tenantId
    authType: authType
    env: concat([
      {
        name: 'SERVICE_ROLE'
        value: 'api'
      }
      {
        name: 'AUTH_TYPE'
        value: authType
      }
      {
        name: 'REQUIRE_AUTH'
        value: 'true'
      }
      {
        name: 'AUTH_CLIENT_ID'
        value: authClientId
      }
      {
        name: 'ALLOW_LEGACY_GROUP_HEADER'
        value: 'false'
      }
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: 'https://graphrag-openai-8476.openai.azure.com/'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
        value: 'https://graphrag-openai-8476.openai.azure.com/'
      }
      {
        name: 'AZURE_TENANT_ID'
        value: subscription().tenantId
      }
    ], [
      {
        name: 'PORT'
        value: '8000'
      }
      {
        name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
        value: 'gpt-5.1'
      }
      {
        name: 'AZURE_OPENAI_ROUTING_DEPLOYMENT'
        value: 'gpt-4o-mini'
      }
      {
        name: 'AZURE_OPENAI_INDEXING_DEPLOYMENT'
        value: 'gpt-4.1'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
        value: 'text-embedding-3-large'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS'
        value: '3072'
      }
      {
        name: 'AZURE_OPENAI_REASONING_EFFORT'
        value: 'high'
      }
      {
        name: 'AZURE_OPENAI_ROUTING_REASONING_EFFORT'
        value: 'medium'
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: '2024-10-21'
      }
      {
        name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'
        value: azureDocumentIntelligenceEndpoint
      }
      {
        name: 'NEO4J_URI'
        value: 'neo4j+s://a86dcf63.databases.neo4j.io'
      }
      {
        name: 'NEO4J_USERNAME'
        value: 'neo4j'
      }
      {
        name: 'NEO4J_PASSWORD'
        secretRef: 'neo4j-password'
      }
      {
        name: 'NEO4J_DATABASE'
        value: 'neo4j'
      }
      {
        name: 'COSMOS_DB_ENDPOINT'
        value: cosmosDb.outputs.cosmosAccountEndpoint
      }
      {
        name: 'COSMOS_DB_DATABASE_NAME'
        value: cosmosDb.outputs.databaseName
      }
      {
        name: 'COSMOS_DB_CHAT_HISTORY_CONTAINER'
        value: cosmosDb.outputs.chatHistoryContainerName
      }
      {
        name: 'COSMOS_DB_USAGE_CONTAINER'
        value: cosmosDb.outputs.usageContainerName
      }
      {
        name: 'REDIS_HOST'
        value: redis.outputs.redisHostName
      }
      {
        name: 'REDIS_PORT'
        value: string(redis.outputs.redisSslPort)
      }
      {
        name: 'REDIS_PASSWORD'
        secretRef: 'redis-password'
      }
      {
        name: 'REDIS_QUEUE_NAME'
        value: 'graphrag_jobs'
      }
      {
        name: 'ENABLE_GROUP_ISOLATION'
        value: 'true'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SELECTION'
        value: 'true'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_MAX_DEPTH'
        value: '2'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET'
        value: '30'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL'
        value: '12'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD'
        value: '25'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE'
        value: '8'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY'
        value: 'true'
      }
      {
        name: 'USE_SECTION_CHUNKING'
        value: '1'
      }
      {
        name: 'VOYAGE_V2_ENABLED'
        value: 'true'
      }
      {
        name: 'VOYAGE_EMBEDDING_MODEL'
        value: 'voyage-context-3'
      }
      {
        name: 'VOYAGE_EMBEDDING_DIM'
        value: '2048'
      }
      {
        name: 'DEFAULT_ALGORITHM_VERSION'
        value: 'v2'
      }
      {
        name: 'ALGORITHM_V1_ENABLED'
        value: 'true'
      }
      {
        name: 'ALGORITHM_V2_ENABLED'
        value: 'true'
      }
      {
        name: 'ALGORITHM_V3_PREVIEW_ENABLED'
        value: 'false'
      }
    ], !empty(voyageApiKey) ? [
      {
        name: 'VOYAGE_API_KEY'
        secretRef: 'voyage-api-key'
      }
    ] : [], !empty(adminApiKey) ? [
      {
        name: 'ADMIN_API_KEY'
        secretRef: 'admin-api-key'
      }
    ] : [])
    secrets: concat([
      {
        name: 'neo4j-password'
        value: neo4jPassword
      }
      {
        name: 'redis-password'
        value: redis.outputs.redisPrimaryKey
      }
    ], !empty(voyageApiKey) ? [
      {
        name: 'voyage-api-key'
        value: voyageApiKey
      }
    ] : [], !empty(adminApiKey) ? [
      {
        name: 'admin-api-key'
        value: adminApiKey
      }
    ] : [])
  }
}

// Shared environment variables for both API and Worker
var sharedEnvVars = [
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: 'https://graphrag-openai-8476.openai.azure.com/'
  }
  {
    name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
    value: 'https://graphrag-openai-8476.openai.azure.com/'
  }
  {
    name: 'AZURE_TENANT_ID'
    value: subscription().tenantId
  }
  {
    name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
    value: 'gpt-5.1'
  }
  {
    name: 'AZURE_OPENAI_ROUTING_DEPLOYMENT'
    value: 'gpt-4o-mini'
  }
  {
    name: 'AZURE_OPENAI_INDEXING_DEPLOYMENT'
    value: 'gpt-4.1'
  }
  {
    name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
    value: 'text-embedding-3-large'
  }
  {
    name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS'
    value: '3072'
  }
  {
    name: 'AZURE_OPENAI_API_VERSION'
    value: '2024-10-21'
  }
  {
    name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'
    value: azureDocumentIntelligenceEndpoint
  }
  {
    name: 'NEO4J_URI'
    value: 'neo4j+s://a86dcf63.databases.neo4j.io'
  }
  {
    name: 'NEO4J_USERNAME'
    value: 'neo4j'
  }
  {
    name: 'NEO4J_PASSWORD'
    secretRef: 'neo4j-password'
  }
  {
    name: 'NEO4J_DATABASE'
    value: 'neo4j'
  }
  {
    name: 'COSMOS_DB_ENDPOINT'
    value: cosmosDb.outputs.cosmosAccountEndpoint
  }
  {
    name: 'COSMOS_DB_DATABASE_NAME'
    value: cosmosDb.outputs.databaseName
  }
  {
    name: 'COSMOS_DB_CHAT_HISTORY_CONTAINER'
    value: cosmosDb.outputs.chatHistoryContainerName
  }
  {
    name: 'COSMOS_DB_USAGE_CONTAINER'
    value: cosmosDb.outputs.usageContainerName
  }
  {
    name: 'REDIS_HOST'
    value: redis.outputs.redisHostName
  }
  {
    name: 'REDIS_PORT'
    value: string(redis.outputs.redisSslPort)
  }
  {
    name: 'REDIS_PASSWORD'
    secretRef: 'redis-password'
  }
  {
    name: 'REDIS_QUEUE_NAME'
    value: 'graphrag_jobs'
  }
  {
    name: 'ENABLE_GROUP_ISOLATION'
    value: 'true'
  }
  {
    name: 'VOYAGE_V2_ENABLED'
    value: 'true'
  }
  {
    name: 'VOYAGE_EMBEDDING_MODEL'
    value: 'voyage-context-3'
  }
  {
    name: 'VOYAGE_EMBEDDING_DIM'
    value: '2048'
  }
]

var sharedSecrets = concat([
  {
    name: 'neo4j-password'
    value: neo4jPassword
  }
  {
    name: 'redis-password'
    value: redis.outputs.redisPrimaryKey
  }
], !empty(voyageApiKey) ? [
  {
    name: 'voyage-api-key'
    value: voyageApiKey
  }
] : [])

// GraphRAG Worker Container App (background job processing)
module graphragWorker './core/host/container-app-worker.bicep' = {
  name: 'graphrag-worker'
  scope: rg
  params: {
    name: 'graphrag-worker'
    location: location
    tags: union(tags, {
      'azd-service-name': 'graphrag-worker'
    })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    containerName: 'graphrag-worker'
    containerImage: workerImageName
    cpuCores: '1.0'
    memory: '2Gi'
    minReplicas: 1
    maxReplicas: 5
    env: concat([
      {
        name: 'SERVICE_ROLE'
        value: 'worker'
      }
      {
        name: 'AZURE_OPENAI_REASONING_EFFORT'
        value: 'high'
      }
      {
        name: 'AZURE_OPENAI_ROUTING_REASONING_EFFORT'
        value: 'medium'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SELECTION'
        value: 'true'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_MAX_DEPTH'
        value: '2'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET'
        value: '30'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL'
        value: '12'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD'
        value: '25'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE'
        value: '8'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY'
        value: 'true'
      }
      {
        name: 'USE_SECTION_CHUNKING'
        value: '1'
      }
    ], sharedEnvVars, !empty(voyageApiKey) ? [
      {
        name: 'VOYAGE_API_KEY'
        secretRef: 'voyage-api-key'
      }
    ] : [])
    secrets: sharedSecrets
  }
}

// Deploy Azure OpenAI Models (Lean Engine Architecture)
module openAiModels './core/ai/openai-models.bicep' = {
  name: 'openai-models'
  scope: rg
  params: {
    openAiResourceName: 'graphrag-openai-8476'
    location: location
  }
}

// Role Assignments for Container App Managed Identities (API + Worker)
module roleAssignments './core/security/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
    documentIntelligenceName: 'doc-intel-graphrag'
    storageAccountName: 'neo4jstorage21224'
    containerRegistryName: containerRegistry.name
    containerAppPrincipalIds: [
      graphragApi.outputs.identityPrincipalId
      graphragWorker.outputs.identityPrincipalId
    ]
    azureOpenAiName: 'graphrag-openai-8476'
    cosmosAccountName: cosmosDb.outputs.cosmosAccountName
  }
  dependsOn: [openAiModels, cosmosDb, graphragApi, graphragWorker] // Ensure resources exist before assigning permissions
}

// ============================================================================
// APIM - Azure API Management (Optional)
// Enable for external API clients requiring rate limiting and API key management
// ============================================================================
module apim './core/gateway/apim.bicep' = if (enableApim) {
  name: 'api-management'
  scope: rg
  params: {
    apimName: 'graphrag-apim-${uniqueString(rg.id)}'
    location: location
    tags: tags
    publisherEmail: apimPublisherEmail
    publisherName: 'GraphRAG Team'
    backendUrl: graphragApi.outputs.uri
    enableDevPortal: false
  }
  dependsOn: [graphragApi]
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = '${containerRegistry.name}.azurecr.io'
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.name
output GRAPHRAG_API_URI string = graphragApi.outputs.uri
output GRAPHRAG_API_NAME string = graphragApi.outputs.name
output GRAPHRAG_WORKER_NAME string = graphragWorker.outputs.name
output COSMOS_DB_ENDPOINT string = cosmosDb.outputs.cosmosAccountEndpoint
output COSMOS_DB_DATABASE_NAME string = cosmosDb.outputs.databaseName
output REDIS_HOST string = redis.outputs.redisHostName
output REDIS_PORT int = redis.outputs.redisSslPort
output APIM_GATEWAY_URL string = enableApim ? apim.outputs.apimGatewayUrl : ''
output APIM_NAME string = enableApim ? apim.outputs.apimName : ''
