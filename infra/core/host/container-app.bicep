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

// Easy Auth parameters
@description('Enable Easy Auth (Microsoft Entra ID authentication)')
param enableAuth bool = false

@description('Entra ID (Azure AD) Client ID for authentication')
param authClientId string = ''

@description('Entra ID Tenant ID')
param authTenantId string = ''

@description('Authentication mode: B2B (groups claim) or B2C (oid claim)')
@allowed(['B2B', 'B2C'])
param authType string = 'B2B'

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

// Easy Auth configuration (Microsoft Entra ID / Azure AD)
resource authConfig 'Microsoft.App/containerApps/authConfigs@2024-10-02-preview' = if (enableAuth && !empty(authClientId)) {
  parent: containerApp
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          openIdIssuer: 'https://login.microsoftonline.com/${authTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${authClientId}'
            authClientId
          ]
          defaultAuthorizationPolicy: {
            allowedPrincipals: {}
          }
        }
        login: {
          loginParameters: authType == 'B2B' ? [
            'scope=openid profile email'
            'response_type=code'
          ] : [
            'scope=openid profile email'
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
      preserveUrlFragmentsForLogins: true
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output identityPrincipalId string = containerApp.identity.principalId
