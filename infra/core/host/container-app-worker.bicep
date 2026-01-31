@description('Name of the container app')
param name string

@description('Location for the container app')
param location string = resourceGroup().location

@description('Tags for the resource')
param tags object = {}

@description('Container Apps Environment ID')
param containerAppsEnvironmentId string

@description('Container Registry Name')
param containerRegistryName string

@description('Container name within the app')
param containerName string

@description('Container image (fully qualified)')
param containerImage string

@description('User-assigned identity ID (optional)')
param userAssignedIdentityId string = ''

@description('Environment variables for the container')
param env array = []

@description('Secrets for the container')
param secrets array = []

@description('CPU allocation (default 0.5 for worker)')
param cpuCores string = '0.5'

@description('Memory allocation (default 1Gi for worker)')
param memory string = '1Gi'

@description('Minimum replicas (default 1)')
param minReplicas int = 1

@description('Maximum replicas (default 5)')
param maxReplicas int = 5

resource containerApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      // No ingress - worker is internal only, communicates via Redis queue
      ingress: null
      registries: [
        {
          server: '${containerRegistryName}.azurecr.io'
          identity: empty(userAssignedIdentityId) ? 'system' : userAssignedIdentityId
        }
      ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: containerName
          image: containerImage
          env: env
          resources: {
            cpu: json(cpuCores)
            memory: memory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        // Scale based on Redis queue length via KEDA
        rules: [
          {
            name: 'redis-queue-scaler'
            custom: {
              type: 'redis'
              metadata: {
                listName: 'graphrag_jobs'
                listLength: '5'
              }
              auth: [
                {
                  secretRef: 'redis-password'
                  triggerParameter: 'password'
                }
              ]
            }
          }
        ]
      }
    }
  }
  identity: {
    type: empty(userAssignedIdentityId) ? 'SystemAssigned' : 'UserAssigned'
    userAssignedIdentities: empty(userAssignedIdentityId) ? null : {
      '${userAssignedIdentityId}': {}
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output identityPrincipalId string = containerApp.identity.principalId
