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
// CIAM issuer uses tenant ID (not tenant name) as subdomain in the iss claim
var openIdIssuerUrl = useExternalIdIssuer && !empty(externalIdTenantName) 
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
        // Both B2B and B2C need offline_access to get refresh tokens.
        // B2B also uses response_type=code for auth code flow.
        // CIAM supports offline_access at the protocol level — the earlier 401 was caused by nonce, not this.
        login: {
          loginParameters: [
            'scope=openid profile email offline_access'
            'response_type=code'
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
      // CIAM (External ID) email OTP flow does NOT include nonce in id_tokens,
      // even though claims_supported lists it. Enabling validateNonce for B2C
      // causes EasyAuth to reject the callback → 401.
      // B2B (standard Entra ID) fully supports nonce validation.
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
