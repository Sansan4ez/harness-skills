from __future__ import annotations

from pathlib import Path

from checks import dashboard_catalog, load_baseline
from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    parse_generator_args,
    render_markdown_table,
    run_generation,
)


def render_dashboard_index(*, repo_root: Path) -> str:
    baseline = load_baseline(repo_root)
    catalog = dashboard_catalog(repo_root=repo_root, baseline=baseline)
    rows = [
        [
            f"`{item['uid']}`",
            item["title"],
            f"`{item['path']}`",
            str(len(item["panels"])),
            ", ".join(f"`{title}`" for title in item["panels"]) or "—",
        ]
        for item in catalog
    ]
    body = render_markdown_table(
        ["UID", "Title", "Source file", "Panels", "Panel titles"],
        rows,
    )
    return "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Dashboard Index",
            "=========================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from Grafana dashboard JSON assets under `victoriametrics/grafana/provisioning/dashboards/files/`.",
            "",
            body,
            "",
        ]
    )


def build_document(*, repo_root: Path) -> GeneratedDocument:
    return GeneratedDocument(
        "docs/generated/dashboard-index.md",
        render_dashboard_index(repo_root=repo_root),
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
        print("generated-dashboard-index-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-dashboard-index-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
