// Azure API Management (Consumption Tier)
// 
// Provides:
// - Rate limiting for external API clients
// - API key management
// - Request/response logging
// - Developer portal (optional)
//
// Usage: Only provision when external clients need API access
// Internal frontend traffic goes directly to Container App

@description('Name of the API Management service')
param apimName string

@description('Location for resources')
param location string = resourceGroup().location

@description('Tags for resources')
param tags object = {}

@description('Publisher email for APIM')
param publisherEmail string

@description('Publisher name for APIM')
param publisherName string = 'GraphRAG Team'

@description('Container App URL to proxy to')
param backendUrl string

@description('Enable developer portal')
param enableDevPortal bool = false

// API Management - Consumption tier (serverless, pay-per-call)
resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: location
  tags: tags
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    // Consumption tier doesn't support VNet, but has built-in DDoS protection
  }
}

// Backend pointing to Container App
resource backend 'Microsoft.ApiManagement/service/backends@2023-05-01-preview' = {
  parent: apim
  name: 'graphrag-backend'
  properties: {
    url: backendUrl
    protocol: 'http'
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

// API definition for GraphRAG
resource api 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'graphrag-api'
  properties: {
    displayName: 'GraphRAG API'
    description: 'GraphRAG Orchestration API - Hybrid knowledge graph retrieval'
    serviceUrl: backendUrl
    path: 'graphrag'
    protocols: ['https']
    subscriptionRequired: true
    subscriptionKeyParameterNames: {
      header: 'Ocp-Apim-Subscription-Key'
      query: 'subscription-key'
    }
    apiVersion: 'v2'
    apiVersionSetId: apiVersionSet.id
  }
}

// API Version Set for versioning
resource apiVersionSet 'Microsoft.ApiManagement/service/apiVersionSets@2023-05-01-preview' = {
  parent: apim
  name: 'graphrag-version-set'
  properties: {
    displayName: 'GraphRAG API Versions'
    versioningScheme: 'Header'
    versionHeaderName: 'X-API-Version'
  }
}

// Chat endpoint
resource chatOperation 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'chat'
  properties: {
    displayName: 'Chat'
    method: 'POST'
    urlTemplate: '/chat'
    description: 'Send a chat message and get a response from GraphRAG'
    request: {
      description: 'Chat request with messages'
      representations: [
        {
          contentType: 'application/json'
          examples: {
            default: {
              value: {
                messages: [
                  {
                    role: 'user'
                    content: 'What are the key findings?'
                  }
                ]
              }
            }
          }
        }
      ]
    }
    responses: [
      {
        statusCode: 200
        description: 'Chat response'
      }
    ]
  }
}

// Chat stream endpoint
resource chatStreamOperation 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'chat-stream'
  properties: {
    displayName: 'Chat Stream'
    method: 'POST'
    urlTemplate: '/chat/stream'
    description: 'Send a chat message and get a streaming response'
  }
}

// Health endpoint (no auth required)
resource healthOperation 'Microsoft.ApiManagement/service/apis/operations@2023-05-01-preview' = {
  parent: api
  name: 'health'
  properties: {
    displayName: 'Health Check'
    method: 'GET'
    urlTemplate: '/health'
    description: 'Check API health status'
  }
}

// Inbound policy for all operations
resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: api
  name: 'policy'
  properties: {
    value: '''
<policies>
    <inbound>
        <base />
        <!-- Rate limiting: 100 requests per minute per subscription -->
        <rate-limit-by-key 
            calls="100" 
            renewal-period="60" 
            counter-key="@(context.Subscription?.Key ?? context.Request.IpAddress)" 
            increment-condition="@(context.Response.StatusCode >= 200 && context.Response.StatusCode < 400)" />
        
        <!-- Quota: 10,000 requests per day per subscription -->
        <quota-by-key 
            calls="10000" 
            renewal-period="86400" 
            counter-key="@(context.Subscription?.Key ?? "anonymous")" />
        
        <!-- Add correlation ID for tracing -->
        <set-header name="X-Correlation-ID" exists-action="skip">
            <value>@(context.RequestId.ToString())</value>
        </set-header>
        
        <!-- Forward to backend -->
        <set-backend-service backend-id="graphrag-backend" />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
        <!-- Add response headers -->
        <set-header name="X-Request-Id" exists-action="override">
            <value>@(context.RequestId.ToString())</value>
        </set-header>
    </outbound>
    <on-error>
        <base />
        <!-- Custom error response -->
        <return-response>
            <set-status code="500" reason="Internal Server Error" />
            <set-header name="Content-Type" exists-action="override">
                <value>application/json</value>
            </set-header>
            <set-body>@{
                return new JObject(
                    new JProperty("error", new JObject(
                        new JProperty("code", context.Response.StatusCode),
                        new JProperty("message", context.LastError?.Message ?? "An error occurred"),
                        new JProperty("requestId", context.RequestId.ToString())
                    ))
                ).ToString();
            }</set-body>
        </return-response>
    </on-error>
</policies>
'''
    format: 'xml'
  }
}

// Health endpoint policy (no subscription required)
resource healthPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2023-05-01-preview' = {
  parent: healthOperation
  name: 'policy'
  properties: {
    value: '''
<policies>
    <inbound>
        <base />
        <!-- Allow anonymous access for health checks -->
        <set-backend-service backend-id="graphrag-backend" />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
    </outbound>
</policies>
'''
    format: 'xml'
  }
}

// Product for external developers
resource product 'Microsoft.ApiManagement/service/products@2023-05-01-preview' = {
  parent: apim
  name: 'graphrag-standard'
  properties: {
    displayName: 'GraphRAG Standard'
    description: 'Standard access to GraphRAG API with rate limiting'
    subscriptionRequired: true
    approvalRequired: false
    subscriptionsLimit: 10
    state: 'published'
    terms: 'Usage subject to GraphRAG terms of service'
  }
}

// Link API to product
resource productApi 'Microsoft.ApiManagement/service/products/apis@2023-05-01-preview' = {
  parent: product
  name: api.name
}

// Named value for backend URL (can be updated without redeployment)
resource backendUrlNamedValue 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'backend-url'
  properties: {
    displayName: 'Backend URL'
    value: backendUrl
    secret: false
  }
}

// Outputs
output apimName string = apim.name
output apimGatewayUrl string = apim.properties.gatewayUrl
output apimDeveloperPortalUrl string = enableDevPortal ? '${apim.properties.developerPortalUrl}' : ''
output apiId string = api.id
output productId string = product.id
