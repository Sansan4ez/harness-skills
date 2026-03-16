Repo Harness Kit Versioning
===========================

Scope
-----

This document defines the release contract for the kit itself.

SemVer Rules
------------

- Patch releases may fix bugs in scripts, templates, and tests, but must not change stable target-repo paths, required schema keys, workflow names, or CLI flags.
- Minor releases may add optional config keys, new templates, new service kinds, and new checks behind additive defaults.
- Major releases may change stable paths, schemas, ownership rules, workflow/check naming, or CLI contracts. Major releases require explicit migration notes.

Compatibility Surface
---------------------

v1.x compatibility covers:

- `harness/**` config paths
- `.github/workflows/harness-*.yml` workflow names and required-check ids
- `docs/generated/**` inventory locations
- `specs/<service>/openapi.yaml` as the default HTTP contract path
- skill-local entrypoints under `skills/<skill>/scripts/**`

Release Inputs
--------------

Every release must include:

1. Upgrade notes under `harness/releases/<version>.md`
2. A passing release matrix:

```bash
uv run python scripts/harness/release_matrix.py --kit-version <version>
```

3. A passing harness suite:

```bash
uv run pytest tests/harness -q
```

4. Confirmation that the three module skills still bundle the current script-first runtime and metadata.

Upgrade Notes Minimum Content
-----------------------------

Each release note must state:

- target version
- compatibility impact (`patch`, `minor`, `major`)
- target-repo action required (`none`, `update`, or `manual migration`)
- changed module areas
- any new service kinds, templates, or checks
