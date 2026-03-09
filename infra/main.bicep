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
param serviceGraphragApiImageName string = ''

@description('Worker container image - processes background jobs')
param serviceGraphragWorkerImageName string = ''

@description('API Gateway image name from azd env (fallback)')
param SERVICE_GRAPHRAG_API_IMAGE_NAME string = ''

@description('Worker image name from azd env (fallback)')
param SERVICE_GRAPHRAG_WORKER_IMAGE_NAME string = ''

// Resolve image names with explicit fallback to ensure correct images
var apiImageName = !empty(serviceGraphragApiImageName) ? serviceGraphragApiImageName : (!empty(SERVICE_GRAPHRAG_API_IMAGE_NAME) ? SERVICE_GRAPHRAG_API_IMAGE_NAME : '${containerRegistry.name}.azurecr.io/graphrag-api:latest')
var workerImageName = !empty(serviceGraphragWorkerImageName) ? serviceGraphragWorkerImageName : (!empty(SERVICE_GRAPHRAG_WORKER_IMAGE_NAME) ? SERVICE_GRAPHRAG_WORKER_IMAGE_NAME : '${containerRegistry.name}.azurecr.io/graphrag-worker:latest')

@secure()
@description('Neo4j Password')
param neo4jPassword string

@secure()
@description('Voyage API Key for V2 embeddings')
param voyageApiKey string = ''

@description('Azure Document Intelligence Endpoint')
param azureDocumentIntelligenceEndpoint string = 'https://doc-intel-graphrag.cognitiveservices.azure.com/'

@description('Azure Translator endpoint for multilingual query translation')
param azureTranslatorEndpoint string = ''

@description('Azure Translator region (defaults to swedencentral)')
param azureTranslatorRegion string = 'swedencentral'

@description('Azure Content Understanding endpoint (alternative to Document Intelligence)')
param azureContentUnderstandingEndpoint string = ''

@description('Enable speech translation for voice input')
param enableSpeechTranslation string = 'false'

// Easy Auth parameters
@description('Enable Easy Auth (Microsoft Entra ID authentication)')
param enableAuth bool = false

@description('Entra ID (Azure AD) Client ID for authentication')
param authClientId string = ''

@description('Authentication mode: B2B (groups claim) or B2C (oid claim)')
@allowed(['B2B', 'B2C'])
param authType string = 'B2B'

// External ID (B2C) parameters for consumer-facing app
@description('Enable External ID (B2C) consumer app deployment')
param enableB2C bool = false

@description('External ID tenant name (e.g., graphragb2c)')
param b2cTenantName string = ''

@description('External ID tenant ID')
param b2cTenantId string = ''

@description('External ID app client ID')
param b2cClientId string = ''

@secure()
@description('External ID app client secret')
param b2cClientSecret string = ''

@secure()
@description('Azure AD client secret for EasyAuth token refresh (B2B)')
param authClientSecret string = ''

// Custom domain parameters
@description('Custom domain for B2B app (e.g., evidoc-enterprise.hulkdesign.com). Empty = no custom domain.')
param b2bCustomDomain string = ''

@description('Custom domain for B2C app (e.g., evidoc.hulkdesign.com). Empty = no custom domain.')
param b2cCustomDomain string = ''

@description('Skip role assignments if they already exist')
param skipRoleAssignments bool = false

// APIM parameters
@description('Enable Azure API Management for external API access')
param enableApim bool = false

@description('Publisher email for APIM (required if enableApim=true)')
param apimPublisherEmail string = ''

@description('Admin API key for version management endpoints')
@secure()
param adminApiKey string = ''

// User upload / ADLS Gen2 storage parameters
@description('Enable user file upload with ADLS Gen2 (hierarchical namespace)')
param useUserUpload bool = true

@description('Container name for user uploads')
param userStorageContainerName string = 'user-content'

@description('Name of the storage account (ADLS Gen2 / HNS-enabled)')
param storageAccountName string = 'neo4jstorage21224'

// ── Additional secret parameters (previously managed by deploy script) ──

@secure()
@description('Mistral AI API key for OCR fallback')
param mistralApiKey string = ''

@secure()
@description('LLMWhisperer API key for OCR fallback')
param llmwhispererApiKey string = ''

@secure()
@description('Neo4j Aura DS client secret for GDS operations')
param auraDsClientSecret string = ''

@description('Neo4j Aura DS client ID for GDS operations')
param auraDsClientId string = ''

// ── Parameterized resource names (previously hardcoded) ─────────────────

@description('Name of the existing resource group')
param resourceGroupName string = 'rg-graphrag-feature'

@description('Name of the existing Azure Container Registry')
param containerRegistryName string = 'graphragacr12153'

@description('Name of the Container Apps Environment')
param containerAppsEnvironmentName string = 'graphrag-env'

@description('Azure OpenAI endpoint URL')
param azureOpenAiEndpoint string = 'https://graphrag-openai-8476.openai.azure.com/'

@description('Azure OpenAI resource name (for RBAC scoping)')
param azureOpenAiResourceName string = 'graphrag-openai-8476'

@description('Document Intelligence resource name')
param documentIntelligenceName string = 'doc-intel-graphrag'

@description('Neo4j connection URI')
param neo4jUri string = 'neo4j+s://a86dcf63.databases.neo4j.io'

@description('Neo4j username')
param neo4jUsername string = 'neo4j'

@description('Neo4j database name')
param neo4jDatabase string = 'neo4j'

@description('Group ID override for shared demo tenant (empty = per-user isolation)')
param groupIdOverride string = ''

@description('Deployment timestamp for cache busting — auto-generated on each deploy')
param deployTimestamp string = utcNow()

// Tags for all resources
var tags = {
  azd_env_name: environmentName
  app: 'graphrag-orchestration'
}

// Reference existing Resource Group in Sweden Central
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: resourceGroupName
}

// Container Apps Environment - Create with consistent name
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: containerAppsEnvironmentName
    location: location
    tags: tags
  }
}

// Reference existing Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: containerRegistryName
  scope: rg
}

var acrCredentials = listCredentials(containerRegistry.id, '2023-01-01-preview')
var acrUsername = acrCredentials.username
var acrPassword = acrCredentials.passwords[0].value
var useAcrPassword = !empty(acrPassword)

// Reference existing storage account for generating token store SAS
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
  scope: rg
}

// Generate SAS URL for EasyAuth token store blob container
var tokenStoreSasExpiry = '2036-01-01T00:00:00Z'
var tokenStoreSas = storageAccount.listAccountSas('2023-05-01', {
  signedProtocol: 'https'
  signedResourceTypes: 'sco'
  signedPermission: 'rwdlacup'
  signedServices: 'b'
  signedExpiry: tokenStoreSasExpiry
}).accountSasToken
var tokenStoreSasUrl = 'https://${storageAccountName}.blob.core.windows.net/tokenstore?${tokenStoreSas}'

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

// Azure Managed Redis for async job queue (Balanced B0 HA)
module redis './core/cache/redis.bicep' = {
  name: 'redis-cache'
  scope: rg
  params: {
    cacheName: 'graphrag-redis-${uniqueString(rg.id)}'
    location: location
    tags: tags
  }
}

// ============================================================================
// Managed Identity — shared by all container apps for Key Vault access
// Created before Key Vault so RBAC can be assigned before container apps deploy.
// ============================================================================
module managedIdentity './core/security/identity.bicep' = {
  name: 'managed-identity'
  scope: rg
  params: {
    name: 'graphrag-identity-${uniqueString(rg.id)}'
    location: location
    tags: tags
  }
}

// ============================================================================
// Key Vault — single source of truth for all secrets
// ============================================================================
module keyVault './core/security/key-vault.bicep' = {
  name: 'key-vault'
  scope: rg
  params: {
    name: 'graphrag-kv-${uniqueString(rg.id)}'
    location: location
    tags: tags
    secretReaderPrincipalIds: [
      managedIdentity.outputs.principalId
    ]
    neo4jPassword: neo4jPassword
    voyageApiKey: voyageApiKey
    mistralApiKey: mistralApiKey
    llmwhispererApiKey: llmwhispererApiKey
    auraDsClientSecret: auraDsClientSecret
    authClientSecret: authClientSecret
    b2cClientSecret: b2cClientSecret
    adminApiKey: adminApiKey
  }
}

// ============================================================================
// Custom Domain Managed Certificates (Optional)
// Prerequisites: CNAME DNS records must be configured BEFORE deploying with
// custom domains. See DNS setup instructions in docs/.
// ============================================================================

// B2B managed certificate (e.g., evidoc-enterprise.hulkdesign.com)
module b2bManagedCert './core/host/managed-certificate.bicep' = if (!empty(b2bCustomDomain)) {
  name: 'b2b-managed-cert'
  scope: rg
  params: {
    environmentName: containerAppsEnvironmentName
    location: location
    domainName: b2bCustomDomain
    existingCertName: 'mc-rg-graphrag-fe-evidoc-enterpris-4005'
  }
  dependsOn: [containerAppsEnvironment]
}

// B2C managed certificate (e.g., evidoc.hulkdesign.com)
module b2cManagedCert './core/host/managed-certificate.bicep' = if (!empty(b2cCustomDomain)) {
  name: 'b2c-managed-cert'
  scope: rg
  params: {
    environmentName: containerAppsEnvironmentName
    location: location
    domainName: b2cCustomDomain
    existingCertName: 'mc-rg-graphrag-fe-evidoc-hulkdesig-2553'
  }
  dependsOn: [containerAppsEnvironment]
}

// GraphRAG API Gateway Container App
module graphragApi './core/host/container-app.bicep' = {
  name: 'graphrag-api'
  scope: rg
  params: {
    name: 'graphrag-api'
    location: location
    tags: union(tags, {
      'azd-service-name': 'graphrag-api'
    })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    registryUsername: useAcrPassword ? acrUsername : ''
    registryPasswordSecretName: useAcrPassword ? 'acr-password' : ''
    containerName: 'graphrag-api'
    containerImage: apiImageName
    userAssignedIdentityId: managedIdentity.outputs.id
    targetPort: 8000
    // Custom domain configuration
    customDomainName: b2bCustomDomain
    customDomainCertificateId: !empty(b2bCustomDomain) ? b2bManagedCert.outputs.certificateId : ''
    // Easy Auth configuration
    enableAuth: enableAuth
    authClientId: authClientId
    authTenantId: subscription().tenantId
    authType: authType
    clientSecretSettingName: !empty(authClientSecret) ? 'aad-client-secret' : ''
    tokenStoreSasSecretName: ''
    env: concat(apiSpecificEnvVars, sharedEnvVars, conditionalSecretEnvVars, !empty(adminApiKey) ? [
      {
        name: 'ADMIN_API_KEY'
        secretRef: 'admin-api-key'
      }
    ] : [])
    secrets: concat(sharedSecrets, !empty(adminApiKey) ? [
      {
        name: 'admin-api-key'
        keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/admin-api-key'
        identity: managedIdentity.outputs.id
      }
    ] : [], !empty(authClientSecret) ? [
      {
        name: 'aad-client-secret'
        keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/aad-client-secret'
        identity: managedIdentity.outputs.id
      }
    ] : [])
  }
}

// ── API-specific env vars (not shared with worker) ──────────────────────
var apiSpecificEnvVars = [
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
    name: 'GROUP_ID_OVERRIDE'
    value: groupIdOverride
  }
  {
    name: 'ALLOW_LEGACY_GROUP_HEADER'
    value: 'false'
  }
  {
    name: 'PORT'
    value: '8000'
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
]

// ── User upload env vars (shared by API and B2C) ────────────────────────
var userUploadEnvVars = [
  {
    name: 'USE_USER_UPLOAD'
    value: 'true'
  }
  {
    name: 'AZURE_STORAGE_ACCOUNT'
    value: storageAccountName
  }
  {
    name: 'AZURE_STORAGE_CONTAINER'
    value: 'documents'
  }
  {
    name: 'AZURE_USERSTORAGE_ACCOUNT'
    value: storageAccountName
  }
  {
    name: 'AZURE_USERSTORAGE_CONTAINER'
    value: userStorageContainerName
  }
]

// ── Conditional secret-ref env vars (added when secrets are provided) ───
var conditionalSecretEnvVars = concat(
  !empty(voyageApiKey) ? [{ name: 'VOYAGE_API_KEY', secretRef: 'voyage-api-key' }] : [],
  !empty(mistralApiKey) ? [{ name: 'MISTRAL_API_KEY', secretRef: 'mistral-api-key' }] : [],
  !empty(llmwhispererApiKey) ? [{ name: 'LLMWHISPERER_API_KEY', secretRef: 'llmwhisperer-api-key' }] : [],
  !empty(auraDsClientSecret) ? [
      { name: 'AURA_DS_CLIENT_ID', value: auraDsClientId }
      { name: 'AURA_DS_CLIENT_SECRET', secretRef: 'aura-ds-client-secret' }
    ] : []
)

// Shared environment variables for both API and Worker
var sharedEnvVars = concat([
  {
    name: 'RUNNING_IN_PRODUCTION'
    value: 'true'
  }
  {
    name: 'REFRESH_TIMESTAMP'
    value: deployTimestamp
  }
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: azureOpenAiEndpoint
  }
  {
    name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
    value: azureOpenAiEndpoint
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
  // DEPRECATED: V1 legacy OpenAI embedding settings (V2 uses Voyage voyage-context-3 / 2048 dims)
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
    name: 'AZURE_CONTENT_UNDERSTANDING_ENDPOINT'
    value: azureContentUnderstandingEndpoint
  }
  {
    name: 'AZURE_TRANSLATOR_ENDPOINT'
    value: azureTranslatorEndpoint
  }
  {
    name: 'AZURE_TRANSLATOR_REGION'
    value: azureTranslatorRegion
  }
  {
    name: 'ENABLE_SPEECH_TRANSLATION'
    value: enableSpeechTranslation
  }
  {
    name: 'NEO4J_URI'
    value: neo4jUri
  }
  {
    name: 'NEO4J_USERNAME'
    value: neo4jUsername
  }
  {
    name: 'NEO4J_PASSWORD'
    secretRef: 'neo4j-password'
  }
  {
    name: 'NEO4J_DATABASE'
    value: neo4jDatabase
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
    value: string(redis.outputs.redisPort)
  }
  {
    name: 'REDIS_PASSWORD'
    secretRef: 'redis-password'
  }
  {
    name: 'REDIS_QUEUE_NAME'
    value: '{graphrag}:jobs:pending'
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
], useUserUpload ? userUploadEnvVars : [])

// Shared secrets — Key Vault references + runtime-generated values
var sharedSecrets = concat([
  {
    name: 'neo4j-password'
    keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/neo4j-password'
    identity: managedIdentity.outputs.id
  }
  {
    name: 'redis-password'
    value: redis.outputs.redisPrimaryKey
  }
], useAcrPassword ? [
  {
    name: 'acr-password'
    value: acrPassword
  }
] : [], !empty(voyageApiKey) ? [
  {
    name: 'voyage-api-key'
    keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/voyage-api-key'
    identity: managedIdentity.outputs.id
  }
] : [], !empty(mistralApiKey) ? [
  {
    name: 'mistral-api-key'
    keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/mistral-api-key'
    identity: managedIdentity.outputs.id
  }
] : [], !empty(llmwhispererApiKey) ? [
  {
    name: 'llmwhisperer-api-key'
    keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/llmwhisperer-api-key'
    identity: managedIdentity.outputs.id
  }
] : [], !empty(auraDsClientSecret) ? [
  {
    name: 'aura-ds-client-secret'
    keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/aura-ds-client-secret'
    identity: managedIdentity.outputs.id
  }
] : [])

// ============================================================================
// GraphRAG API B2C (External ID) - Consumer-facing endpoint
// ============================================================================
// Deploys a separate container app for External ID (B2C) authentication
// Uses oid (user object ID) as partition key instead of groups
module graphragApiB2C './core/host/container-app.bicep' = if (enableB2C && !empty(b2cClientId)) {
  name: 'graphrag-api-b2c'
  scope: rg
  params: {
    name: 'graphrag-api-b2c'
    location: location
    tags: union(tags, {
      'azd-service-name': 'graphrag-api-b2c'
    })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    registryUsername: useAcrPassword ? acrUsername : ''
    registryPasswordSecretName: useAcrPassword ? 'acr-password' : ''
    containerName: 'graphrag-api-b2c'
    containerImage: apiImageName
    userAssignedIdentityId: managedIdentity.outputs.id
    targetPort: 8000
    // Custom domain configuration
    customDomainName: b2cCustomDomain
    customDomainCertificateId: !empty(b2cCustomDomain) ? b2cManagedCert.outputs.certificateId : ''
    // External ID (B2C) auth configuration
    enableAuth: true
    authClientId: b2cClientId
    authTenantId: b2cTenantId
    authType: 'B2C'
    useExternalIdIssuer: true
    externalIdTenantName: b2cTenantName
    clientSecretSettingName: !empty(b2cClientSecret) ? 'b2c-client-secret' : ''
    tokenStoreSasSecretName: 'token-store-sas'
    env: concat([
      {
        name: 'SERVICE_ROLE'
        value: 'api'
      }
      {
        name: 'AUTH_TYPE'
        value: 'B2C'
      }
      {
        name: 'REQUIRE_AUTH'
        value: 'true'
      }
      {
        name: 'AUTH_CLIENT_ID'
        value: b2cClientId
      }
      {
        name: 'ALLOW_LEGACY_GROUP_HEADER'
        value: 'false'
      }
    ], sharedEnvVars, conditionalSecretEnvVars, !empty(adminApiKey) ? [
      {
        name: 'ADMIN_API_KEY'
        secretRef: 'admin-api-key'
      }
    ] : [])
    secrets: concat(sharedSecrets, [
      {
        name: 'token-store-sas'
        value: tokenStoreSasUrl
      }
    ], !empty(adminApiKey) ? [
      {
        name: 'admin-api-key'
        keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/admin-api-key'
        identity: managedIdentity.outputs.id
      }
    ] : [], !empty(b2cClientSecret) ? [
      {
        name: 'b2c-client-secret'
        keyVaultUrl: '${keyVault.outputs.vaultUri}secrets/b2c-client-secret'
        identity: managedIdentity.outputs.id
      }
    ] : [])
  }
}

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
    registryUsername: useAcrPassword ? acrUsername : ''
    registryPasswordSecretName: useAcrPassword ? 'acr-password' : ''
    containerName: 'graphrag-worker'
    containerImage: workerImageName
    userAssignedIdentityId: managedIdentity.outputs.id
    cpuCores: '1.0'
    memory: '2Gi'
    minReplicas: 1
    maxReplicas: 5
    redisHost: redis.outputs.redisHostName
    redisPort: redis.outputs.redisPort
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
    ], sharedEnvVars, conditionalSecretEnvVars)
    secrets: sharedSecrets
  }
}

// Deploy Azure OpenAI Models (Lean Engine Architecture)
module openAiModels './core/ai/openai-models.bicep' = {
  name: 'openai-models'
  scope: rg
  params: {
    openAiResourceName: azureOpenAiResourceName
    location: location
  }
}

// Role Assignments — all container apps share the same user-assigned managed identity
module roleAssignments './core/security/role-assignments.bicep' = if (!skipRoleAssignments) {
  name: 'role-assignments'
  scope: rg
  params: {
    documentIntelligenceName: documentIntelligenceName
    storageAccountName: storageAccountName
    containerRegistryName: containerRegistry.name
    containerAppPrincipalIds: [
      managedIdentity.outputs.principalId
    ]
    azureOpenAiName: azureOpenAiResourceName
    cosmosAccountName: cosmosDb.outputs.cosmosAccountName
    userStorageAccountName: useUserUpload ? storageAccountName : ''
  }
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
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = '${containerRegistry.name}.azurecr.io'
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.name
output GRAPHRAG_API_URI string = graphragApi.outputs.uri
output GRAPHRAG_API_NAME string = graphragApi.outputs.name
output GRAPHRAG_API_B2C_URI string = enableB2C && !empty(b2cClientId) ? graphragApiB2C.outputs.uri : ''
output GRAPHRAG_API_B2C_NAME string = enableB2C && !empty(b2cClientId) ? graphragApiB2C.outputs.name : ''
output GRAPHRAG_WORKER_NAME string = graphragWorker.outputs.name
output COSMOS_DB_ENDPOINT string = cosmosDb.outputs.cosmosAccountEndpoint
output COSMOS_DB_DATABASE_NAME string = cosmosDb.outputs.databaseName
output APIM_GATEWAY_URL string = enableApim ? apim.outputs.apimGatewayUrl : ''
output APIM_NAME string = enableApim ? apim.outputs.apimName : ''
output GRAPHRAG_API_CUSTOM_DOMAIN string = !empty(b2bCustomDomain) ? 'https://${b2bCustomDomain}' : ''
output GRAPHRAG_API_B2C_CUSTOM_DOMAIN string = !empty(b2cCustomDomain) ? 'https://${b2cCustomDomain}' : ''
output AZURE_USERSTORAGE_ACCOUNT string = useUserUpload ? storageAccountName : ''
output AZURE_USERSTORAGE_CONTAINER string = useUserUpload ? userStorageContainerName : ''
output KEY_VAULT_NAME string = keyVault.outputs.vaultName
output KEY_VAULT_URI string = keyVault.outputs.vaultUri
output MANAGED_IDENTITY_ID string = managedIdentity.outputs.id
