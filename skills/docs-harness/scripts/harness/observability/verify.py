from __future__ import annotations

from pathlib import Path

from checks import (
    REQUIRED_OBSERVABILITY_DOCS,
    dashboard_titles,
    expected_stack_paths,
    load_alert_catalog,
    load_baseline,
    load_manifest,
    load_signals_cfg,
    load_vmalert_rules,
    validate_alert_execution,
    validate_signal_catalog,
)
from common import GenerationError, parse_verify_args
from generate_all import generate_documents


def verify(*, repo_root: Path) -> list[str]:
    errors: list[str] = []

    try:
        manifest = load_manifest(repo_root)
        baseline = load_baseline(repo_root)
        signals_cfg = load_signals_cfg(repo_root)
    except GenerationError as e:
        return [str(e)]

    for rel_path in REQUIRED_OBSERVABILITY_DOCS:
        if not (repo_root / rel_path).exists():
            errors.append(f"missing required observability doc: {rel_path}")

    for rel_path in expected_stack_paths(baseline):
        if not (repo_root / rel_path).exists():
            errors.append(f"missing observability asset: {rel_path}")

    try:
        dashboards = dashboard_titles(repo_root=repo_root, baseline=baseline)
        alerts = load_alert_catalog(repo_root=repo_root, baseline=baseline)
        rules = load_vmalert_rules(repo_root=repo_root, baseline=baseline)
    except GenerationError as e:
        errors.append(str(e))
        return errors

    errors.extend(validate_alert_execution(alerts=alerts, vmalert_rules=rules))

    signal_errors, _ = validate_signal_catalog(
        repo_root=repo_root,
        manifest=manifest,
        signals_cfg=signals_cfg,
        dashboards=dashboards,
        alert_ids={str(alert["id"]) for alert in alerts},
    )
    errors.extend(signal_errors)
    errors.extend(generate_documents(repo_root=repo_root, check=True))
    return errors


def main() -> int:
    args = parse_verify_args()
    repo_root = Path(args.repo_root).resolve()
    errors = verify(repo_root=repo_root)
    if errors:
        print("observability-harness-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("observability-harness-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
