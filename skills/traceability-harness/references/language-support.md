Repo Harness Kit Language Support
=================================

v1 Support
----------

- `fastapi`: docs, OpenAPI/traceability, and HTTP smoke enabled by default
- `worker`: docs by default; HTTP/OpenAPI checks stay opt-in
- `service`: generic docs baseline only
- `typescript`: docs-only baseline in v1
- `javascript`: docs-only baseline in v1
- `go`: docs-only baseline in v1
- `rust`: docs-only baseline in v1

Expansion Rule
--------------

New languages start as docs-first adapters:

1. Add a new `kind` to `scripts/harness/service_profiles.py`.
2. Keep OpenAPI, traceability, and smoke disabled until a concrete adapter exists.
3. Extend bootstrap scaffolding for the new language's placeholder source file.
4. Re-bundle the affected skills and add or update a fixture plus release-matrix coverage before enabling stronger checks.
