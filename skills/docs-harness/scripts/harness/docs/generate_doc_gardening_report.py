from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    GenerationError,
    load_yaml,
    parse_generator_args,
    render_markdown_table,
    run_generation,
)
from doc_garden import analyze_doc_garden


def _docs_generated_dir(*, docs_cfg: dict[str, Any]) -> str:
    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _load_docs_cfg(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/docs.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/docs.yaml must be a YAML object")
    return cfg


def _active_docs(repo_root: Path, docs_cfg: dict[str, Any]) -> set[str]:
    active: set[str] = set()

    entrypoint = str(docs_cfg.get("entrypoint", "")).strip()
    if entrypoint:
        active.add(entrypoint)

    domain_indexes = docs_cfg.get("domain_indexes") or {}
    if isinstance(domain_indexes, dict):
        for v in domain_indexes.values():
            if isinstance(v, str) and v.strip():
                active.add(v.strip())

    service_hub_dir = docs_cfg.get("service_hub_dir")
    if isinstance(service_hub_dir, str) and (repo_root / service_hub_dir).exists():
        for path in (repo_root / service_hub_dir).glob("*/index.md"):
            active.add(path.relative_to(repo_root).as_posix())

    if (repo_root / "docs/architecture/c4/index.md").exists():
        active.add("docs/architecture/c4/index.md")

    return active


def render_doc_gardening_report(*, repo_root: Path) -> tuple[str, str]:
    docs_cfg = _load_docs_cfg(repo_root)
    generated_dir = _docs_generated_dir(docs_cfg=docs_cfg)

    analysis = analyze_doc_garden(
        repo_root, docs_cfg=docs_cfg, active_docs=_active_docs(repo_root, docs_cfg)
    )

    redirects = analysis.compatibility_redirects
    stale = analysis.stale_asset_references
    hist = analysis.historical_reference_issues

    sections: list[str] = [
        GENERATED_HEADER,
        "",
        "Generated Doc Gardening Report",
        "==============================",
        "",
        "Summary",
        "-------",
        "",
        f"- Compatibility redirects: {len(redirects)}",
        f"- Stale asset references: {len(stale)}",
        f"- Historical reference issues: {len(hist)}",
        "",
    ]

    if redirects:
        rows = [[f"`{p}`"] for p in redirects]
        sections.extend(
            [
                "Compatibility Redirects",
                "-----------------------",
                "",
                render_markdown_table(["Path"], rows),
                "",
            ]
        )

    if stale:
        rows = [[f"`{x.source_path}`", f"`{x.target_path}`"] for x in stale]
        sections.extend(
            [
                "Stale Asset References",
                "----------------------",
                "",
                render_markdown_table(["Source", "Missing target"], rows),
                "",
            ]
        )

    if hist:
        rows = [[f"`{x.source_path}`", f"`{x.target_path}`", x.line] for x in hist]
        sections.extend(
            [
                "Historical Reference Issues",
                "---------------------------",
                "",
                render_markdown_table(["Source", "Historical target", "Line"], rows),
                "",
            ]
        )

    return f"{generated_dir}/doc-gardening-report.md", "\n".join(sections)


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_doc_gardening_report(repo_root=repo_root)
    return GeneratedDocument(rel_path, content)


def main() -> int:
    args = parse_generator_args()
    repo_root = Path(args.repo_root).resolve()
    errors = run_generation(
        repo_root=repo_root,
        documents=[build_document(repo_root=repo_root)],
        check=bool(args.check),
    )
    if errors:
        print("generated-doc-gardening-report-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-doc-gardening-report-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

