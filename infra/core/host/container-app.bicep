param name string
param location string = resourceGroup().location
param tags object = {}
param containerAppsEnvironmentId string
param containerRegistryName string
param registryUsername string = ''
param registryPasswordSecretName string = ''
param containerName string
param containerImage string
param userAssignedIdentityId string = ''
param targetPort int = 8000
param env array = []
param secrets array = []

// Custom domain parameters
@description('Custom domain name (e.g., evidoc.hulkdesign.com). Empty = no custom domain.')
param customDomainName string = ''

@description('Managed certificate ID for custom domain TLS. Required if customDomainName is set.')
param customDomainCertificateId string = ''

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

@description('Use External ID (ciamlogin.com) issuer instead of standard Azure AD')
param useExternalIdIssuer bool = false

@description('External ID tenant name (e.g., graphragb2c) - required if useExternalIdIssuer is true')
param externalIdTenantName string = ''

@secure()
@description('Name of the Container App secret holding the Azure AD client secret (required for token refresh)')
param clientSecretSettingName string = ''

@description('Name of the Container App secret holding the SAS URL for the EasyAuth token store blob container')
param tokenStoreSasSecretName string = ''

// Calculate the OpenID issuer URL based on auth type
// CIAM (Entra External ID): use tenant ID as subdomain per Microsoft guidance
// https://learn.microsoft.com/en-ca/answers/questions/5615481/issuer-id-is-always-https-sts-windows-net
var openIdIssuerUrl = useExternalIdIssuer
  ? 'https://${authTenantId}.ciamlogin.com/${authTenantId}/v2.0'
  : 'https://login.microsoftonline.com/${authTenantId}/v2.0'

resource containerApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true  // API must be externally reachable; protected by Easy Auth + JWT middleware
        targetPort: targetPort
        transport: 'http'
        customDomains: !empty(customDomainName) && !empty(customDomainCertificateId) ? [
          {
            name: customDomainName
            certificateId: customDomainCertificateId
            bindingType: 'SniEnabled'
          }
        ] : []
      }
      registries: [
        !empty(registryUsername) ? {
          server: '${containerRegistryName}.azurecr.io'
          username: registryUsername
          passwordSecretRef: registryPasswordSecretName
        } : {
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
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: targetPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: targetPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 10
              timeoutSeconds: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
      }
    }
  }
  identity: {
    type: empty(userAssignedIdentityId) ? 'SystemAssigned' : 'SystemAssigned,UserAssigned'
    userAssignedIdentities: empty(userAssignedIdentityId) ? null : {
      '${userAssignedIdentityId}': {}
    }
  }
}

// Easy Auth configuration (Microsoft Entra ID / Azure AD)
// Both B2B and B2C use the standard azureActiveDirectory provider.
// CIAM (Entra External ID) works with the default hybrid flow (code id_token)
// when client secret is set and nonce validation is disabled for B2C.
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
          clientSecretSettingName: !empty(clientSecretSettingName) ? clientSecretSettingName : null
          openIdIssuer: openIdIssuerUrl
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
          loginParameters: [
            'scope=openid profile email offline_access'
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
        tokenRefreshExtensionHours: 72
        azureBlobStorage: !empty(tokenStoreSasSecretName) ? {
          sasUrlSettingName: tokenStoreSasSecretName
        } : null
      }
      preserveUrlFragmentsForLogins: true
      cookieExpiration: {
        convention: 'FixedTime'
        timeToExpiration: '08:00:00'
      }
      // CIAM (External ID) does not support nonce validation — only enable for B2B
      nonce: authType == 'B2B' ? {
        validateNonce: true
        nonceExpirationInterval: '00:05:00'
      } : null
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output identityPrincipalId string = containerApp.identity.principalId
