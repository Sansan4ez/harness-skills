C4 L2 - Containers (Services)
=============================

Purpose
-------

This document describes the repository's containers/services. The list of services must match `harness/manifest.yaml`.

Diagram
-------

```mermaid
flowchart LR
  subgraph repo[Repository]
    svc1[service: {{service_a}}]
    svc2[service: {{service_b}}]
  end
```

Notes
-----

- Keep service ids aligned with `harness/manifest.yaml`.
- Annotate edges with protocols and data ownership when it adds clarity.
