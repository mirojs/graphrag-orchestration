@description('Redis cache name')
param cacheName string

@description('Location for the Redis cache')
param location string = resourceGroup().location

@description('Tags to apply to all resources')
param tags object = {}

@description('Redis SKU (Basic, Standard, Premium)')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param sku string = 'Basic'

@description('Redis capacity (0-6 for Basic/Standard, 1-5 for Premium)')
@minValue(0)
@maxValue(6)
param capacity int = 0

// Create Redis Cache
resource redisCache 'Microsoft.Cache/redis@2024-03-01' = {
  name: cacheName
  location: location
  tags: tags
  properties: {
    sku: {
      name: sku
      family: sku == 'Premium' ? 'P' : 'C'
      capacity: capacity
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

// Outputs
output redisCacheName string = redisCache.name
output redisHostName string = redisCache.properties.hostName
output redisSslPort int = redisCache.properties.sslPort
output redisPrimaryKey string = listKeys(redisCache.id, redisCache.apiVersion).primaryKey
