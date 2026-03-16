from __future__ import annotations

from pathlib import Path

from checks import (
    dashboard_titles,
    load_alert_catalog,
    load_baseline,
    load_manifest,
    load_signals_cfg,
    validate_signal_catalog,
)
from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    GenerationError,
    parse_generator_args,
    render_markdown_table,
    run_generation,
)


def render_signal_inventory(*, repo_root: Path) -> str:
    manifest = load_manifest(repo_root)
    baseline = load_baseline(repo_root)
    signals_cfg = load_signals_cfg(repo_root)
    dashboards = dashboard_titles(repo_root=repo_root, baseline=baseline)
    alerts = load_alert_catalog(repo_root=repo_root, baseline=baseline)
    errors, rows = validate_signal_catalog(
        repo_root=repo_root,
        manifest=manifest,
        signals_cfg=signals_cfg,
        dashboards=dashboards,
        alert_ids={str(alert["id"]) for alert in alerts},
    )
    if errors:
        raise GenerationError("; ".join(errors))

    body = render_markdown_table(
        ["Service", "Signal", "Kind", "Emitter", "Consumers", "Coverage"],
        [
            [
                row["service"],
                row["signal"],
                row["kind"],
                row["emitter"],
                row["consumers"],
                row["coverage"],
            ]
            for row in rows
        ],
    )

    return "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Observability Signals",
            "===============================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from `harness/observability/signals.yaml`.",
            "It provides the mechanical mapping between emitted signals, their operational consumers, and the repository files that prove alignment.",
            "",
            body,
            "",
        ]
    )


def build_document(*, repo_root: Path) -> GeneratedDocument:
    return GeneratedDocument(
        "docs/generated/observability-signals.md",
        render_signal_inventory(repo_root=repo_root),
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
        print("generated-observability-signals-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-observability-signals-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
