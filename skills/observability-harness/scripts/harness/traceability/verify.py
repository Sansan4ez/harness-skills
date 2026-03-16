from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import yaml

PARENT_DIR = Path(__file__).resolve().parents[1]
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from service_profiles import profile_for_service, should_validate_openapi

from common import GenerationError, load_yaml, parse_verify_args
from generate_all import generate_documents


HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head")

IGNORE_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}


@dataclass(frozen=True)
class RequirementCatalog:
    ids: set[str]
    sources_by_id: dict[str, set[str]]


@dataclass(frozen=True)
class TestMarkerScan:
    references: dict[str, set[str]]
    files_with_tests: set[str]
    files_with_markers: set[str]


def _repo_relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _load_trace_cfg(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/traceability.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/traceability.yaml must be a YAML object")
    return cfg


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/manifest.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/manifest.yaml must be a YAML object")
    return cfg


def _iter_requirement_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items: list[dict[str, Any]] = []
    for key, value in payload.items():
        if not str(key).endswith("_requirements"):
            continue
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                items.append(item)
    return items


def _load_requirement_catalog(*, repo_root: Path, trace_cfg: dict[str, Any]) -> RequirementCatalog:
    req = trace_cfg.get("requirements") or {}
    sources = req.get("sources") if isinstance(req, dict) else None
    if not isinstance(sources, list) or not sources:
        raise GenerationError("traceability.requirements.sources must be a non-empty list")

    id_pattern = req.get("id_pattern") if isinstance(req, dict) else None
    if not isinstance(id_pattern, str) or not id_pattern.strip():
        raise GenerationError("traceability.requirements.id_pattern must be a non-empty regex string")

    try:
        id_re = re.compile(id_pattern)
    except re.error as e:
        raise GenerationError(f"traceability.requirements.id_pattern is not a valid regex: {e}") from e

    sources_by_id: dict[str, set[str]] = {}
    matched_files = 0
    for glob_expr in sources:
        if not isinstance(glob_expr, str) or not glob_expr.strip():
            continue
        for path in sorted(repo_root.glob(glob_expr)):
            if not path.is_file():
                continue
            matched_files += 1
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            rel = _repo_relative(repo_root, path)
            for item in _iter_requirement_items(payload):
                rid = str(item.get("id", "")).strip()
                if not rid:
                    raise GenerationError(f"{rel}: requirement item is missing id")
                if not id_re.match(rid):
                    raise GenerationError(f"{rel}: requirement id does not match id_pattern: {rid}")
                sources_by_id.setdefault(rid, set()).add(rel)

    if matched_files == 0:
        raise GenerationError("traceability.requirements.sources did not match any files")

    duplicates = sorted(rid for rid, srcs in sources_by_id.items() if len(srcs) > 1)
    if duplicates:
        rendered = ", ".join(f"{rid} ({', '.join(sorted(sources_by_id[rid]))})" for rid in duplicates)
        raise GenerationError(f"duplicate requirement ids across sources: {rendered}")

    return RequirementCatalog(ids=set(sources_by_id.keys()), sources_by_id=sources_by_id)


def _validate_openapi_requirements(
    *,
    repo_root: Path,
    trace_cfg: dict[str, Any],
    manifest: dict[str, Any],
    catalog: RequirementCatalog,
    errors: list[str],
) -> dict[str, set[str]]:
    openapi_cfg = trace_cfg.get("openapi") or {}
    requirement_extension = (
        str(openapi_cfg.get("requirement_extension", "x-requirements")).strip()
        if isinstance(openapi_cfg, dict)
        else "x-requirements"
    )
    if not requirement_extension:
        errors.append("traceability.openapi.requirement_extension must be a non-empty string")
        requirement_extension = "x-requirements"

    services = manifest.get("services") or []
    if not isinstance(services, list):
        errors.append("harness/manifest.yaml: services must be a list")
        return {}

    referenced_by_service: dict[str, set[str]] = {}

    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = str(svc.get("id", "")).strip()
        openapi_rel = str(svc.get("openapi", "")).strip()
        if not sid:
            continue
        profile, _ = profile_for_service(svc)
        if not openapi_rel:
            if profile.requires_openapi:
                errors.append(f"{sid}: {profile.name} service is missing openapi")
            continue
        if not should_validate_openapi(svc):
            continue

        path = repo_root / openapi_rel
        if not path.exists():
            errors.append(f"{sid}: openapi file not found: {openapi_rel}")
            continue

        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}: openapi YAML parse failed: {openapi_rel}: {e}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{sid}: openapi must be a YAML object: {openapi_rel}")
            continue

        paths = payload.get("paths") or {}
        if not isinstance(paths, dict):
            errors.append(f"{sid}: openapi.paths must be a map: {openapi_rel}")
            continue

        for p, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                method_l = str(method).lower()
                if method_l not in HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    continue
                method_u = method_l.upper()

                operation_id = str(operation.get("operationId", "")).strip()
                if not operation_id:
                    errors.append(f"{sid}: missing operationId for {method_u} {p} ({openapi_rel})")

                requirements_raw = operation.get(requirement_extension, [])
                if not isinstance(requirements_raw, list) or not requirements_raw:
                    errors.append(
                        f"{sid}: missing {requirement_extension} for {method_u} {p} ({openapi_rel})"
                    )
                    continue

                req_ids = {str(x).strip() for x in requirements_raw if str(x).strip()}
                if not req_ids:
                    errors.append(
                        f"{sid}: {requirement_extension} must include at least one id for {method_u} {p} ({openapi_rel})"
                    )
                    continue

                missing = sorted(rid for rid in req_ids if rid not in catalog.ids)
                if missing:
                    errors.append(
                        f"{sid}: dangling requirement ids in {openapi_rel} for {method_u} {p}: "
                        + ", ".join(missing)
                    )
                    continue

                referenced_by_service.setdefault(sid, set()).update(req_ids)

    return referenced_by_service


TEST_MARK_RE_TEMPLATE = r"pytest\.mark\.{marker}\((?P<args>.*?)\)"
STRING_LITERAL_RE = re.compile(r"['\"](?P<value>[^'\"]+)['\"]")
TEST_DEF_RE = re.compile("^\\s*def\\s+test_[A-Za-z0-9_]+\\s*\\(", re.MULTILINE)


def _iter_test_roots(repo_root: Path, manifest: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    if (repo_root / "tests").exists():
        roots.append(repo_root / "tests")

    services = manifest.get("services") or []
    if isinstance(services, list):
        for svc in services:
            if not isinstance(svc, dict):
                continue
            path_rel = str(svc.get("path", "")).strip()
            if not path_rel:
                continue
            svc_tests = repo_root / path_rel / "tests"
            if svc_tests.exists():
                roots.append(svc_tests)
    # Keep deterministic order.
    return sorted({p.resolve() for p in roots})


def _collect_test_marker_references(
    *,
    repo_root: Path,
    marker: str,
    id_re: re.Pattern[str],
    manifest: dict[str, Any],
) -> TestMarkerScan:
    references: dict[str, set[str]] = {}
    files_with_tests: set[str] = set()
    files_with_markers: set[str] = set()
    mark_re = re.compile(TEST_MARK_RE_TEMPLATE.format(marker=re.escape(marker)), re.DOTALL)

    for root in _iter_test_roots(repo_root, manifest):
        for path in root.rglob("*.py"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(repo_root).parts
            if any(part in IGNORE_DIR_NAMES for part in rel_parts):
                continue

            rel = _repo_relative(repo_root, path)
            content = path.read_text(encoding="utf-8", errors="ignore")
            if TEST_DEF_RE.search(content):
                files_with_tests.add(rel)

            found_marker = False
            for match in mark_re.finditer(content):
                found_marker = True
                args = match.group("args") or ""
                for m in STRING_LITERAL_RE.finditer(args):
                    value = str(m.group("value")).strip()
                    if not value or not id_re.match(value):
                        continue
                    references.setdefault(value, set()).add(rel)

            if found_marker:
                files_with_markers.add(rel)

    return TestMarkerScan(
        references=references,
        files_with_tests=files_with_tests,
        files_with_markers=files_with_markers,
    )


def _validate_test_traceability(
    *,
    repo_root: Path,
    trace_cfg: dict[str, Any],
    manifest: dict[str, Any],
    catalog: RequirementCatalog,
    referenced_by_service: dict[str, set[str]],
    warnings: list[str],
    errors: list[str],
) -> None:
    tests_cfg = trace_cfg.get("tests") or {}
    if not isinstance(tests_cfg, dict):
        return

    coverage = str(tests_cfg.get("openapi_requirements_coverage", "error")).strip().lower()
    if coverage not in {"off", "warn", "error"}:
        errors.append("traceability.tests.openapi_requirements_coverage must be one of: off|warn|error")
        coverage = "error"
    allow_unmarked_tests = bool(tests_cfg.get("allow_unmarked_tests", True))
    if coverage == "off" and allow_unmarked_tests:
        return

    marker = str(tests_cfg.get("marker", "")).strip()
    if not marker:
        errors.append(
            "traceability.tests.marker is required when openapi_requirements_coverage is enabled "
            "or allow_unmarked_tests is false"
        )
        return

    req = trace_cfg.get("requirements") or {}
    id_pattern = req.get("id_pattern") if isinstance(req, dict) else None
    try:
        id_re = re.compile(str(id_pattern))
    except re.error:
        # This is validated earlier; keep behavior safe.
        id_re = re.compile(r"^$")

    scan = _collect_test_marker_references(
        repo_root=repo_root, marker=marker, id_re=id_re, manifest=manifest
    )
    marker_refs = scan.references

    # Sanity: tests may reference ids that don't exist.
    unknown_ids = sorted(rid for rid in marker_refs if rid not in catalog.ids)
    if unknown_ids:
        msg = "pytest requirement markers reference unknown requirement ids: " + ", ".join(unknown_ids)
        errors.append(msg)

    if not allow_unmarked_tests:
        unmarked = sorted(scan.files_with_tests - scan.files_with_markers)
        if unmarked:
            rendered = ", ".join(unmarked[:10])
            if len(unmarked) > 10:
                rendered += f", +{len(unmarked) - 10} more"
            errors.append(
                "unmarked test files detected (allow_unmarked_tests=false): " + rendered
            )

    # Coverage: any requirement referenced from OpenAPI must be covered by at least one test marker.
    if coverage == "off":
        return
    required_ids = sorted({rid for ids in referenced_by_service.values() for rid in ids})
    missing_coverage = sorted(rid for rid in required_ids if rid not in marker_refs)
    if not missing_coverage:
        return

    msg = "requirements referenced from OpenAPI lack pytest marker coverage: " + ", ".join(missing_coverage)
    if coverage == "warn":
        warnings.append(msg)
    else:
        errors.append(msg)


def verify(*, repo_root: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    try:
        trace_cfg = _load_trace_cfg(repo_root)
        manifest = _load_manifest(repo_root)
        catalog = _load_requirement_catalog(repo_root=repo_root, trace_cfg=trace_cfg)
    except GenerationError as e:
        return [], [str(e)]

    referenced_by_service = _validate_openapi_requirements(
        repo_root=repo_root,
        trace_cfg=trace_cfg,
        manifest=manifest,
        catalog=catalog,
        errors=errors,
    )

    _validate_test_traceability(
        repo_root=repo_root,
        trace_cfg=trace_cfg,
        manifest=manifest,
        catalog=catalog,
        referenced_by_service=referenced_by_service,
        warnings=warnings,
        errors=errors,
    )

    errors.extend(generate_documents(repo_root=repo_root, check=True))
    return warnings, errors


def main() -> int:
    args = parse_verify_args()
    repo_root = Path(args.repo_root).resolve()

    warnings, errors = verify(repo_root=repo_root)
    if errors:
        print("traceability-harness-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    if warnings:
        print("traceability-harness-check: warnings")
        for warning in warnings:
            print(f"- {warning}")
        return 0
    print("traceability-harness-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
