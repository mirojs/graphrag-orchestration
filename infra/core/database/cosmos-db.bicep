@description('Cosmos DB account name')
param accountName string

@description('Location for the Cosmos DB account')
param location string = resourceGroup().location

@description('Tags to apply to all resources')
param tags object = {}

@description('Database name')
param databaseName string = 'graphrag'

// Create Cosmos DB account (serverless)
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
  }
}

// Create database
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// Create chat_history container
resource chatHistoryContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'chat_history'
  properties: {
    resource: {
      id: 'chat_history'
      partitionKey: {
        paths: [
          '/user_id'
        ]
        kind: 'Hash'
      }
      defaultTtl: 7776000 // 90 days in seconds
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/_etag/?'
          }
        ]
      }
    }
  }
}

// Create usage container
resource usageContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'usage'
  properties: {
    resource: {
      id: 'usage'
      partitionKey: {
        paths: [
          '/partition_id'
        ]
        kind: 'Hash'
      }
      defaultTtl: 7776000 // 90 days in seconds
      indexingPolicy: {
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/_etag/?'
          }
        ]
      }
    }
  }
}

// Outputs
output cosmosAccountName string = cosmosAccount.name
output cosmosAccountEndpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = database.name
output chatHistoryContainerName string = chatHistoryContainer.name
output usageContainerName string = usageContainer.name
