# Harness Skills

Reusable Agent Skills for repository documentation, traceability, and observability.

## Included skills

- `docs-harness`
- `traceability-harness`
- `observability-harness`

## Install with skills.sh

```bash
npx skills add <owner>/harness-skills --list
npx skills add <owner>/harness-skills --skill docs-harness --skill traceability-harness --skill observability-harness -g -a codex -y
```

Project-local install is also supported:

```bash
npx skills add <owner>/harness-skills --skill '*' -a codex -y
```

That installs the skills into the agent-specific project directory, for example `.agents/skills/`.

## Repository layout

```text
harness-skills/
├── README.md
├── pyproject.toml
├── .github/workflows/validate.yml
├── skills/
│   ├── docs-harness/
│   ├── traceability-harness/
│   └── observability-harness/
└── tests/
    ├── fixtures/
    └── test_export_repo.py
```

## Verification

```bash
uv sync
cd skills/docs-harness && uv sync && cd ../..
cd skills/traceability-harness && uv sync && cd ../..
cd skills/observability-harness && uv sync && cd ../..
uv run pytest tests -q
```
