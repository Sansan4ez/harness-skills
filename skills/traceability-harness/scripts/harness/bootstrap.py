#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harness import _kit_version_from_source


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
DEFAULT_MODULES = ("docs", "traceability", "observability")
DEFAULT_OBSERVABILITY_VARS = (
    ("GRAFANA_PORT", "3000", "observability smoke grafana endpoint", False),
    ("OTEL_COLLECTOR_HEALTH_PORT", "13133", "observability smoke collector health endpoint", False),
    ("VICTORIAMETRICS_PORT", "8428", "observability smoke metrics backend endpoint", False),
    ("VICTORIALOGS_PORT", "9428", "observability smoke logs backend endpoint", False),
    ("VICTORIATRACES_PORT", "10428", "observability smoke traces backend endpoint", False),
    ("OBSERVABILITY_PROJECT_NAME", "repo-harness-observability", "observability compose project name", False),
    ("OTEL_COLLECTOR_PORT_GRPC", "4317", "observability collector OTLP gRPC port", False),
    ("OTEL_COLLECTOR_PORT_HTTP", "4318", "observability collector OTLP HTTP port", False),
    ("ALERTMANAGER_PORT", "9093", "observability alertmanager endpoint", False),
    ("SMOKE_REPORT_FILE", "", "observability smoke artifact override", False),
    ("SMOKE_HEALTH_TIMEOUT_SECONDS", "60", "observability smoke wait budget", False),
    ("SMOKE_METRIC_SIGNAL", "http_server_duration_milliseconds", "observability smoke metric probe", False),
    ("SMOKE_LOG_SIGNAL", "HTTP request completed", "observability smoke log probe", False),
    ("SMOKE_TRACE_SIGNAL", "request", "observability smoke trace probe", False),
)


@dataclass(frozen=True)
class BootstrapService:
    service_id: str
    kind: str
    path: str
    compose_service: str
    health_url: str | None = None

    @property
    def openapi_path(self) -> str | None:
        if self.kind == "fastapi":
            return f"specs/{self.service_id}/openapi.yaml"
        return None

    @property
    def emitter_relpath(self) -> str:
        suffix_by_kind = {
            "fastapi": "app.py",
            "worker": "worker.py",
            "service": "service.py",
            "typescript": "index.ts",
            "javascript": "index.js",
            "go": "main.go",
            "rust": "main.rs",
        }
        suffix = suffix_by_kind.get(self.kind, "README.md")
        return f"{self.path.rstrip('/')}/{suffix}"


def _parse_service(spec: str) -> BootstrapService:
    parts = spec.split(":")
    if len(parts) < 4:
        raise argparse.ArgumentTypeError(
            "--service must use 'id:kind:path:compose_service[:health_url]'"
        )
    service_id, kind, path, compose_service = parts[:4]
    rest = parts[4:]
    if not all(item.strip() for item in (service_id, kind, path, compose_service)):
        raise argparse.ArgumentTypeError("service spec fields must be non-empty")
    health_url = ":".join(rest).strip() if rest else None
    if health_url == "":
        health_url = None
    if kind.strip() == "fastapi" and not health_url:
        health_url = "http://localhost:8080/healthz"
    return BootstrapService(
        service_id=service_id.strip(),
        kind=kind.strip(),
        path=path.strip(),
        compose_service=compose_service.strip(),
        health_url=health_url,
    )


def _write_text_if_missing(
    repo_root: Path,
    rel_path: str,
    content: str,
    *,
    created: list[str],
    skipped: list[str],
) -> None:
    path = repo_root / rel_path
    if path.exists():
        skipped.append(rel_path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    created.append(rel_path)


def _write_yaml_if_missing(
    repo_root: Path,
    rel_path: str,
    payload: dict[str, Any],
    *,
    created: list[str],
    skipped: list[str],
) -> None:
    content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    _write_text_if_missing(repo_root, rel_path, content, created=created, skipped=skipped)


def _copy_template_if_missing(
    repo_root: Path,
    template_rel: str,
    target_rel: str,
    *,
    replacements: dict[str, str] | None,
    created: list[str],
    skipped: list[str],
) -> None:
    template_path = ROOT / template_rel
    content = template_path.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        content = content.replace(key, value)
    _write_text_if_missing(repo_root, target_rel, content, created=created, skipped=skipped)


def _docs_index(services: list[BootstrapService]) -> str:
    service_lines = "\n".join(
        f"- Service hub ({svc.service_id}) -> `docs/services/{svc.service_id}/index.md`"
        for svc in services
    )
    return f"""Repository Knowledge Base
=========================

Purpose
-------

This is the single knowledge entrypoint for the repository.

Indexes
-------

- Architecture -> `docs/architecture/index.md`
- Operations -> `docs/operations/index.md`
- Requirements -> `docs/requirements/index.md`
- Plans -> `docs/plans/index.md`
- Generated -> `docs/generated/index.md`
- Specs -> `specs/index.md`

Service Hubs
------------

{service_lines}
"""


def _c4_index(services: list[BootstrapService]) -> str:
    service_lines = "\n".join(
        f"- L3 components ({svc.service_id}) -> `docs/architecture/c4/services/{svc.service_id}/l3-components.md`"
        for svc in services
    )
    return f"""C4 Architecture Spine
====================

Artifacts
---------

- L1 system context -> `docs/architecture/c4/l1-system-context.md`
- L2 containers -> `docs/architecture/c4/l2-containers.md`
{service_lines}
"""


def _architecture_index(services: list[BootstrapService]) -> str:
    service_lines = "\n".join(
        f"- Service components ({svc.service_id}) -> `docs/services/{svc.service_id}/index.md`"
        for svc in services
    )
    return f"""Architecture Docs
=================

Purpose
-------

Use this index when changing service boundaries, inter-service contracts, or accepted technical decisions.

Read by Intent
--------------

- Repository architecture overview -> `ARCHITECTURE.md`
- C4 diagrams -> `docs/architecture/c4/index.md`
{service_lines}
"""


def _l2_containers(services: list[BootstrapService]) -> str:
    nodes = "\n".join(
        f"    {svc.service_id.replace('-', '_')}[{svc.service_id} ({svc.kind})]"
        for svc in services
    )
    return f"""C4 L2 - Containers (Services)
=============================

Purpose
-------

This document describes the repository's containers/services. The list must match `harness/manifest.yaml`.

Diagram
-------

```mermaid
flowchart LR
  subgraph repo[Repository]
{nodes}
  end
```
"""


def _service_hub(service: BootstrapService) -> str:
    lines = [
        f"Service: {service.service_id}",
        "=" * (9 + len(service.service_id)),
        "",
        "Purpose",
        "-------",
        "",
        f"This is the documentation hub for the `{service.service_id}` service.",
        "",
        "Artifacts",
        "---------",
        "",
        f"- C4 L3 components -> `docs/architecture/c4/services/{service.service_id}/l3-components.md`",
        "- Requirements coverage -> `docs/requirements/traceability.md`",
        "- Operations notes -> `docs/operations/index.md`",
    ]
    if service.openapi_path:
        lines.insert(
            11,
            f"- OpenAPI contract -> `{service.openapi_path}`",
        )
    return "\n".join(lines)


def _requirements_index(fastapi_services: list[BootstrapService]) -> str:
    service_lines = "\n".join(
        f"- OpenAPI ({svc.service_id}) -> `{svc.openapi_path}`"
        for svc in fastapi_services
        if svc.openapi_path
    )
    extra = f"\n{service_lines}\n" if service_lines else "\n"
    return f"""Requirements Index
==================

Artifacts
---------

- Functional -> `docs/requirements/functional/fr.yaml`
- Non-functional -> `docs/requirements/non-functional/nfr.yaml`
- Traceability -> `docs/requirements/traceability.md`{extra}"""


def _traceability_doc(fastapi_services: list[BootstrapService]) -> str:
    rows = []
    for index, svc in enumerate(fastapi_services, start=1):
        req_id = f"FR-{index:03d}"
        rows.append(
            f"| `{req_id}` | `{svc.openapi_path}` | `tests/test_traceability_markers.py` |"
        )
    table = "\n".join(rows) or "| — | — | — |"
    return f"""Traceability
============

This matrix links requirement ids to service contracts and tests.

| Requirement | Contract | Evidence |
| --- | --- | --- |
{table}
"""


def _specs_index(fastapi_services: list[BootstrapService]) -> str:
    if not fastapi_services:
        artifacts = "- No HTTP contracts yet. Add `specs/<service>/openapi.yaml` when a service exposes HTTP."
    else:
        artifacts = "\n".join(
            f"- OpenAPI ({svc.service_id}) -> `{svc.openapi_path}`"
            for svc in fastapi_services
            if svc.openapi_path
        )
    return f"""Runtime Contract Index
======================

Purpose
-------

Use this index when changing HTTP behavior, payloads, or requirement traceability for a service runtime.

Artifacts
---------

{artifacts}
"""


def _functional_requirements(fastapi_services: list[BootstrapService]) -> dict[str, Any]:
    items = []
    for index, svc in enumerate(fastapi_services, start=1):
        items.append(
            {
                "id": f"FR-{index:03d}",
                "title": f"{svc.service_id} public contract",
                "owners": ["repo-harness-kit"],
                "notes": f"Bootstrap contract requirement for {svc.service_id}.",
            }
        )
    if not items:
        items.append(
            {
                "id": "FR-001",
                "title": "Repository docs baseline",
                "owners": ["repo-harness-kit"],
                "notes": "Bootstrap placeholder requirement when no HTTP service is present.",
            }
        )
    return {"functional_requirements": items}


def _non_functional_requirements() -> dict[str, Any]:
    return {
        "non_functional_requirements": [
            {
                "id": "NFR-OBS-001",
                "title": "Observability baseline is installed",
                "owners": ["repo-harness-kit"],
                "notes": "Bootstrap placeholder NFR for Victoria-based observability.",
            }
        ]
    }


def _openapi_stub(service: BootstrapService, requirement_id: str) -> str:
    return f"""openapi: 3.0.3
info:
  title: {service.service_id} API
  version: 1.0.0
paths:
  /healthz:
    get:
      operationId: get{service.service_id.title().replace("-", "")}Healthz
      summary: Health check
      x-requirements: ["{requirement_id}"]
      responses:
        "200":
          description: OK
"""


def _python_service_stub(service: BootstrapService) -> str:
    trace_signal = f"{service.service_id}.request"
    return f"""def bootstrap_entrypoint() -> dict[str, str]:
    metrics = ["http_server_duration_milliseconds"]
    logs = ["HTTP request completed"]
    traces = ["{trace_signal}"]
    return {{
        "service": "{service.service_id}",
        "metrics": ",".join(metrics),
        "logs": ",".join(logs),
        "traces": ",".join(traces),
    }}
"""


def _text_service_stub(service: BootstrapService) -> str:
    return f"Bootstrap placeholder for {service.service_id} ({service.kind}).\n"


def _test_markers(fastapi_services: list[BootstrapService]) -> str:
    lines = ["import pytest", ""]
    for index, svc in enumerate(fastapi_services, start=1):
        req_id = f"FR-{index:03d}"
        test_name = svc.service_id.replace("-", "_")
        lines.extend(
            [
                f'@pytest.mark.req("{req_id}")',
                f"def test_requirement_marker_{test_name}() -> None:",
                "    assert True",
                "",
            ]
        )
    if not fastapi_services:
        lines.extend(
            [
                '@pytest.mark.req("FR-001")',
                "def test_requirement_marker_docs_baseline() -> None:",
                "    assert True",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _env_example(fastapi_services: list[BootstrapService]) -> str:
    service_name = fastapi_services[0].service_id if fastapi_services else "service"
    health_url = (
        fastapi_services[0].health_url
        if fastapi_services and fastapi_services[0].health_url
        else "http://localhost:8080/healthz"
    )
    return f"""API_PORT=8080
LOG_LEVEL=INFO
APP_HEALTH_URL={health_url}
SERVICE_NAME={service_name}
VMALERT_PORT=8880
"""


def _env_vars(fastapi_services: list[BootstrapService]) -> dict[str, Any]:
    service_name = fastapi_services[0].service_id if fastapi_services else "service"
    health_url = (
        fastapi_services[0].health_url
        if fastapi_services and fastapi_services[0].health_url
        else "http://localhost:8080/healthz"
    )
    vars_payload = [
        {"name": "API_PORT", "default": "8080", "relevance": "bootstrap compose port"},
        {"name": "LOG_LEVEL", "default": "INFO", "relevance": "bootstrap runtime logging"},
        {
            "name": "APP_HEALTH_URL",
            "default": health_url,
            "relevance": "observability smoke target",
        },
        {
            "name": "SERVICE_NAME",
            "default": service_name,
            "relevance": "observability smoke service.name probe",
        },
        {"name": "VMALERT_PORT", "default": "8880", "relevance": "observability smoke vmalert endpoint"},
    ]
    for name, default, relevance, in_env_example in DEFAULT_OBSERVABILITY_VARS:
        item: dict[str, Any] = {"name": name, "default": default, "relevance": relevance}
        if not in_env_example:
            item["in_env_example"] = False
        vars_payload.append(item)
    return {
        "version": 1,
        "env_example": ".env.example",
        "vars": vars_payload,
        "ignored": [],
    }


def _surface_registry(services: list[BootstrapService], fastapi_services: list[BootstrapService]) -> dict[str, Any]:
    first_impl = fastapi_services[0].path if fastapi_services else services[0].path
    payload: dict[str, Any] = {
        "version": 1,
        "surfaces": {
            "compose_topology": {
                "owner": "repo-harness-kit",
                "summary": "Compose topology changes.",
                "implementation_patterns": ["docker-compose*.yml", "docker-compose*.yaml"],
                "required_alignment_patterns": [
                    "harness/manifest.yaml",
                    "docs/architecture/c4/l2-containers.md",
                ],
            },
            "env_vars_catalog": {
                "owner": "repo-harness-kit",
                "summary": "Supported env vars and defaults used by the repo.",
                "implementation_patterns": [".env.example", "harness/env-vars.yaml"],
                "required_alignment_patterns": ["docs/generated/env-matrix.md"],
            },
            "telemetry_signals_catalog": {
                "owner": "repo-harness-kit",
                "summary": "Telemetry signal catalog changes.",
                "implementation_patterns": ["harness/observability/signals.yaml"],
                "required_alignment_patterns": [
                    "docs/operations/observability-baseline.md",
                    "docs/operations/observability-policy.md",
                    "docs/operations/observability-runbook.md",
                ],
            },
        },
    }
    if fastapi_services:
        payload["surfaces"]["api_http"] = {
            "owner": "repo-harness-kit",
            "summary": "HTTP runtime contract surface.",
            "implementation_patterns": [f"{svc.path}/**" for svc in fastapi_services],
            "required_alignment_patterns": [
                svc.openapi_path for svc in fastapi_services if svc.openapi_path
            ]
            + ["docs/requirements/traceability.md", "tests/**"],
        }
    else:
        payload["surfaces"]["service_code"] = {
            "owner": "repo-harness-kit",
            "summary": "Generic service implementation surface.",
            "implementation_patterns": [f"{first_impl}/**"],
            "required_alignment_patterns": ["docs/services/"],
        }
    return payload


def _signals_config(fastapi_services: list[BootstrapService]) -> dict[str, Any]:
    catalog: list[dict[str, Any]] = []
    for svc in fastapi_services:
        trace_signal = f"{svc.service_id}.request"
        catalog.extend(
            [
                {
                    "name": "http_server_duration_milliseconds",
                    "kind": "metric",
                    "service": svc.service_id,
                    "emitter": {
                        "path": svc.emitter_relpath,
                        "description": f"Request metrics exported by the {svc.service_id} service.",
                    },
                    "consumers": [
                        {"kind": "dashboard", "ref": "HTTP Throughput"},
                        {"kind": "dashboard", "ref": "HTTP 5xx Ratio"},
                        {"kind": "alert", "ref": "OBS-ALERT-001"},
                        {"kind": "smoke", "ref": "victoriametrics/smoke_test.sh"},
                    ],
                    "coverage_paths": [
                        svc.emitter_relpath,
                        "victoriametrics/alerts/minimum-alerts.yaml",
                        "victoriametrics/alerts/vmalert-rules.yaml",
                        {
                            "path": "victoriametrics/grafana/provisioning/dashboards/files/harness-service-overview.json",
                            "contains": ["HTTP Throughput", "HTTP 5xx Ratio"],
                        },
                        "victoriametrics/smoke_test.sh",
                    ],
                },
                {
                    "name": "HTTP request completed",
                    "kind": "log",
                    "service": svc.service_id,
                    "emitter": {
                        "path": svc.emitter_relpath,
                        "description": f"Structured completion log for {svc.service_id} requests.",
                    },
                    "consumers": [
                        {"kind": "smoke", "ref": "victoriametrics/smoke_test.sh"},
                        {"kind": "runbook", "ref": "docs/operations/observability-runbook.md"},
                    ],
                    "coverage_paths": [svc.emitter_relpath, "victoriametrics/smoke_test.sh"],
                },
                {
                    "name": trace_signal,
                    "kind": "trace",
                    "service": svc.service_id,
                    "emitter": {
                        "path": svc.emitter_relpath,
                        "description": f"Top-level request trace span for {svc.service_id}.",
                    },
                    "consumers": [
                        {"kind": "runbook", "ref": "docs/operations/observability-runbook.md"},
                        {"kind": "policy", "ref": "docs/operations/observability-policy.md"},
                    ],
                    "coverage_paths": [svc.emitter_relpath],
                },
            ]
        )
    return {
        "version": 1,
        "resource_attributes": {"required": ["service.name"]},
        "signal_kinds": {"required": ["traces", "metrics", "logs"]},
        "correlation": {"required_log_fields": ["trace_id", "span_id", "request_id"]},
        "catalog": catalog,
    }


def _manifest(services: list[BootstrapService]) -> dict[str, Any]:
    items = []
    for svc in services:
        item: dict[str, Any] = {
            "id": svc.service_id,
            "kind": svc.kind,
            "path": svc.path,
            "compose_service": svc.compose_service,
            "otel_service_name": svc.service_id,
        }
        if svc.openapi_path:
            item["openapi"] = svc.openapi_path
        if svc.health_url:
            item["health_url"] = svc.health_url
        items.append(item)
    return {"version": 1, "services": items}


def _docs_config() -> dict[str, Any]:
    return {
        "version": 1,
        "entrypoint": "docs/index.md",
        "domain_indexes": {
            "architecture": "docs/architecture/index.md",
            "operations": "docs/operations/index.md",
            "requirements": "docs/requirements/index.md",
            "plans": "docs/plans/index.md",
            "generated": "docs/generated/index.md",
            "specs": "specs/index.md",
        },
        "generated_dir": "docs/generated",
        "service_hub_dir": "docs/services",
        "c4": {
            "l1": "docs/architecture/c4/l1-system-context.md",
            "l2": "docs/architecture/c4/l2-containers.md",
            "l3_dir": "docs/architecture/c4/services",
        },
        "rules": {"require_reachability": True},
    }


def _traceability_config() -> dict[str, Any]:
    return {
        "version": 1,
        "requirements": {
            "sources": [
                "docs/requirements/functional/*.yaml",
                "docs/requirements/non-functional/*.yaml",
            ],
            "id_pattern": "^(FR|NFR-[A-Z]+)-[0-9]{3}$",
        },
        "openapi": {"requirement_extension": "x-requirements"},
        "tests": {
            "marker": "req",
            "allow_unmarked_tests": True,
            "openapi_requirements_coverage": "error",
        },
    }


def _observability_baseline() -> dict[str, Any]:
    return {
        "version": 1,
        "stack": {
            "victoriametrics_dir": "victoriametrics",
            "compose_file": "victoriametrics/docker-compose.yml",
        },
        "app": {
            "compose_files": [
                "docker-compose.yml",
                "docker-compose.dev.yml",
                "docker-compose.observability.yml",
            ]
        },
        "smoke": {
            "pr_label": "observability-smoke",
            "health_timeout_seconds": 60,
            "artifacts_dir": "victoriametrics/smoke",
            "required_on": ["release"],
        },
    }


def _compose_file(services: list[BootstrapService]) -> str:
    lines = ['services:']
    for svc in services:
        lines.extend(
            [
                f"  {svc.compose_service}:",
                "    image: busybox:1.36",
                '    command: ["sh", "-c", "sleep 3600"]',
            ]
        )
    return "\n".join(lines) + "\n"


def _compose_overlay(title: str, services: list[BootstrapService]) -> str:
    lines = [f"# {title}", "services:"]
    for svc in services:
        lines.extend([f"  {svc.compose_service}:", "    environment:", f'      LOG_LEVEL: "${{LOG_LEVEL:-INFO}}"'])
    return "\n".join(lines) + "\n"


def _readme(repo_name: str) -> str:
    return f"""# {repo_name}

Bootstrap repository for Repo Harness Kit validation.
"""


def _architecture_overview(repo_name: str) -> str:
    return f"""# {repo_name} Architecture

This file anchors the repository-level architecture narrative used by the docs harness.
"""


def _plans_tech_debt() -> str:
    return """Tech Debt
=========

- Capture repo-specific follow-up work here.
"""


def _pyproject_toml() -> str:
    return """[project]
name = "repo-harness-bootstrap"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "jsonschema>=4.25.0",
  "PyYAML>=6.0.2",
]

[dependency-groups]
dev = [
  "pytest>=8.4.0",
]

[tool.pytest.ini_options]
markers = [
  "req(name): requirement traceability marker",
]
"""


def _install_module(repo_root: Path, module: str, kit_version: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/harness/harness.py"),
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
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "errors": [proc.stdout + proc.stderr]}
    payload.setdefault("ok", proc.returncode == 0)
    payload["returncode"] = proc.returncode
    if proc.returncode != 0 and not payload.get("errors"):
        payload["errors"] = [(proc.stdout + proc.stderr).strip() or f"{module} install failed"]
    return payload


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="repo-harness-bootstrap")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--service",
        action="append",
        type=_parse_service,
        dest="services",
        help="Service definition: id:kind:path:compose_service[:health_url]",
    )
    parser.add_argument(
        "--module",
        action="append",
        choices=["docs", "traceability", "observability"],
        dest="modules",
    )
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--kit-version", default=_kit_version_from_source())
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    services = list(args.services or [])
    if not services:
        services = [_parse_service("api:fastapi:services/api:api:http://localhost:8080/healthz")]
    modules = list(dict.fromkeys(args.modules or list(DEFAULT_MODULES)))
    fastapi_services = [svc for svc in services if svc.kind == "fastapi"]

    created_files: list[str] = []
    skipped_files: list[str] = []
    install_results: dict[str, Any] = {}
    errors: list[str] = []

    planned_files = [
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        "ARCHITECTURE.md",
        "harness/manifest.yaml",
        "harness/docs.yaml",
        "harness/env-vars.yaml",
        "harness/traceability.yaml",
        "harness/surface-registry.yaml",
        "harness/ownership.yaml",
        "harness/observability/baseline.yaml",
        "harness/observability/signals.yaml",
        "docs/index.md",
        "docs/architecture/index.md",
        "docs/architecture/c4/index.md",
        "docs/architecture/c4/l1-system-context.md",
        "docs/architecture/c4/l2-containers.md",
        "docs/requirements/index.md",
        "docs/requirements/traceability.md",
        "docs/requirements/functional/fr.yaml",
        "docs/requirements/non-functional/nfr.yaml",
        "docs/operations/index.md",
        "docs/operations/observability-baseline.md",
        "docs/operations/observability-policy.md",
        "docs/operations/observability-runbook.md",
        "docs/plans/index.md",
        "docs/plans/tech-debt.md",
        "docs/generated/index.md",
        "specs/index.md",
        ".env.example",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "docker-compose.observability.yml",
        "tests/test_traceability_markers.py",
    ]
    planned_files.extend(f"docs/services/{svc.service_id}/index.md" for svc in services)
    planned_files.extend(
        f"docs/architecture/c4/services/{svc.service_id}/l3-components.md" for svc in services
    )
    planned_files.extend(svc.emitter_relpath for svc in services)
    planned_files.extend(svc.openapi_path for svc in fastapi_services if svc.openapi_path)

    if args.dry_run:
        payload = {
            "ok": True,
            "repo_root": str(repo_root),
            "modules": modules,
            "services": [svc.__dict__ for svc in services],
            "created_files": [],
            "skipped_files": sorted(set(planned_files)),
            "install_results": {},
            "errors": [],
        }
        rendered = json.dumps(payload, indent=2) if args.output_format == "json" else yaml.safe_dump(payload, sort_keys=False)
        print(rendered)
        return 0

    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "docs/plans/active").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs/plans/completed").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs/architecture/adr").mkdir(parents=True, exist_ok=True)

    _copy_template_if_missing(
        repo_root,
        "harness/templates/AGENTS.md",
        "AGENTS.md",
        replacements=None,
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(repo_root, "README.md", _readme(repo_root.name), created=created_files, skipped=skipped_files)
    _write_text_if_missing(
        repo_root,
        "pyproject.toml",
        _pyproject_toml(),
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(
        repo_root,
        "ARCHITECTURE.md",
        _architecture_overview(repo_root.name),
        created=created_files,
        skipped=skipped_files,
    )

    _write_yaml_if_missing(repo_root, "harness/manifest.yaml", _manifest(services), created=created_files, skipped=skipped_files)
    _write_yaml_if_missing(repo_root, "harness/docs.yaml", _docs_config(), created=created_files, skipped=skipped_files)
    _write_yaml_if_missing(repo_root, "harness/env-vars.yaml", _env_vars(fastapi_services), created=created_files, skipped=skipped_files)
    _write_yaml_if_missing(
        repo_root,
        "harness/traceability.yaml",
        _traceability_config(),
        created=created_files,
        skipped=skipped_files,
    )
    _write_yaml_if_missing(
        repo_root,
        "harness/surface-registry.yaml",
        _surface_registry(services, fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )
    _copy_template_if_missing(
        repo_root,
        "harness/ownership.yaml",
        "harness/ownership.yaml",
        replacements=None,
        created=created_files,
        skipped=skipped_files,
    )
    _write_yaml_if_missing(
        repo_root,
        "harness/observability/baseline.yaml",
        _observability_baseline(),
        created=created_files,
        skipped=skipped_files,
    )
    _write_yaml_if_missing(
        repo_root,
        "harness/observability/signals.yaml",
        _signals_config(fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )

    _write_text_if_missing(repo_root, "docs/index.md", _docs_index(services), created=created_files, skipped=skipped_files)
    _write_text_if_missing(
        repo_root,
        "docs/architecture/index.md",
        _architecture_index(services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(repo_root, "docs/architecture/c4/index.md", _c4_index(services), created=created_files, skipped=skipped_files)
    _copy_template_if_missing(
        repo_root,
        "harness/templates/docs/architecture/c4/l1-system-context.md",
        "docs/architecture/c4/l1-system-context.md",
        replacements={"{{system_name}}": repo_root.name},
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(repo_root, "docs/architecture/c4/l2-containers.md", _l2_containers(services), created=created_files, skipped=skipped_files)
    for svc in services:
        _write_text_if_missing(
            repo_root,
            f"docs/services/{svc.service_id}/index.md",
            _service_hub(svc),
            created=created_files,
            skipped=skipped_files,
        )
        _copy_template_if_missing(
            repo_root,
            "harness/templates/docs/architecture/c4/services/__service__/l3-components.md",
            f"docs/architecture/c4/services/{svc.service_id}/l3-components.md",
            replacements={"{{service_id}}": svc.service_id},
            created=created_files,
            skipped=skipped_files,
        )

    _write_text_if_missing(repo_root, "docs/requirements/index.md", _requirements_index(fastapi_services), created=created_files, skipped=skipped_files)
    _write_text_if_missing(
        repo_root,
        "docs/requirements/traceability.md",
        _traceability_doc(fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_yaml_if_missing(
        repo_root,
        "docs/requirements/functional/fr.yaml",
        _functional_requirements(fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_yaml_if_missing(
        repo_root,
        "docs/requirements/non-functional/nfr.yaml",
        _non_functional_requirements(),
        created=created_files,
        skipped=skipped_files,
    )

    _copy_template_if_missing(
        repo_root,
        "harness/templates/docs/operations/index.md",
        "docs/operations/index.md",
        replacements=None,
        created=created_files,
        skipped=skipped_files,
    )
    for template_rel, target_rel in (
        ("harness/templates/docs/operations/observability-baseline.md", "docs/operations/observability-baseline.md"),
        ("harness/templates/docs/operations/observability-policy.md", "docs/operations/observability-policy.md"),
        ("harness/templates/docs/operations/observability-runbook.md", "docs/operations/observability-runbook.md"),
        ("harness/templates/docs/plans/index.md", "docs/plans/index.md"),
        ("harness/templates/docs/generated/index.md", "docs/generated/index.md"),
    ):
        _copy_template_if_missing(
            repo_root,
            template_rel,
            target_rel,
            replacements=None,
            created=created_files,
            skipped=skipped_files,
        )
    _write_text_if_missing(
        repo_root,
        "specs/index.md",
        _specs_index(fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(repo_root, "docs/plans/tech-debt.md", _plans_tech_debt(), created=created_files, skipped=skipped_files)

    _write_text_if_missing(repo_root, ".env.example", _env_example(fastapi_services), created=created_files, skipped=skipped_files)
    _write_text_if_missing(repo_root, "docker-compose.yml", _compose_file(services), created=created_files, skipped=skipped_files)
    _write_text_if_missing(
        repo_root,
        "docker-compose.dev.yml",
        _compose_overlay("Bootstrap dev overlay", services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(
        repo_root,
        "docker-compose.observability.yml",
        _compose_overlay("Bootstrap observability overlay", services),
        created=created_files,
        skipped=skipped_files,
    )
    _write_text_if_missing(
        repo_root,
        "tests/test_traceability_markers.py",
        _test_markers(fastapi_services),
        created=created_files,
        skipped=skipped_files,
    )

    for index, svc in enumerate(fastapi_services, start=1):
        _write_text_if_missing(
            repo_root,
            svc.openapi_path or f"specs/{svc.service_id}/openapi.yaml",
            _openapi_stub(svc, f"FR-{index:03d}"),
            created=created_files,
            skipped=skipped_files,
        )

    for svc in services:
        if svc.kind in {"fastapi", "worker", "service"}:
            content = _python_service_stub(svc)
        else:
            content = _text_service_stub(svc)
        _write_text_if_missing(repo_root, svc.emitter_relpath, content, created=created_files, skipped=skipped_files)

    if not args.skip_install:
        for module in modules:
            result = _install_module(repo_root, module, str(args.kit_version))
            install_results[module] = result
            if not result.get("ok"):
                errors.extend(str(item) for item in result.get("errors") or [f"{module} install failed"])

    payload = {
        "ok": not errors,
        "repo_root": str(repo_root),
        "modules": modules,
        "services": [svc.__dict__ for svc in services],
        "created_files": sorted(created_files),
        "skipped_files": sorted(skipped_files),
        "install_results": install_results,
        "errors": errors,
    }
    rendered = json.dumps(payload, indent=2) if args.output_format == "json" else yaml.safe_dump(payload, sort_keys=False)
    print(rendered)
    return 0 if not errors else 2


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
