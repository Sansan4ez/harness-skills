#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from service_profiles import profile_for_service, profile_summary


SCRIPT_DIR = Path(__file__).resolve().parent
KIT_SOURCE_ROOT = SCRIPT_DIR.parents[1]
KIT_NAME = "repo-harness-kit"
IGNORED_MANAGED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
IGNORED_MANAGED_SUFFIXES = {".pyc", ".pyo"}

COMMON_MANAGED_MAPPINGS = (("harness/required-checks.yaml", "harness/required-checks.yaml"),)

MODULE_MANAGED_MAPPINGS = {
    "docs": (
        ("harness/templates/.github/workflows/harness-docs.yml", ".github/workflows/harness-docs.yml"),
    ),
    "traceability": (
        (
            "harness/templates/.github/workflows/harness-traceability.yml",
            ".github/workflows/harness-traceability.yml",
        ),
    ),
    "observability": (
        (
            "harness/templates/.github/workflows/harness-observability-smoke.yml",
            ".github/workflows/harness-observability-smoke.yml",
        ),
        ("harness/templates/victoriametrics", "victoriametrics"),
    ),
}

LOCK_REL_PATH = "harness/kit-lock.yaml"
POST_APPLY_GENERATORS = {
    "docs": ("scripts/harness/docs/generate_all.py",),
    "traceability": (
        "scripts/harness/traceability/generate_all.py",
        "scripts/harness/docs/generate_all.py",
    ),
    "observability": (
        "scripts/harness/observability/generate_all.py",
        "scripts/harness/docs/generate_all.py",
    ),
}
POST_APPLY_STATE_ROOTS = {
    "docs": ("docs/generated",),
    "traceability": ("docs/generated",),
    "observability": ("docs/generated",),
}


@dataclass(frozen=True)
class MappingEntry:
    source_rel: str
    target_rel: str
    source_is_dir: bool


@dataclass(frozen=True)
class StateSnapshot:
    backup_root: Path
    states: dict[str, str]


@dataclass(frozen=True)
class Result:
    ok: bool
    mode: str
    module: str
    files_checked: list[str]
    services_checked: list[str]
    warnings: list[str]
    errors: list[str]
    copied_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    profile_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_path(name: str) -> Path:
    return SCRIPT_DIR / "schemas" / name


def _validate_schema(payload: Any, schema: Any) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for err in sorted(validator.iter_errors(payload), key=str):
        loc = "/".join(str(x) for x in err.absolute_path)
        prefix = f"{loc}: " if loc else ""
        errors.append(f"{prefix}{err.message}")
    return errors


def _ensure_relative(repo_root: Path, rel: str) -> Path:
    path = (repo_root / rel).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as e:
        raise ValueError(f"path escapes repo root: {rel}") from e
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kit_version_from_source() -> str:
    lock_path = KIT_SOURCE_ROOT / LOCK_REL_PATH
    if not lock_path.exists():
        return "0.0.0-dev"
    payload = _load_yaml(lock_path)
    if not isinstance(payload, dict):
        return "0.0.0-dev"
    kit = payload.get("kit") or {}
    if not isinstance(kit, dict):
        return "0.0.0-dev"
    value = str(kit.get("version", "")).strip()
    return value or "0.0.0-dev"


def _load_target_lock(repo_root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = repo_root / LOCK_REL_PATH
    if not path.exists():
        return None, []
    payload = _load_yaml(path)
    schema = _load_json(_schema_path("harness.kit-lock.v1.schema.json"))
    errors = _validate_schema(payload, schema)
    if errors:
        return None, [f"{LOCK_REL_PATH}: {error}" for error in errors]
    if not isinstance(payload, dict):
        return None, [f"{LOCK_REL_PATH}: lock file must be a YAML object"]
    return payload, []


def _selected_services(
    manifest: dict[str, Any],
    *,
    service_filter: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    services = manifest.get("services") or []
    if not isinstance(services, list):
        return [], ["services must be a list"]

    selected = [svc for svc in services if isinstance(svc, dict)]
    if service_filter == "all":
        return selected, errors

    selected = [svc for svc in selected if str(svc.get("id", "")).strip() == service_filter]
    if not selected:
        errors.append(f"service not found: {service_filter}")
    return selected, errors


def _profile_decisions(
    manifest: dict[str, Any],
    *,
    service_filter: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    decisions: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    selected, errors = _selected_services(manifest, service_filter=service_filter)
    if errors:
        return decisions, errors
    for svc in selected:
        sid = str(svc.get("id", "")).strip()
        if not sid:
            continue
        summary = profile_summary(svc)
        decisions[sid] = summary
        warning = summary.get("warning")
        if isinstance(warning, str) and warning:
            warnings.append(f"{sid}: {warning}")
    return decisions, warnings


def _validate_manifest(
    repo_root: Path, manifest: dict[str, Any], service_filter: str, strict: bool
) -> tuple[list[str], list[str], list[str], dict[str, dict[str, Any]]]:
    warnings: list[str] = []
    errors: list[str] = []
    services_checked: list[str] = []
    profile_decisions, profile_warnings = _profile_decisions(
        manifest,
        service_filter=service_filter,
    )
    warnings.extend(profile_warnings)
    if profile_warnings and strict:
        errors.extend(profile_warnings)

    services = manifest.get("services") or []
    if not isinstance(services, list):
        return warnings, ["services must be a list"], services_checked, profile_decisions

    ids: list[str] = []
    for svc in services:
        if isinstance(svc, dict) and "id" in svc:
            ids.append(str(svc["id"]))
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"duplicate service ids: {', '.join(dupes)}")

    selected, selection_errors = _selected_services(manifest, service_filter=service_filter)
    errors.extend(selection_errors)
    if selection_errors:
        return warnings, errors, services_checked, profile_decisions

    for svc in selected:
        sid = str(svc.get("id", "")).strip()
        services_checked.append(sid)

        path_rel = str(svc.get("path", "")).strip()
        if not path_rel:
            errors.append(f"{sid}: missing path")
        else:
            try:
                svc_path = _ensure_relative(repo_root, path_rel)
            except ValueError as e:
                errors.append(f"{sid}: {e}")
            else:
                if not svc_path.exists():
                    errors.append(f"{sid}: path does not exist: {path_rel}")

        profile, _ = profile_for_service(svc)
        openapi_rel = str(svc.get("openapi", "")).strip()
        if openapi_rel:
            try:
                openapi_path = _ensure_relative(repo_root, openapi_rel)
            except ValueError as e:
                errors.append(f"{sid}: {e}")
            else:
                if not openapi_path.exists():
                    errors.append(f"{sid}: openapi file does not exist: {openapi_rel}")
        elif profile.requires_openapi:
            msg = f"{sid}: {profile.name} services should set openapi"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)

        health_url = str(svc.get("health_url", "")).strip()
        if health_url and not (health_url.startswith("http://") or health_url.startswith("https://")):
            warnings.append(f"{sid}: health_url should be http(s): {health_url}")

        if not str(svc.get("otel_service_name", "")).strip():
            warnings.append(f"{sid}: missing otel_service_name (defaults to id)")

    return warnings, errors, services_checked, profile_decisions


def _validate_docs_config(repo_root: Path, docs_cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    entrypoint = str(docs_cfg.get("entrypoint", "")).strip()
    if entrypoint:
        if not _ensure_relative(repo_root, entrypoint).exists():
            errors.append(f"docs entrypoint does not exist: {entrypoint}")

    domain_indexes = docs_cfg.get("domain_indexes") or {}
    if isinstance(domain_indexes, dict):
        for k, v in domain_indexes.items():
            if not isinstance(v, str):
                errors.append(f"domain_indexes.{k} must be a string path")
                continue
            p = v.strip()
            if p and not _ensure_relative(repo_root, p).exists():
                errors.append(f"domain index does not exist: {p}")

    generated_dir = str(docs_cfg.get("generated_dir", "")).strip()
    if generated_dir and not _ensure_relative(repo_root, generated_dir).exists():
        warnings.append(f"generated_dir does not exist yet: {generated_dir}")

    return warnings, errors


def _validate_env_vars_config(
    repo_root: Path, env_cfg: dict[str, Any]
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    env_example = str(env_cfg.get("env_example", "")).strip()
    if env_example and not _ensure_relative(repo_root, env_example).exists():
        errors.append(f"env_example does not exist: {env_example}")

    ignored = env_cfg.get("ignored") or []
    if ignored and not isinstance(ignored, list):
        errors.append("ignored must be a list of strings")

    vars_ = env_cfg.get("vars") or []
    if not isinstance(vars_, list):
        return warnings, ["vars must be a list"]

    names: list[str] = []
    for item in vars_:
        if isinstance(item, dict) and "name" in item:
            names.append(str(item["name"]))
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        errors.append(f"duplicate env var names: {', '.join(dupes)}")

    return warnings, errors


def _validate_traceability_config(
    repo_root: Path, trace_cfg: dict[str, Any]
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    req = trace_cfg.get("requirements") or {}
    sources = req.get("sources") if isinstance(req, dict) else None
    if isinstance(sources, list):
        matched = 0
        for glob_expr in sources:
            if not isinstance(glob_expr, str):
                errors.append("requirements.sources must be a list of strings")
                continue
            matched += len(list(repo_root.glob(glob_expr)))
        if matched == 0:
            errors.append("requirements.sources did not match any files")

    id_pattern = req.get("id_pattern") if isinstance(req, dict) else None
    if isinstance(id_pattern, str):
        import re

        try:
            re.compile(id_pattern)
        except re.error as e:
            errors.append(f"requirements.id_pattern is not a valid regex: {e}")

    return warnings, errors


def _validate_observability_configs(
    repo_root: Path, baseline: dict[str, Any]
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    stack = baseline.get("stack") or {}
    compose_file = stack.get("compose_file") if isinstance(stack, dict) else None
    if isinstance(compose_file, str) and compose_file.strip():
        if not _ensure_relative(repo_root, compose_file.strip()).exists():
            errors.append(f"observability stack compose_file does not exist: {compose_file.strip()}")

    app = baseline.get("app") or {}
    compose_files = app.get("compose_files") if isinstance(app, dict) else None
    if isinstance(compose_files, list):
        for f in compose_files:
            if not isinstance(f, str):
                errors.append("app.compose_files must be a list of strings")
                continue
            p = f.strip()
            if p and not _ensure_relative(repo_root, p).exists():
                errors.append(f"app compose file does not exist: {p}")

    return warnings, errors


def _validate_required_checks(repo_root: Path, required: dict[str, Any]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    checks = required.get("checks") or []
    if not isinstance(checks, list):
        return warnings, ["checks must be a list"]

    ids: list[str] = []
    for chk in checks:
        if isinstance(chk, dict) and "id" in chk:
            ids.append(str(chk["id"]))
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"duplicate check ids: {', '.join(dupes)}")

    for chk in checks:
        if not isinstance(chk, dict):
            continue
        wf_file = str(chk.get("workflow_file", "")).strip()
        wf_name = str(chk.get("workflow_name", "")).strip()
        job = str(chk.get("job", "")).strip()

        if wf_file:
            candidate_paths = [
                _ensure_relative(repo_root, wf_file),
                _ensure_relative(repo_root, f"harness/templates/{wf_file}"),
            ]
            workflow_path = next((path for path in candidate_paths if path.exists()), None)
            if workflow_path is None:
                errors.append(
                    f"workflow file missing: {wf_file} "
                    f"(also checked harness/templates/{wf_file})"
                )
            else:
                try:
                    payload = _load_yaml(workflow_path)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"workflow template is not valid YAML: {wf_file}: {e}")
                else:
                    if wf_name and str(payload.get("name", "")).strip() != wf_name:
                        errors.append(f"workflow_name mismatch for {wf_file}: expected '{wf_name}'")
                    jobs = payload.get("jobs") or {}
                    if job and isinstance(jobs, dict) and job not in jobs:
                        errors.append(f"job '{job}' not found in {wf_file}")

        gating = chk.get("gating") or {}
        if isinstance(gating, dict) and gating.get("on_pull_request") == "label":
            if not str(gating.get("label", "")).strip():
                errors.append(f"{chk.get('id')}: gating.label is required when on_pull_request=label")

    return warnings, errors


def _validate_file(
    *,
    repo_root: Path,
    relpath: str,
    schema_name: str,
    required: bool = True,
) -> tuple[Any | None, list[str]]:
    path = repo_root / relpath
    if not path.exists():
        if required:
            return None, [f"missing required file: {relpath}"]
        return None, []

    payload = _load_yaml(path)
    schema = _load_json(_schema_path(schema_name))
    return payload, _validate_schema(payload, schema)


def _mapping_entries(module: str) -> list[MappingEntry]:
    if module not in MODULE_MANAGED_MAPPINGS:
        raise ValueError(f"unknown module: {module}")

    entries: list[MappingEntry] = []
    seen: set[str] = set()
    for source_rel, target_rel in (*COMMON_MANAGED_MAPPINGS, *MODULE_MANAGED_MAPPINGS[module]):
        key = target_rel.lstrip("/")
        if key in seen:
            continue
        entries.append(
            MappingEntry(
                source_rel=source_rel,
                target_rel=key,
                source_is_dir=(KIT_SOURCE_ROOT / source_rel).is_dir(),
            )
        )
        seen.add(key)
    return entries


def _iter_source_target_files(module: str) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for entry in _mapping_entries(module):
        source_path = KIT_SOURCE_ROOT / entry.source_rel
        if entry.source_is_dir:
            for path in sorted(source_path.rglob("*")):
                if not path.is_file():
                    continue
                if any(part in IGNORED_MANAGED_PARTS for part in path.parts):
                    continue
                if path.suffix in IGNORED_MANAGED_SUFFIXES:
                    continue
                rel_suffix = path.relative_to(source_path).as_posix()
                target_path = f"{entry.target_rel.rstrip('/')}/{rel_suffix}".lstrip("/")
                if target_path in seen:
                    continue
                files.append((path, target_path))
                seen.add(target_path)
            continue
        if entry.target_rel in seen:
            continue
        files.append((source_path, entry.target_rel))
        seen.add(entry.target_rel)
    return files


def _managed_state_roots(module: str) -> list[str]:
    roots = [entry.target_rel for entry in _mapping_entries(module)]
    roots.extend(POST_APPLY_STATE_ROOTS.get(module, ()))
    roots.append(LOCK_REL_PATH)
    return sorted(set(roots))


def _path_in_module_scope(module: str, rel_path: str) -> bool:
    normalized = rel_path.strip().lstrip("/")
    for entry in _mapping_entries(module):
        root = entry.target_rel.rstrip("/")
        if entry.source_is_dir:
            if normalized == root or normalized.startswith(f"{root}/"):
                return True
            continue
        if normalized == root:
            return True
    return False


def _snapshot_state(repo_root: Path, roots: list[str]) -> StateSnapshot:
    backup_root = Path(tempfile.mkdtemp(prefix="repo-harness-snapshot-"))
    states: dict[str, str] = {}
    for rel_root in roots:
        target = repo_root / rel_root
        if target.is_dir():
            shutil.copytree(target, backup_root / rel_root)
            states[rel_root] = "dir"
        elif target.is_file():
            backup_path = backup_root / rel_root
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
            states[rel_root] = "file"
        else:
            states[rel_root] = "absent"
    return StateSnapshot(backup_root=backup_root, states=states)


def _restore_state(repo_root: Path, snapshot: StateSnapshot) -> None:
    for rel_root, kind in snapshot.states.items():
        target = repo_root / rel_root
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

        backup = snapshot.backup_root / rel_root
        if kind == "dir":
            shutil.copytree(backup, target)
        elif kind == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
    for rel_root, kind in sorted(
        snapshot.states.items(),
        key=lambda item: len(Path(item[0]).parts),
        reverse=True,
    ):
        if kind != "absent":
            continue
        target = repo_root / rel_root
        cursor = target if target.is_dir() else target.parent
        while cursor != repo_root and cursor.exists():
            try:
                cursor.rmdir()
            except OSError:
                break
            cursor = cursor.parent
    shutil.rmtree(snapshot.backup_root, ignore_errors=True)


def _cleanup_snapshot(snapshot: StateSnapshot | None) -> None:
    if snapshot is None:
        return
    shutil.rmtree(snapshot.backup_root, ignore_errors=True)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_lock_payload(
    *,
    previous: dict[str, Any] | None,
    module: str,
    kit_version: str,
    managed_digests: dict[str, str],
) -> dict[str, Any]:
    previous_modules = []
    if isinstance(previous, dict):
        previous_modules = [str(item) for item in previous.get("modules") or [] if str(item)]
    modules = sorted(set(previous_modules) | {module})
    return {
        "version": 1,
        "kit": {
            "name": KIT_NAME,
            "version": kit_version,
        },
        "modules": modules,
        "applied_at": _now_utc(),
        "managed_files": dict(sorted(managed_digests.items())),
    }


def _write_lock(
    *,
    repo_root: Path,
    previous_lock: dict[str, Any] | None,
    module: str,
    kit_version: str,
    managed_digests: dict[str, str],
) -> None:
    lock_payload = _build_lock_payload(
        previous=previous_lock,
        module=module,
        kit_version=kit_version,
        managed_digests=managed_digests,
    )
    lock_path = repo_root / LOCK_REL_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(yaml.safe_dump(lock_payload, sort_keys=False), encoding="utf-8")


def _apply_managed_files(
    *,
    repo_root: Path,
    module: str,
    mode: str,
    force_managed_conflicts: bool,
    kit_version: str,
) -> tuple[list[str], list[str], list[str], list[str], dict[str, str], dict[str, Any] | None]:
    warnings: list[str] = []
    copied_files: list[str] = []
    skipped_files: list[str] = []
    conflicts: list[str] = []

    source_target_files = _iter_source_target_files(module)
    previous_lock, lock_errors = _load_target_lock(repo_root)
    if lock_errors:
        conflicts.extend(lock_errors)
        return warnings, copied_files, skipped_files, conflicts
    if mode == "update" and previous_lock is None:
        conflicts.append(f"{LOCK_REL_PATH} is required for update mode")
        return warnings, copied_files, skipped_files, conflicts

    previous_digests = {}
    if isinstance(previous_lock, dict):
        previous_digests = {
            str(path): str(digest)
            for path, digest in (previous_lock.get("managed_files") or {}).items()
            if str(path) and str(digest)
        }
    desired_targets = {target_rel for _, target_rel in source_target_files}
    stale_targets = sorted(
        rel_path
        for rel_path in previous_digests
        if _path_in_module_scope(module, rel_path) and rel_path not in desired_targets
    )

    for source_path, target_rel in source_target_files:
        target_path = repo_root / target_rel
        source_digest = _sha256(source_path)
        if target_path.exists():
            current_digest = _sha256(target_path)
            expected_digest = previous_digests.get(target_rel)
            if expected_digest:
                if current_digest != expected_digest and current_digest != source_digest:
                    conflicts.append(
                        f"kit-managed file changed locally: {target_rel} "
                        f"(lock digest {expected_digest[:12]}, current {current_digest[:12]})"
                    )
            elif current_digest != source_digest:
                conflicts.append(
                    f"target file exists but is not tracked in {LOCK_REL_PATH}: {target_rel}"
                )
    for target_rel in stale_targets:
        target_path = repo_root / target_rel
        if not target_path.exists():
            continue
        current_digest = _sha256(target_path)
        expected_digest = previous_digests[target_rel]
        if current_digest != expected_digest:
            conflicts.append(
                f"obsolete kit-managed file changed locally: {target_rel} "
                f"(lock digest {expected_digest[:12]}, current {current_digest[:12]})"
            )

    if conflicts and not force_managed_conflicts:
        return warnings, copied_files, skipped_files, conflicts, {}, previous_lock
    if conflicts and force_managed_conflicts:
        warnings.extend(conflicts)
        conflicts = []

    managed_digests = dict(previous_digests)
    for source_path, target_rel in source_target_files:
        target_path = repo_root / target_rel
        source_text = source_path.read_text(encoding="utf-8")
        current_text = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current_text == source_text:
            skipped_files.append(target_rel)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(source_text, encoding="utf-8")
            copied_files.append(target_rel)
        managed_digests[target_rel] = _sha256(target_path)
    for target_rel in stale_targets:
        target_path = repo_root / target_rel
        if target_path.exists():
            target_path.unlink()
            copied_files.append(target_rel)
        managed_digests.pop(target_rel, None)

    return warnings, copied_files, skipped_files, conflicts, managed_digests, previous_lock


def _run_post_apply_generators(*, repo_root: Path, module: str) -> list[str]:
    errors: list[str] = []
    for rel_script in POST_APPLY_GENERATORS.get(module, ()):
        proc = subprocess.run(
            [sys.executable, str(KIT_SOURCE_ROOT / rel_script), "--repo-root", str(repo_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            continue
        output = (proc.stdout + proc.stderr).strip()
        if not output:
            output = "generator exited without output"
        errors.append(f"post-apply generator failed ({rel_script}): {output}")
    return errors


def run(argv: list[str]) -> Result:
    parser = argparse.ArgumentParser(prog="repo-harness-kit")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--mode", required=True, choices=["install", "update", "check"])
    parser.add_argument("--module", required=True, choices=["docs", "traceability", "observability"])
    parser.add_argument("--service", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    parser.add_argument("--force-managed-conflicts", action="store_true")
    parser.add_argument("--kit-version", default=_kit_version_from_source())
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    mode = str(args.mode)
    module = str(args.module)
    strict = bool(args.strict)

    files_checked: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    services_checked: list[str] = []
    copied_files: list[str] = []
    skipped_files: list[str] = []
    conflicts: list[str] = []
    profile_decisions: dict[str, dict[str, Any]] = {}

    if mode in {"install", "update"}:
        manifest, m_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/manifest.yaml",
            schema_name="harness.manifest.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/manifest.yaml")
        errors.extend(m_errors)
        if isinstance(manifest, dict):
            w, e, svc_checked, profile_decisions = _validate_manifest(
                repo_root, manifest, service_filter=str(args.service), strict=False
            )
            warnings.extend(w)
            errors.extend(e)
            services_checked = svc_checked

        if errors:
            return Result(
                ok=False,
                mode=mode,
                module=module,
                files_checked=sorted(set(files_checked)),
                services_checked=services_checked,
                warnings=warnings,
                errors=errors,
                copied_files=copied_files,
                skipped_files=skipped_files,
                conflicts=conflicts,
                profile_decisions=profile_decisions,
            )

        if args.dry_run:
            planned = [target for _, target in _iter_source_target_files(module)]
            return Result(
                ok=True,
                mode=mode,
                module=module,
                files_checked=sorted(set(files_checked + planned)),
                services_checked=services_checked,
                warnings=warnings,
                errors=[],
                copied_files=[],
                skipped_files=planned,
                conflicts=[],
                profile_decisions=profile_decisions,
            )

        snapshot = _snapshot_state(repo_root, _managed_state_roots(module))
        try:
            (
                w,
                copied_files,
                skipped_files,
                conflicts,
                managed_digests,
                previous_lock,
            ) = _apply_managed_files(
                repo_root=repo_root,
                module=module,
                mode=mode,
                force_managed_conflicts=bool(args.force_managed_conflicts),
                kit_version=str(args.kit_version),
            )
            warnings.extend(w)
            errors.extend(conflicts)
            if not errors:
                errors.extend(_run_post_apply_generators(repo_root=repo_root, module=module))
            if not errors:
                _write_lock(
                    repo_root=repo_root,
                    previous_lock=previous_lock,
                    module=module,
                    kit_version=str(args.kit_version),
                    managed_digests=managed_digests,
                )
            else:
                _restore_state(repo_root, snapshot)
                snapshot = None
        except Exception as e:  # noqa: BLE001
            _restore_state(repo_root, snapshot)
            snapshot = None
            errors.append(f"{mode} failed before completion: {e}")
        finally:
            _cleanup_snapshot(snapshot)
        files_checked.extend([target for _, target in _iter_source_target_files(module)])
        files_checked.append(LOCK_REL_PATH)
        return Result(
            ok=not errors,
            mode=mode,
            module=module,
            files_checked=sorted(set(files_checked)),
            services_checked=services_checked,
            warnings=warnings,
            errors=errors,
            copied_files=sorted(copied_files),
            skipped_files=sorted(skipped_files),
            conflicts=conflicts,
            profile_decisions=profile_decisions,
        )

    manifest, m_errors = _validate_file(
        repo_root=repo_root,
        relpath="harness/manifest.yaml",
        schema_name="harness.manifest.v1.schema.json",
        required=True,
    )
    files_checked.append("harness/manifest.yaml")
    errors.extend(m_errors)

    if isinstance(manifest, dict):
        w, e, svc_checked, profile_decisions = _validate_manifest(
            repo_root, manifest, service_filter=str(args.service), strict=strict
        )
        warnings.extend(w)
        errors.extend(e)
        services_checked = svc_checked

    if module == "docs":
        docs_cfg, d_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/docs.yaml",
            schema_name="harness.docs.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/docs.yaml")
        errors.extend(d_errors)
        if isinstance(docs_cfg, dict):
            w, e = _validate_docs_config(repo_root, docs_cfg)
            warnings.extend(w)
            errors.extend(e)

        env_cfg, e_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/env-vars.yaml",
            schema_name="harness.env-vars.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/env-vars.yaml")
        errors.extend(e_errors)
        if isinstance(env_cfg, dict):
            w, e = _validate_env_vars_config(repo_root, env_cfg)
            warnings.extend(w)
            errors.extend(e)

    if module == "traceability":
        trace_cfg, t_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/traceability.yaml",
            schema_name="harness.traceability.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/traceability.yaml")
        errors.extend(t_errors)
        if isinstance(trace_cfg, dict):
            w, e = _validate_traceability_config(repo_root, trace_cfg)
            warnings.extend(w)
            errors.extend(e)

        _, sr_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/surface-registry.yaml",
            schema_name="harness.surface-registry.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/surface-registry.yaml")
        errors.extend(sr_errors)

    if module == "observability":
        baseline, b_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/observability/baseline.yaml",
            schema_name="harness.observability.baseline.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/observability/baseline.yaml")
        errors.extend(b_errors)
        if isinstance(baseline, dict):
            w, e = _validate_observability_configs(repo_root, baseline)
            warnings.extend(w)
            errors.extend(e)

        _, s_errors = _validate_file(
            repo_root=repo_root,
            relpath="harness/observability/signals.yaml",
            schema_name="harness.observability.signals.v1.schema.json",
            required=True,
        )
        files_checked.append("harness/observability/signals.yaml")
        errors.extend(s_errors)

    _, o_errors = _validate_file(
        repo_root=repo_root,
        relpath="harness/ownership.yaml",
        schema_name="harness.ownership.v1.schema.json",
        required=False,
    )
    if (repo_root / "harness/ownership.yaml").exists():
        files_checked.append("harness/ownership.yaml")
    errors.extend(o_errors)

    _, k_errors = _validate_file(
        repo_root=repo_root,
        relpath="harness/kit-lock.yaml",
        schema_name="harness.kit-lock.v1.schema.json",
        required=False,
    )
    if (repo_root / "harness/kit-lock.yaml").exists():
        files_checked.append("harness/kit-lock.yaml")
    errors.extend(k_errors)

    required_checks, rc_errors = _validate_file(
        repo_root=repo_root,
        relpath="harness/required-checks.yaml",
        schema_name="harness.required-checks.v1.schema.json",
        required=False,
    )
    if (repo_root / "harness/required-checks.yaml").exists():
        files_checked.append("harness/required-checks.yaml")
    errors.extend(rc_errors)
    if isinstance(required_checks, dict):
        w, e = _validate_required_checks(repo_root, required_checks)
        warnings.extend(w)
        errors.extend(e)

    ok = (not errors) and (not warnings or not strict)
    if warnings and strict:
        errors.append("strict mode: warnings treated as errors")

    return Result(
        ok=ok,
        mode=mode,
        module=module,
        files_checked=sorted(set(files_checked)),
        services_checked=services_checked,
        warnings=warnings,
        errors=errors,
        copied_files=copied_files,
        skipped_files=skipped_files,
        conflicts=conflicts,
        profile_decisions=profile_decisions,
    )


def main() -> None:
    result = run(sys.argv[1:])
    output = {
        "ok": result.ok,
        "mode": result.mode,
        "module": result.module,
        "files_checked": result.files_checked,
        "services_checked": result.services_checked,
        "warnings": result.warnings,
        "errors": result.errors,
        "copied_files": result.copied_files,
        "skipped_files": result.skipped_files,
        "conflicts": result.conflicts,
        "profile_decisions": result.profile_decisions,
    }

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    fmt, _ = parser.parse_known_args(sys.argv[1:])
    if fmt.output_format == "yaml":
        print(yaml.safe_dump(output, sort_keys=True))
    else:
        print(json.dumps(output, indent=2, sort_keys=True))

    raise SystemExit(0 if result.ok else 2)


if __name__ == "__main__":
    main()
