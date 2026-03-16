Repository Knowledge Base
=========================

Purpose
-------

This is the single knowledge entrypoint for the repository. Start here, choose the intent that matches the change, and only then open deeper documents.

If you need to change X, read Y
-------------------------------

- Run or configure services locally -> `README.md`
- Change runtime endpoints, payloads, or API requirements -> `specs/index.md`
- Change architecture boundaries or C4 diagrams -> `docs/architecture/index.md`
- Change telemetry, smoke, dashboards, alerts, or Docker operations -> `docs/operations/index.md`
- Change requirement IDs or traceability rules -> `docs/requirements/index.md`
- Track delivery status or phased plans -> `docs/plans/index.md`
- Review generated inventories -> `docs/generated/index.md`

Domain Indexes
--------------

- Architecture -> `docs/architecture/index.md`
- Operations -> `docs/operations/index.md`
- Requirements -> `docs/requirements/index.md`
- Plans -> `docs/plans/index.md`
- Generated -> `docs/generated/index.md`
- Runtime specs -> `specs/index.md`

Normative Sources
-----------------

- C4 architecture spine (L1/L2/L3) -> `docs/architecture/c4/index.md`
- Per-service docs hubs -> `docs/services/<service>/index.md`
- Per-service OpenAPI contracts -> `specs/<service>/openapi.yaml`

Maintenance Rules
-----------------

- Every Markdown file under `docs/` and every spec under `specs/` must be reachable from an index document.
- Generated inventories under `docs/generated/` must be kept in sync with env/spec/telemetry sources.
