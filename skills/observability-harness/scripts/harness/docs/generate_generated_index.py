from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    load_yaml,
    parse_generator_args,
    repo_relative,
    run_generation,
)


def _docs_generated_dir(*, docs_cfg: dict[str, Any]) -> str:
    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _iter_existing_generated_docs(repo_root: Path, generated_dir: str) -> list[str]:
    base = repo_root / generated_dir
    if not base.exists():
        return []
    paths: list[str] = []
    for path in base.rglob("*.md"):
        if not path.is_file():
            continue
        rel = repo_relative(repo_root, path)
        if rel == f"{generated_dir}/index.md":
            continue
        paths.append(rel)
    return sorted(set(paths))


def render_generated_index(*, repo_root: Path) -> tuple[str, str]:
    docs_cfg_raw = load_yaml(repo_root, "harness/docs.yaml")
    docs_cfg = docs_cfg_raw if isinstance(docs_cfg_raw, dict) else {}
    generated_dir = _docs_generated_dir(docs_cfg=docs_cfg)

    # Always include docs-harness inventories (even on first generation) so the index
    # doesn't depend on filesystem state at the time it's built.
    expected = [
        f"{generated_dir}/service-inventory.md",
        f"{generated_dir}/env-matrix.md",
        f"{generated_dir}/doc-gardening-report.md",
        f"{generated_dir}/doc-inventory.md",
    ]

    existing = _iter_existing_generated_docs(repo_root, generated_dir)

    artifacts: list[str] = []
    seen: set[str] = set()
    for rel in [*expected, *existing]:
        if rel in seen:
            continue
        seen.add(rel)
        artifacts.append(rel)

    bullet_lines = [f"- `{rel}`" for rel in artifacts]

    content = "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Inventories",
            "=====================",
            "",
            "Purpose",
            "-------",
            "",
            "This index is generated from `docs/generated/` and is used to keep all generated artifacts reachable from the docs entrypoint.",
            "",
            "Artifacts",
            "---------",
            "",
            *bullet_lines,
            "",
        ]
    )
    return f"{generated_dir}/index.md", content


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_generated_index(repo_root=repo_root)
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
        print("generated-generated-index-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-generated-index-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

