# AGENTS.md

Repository Map for Agents
=========================

Primary Entry
-------------

- Start with `docs/index.md`.

Intent Map
----------

- Runtime/API changes -> `specs/index.md`
- Architecture changes -> `docs/architecture/index.md`
- Operations/observability changes -> `docs/operations/index.md`
- Requirements/acceptance rules -> `docs/requirements/index.md`
- Delivery status and plans -> `docs/plans/index.md`
- Generated inventories -> `docs/generated/index.md`
- Local bootstrap and dev commands -> `README.md`

Source of Truth
---------------

- Service inventory (services + hubs + contracts) -> `docs/generated/service-inventory.md`
- Runtime contracts (HTTP) -> `specs/<service>/openapi.yaml`
- Architecture spine (C4 L1/L2/L3) -> `docs/architecture/c4/`
- Requirements -> `docs/requirements/`
- Operations runbooks/checklists -> `docs/operations/`
- Generated inventories -> `docs/generated/`

Validation
----------

- Run the installed `docs-harness` skill in `check` mode against the repo root.
- Use the `docs-harness` verify command when docs indexes or generated inventories change.
