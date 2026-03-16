C4 L3 - Components (Service: {{service_id}})
============================================

Purpose
-------

This document describes the internal component view of the `{{service_id}}` service.

Diagram
-------

```mermaid
flowchart TB
  subgraph svc[service: {{service_id}}]
    api[entrypoint] --> core[business logic]
    core --> deps[(external deps)]
  end
```

Notes
-----

- Keep names stable and implementation-neutral.
- Use this view to document boundaries, not every file.

