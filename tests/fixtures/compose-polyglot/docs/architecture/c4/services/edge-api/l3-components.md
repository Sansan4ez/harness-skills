C4 L3 - Components (Service: edge-api) (Fixture)
===============================================

- OpenAPI contract -> `specs/edge-api/openapi.yaml`

```mermaid
flowchart TB
  subgraph edge_api[service: edge-api]
    entry[entrypoint] --> core[business logic]
  end
```
