import json
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
