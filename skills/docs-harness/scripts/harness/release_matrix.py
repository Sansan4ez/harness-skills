#!/usr/bin/env python3

from __future__ import annotations

import argparse
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = ROOT / "tests/harness/fixtures"
DEFAULT_FIXTURES = ("monorepo", "compose-polyglot")
MODULES = ("docs", "traceability", "observability")
VERIFY_BY_MODULE = {
    "docs": "scripts/harness/docs/verify.py",
    "traceability": "scripts/harness/traceability/verify.py",
    "observability": "scripts/harness/observability/verify.py",
}
GENERATE_BY_MODULE = {
    "docs": "scripts/harness/docs/generate_all.py",
    "traceability": "scripts/harness/traceability/generate_all.py",
    "observability": "scripts/harness/observability/generate_all.py",
}


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _remove_managed_paths(repo_root: Path) -> None:
    for rel_path in (".github", "victoriametrics"):
        target = repo_root / rel_path
        if target.exists():
            shutil.rmtree(target)
    for rel_path in ("harness/kit-lock.yaml", "harness/required-checks.yaml"):
        target = repo_root / rel_path
        if target.exists():
            target.unlink()


def _clone_fixture(fixture_name: str) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix=f"repo-harness-{fixture_name}-"))
    source = FIXTURES_ROOT / fixture_name
    target = temp_root / fixture_name
    shutil.copytree(source, target)
    _remove_managed_paths(target)
    return target


def _module_combinations() -> list[tuple[str, ...]]:
    combos: list[tuple[str, ...]] = []
    for size in range(1, len(MODULES) + 1):
        combos.extend(itertools.combinations(MODULES, size))
    return combos


def _run_install(repo_root: Path, module: str, kit_version: str) -> tuple[bool, str]:
    proc = _run(
        "scripts/harness/harness.py",
        "--repo-root",
        str(repo_root),
        "--mode",
        "install",
        "--module",
        module,
        "--kit-version",
        kit_version,
        "--output-format",
        "json",
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _run_verify(repo_root: Path, module: str) -> tuple[bool, str]:
    verify_proc = _run(VERIFY_BY_MODULE[module], "--repo-root", str(repo_root))
    if verify_proc.returncode != 0:
        return False, (verify_proc.stdout + verify_proc.stderr).strip()
    check_proc = _run(GENERATE_BY_MODULE[module], "--repo-root", str(repo_root), "--check")
    return check_proc.returncode == 0, (check_proc.stdout + check_proc.stderr).strip()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="repo-harness-release-matrix")
    parser.add_argument("--fixture", action="append", dest="fixtures")
    parser.add_argument("--kit-version", default="1.0.0")
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    args = parser.parse_args(argv)

    fixtures = list(dict.fromkeys(args.fixtures or list(DEFAULT_FIXTURES)))
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for fixture in fixtures:
        for combo in _module_combinations():
            repo_root = _clone_fixture(fixture)
            combo_name = "+".join(combo)
            install_logs: dict[str, str] = {}
            verify_logs: dict[str, str] = {}
            ok = True
            try:
                for module in combo:
                    install_ok, install_log = _run_install(repo_root, module, str(args.kit_version))
                    install_logs[module] = install_log
                    if not install_ok:
                        ok = False
                        errors.append(f"{fixture}:{combo_name}: install failed for {module}")
                        break
                if ok:
                    for module in combo:
                        verify_ok, verify_log = _run_verify(repo_root, module)
                        verify_logs[module] = verify_log
                        if not verify_ok:
                            ok = False
                            errors.append(f"{fixture}:{combo_name}: verify/check failed for {module}")
                            break
                rows.append(
                    {
                        "fixture": fixture,
                        "modules": list(combo),
                        "ok": ok,
                        "install_logs": install_logs,
                        "verify_logs": verify_logs,
                    }
                )
            finally:
                shutil.rmtree(repo_root.parent, ignore_errors=True)

    payload = {
        "ok": not errors,
        "fixtures": fixtures,
        "combinations": rows,
        "errors": errors,
    }
    if args.output_format == "json":
        print(json.dumps(payload, indent=2))
    else:
        import yaml

        print(yaml.safe_dump(payload, sort_keys=False))
    return 0 if not errors else 2


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
