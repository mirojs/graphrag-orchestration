@description('Name of the Container Apps Environment')
param environmentName string

@description('Location for the certificate resource')
param location string = resourceGroup().location

@description('Custom domain name for the certificate (e.g., evidoc.hulkdesign.com)')
param domainName string

@description('Name of an existing managed certificate to reference. When set, no new certificate is created.')
param existingCertName string = ''

// Reference the existing Container Apps Environment
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-10-02-preview' existing = {
  name: environmentName
}

// Reference an existing managed certificate (already provisioned outside Bicep)
resource existingCertificate 'Microsoft.App/managedEnvironments/managedCertificates@2024-10-02-preview' existing = if (!empty(existingCertName)) {
  parent: containerAppsEnvironment
  name: existingCertName
}

// Create a new managed certificate only when no existing cert name is provided
resource newCertificate 'Microsoft.App/managedEnvironments/managedCertificates@2024-10-02-preview' = if (empty(existingCertName)) {
  parent: containerAppsEnvironment
  name: 'cert-${replace(domainName, '.', '-')}'
  location: location
  properties: {
    subjectName: domainName
    domainControlValidation: 'CNAME'
  }
}

output certificateId string = !empty(existingCertName) ? existingCertificate.id : newCertificate.id
