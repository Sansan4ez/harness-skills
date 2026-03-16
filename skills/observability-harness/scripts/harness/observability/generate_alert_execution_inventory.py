from __future__ import annotations

from pathlib import Path

from checks import load_alert_catalog, load_baseline, load_vmalert_rules, validate_alert_execution
from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    GenerationError,
    parse_generator_args,
    render_markdown_table,
    run_generation,
)


def render_alert_execution_inventory(*, repo_root: Path) -> str:
    baseline = load_baseline(repo_root)
    alerts = load_alert_catalog(repo_root=repo_root, baseline=baseline)
    rules = load_vmalert_rules(repo_root=repo_root, baseline=baseline)
    errors = validate_alert_execution(alerts=alerts, vmalert_rules=rules)
    if errors:
        raise GenerationError("; ".join(errors))

    rows: list[list[str]] = []
    for alert in alerts:
        alert_id = str(alert["id"])
        execution = str(alert.get("execution", ""))
        if execution == "vmalert":
            group_name, rule = rules[alert_id]
            loaded = "yes"
            rule_name = f"`{rule['alert']}`"
            source = "`victoriametrics/alerts/vmalert-rules.yaml`"
        else:
            group_name = "—"
            loaded = "no"
            rule_name = "—"
            source = "manual only"
        rows.append(
            [
                f"`{alert_id}`",
                execution,
                loaded,
                rule_name,
                group_name,
                source,
                f"`{alert['runbook']}`",
            ]
        )

    body = render_markdown_table(
        ["Alert ID", "Execution mode", "Loaded in vmalert", "Rule name", "Rule group", "Source", "Runbook"],
        rows,
    )
    return "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Alert Execution Inventory",
            "===================================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory cross-checks the minimum alert catalog against the executable `vmalert` rules.",
            "",
            body,
            "",
        ]
    )


def build_document(*, repo_root: Path) -> GeneratedDocument:
    return GeneratedDocument(
        "docs/generated/alert-execution.md",
        render_alert_execution_inventory(repo_root=repo_root),
    )


def main() -> int:
    args = parse_generator_args()
    repo_root = Path(args.repo_root).resolve()
    errors = run_generation(
        repo_root=repo_root,
        documents=[build_document(repo_root=repo_root)],
        check=bool(args.check),
    )
    if errors:
        print("generated-alert-execution-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-alert-execution-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
