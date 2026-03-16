from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import GenerationError, load_yaml


REQUIRED_OBSERVABILITY_DOCS = (
    "docs/operations/observability-runbook.md",
    "docs/operations/observability-baseline.md",
    "docs/operations/observability-policy.md",
)

REQUIRED_STACK_FILES = (
    "docker-compose.yml",
    "otel-collector-config.yml",
    "alertmanager.yml",
    "smoke_test.sh",
    "alerts/minimum-alerts.yaml",
    "alerts/vmalert-rules.yaml",
    "grafana/provisioning/datasources/datasources.yaml",
    "grafana/provisioning/dashboards/dashboards.yaml",
)

REQUIRED_ALERT_FIELDS = ("id", "title", "severity", "execution", "summary", "runbook")
CONSUMER_FILE_KINDS = {"smoke", "runbook", "policy", "baseline"}
SMOKE_SIGNAL_KINDS = ("metric", "log", "trace")


def load_manifest(repo_root: Path) -> dict[str, Any]:
    payload = load_yaml(repo_root, "harness/manifest.yaml")
    if not isinstance(payload, dict):
        raise GenerationError("harness/manifest.yaml must be a YAML object")
    return payload


def load_baseline(repo_root: Path) -> dict[str, Any]:
    payload = load_yaml(repo_root, "harness/observability/baseline.yaml")
    if not isinstance(payload, dict):
        raise GenerationError("harness/observability/baseline.yaml must be a YAML object")
    return payload


def load_signals_cfg(repo_root: Path) -> dict[str, Any]:
    payload = load_yaml(repo_root, "harness/observability/signals.yaml")
    if not isinstance(payload, dict):
        raise GenerationError("harness/observability/signals.yaml must be a YAML object")
    return payload


def observability_dir(baseline: dict[str, Any]) -> str:
    stack = baseline.get("stack") or {}
    if not isinstance(stack, dict):
        raise GenerationError("observability baseline stack config must be an object")
    rel = str(stack.get("victoriametrics_dir", "")).strip().rstrip("/")
    if not rel:
        raise GenerationError("observability baseline stack.victoriametrics_dir is required")
    return rel


def expected_stack_paths(baseline: dict[str, Any]) -> list[str]:
    base = observability_dir(baseline)
    return [f"{base}/{suffix}" for suffix in REQUIRED_STACK_FILES]


def iter_selected_services(*, manifest: dict[str, Any], service_filter: str = "all") -> list[dict[str, Any]]:
    services = manifest.get("services") or []
    if not isinstance(services, list):
        raise GenerationError("harness/manifest.yaml: services must be a list")
    selected = [svc for svc in services if isinstance(svc, dict)]
    if service_filter == "all":
        return selected
    matches = [svc for svc in selected if str(svc.get("id", "")).strip() == service_filter]
    if not matches:
        raise GenerationError(f"service not found: {service_filter}")
    return matches


def smoke_artifacts_dir(baseline: dict[str, Any]) -> str:
    smoke = baseline.get("smoke") or {}
    if not isinstance(smoke, dict):
        raise GenerationError("observability baseline smoke config must be an object")
    configured = str(smoke.get("artifacts_dir", "")).strip().rstrip("/")
    if configured:
        return configured
    return f"{observability_dir(baseline)}/smoke"


def health_timeout_seconds(baseline: dict[str, Any]) -> int:
    smoke = baseline.get("smoke") or {}
    if not isinstance(smoke, dict):
        raise GenerationError("observability baseline smoke config must be an object")
    raw = smoke.get("health_timeout_seconds", 60)
    try:
        value = int(raw)
    except (TypeError, ValueError) as e:
        raise GenerationError("observability baseline smoke.health_timeout_seconds must be an integer") from e
    if value < 1:
        raise GenerationError("observability baseline smoke.health_timeout_seconds must be >= 1")
    return value


def pull_request_label(baseline: dict[str, Any]) -> str:
    smoke = baseline.get("smoke") or {}
    if not isinstance(smoke, dict):
        raise GenerationError("observability baseline smoke config must be an object")
    label = str(smoke.get("pr_label", "")).strip()
    if not label:
        raise GenerationError("observability baseline smoke.pr_label is required")
    return label


def stack_compose_file(baseline: dict[str, Any]) -> str:
    stack = baseline.get("stack") or {}
    if not isinstance(stack, dict):
        raise GenerationError("observability baseline stack config must be an object")
    compose_file = str(stack.get("compose_file", "")).strip()
    if not compose_file:
        raise GenerationError("observability baseline stack.compose_file is required")
    return compose_file


def app_compose_files(baseline: dict[str, Any]) -> list[str]:
    app = baseline.get("app") or {}
    if not isinstance(app, dict):
        raise GenerationError("observability baseline app config must be an object")
    compose_files = app.get("compose_files") or []
    if not isinstance(compose_files, list) or not compose_files:
        raise GenerationError("observability baseline app.compose_files must be a non-empty list")
    values = [str(item).strip() for item in compose_files if str(item).strip()]
    if not values:
        raise GenerationError("observability baseline app.compose_files must contain non-empty paths")
    return values


def dashboard_files(*, repo_root: Path, baseline: dict[str, Any]) -> list[Path]:
    base = observability_dir(baseline)
    dashboard_dir = repo_root / base / "grafana/provisioning/dashboards/files"
    files = sorted(dashboard_dir.glob("*.json"))
    if not files:
        raise GenerationError(f"no dashboard JSON files found in {dashboard_dir.relative_to(repo_root)}")
    return files


def dashboard_catalog(*, repo_root: Path, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for path in dashboard_files(repo_root=repo_root, baseline=baseline):
        payload = json.loads(path.read_text(encoding="utf-8"))
        uid = str(payload.get("uid", "")).strip()
        title = str(payload.get("title", "")).strip()
        if not uid or not title:
            raise GenerationError(f"{path.relative_to(repo_root)} is missing uid or title")
        panel_titles = [
            str(panel.get("title", "")).strip()
            for panel in payload.get("panels", [])
            if isinstance(panel, dict) and str(panel.get("title", "")).strip()
        ]
        catalog.append(
            {
                "uid": uid,
                "title": title,
                "panels": panel_titles,
                "path": path.relative_to(repo_root).as_posix(),
            }
        )
    return catalog


def dashboard_titles(*, repo_root: Path, baseline: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for dashboard in dashboard_catalog(repo_root=repo_root, baseline=baseline):
        titles.add(dashboard["title"])
        titles.update(dashboard["panels"])
    return titles


def load_alert_catalog(*, repo_root: Path, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    base = observability_dir(baseline)
    rel_path = f"{base}/alerts/minimum-alerts.yaml"
    payload = load_yaml(repo_root, rel_path)
    if not isinstance(payload, dict):
        raise GenerationError(f"{rel_path} must be a YAML object")
    alerts = payload.get("alerts") or []
    if not isinstance(alerts, list) or not alerts:
        raise GenerationError(f"{rel_path}: alerts must be a non-empty list")

    seen_ids: set[str] = set()
    for alert in alerts:
        if not isinstance(alert, dict):
            raise GenerationError(f"{rel_path}: alerts entries must be objects")
        alert_id = str(alert.get("id", "")).strip()
        if not alert_id:
            raise GenerationError(f"{rel_path}: alert is missing id")
        if alert_id in seen_ids:
            raise GenerationError(f"{rel_path}: duplicate alert id: {alert_id}")
        seen_ids.add(alert_id)
        for field in REQUIRED_ALERT_FIELDS:
            if not str(alert.get(field, "")).strip():
                raise GenerationError(f"{rel_path}: alert {alert_id} missing field: {field}")
    return alerts


def load_vmalert_rules(*, repo_root: Path, baseline: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    base = observability_dir(baseline)
    rel_path = f"{base}/alerts/vmalert-rules.yaml"
    payload = load_yaml(repo_root, rel_path)
    if not isinstance(payload, dict):
        raise GenerationError(f"{rel_path} must be a YAML object")
    groups = payload.get("groups") or []
    if not isinstance(groups, list) or not groups:
        raise GenerationError(f"{rel_path}: groups must be a non-empty list")

    rules: dict[str, tuple[str, dict[str, Any]]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise GenerationError(f"{rel_path}: groups entries must be objects")
        group_name = str(group.get("name", "")).strip() or "default"
        for rule in group.get("rules", []) or []:
            if not isinstance(rule, dict):
                raise GenerationError(f"{rel_path}: rules must be objects")
            labels = rule.get("labels") or {}
            if not isinstance(labels, dict):
                raise GenerationError(f"{rel_path}: rule labels must be an object")
            alert_id = str(labels.get("alert_id", "")).strip()
            if not alert_id:
                raise GenerationError(f"{rel_path}: rule missing labels.alert_id")
            if alert_id in rules:
                raise GenerationError(f"{rel_path}: duplicate rule for alert_id {alert_id}")
            rules[alert_id] = (group_name, rule)
    return rules


def validate_alert_execution(
    *,
    alerts: list[dict[str, Any]],
    vmalert_rules: dict[str, tuple[str, dict[str, Any]]],
) -> list[str]:
    errors: list[str] = []
    catalog_by_id = {str(alert["id"]): alert for alert in alerts}
    expected_vmalert = {
        alert_id
        for alert_id, alert in catalog_by_id.items()
        if str(alert.get("execution", "")).strip() == "vmalert"
    }
    actual_ids = set(vmalert_rules)
    missing = sorted(expected_vmalert - actual_ids)
    unexpected = sorted(actual_ids - expected_vmalert)
    if missing:
        errors.append(
            "catalogued vmalert alerts missing from vmalert-rules.yaml: " + ", ".join(missing)
        )
    if unexpected:
        errors.append(
            "unexpected vmalert rules not present in minimum-alerts.yaml: " + ", ".join(unexpected)
        )

    for alert_id in sorted(expected_vmalert & actual_ids):
        alert = catalog_by_id[alert_id]
        _, rule = vmalert_rules[alert_id]
        if str(rule.get("alert", "")).strip() != str(alert.get("alert_name", "")).strip():
            errors.append(f"alert name mismatch for {alert_id}")
        if str(rule.get("expr", "")).strip() != str(alert.get("expr", "")).strip():
            errors.append(f"expression mismatch for {alert_id}")
        if str(rule.get("for", "")).strip() != str(alert.get("for", "")).strip():
            errors.append(f"duration mismatch for {alert_id}")
        labels = rule.get("labels") or {}
        annotations = rule.get("annotations") or {}
        if str(labels.get("severity", "")).strip() != str(alert.get("severity", "")).strip():
            errors.append(f"severity mismatch for {alert_id}")
        if str(annotations.get("summary", "")).strip() != str(alert.get("summary", "")).strip():
            errors.append(f"summary mismatch for {alert_id}")
        if str(annotations.get("runbook", "")).strip() != str(alert.get("runbook", "")).strip():
            errors.append(f"runbook mismatch for {alert_id}")
    return errors


def _service_matches_signal(*, item: dict[str, Any], service_id: str) -> bool:
    service = str(item.get("service", "")).strip()
    return not service or service == service_id


def _has_smoke_consumer(item: dict[str, Any]) -> bool:
    consumers = item.get("consumers") or []
    for consumer in consumers:
        if isinstance(consumer, dict) and str(consumer.get("kind", "")).strip() == "smoke":
            return True
    return False


def smoke_signals_for_service(
    *,
    signals_cfg: dict[str, Any],
    service_id: str,
) -> tuple[list[str], dict[str, str]]:
    catalog = signals_cfg.get("catalog") or []
    if not isinstance(catalog, list):
        raise GenerationError("harness/observability/signals.yaml: catalog must be a list")

    errors: list[str] = []
    selected: dict[str, str] = {}
    for kind in SMOKE_SIGNAL_KINDS:
        candidates = [
            item
            for item in catalog
            if isinstance(item, dict)
            and str(item.get("kind", "")).strip() == kind
            and _service_matches_signal(item=item, service_id=service_id)
        ]
        if not candidates:
            errors.append(f"service {service_id}: missing {kind} signal in harness/observability/signals.yaml")
            continue
        preferred = next((item for item in candidates if _has_smoke_consumer(item)), candidates[0])
        name = str(preferred.get("name", "")).strip()
        if not name:
            errors.append(f"service {service_id}: selected {kind} signal is missing name")
            continue
        selected[kind] = name
    return errors, selected


def _normalize_coverage_entry(
    *,
    signal_name: str,
    raw_entry: Any,
) -> tuple[str, list[str]] | None:
    if isinstance(raw_entry, str):
        ref = raw_entry.strip()
        if not ref:
            return None
        return ref, [signal_name]
    if not isinstance(raw_entry, dict):
        return None
    ref = str(raw_entry.get("path", "")).strip()
    if not ref:
        return None
    contains = raw_entry.get("contains")
    if contains is None:
        return ref, [signal_name]
    if isinstance(contains, str):
        tokens = [contains.strip()] if contains.strip() else []
    elif isinstance(contains, list):
        tokens = [str(item).strip() for item in contains if str(item).strip()]
    else:
        tokens = []
    return ref, tokens or [signal_name]


def validate_signal_catalog(
    *,
    repo_root: Path,
    manifest: dict[str, Any],
    signals_cfg: dict[str, Any],
    dashboards: set[str],
    alert_ids: set[str],
) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    rows: list[dict[str, str]] = []
    services = {
        str(svc.get("id", "")).strip()
        for svc in manifest.get("services", []) or []
        if isinstance(svc, dict) and str(svc.get("id", "")).strip()
    }

    catalog = signals_cfg.get("catalog") or []
    if not isinstance(catalog, list):
        raise GenerationError("harness/observability/signals.yaml: catalog must be a list")

    seen_names: set[str] = set()
    for item in catalog:
        if not isinstance(item, dict):
            errors.append("signal catalog entries must be objects")
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            errors.append("signal catalog entry is missing name")
            continue
        if name in seen_names:
            errors.append(f"duplicate signal name: {name}")
            continue
        seen_names.add(name)

        service = str(item.get("service", "")).strip()
        if service and service not in services:
            errors.append(f"signal {name}: service not found in manifest: {service}")

        emitter = item.get("emitter") or {}
        emitter_path = str(emitter.get("path", "")).strip() if isinstance(emitter, dict) else ""
        if not emitter_path:
            errors.append(f"signal {name}: emitter.path is required")
        elif not (repo_root / emitter_path).exists():
            errors.append(f"signal {name}: emitter path does not exist: {emitter_path}")

        consumer_parts: list[str] = []
        for consumer in item.get("consumers", []) or []:
            if not isinstance(consumer, dict):
                errors.append(f"signal {name}: consumers must be objects")
                continue
            kind = str(consumer.get("kind", "")).strip()
            ref = str(consumer.get("ref", "")).strip()
            if not kind or not ref:
                errors.append(f"signal {name}: consumers require kind and ref")
                continue
            consumer_parts.append(f"{kind}:`{ref}`")
            if kind == "dashboard" and ref not in dashboards:
                errors.append(f"signal {name}: dashboard consumer not found: {ref}")
            elif kind == "alert" and ref not in alert_ids:
                errors.append(f"signal {name}: alert consumer not found: {ref}")
            elif kind in CONSUMER_FILE_KINDS and not (repo_root / ref).exists():
                errors.append(f"signal {name}: consumer file does not exist: {ref}")

        coverage_paths = item.get("coverage_paths") or []
        rendered_coverage: list[str] = []
        for raw_entry in coverage_paths:
            normalized = _normalize_coverage_entry(signal_name=name, raw_entry=raw_entry)
            if not normalized:
                errors.append(f"signal {name}: invalid coverage entry")
                continue
            ref, expected_tokens = normalized
            if expected_tokens == [name]:
                rendered_coverage.append(f"`{ref}`")
            else:
                rendered_coverage.append(
                    f"`{ref}` -> " + ", ".join(f"`{token}`" for token in expected_tokens)
                )
            path = repo_root / ref
            if not path.exists():
                errors.append(f"signal {name}: coverage path does not exist: {ref}")
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            missing_tokens = [token for token in expected_tokens if token not in text]
            if missing_tokens:
                errors.append(
                    f"signal {name}: coverage path does not prove alignment for {ref}; "
                    f"missing {', '.join(missing_tokens)}"
                )

        rows.append(
            {
                "service": service or "shared",
                "signal": f"`{name}`",
                "kind": str(item.get("kind", "")).strip(),
                "emitter": f"`{emitter_path}`" if emitter_path else "—",
                "consumers": "; ".join(consumer_parts) or "—",
                "coverage": ", ".join(rendered_coverage) or "—",
            }
        )

    return errors, rows
