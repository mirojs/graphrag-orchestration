targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Id of the user or app to assign application roles')
param principalId string = ''

@description('Azure OpenAI API Key (leave empty to use Managed Identity)')
param azureOpenAiApiKey string = ''

@description('Neo4j Password')
param neo4jPassword string = 'uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI'

@description('Azure Document Intelligence Endpoint')
param azureDocumentIntelligenceEndpoint string = 'https://doc-intel-graphrag.cognitiveservices.azure.com/'

@description('Azure AI Search Endpoint')
param azureSearchEndpoint string = 'https://graphrag-search.search.windows.net'

@description('Azure AI Search API Key (for RAPTOR indexing)')
@secure()
param azureSearchApiKey string = ''

// Tags for all resources
var tags = {
  'azd-env-name': environmentName
  'app': 'graphrag-orchestration'
}

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

// Reference existing Resource Group in Sweden Central
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: 'rg-graphrag-feature'
}

// Container Apps Environment
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
  }
}

// Reference existing Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: 'graphragacr12153'
  scope: rg
}

// GraphRAG Orchestration Container App
module graphragApp './core/host/container-app.bicep' = {
  name: 'graphrag-app'
  scope: rg
  params: {
    name: 'graphrag-orchestration'
    location: location
    tags: tags
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    containerName: 'graphrag-orchestration'
    containerImage: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' // Placeholder
    targetPort: 8000
    env: concat([
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: ''  // Set via azd env
      }
    ], azureOpenAiApiKey != '' ? [
      {
        name: 'AZURE_OPENAI_API_KEY'
        secretRef: 'azure-openai-api-key'
      }
    ] : [], [
      {
        name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
        value: 'gpt-4o'
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
        name: 'AZURE_SEARCH_ENDPOINT'
        value: azureSearchEndpoint
      }
    ], azureSearchApiKey != '' ? [
      {
        name: 'AZURE_SEARCH_API_KEY'
        secretRef: 'azure-search-api-key'
      }
    ] : [], [
      {
        name: 'AZURE_SEARCH_INDEX_NAME'
        value: 'graphrag-raptor'
      }
      {
        name: 'VECTOR_STORE_TYPE'
        value: 'azure_search'
      }
      {
        name: 'NEO4J_URI'
        value: ''  // Set via azd env
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
        name: 'ENABLE_GROUP_ISOLATION'
        value: 'true'
      }
    ])
    secrets: concat(azureOpenAiApiKey != '' ? [
      {
        name: 'azure-openai-api-key'
        value: azureOpenAiApiKey
      }
    ] : [], azureSearchApiKey != '' ? [
      {
        name: 'azure-search-api-key'
        value: azureSearchApiKey
      }
    ] : [], [
      {
        name: 'neo4j-password'
        value: neo4jPassword
      }
    ])
  }
}

// Role Assignments for Container App Managed Identity
module roleAssignments './core/security/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
    documentIntelligenceName: 'doc-intel-graphrag'
    storageAccountName: 'neo4jstorage21224'
    containerRegistryName: containerRegistry.name
    containerAppPrincipalId: graphragApp.outputs.identityPrincipalId
  }
  dependsOn: [
    graphragApp
  ]
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = '${containerRegistry.name}.azurecr.io'
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.name
output GRAPHRAG_APP_URI string = graphragApp.outputs.uri
output GRAPHRAG_APP_NAME string = graphragApp.outputs.name
