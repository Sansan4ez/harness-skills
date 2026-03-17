#!/usr/bin/env python3

from __future__ import annotations

import shutil
from pathlib import Path

from export_skill_bundles import export as export_skill_bundles


ROOT = Path(__file__).resolve().parents[2]
EXPORT_ROOT = ROOT / "harness-skills"
SOURCE_SKILLS_ROOT = ROOT / "skills"
SOURCE_FIXTURES_ROOT = ROOT / "tests" / "harness" / "fixtures"
SKILLS = ("docs-harness", "traceability-harness", "observability-harness")
IGNORE_NAMES = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

README = """# Harness Skills

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
"""

ROOT_PYPROJECT = """[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "harness-skills-repo"
version = "1.0.0"
description = "Validation environment for the exported harness skill repository"
requires-python = ">=3.10, <3.14"
dependencies = [
    "jsonschema>=4.23.0",
    "pytest>=9.0.0",
    "pytest-asyncio>=1.2.0",
    "pyyaml>=6.0.2",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = [
    "req(requirement_id): requirement traceability marker",
]
"""

ROOT_GITIGNORE = """.venv/
**/.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
"""

VALIDATE_WORKFLOW = """name: Validate Harness Skills

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"
    steps:
      - uses: actions/checkout@v5

      - name: Install uv
        uses: astral-sh/setup-uv@v7

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install repo test runtime
        run: uv sync

      - name: Install standalone skill runtimes
        run: |
          cd skills/docs-harness && uv sync
          cd ../../skills/traceability-harness && uv sync
          cd ../../skills/observability-harness && uv sync

      - name: Run export repo tests
        run: uv run pytest tests -q
"""

EXPORT_TEST = """import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("docs-harness", "traceability-harness", "observability-harness")


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _skill_root(skill_name: str) -> Path:
    return ROOT / "skills" / skill_name


def test_export_layout_exists() -> None:
    assert (ROOT / "README.md").exists()
    for skill_name in SKILLS:
        skill_root = _skill_root(skill_name)
        assert (skill_root / "SKILL.md").exists()
        assert (skill_root / "pyproject.toml").exists()
        assert (skill_root / "uv.lock").exists()
        assert (skill_root / "agents/openai.yaml").exists()
        assert (skill_root / "scripts/harness/harness.py").exists()


def test_skill_entrypoints_help() -> None:
    for skill_name in SKILLS:
        proc = _run("scripts/harness/harness.py", "--help", cwd=_skill_root(skill_name))
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_docs_traceability_observability_checks_pass_on_fixture() -> None:
    fixture_root = ROOT / "tests" / "fixtures" / "monorepo"
    commands = [
        ("docs-harness", "scripts/harness/harness.py", "--repo-root", str(fixture_root), "--mode", "check", "--module", "docs"),
        ("docs-harness", "scripts/harness/docs/verify.py", "--repo-root", str(fixture_root)),
        ("traceability-harness", "scripts/harness/harness.py", "--repo-root", str(fixture_root), "--mode", "check", "--module", "traceability"),
        ("traceability-harness", "scripts/harness/traceability/verify.py", "--repo-root", str(fixture_root)),
        ("observability-harness", "scripts/harness/harness.py", "--repo-root", str(fixture_root), "--mode", "check", "--module", "observability"),
        ("observability-harness", "scripts/harness/observability/verify.py", "--repo-root", str(fixture_root)),
    ]
    for skill_name, *cmd in commands:
        proc = _run(*cmd, cwd=_skill_root(skill_name))
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_install_keeps_target_repo_clean(tmp_path: Path) -> None:
    source = ROOT / "tests" / "fixtures" / "monorepo"
    repo_root = tmp_path / "repo"
    shutil.copytree(source, repo_root)

    for rel_path in (".github", "victoriametrics", "harness/required-checks.yaml", "harness/kit-lock.yaml"):
        target = repo_root / rel_path
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    for skill_name, module in (
        ("docs-harness", "docs"),
        ("traceability-harness", "traceability"),
        ("observability-harness", "observability"),
    ):
        proc = _run(
            "scripts/harness/harness.py",
            "--repo-root",
            str(repo_root),
            "--mode",
            "install",
            "--module",
            module,
            "--kit-version",
            "1.0.0",
            "--output-format",
            "json",
            cwd=_skill_root(skill_name),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    assert not (repo_root / "scripts/harness").exists()


def test_target_repo_workflows_use_external_checkout() -> None:
    docs_workflow = (
        ROOT / "skills" / "docs-harness" / "harness" / "templates" / "workflows" / "harness-docs.yml"
    ).read_text(encoding="utf-8")
    assert "repository: ${{ vars.HARNESS_SKILLS_REPOSITORY }}" in docs_workflow
    assert "working-directory: .skills/harness/skills/docs-harness" in docs_workflow


def test_empty_repo_check_returns_exit_2(tmp_path: Path) -> None:
    repo_root = tmp_path / "empty"
    repo_root.mkdir()
    proc = _run(
        "scripts/harness/harness.py",
        "--repo-root",
        str(repo_root),
        "--mode",
        "check",
        "--module",
        "docs",
        "--output-format",
        "json",
        cwd=_skill_root("docs-harness"),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["errors"]
"""


def _ignore(path: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in IGNORE_NAMES:
            ignored.add(name)
        if name.endswith(".pyc"):
            ignored.add(name)
    return ignored


def _reset_export_root() -> None:
    if EXPORT_ROOT.exists():
        shutil.rmtree(EXPORT_ROOT)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)


def _write(rel_path: str, content: str) -> None:
    target = EXPORT_ROOT / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def build() -> None:
    export_skill_bundles()
    _reset_export_root()

    _write("README.md", README)
    _write(".gitignore", ROOT_GITIGNORE)
    _write("pyproject.toml", ROOT_PYPROJECT)
    _write(".github/workflows/validate.yml", VALIDATE_WORKFLOW)
    _write("tests/test_export_repo.py", EXPORT_TEST)

    shutil.copytree(
        SOURCE_FIXTURES_ROOT,
        EXPORT_ROOT / "tests" / "fixtures",
        ignore=_ignore,
        dirs_exist_ok=True,
    )

    skills_root = EXPORT_ROOT / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for skill_name in SKILLS:
        shutil.copytree(
            SOURCE_SKILLS_ROOT / skill_name,
            skills_root / skill_name,
            ignore=_ignore,
            dirs_exist_ok=True,
        )


if __name__ == "__main__":
    build()
