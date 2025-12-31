param name string
param location string = resourceGroup().location
param tags object = {}
param containerAppsEnvironmentId string
param containerRegistryName string
param containerName string
param containerImage string
param userAssignedIdentityId string = ''
param targetPort int = 8000
param env array = []
param secrets array = []

resource containerApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'http'
      }
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
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
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
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output identityPrincipalId string = containerApp.identity.principalId
