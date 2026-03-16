from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
import sys
from typing import Any

import yaml

PARENT_DIR = Path(__file__).resolve().parents[1]
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from service_profiles import profile_for_service, should_validate_openapi

from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    GenerationError,
    load_yaml,
    render_markdown_table,
)


HTTP_METHODS = ("get", "put", "post", "delete", "patch", "options", "head")


@dataclass(frozen=True)
class EndpointRow:
    service: str
    method: str
    path: str
    operation_id: str
    requirements: tuple[str, ...]
    summary: str


def _docs_generated_dir(repo_root: Path) -> str:
    docs_cfg = {}
    try:
        raw = load_yaml(repo_root, "harness/docs.yaml")
        docs_cfg = raw if isinstance(raw, dict) else {}
    except GenerationError:
        docs_cfg = {}

    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    payload = load_yaml(repo_root, "harness/manifest.yaml")
    if not isinstance(payload, dict):
        raise GenerationError("harness/manifest.yaml must be a YAML object")
    return payload


def _load_trace_cfg(repo_root: Path) -> dict[str, Any]:
    payload = load_yaml(repo_root, "harness/traceability.yaml")
    if not isinstance(payload, dict):
        raise GenerationError("harness/traceability.yaml must be a YAML object")
    return payload


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


def _load_requirement_catalog(repo_root: Path, trace_cfg: dict[str, Any]) -> set[str]:
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

    ids: dict[str, set[str]] = {}
    matched_files = 0
    for glob_expr in sources:
        if not isinstance(glob_expr, str) or not glob_expr.strip():
            continue
        for path in sorted(repo_root.glob(glob_expr)):
            if not path.is_file():
                continue
            matched_files += 1
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            for item in _iter_requirement_items(payload):
                rid = str(item.get("id", "")).strip()
                if not rid:
                    raise GenerationError(
                        f"{path.relative_to(repo_root).as_posix()}: requirement item is missing id"
                    )
                if not id_re.match(rid):
                    raise GenerationError(
                        f"{path.relative_to(repo_root).as_posix()}: requirement id does not match id_pattern: {rid}"
                    )
                ids.setdefault(rid, set()).add(path.relative_to(repo_root).as_posix())

    if matched_files == 0:
        raise GenerationError("traceability.requirements.sources did not match any files")

    duplicates = sorted(rid for rid, srcs in ids.items() if len(srcs) > 1)
    if duplicates:
        rendered = ", ".join(f"{rid} ({', '.join(sorted(ids[rid]))})" for rid in duplicates)
        raise GenerationError(f"duplicate requirement ids across sources: {rendered}")

    return set(ids.keys())


def _method_sort_key(method: str) -> int:
    order = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    method_u = method.upper()
    return order.index(method_u) if method_u in order else 999


def _load_openapi(*, repo_root: Path, openapi_rel: str) -> dict[str, Any]:
    path = repo_root / openapi_rel
    if not path.exists():
        raise GenerationError(f"openapi file not found: {openapi_rel}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GenerationError(f"openapi must be a YAML object: {openapi_rel}")
    return payload


def _extract_endpoints(
    *,
    repo_root: Path,
    service_id: str,
    openapi_rel: str,
    requirement_extension: str,
    known_requirements: set[str],
) -> list[EndpointRow]:
    payload = _load_openapi(repo_root=repo_root, openapi_rel=openapi_rel)
    paths = payload.get("paths") or {}
    if not isinstance(paths, dict):
        raise GenerationError(f"openapi.paths must be a map: {openapi_rel}")

    rows: list[EndpointRow] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            method_l = str(method).lower()
            if method_l not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            operation_id = str(operation.get("operationId", "")).strip()
            if not operation_id:
                raise GenerationError(
                    f"{service_id}: missing operationId for {method_l.upper()} {path} ({openapi_rel})"
                )

            requirements_raw = operation.get(requirement_extension, [])
            if not isinstance(requirements_raw, list) or not requirements_raw:
                raise GenerationError(
                    f"{service_id}: missing {requirement_extension} for {method_l.upper()} {path} ({openapi_rel})"
                )

            requirements = tuple(str(x).strip() for x in requirements_raw if str(x).strip())
            if not requirements:
                raise GenerationError(
                    f"{service_id}: {requirement_extension} must contain at least one id for {method_l.upper()} {path} ({openapi_rel})"
                )

            missing = sorted(rid for rid in requirements if rid not in known_requirements)
            if missing:
                raise GenerationError(
                    f"{service_id}: dangling requirement ids in {openapi_rel} for {method_l.upper()} {path}: "
                    + ", ".join(missing)
                )

            summary = str(operation.get("summary", "")).strip() or "—"
            rows.append(
                EndpointRow(
                    service=service_id,
                    method=method_l.upper(),
                    path=str(path),
                    operation_id=operation_id,
                    requirements=requirements,
                    summary=summary,
                )
            )

    return rows


def render_http_endpoints_inventory(*, repo_root: Path) -> tuple[str, str]:
    manifest = _load_manifest(repo_root)
    trace_cfg = _load_trace_cfg(repo_root)

    openapi_cfg = trace_cfg.get("openapi") or {}
    requirement_extension = (
        str(openapi_cfg.get("requirement_extension", "x-requirements")).strip()
        if isinstance(openapi_cfg, dict)
        else "x-requirements"
    )
    if not requirement_extension:
        raise GenerationError("traceability.openapi.requirement_extension must be a non-empty string")

    known_requirements = _load_requirement_catalog(repo_root, trace_cfg)

    services = manifest.get("services") or []
    if not isinstance(services, list):
        raise GenerationError("harness/manifest.yaml: services must be a list")

    endpoint_rows: list[EndpointRow] = []
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
                raise GenerationError(f"{sid}: {profile.name} service is missing openapi")
            continue
        if not should_validate_openapi(svc):
            continue
        endpoint_rows.extend(
            _extract_endpoints(
                repo_root=repo_root,
                service_id=sid,
                openapi_rel=openapi_rel,
                requirement_extension=requirement_extension,
                known_requirements=known_requirements,
            )
        )

    endpoint_rows = sorted(
        endpoint_rows,
        key=lambda row: (row.service, row.path, _method_sort_key(row.method), row.operation_id),
    )

    table_rows: list[list[str]] = []
    for row in endpoint_rows:
        table_rows.append(
            [
                f"`{row.service}`",
                row.method,
                row.path,
                f"`{row.operation_id}`",
                ", ".join(f"`{rid}`" for rid in row.requirements),
                row.summary,
            ]
        )

    body = render_markdown_table(
        ["Service", "Method", "Path", "Operation ID", "Requirements", "Summary"],
        table_rows,
    )

    generated_dir = _docs_generated_dir(repo_root)
    rel_path = f"{generated_dir}/http-endpoints.md"
    content = "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated HTTP Endpoints Inventory",
            "==================================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from per-service OpenAPI specs (recommended: `specs/<service>/openapi.yaml`).",
            f"Each operation must declare `{requirement_extension}` pointing at IDs from the requirement catalog sources.",
            "",
            body,
            "",
        ]
    )
    return rel_path, content


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_http_endpoints_inventory(repo_root=repo_root)
    return GeneratedDocument(rel_path, content)
