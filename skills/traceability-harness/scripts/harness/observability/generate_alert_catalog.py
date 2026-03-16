from __future__ import annotations

from pathlib import Path

from checks import load_alert_catalog, load_baseline
from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    parse_generator_args,
    render_markdown_table,
    run_generation,
)


def render_alert_catalog(*, repo_root: Path) -> str:
    baseline = load_baseline(repo_root)
    alerts = load_alert_catalog(repo_root=repo_root, baseline=baseline)
    rows = [
        [
            f"`{alert['id']}`",
            str(alert.get("execution", "")),
            alert["title"],
            str(alert.get("severity", "")),
            str(alert.get("datasource", "—")),
            f"`{alert['runbook']}`",
        ]
        for alert in alerts
    ]
    body = render_markdown_table(
        ["Alert ID", "Execution", "Title", "Severity", "Datasource", "Runbook"],
        rows,
    )
    return "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Alert Catalog",
            "=======================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from the minimum alert catalog under `victoriametrics/alerts/`.",
            "",
            body,
            "",
        ]
    )


def build_document(*, repo_root: Path) -> GeneratedDocument:
    return GeneratedDocument(
        "docs/generated/alert-catalog.md",
        render_alert_catalog(repo_root=repo_root),
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
        print("generated-alert-catalog-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-alert-catalog-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
