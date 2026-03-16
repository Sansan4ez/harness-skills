from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    load_yaml,
    parse_generator_args,
    render_markdown_table,
    repo_relative,
    run_generation,
)


def _docs_generated_dir(*, docs_cfg: dict[str, Any]) -> str:
    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _classification(rel_path: str) -> str:
    if rel_path.startswith("docs/generated/"):
        return "generated"
    if rel_path.startswith("docs/references/"):
        return "reference"
    if rel_path.startswith("docs/archive/") or rel_path.startswith("docs/plans/completed/"):
        return "historical"
    return "source-of-truth"


def _responsible_area(rel_path: str) -> str:
    if rel_path in {"AGENTS.md", "ARCHITECTURE.md", "README.md", "docs/index.md"}:
        return "repository-navigation"
    if rel_path.startswith("docs/architecture/") or rel_path == "ARCHITECTURE.md":
        return "architecture"
    if rel_path.startswith("docs/operations/"):
        return "operations"
    if rel_path.startswith("docs/requirements/") or rel_path.startswith("specs/"):
        return "requirements-and-contract"
    if rel_path.startswith("docs/plans/"):
        return "delivery-planning"
    if rel_path.startswith("docs/references/"):
        return "reference-material"
    if rel_path.startswith("docs/generated/"):
        return "docs-automation"
    return "repository-navigation"


def _note(rel_path: str) -> str:
    if rel_path.endswith("/index.md"):
        return "domain index"
    if rel_path.startswith("docs/architecture/adr/"):
        return "accepted decision record"
    if rel_path.startswith("docs/requirements/non-functional/"):
        return "non-functional requirement"
    if rel_path.startswith("docs/requirements/functional/"):
        return "functional requirement"
    if rel_path.startswith("docs/plans/active/"):
        return "active execution plan"
    if rel_path == "docs/plans/tech-debt.md":
        return "technical debt register"
    if rel_path.startswith("specs/"):
        return "runtime contract"
    return "repository document"


def _iter_inventory_paths(repo_root: Path) -> list[str]:
    rel_paths: list[str] = []
    for root_doc in ("AGENTS.md", "ARCHITECTURE.md", "README.md"):
        if (repo_root / root_doc).exists():
            rel_paths.append(root_doc)

    rel_paths.extend(
        sorted(repo_relative(repo_root, path) for path in (repo_root / "docs").rglob("*.md"))
        if (repo_root / "docs").exists()
        else []
    )
    if (repo_root / "specs").exists():
        rel_paths.extend(
            sorted(
                repo_relative(repo_root, path)
                for path in (repo_root / "specs").rglob("*")
                if path.is_file()
            )
        )

    return rel_paths


def render_doc_inventory(*, repo_root: Path) -> tuple[str, str]:
    docs_cfg_raw = load_yaml(repo_root, "harness/docs.yaml")
    docs_cfg = docs_cfg_raw if isinstance(docs_cfg_raw, dict) else {}
    generated_dir = _docs_generated_dir(docs_cfg=docs_cfg)

    rows: list[list[str]] = []
    inventory_paths = _iter_inventory_paths(repo_root)
    # Ensure the inventory always includes itself (stable output on first generation).
    inventory_paths.append(f"{generated_dir}/doc-inventory.md")
    for rel_path in sorted(set(inventory_paths)):
        rows.append(
            [
                f"`{rel_path}`",
                _classification(rel_path),
                _responsible_area(rel_path),
                _note(rel_path),
            ]
        )

    body = render_markdown_table(
        ["Path", "Classification", "Responsible area", "Notes"],
        rows,
    )

    content = "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Doc Inventory",
            "=======================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from the repository doc tree and classifies each artifact as `source-of-truth`, `generated`, `historical`, or `reference`.",
            "It is used by docs-harness checks (reachability and doc-gardening rules).",
            "",
            body,
            "",
        ]
    )
    return f"{generated_dir}/doc-inventory.md", content


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_doc_inventory(repo_root=repo_root)
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
        print("generated-doc-inventory-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-doc-inventory-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
