param location string = resourceGroup().location

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'conformance-plan'
  location: location
  sku: {
    name: 'B1'
  }
}
