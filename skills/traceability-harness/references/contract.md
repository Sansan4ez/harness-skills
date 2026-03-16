Repo Harness Kit Contract (v1)
==============================

Purpose
-------

This contract defines the stable, manifest-driven interface that an agent can rely on when applying the Repo Harness Kit to a target repository.

This contract is intentionally small. Anything not listed here is allowed to vary between repos.

Naming
------

- System name: "Repo Harness Kit" (short: "harness")
- Modules (agent skills): `docs-harness`, `traceability-harness`, `observability-harness`
- Target repo config root: `harness/`

Stable On-Disk Paths (Target Repos)
-----------------------------------

These paths are treated as stable in v1.x:

- Project config: `harness/manifest.yaml`
- Module configs:
  - `harness/docs.yaml`
  - `harness/env-vars.yaml` (docs-harness env var catalog)
  - `harness/traceability.yaml`
  - `harness/surface-registry.yaml` (traceability-harness contract sync registry)
  - `harness/observability/baseline.yaml`
  - `harness/observability/signals.yaml`
- Ownership overrides: `harness/ownership.yaml`
- Kit lock file: `harness/kit-lock.yaml`
- Kit-managed CI workflows: `.github/workflows/harness-*.yml`
- Generated docs: `docs/generated/**`
- Per-service OpenAPI (recommended convention): `specs/<service>/openapi.yaml`

Schema Locations
----------------

Schemas and enforcement code live in the harness skill repository, not in the target repo.

Manifest Rules
--------------

`harness/manifest.yaml` is the source of truth for the list of code services in the repo.

Minimum required service fields:

- `id` (stable identifier)
- `kind` (starts with: `fastapi`, `worker`, `service`; unknown kinds are allowed)
- `path` (service root directory)
- `compose_service` (Docker Compose service name)

Optional service fields:

- `openapi` (path to service contract; recommended for `kind: fastapi`)
- `otel_service_name` (defaults to `id` when omitted)
- `health_url` (used by smoke orchestration; optional for non-HTTP services)

Built-in profile semantics:

- `fastapi`: docs + OpenAPI/traceability + HTTP smoke are enabled by default
- `worker`: docs + optional observability; HTTP/OpenAPI checks stay opt-in
- `service`: generic docs baseline only; protocol-specific checks are opt-in
- `typescript`, `javascript`, `go`, `rust`: docs-only baseline in v1; stronger checks stay opt-in until adapters exist
- unknown kinds fall back to the generic `service` profile with an explicit warning

Service-to-service relations
----------------------------

In v1, the manifest does not model edges/relations. C4 edges are documented directly in the C4 diagrams.

Ownership and Updates
---------------------

Default ownership model:

- Kit-managed (safe to overwrite on update): `.github/workflows/harness-*.yml`, `victoriametrics/**`, `docs/generated/**`, `harness/required-checks.yaml`, `harness/kit-lock.yaml`
- Project-owned (never overwritten by default): `docs/**` (except `docs/generated/**`), `specs/**`, `services/**`, app code, Compose files, env files

If a repo needs different ownership boundaries, overrides live in `harness/ownership.yaml`.

Kit-managed file marker convention:

- For text files that support comments, the kit may include a first-line marker:
  - `# repo-harness-kit:managed` (YAML, Python, shell)
  - `<!-- repo-harness-kit:managed -->` (Markdown)
- For all file types, the primary update safety mechanism is the lock file (`harness/kit-lock.yaml`) which may record file digests.

Update conflict policy:

- If a kit-managed file differs from what the lock file expects (digest mismatch), `update` must fail by default and report the conflicts.
- Applying kit updates over local edits requires an explicit override flag (agent-controlled).
- `install` and `update` only write kit-managed files; project-owned files remain outside the automatic overwrite path.

Required Checks (GitHub Actions Contract)
-----------------------------------------

Required check names and gating rules are defined in `harness/required-checks.yaml`.
Validation must work in both contexts:

- in the kit repo against `harness/templates/.github/workflows/**`
- in installed target repos against `.github/workflows/**`

Branch protection should require at least:

- `Harness Docs / docs`
- `Harness Traceability / traceability`

Observability smoke is label-gated in PRs and required only on release/tag pipelines:

- `Harness Observability Smoke / smoke`

Index Reachability (Docs Discipline)
------------------------------------

- Everything under `docs/` and `specs/` must be reachable from an index.
- The docs module enforces this mechanically (a repo must provide a deterministic reachability checker).

Agent Skill CLI Contract
------------------------

All module entrypoints must support:

- `--repo-root <path>`
- `--mode install|update|check`
- `--module docs|traceability|observability`
- `--service <id>|all` (optional; defaults to `all`)
- `--dry-run` (optional)
- `--strict` (optional)

Bootstrap flow:

- New repos may be scaffolded with the `bootstrap.py` entrypoint shipped inside the installed skill repository
- Bootstrap must stay additive-only for project-owned files unless an explicit override mode is introduced in a future major version

Service filter semantics:

- When `--service <id>` is provided, checks that are service-scoped must only validate that service (for example: OpenAPI presence, health URL expectations, per-service inventories).

Exit codes:

- `0` success
- `2` validation failure / check failure

Machine-readable summary (stdout):

- JSON or YAML object with:
  - `ok` (bool)
  - `mode`, `module`
  - `files_checked` (list)
  - `services_checked` (list)
  - `warnings` (list of strings)
  - `errors` (list of strings)

Optional additive fields used by agent automation:

- `copied_files`, `skipped_files`, `conflicts`
- `profile_decisions` keyed by service id

Deprecation Policy
------------------

- Patch releases: bugfixes only, no interface changes.
- Minor releases: additive changes only (new optional keys, new templates, new checks behind flags).
- Major releases: may change file paths, required keys, or check naming contracts. Must include explicit migration notes.

Release Support Files
---------------------

- Versioning policy: `harness/VERSIONING.md`
- Language support policy: `harness/LANGUAGE-SUPPORT.md`
- Release notes: `harness/releases/<version>.md`
