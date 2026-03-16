from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    GENERATED_HEADER,
    GeneratedDocument,
    GenerationError,
    collect_env_references,
    format_file_refs,
    load_yaml,
    parse_generator_args,
    parse_env_example,
    render_markdown_table,
    run_generation,
)


def _docs_generated_dir(*, docs_cfg: dict[str, Any]) -> str:
    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _normalize_default(value: str) -> str:
    if value == "":
        return "required / no default"
    return f"`{value}`"


def _load_env_vars(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/env-vars.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/env-vars.yaml must be a YAML object")
    return cfg


def _load_docs_cfg(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/docs.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/docs.yaml must be a YAML object")
    return cfg


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    cfg = load_yaml(repo_root, "harness/manifest.yaml")
    if not isinstance(cfg, dict):
        raise GenerationError("harness/manifest.yaml must be a YAML object")
    return cfg


def _validate_env_vars_metadata(env_cfg: dict[str, Any]) -> None:
    vars_ = env_cfg.get("vars") or []
    if not isinstance(vars_, list):
        raise GenerationError("env-vars.yaml: vars must be a list")
    names = [str(item.get("name", "")) for item in vars_ if isinstance(item, dict)]
    duplicates = {name for name in names if name and names.count(name) > 1}
    if duplicates:
        raise GenerationError(
            "env-vars.yaml: duplicate var entries: " + ", ".join(sorted(duplicates))
        )


def _validate_against_repo(*, repo_root: Path, env_cfg: dict[str, Any]) -> dict[str, set[str]]:
    manifest = _load_manifest(repo_root)
    env_example = str(env_cfg.get("env_example", ".env.example")).strip() or ".env.example"
    ignored = env_cfg.get("ignored") or []
    ignored_set = {str(x) for x in ignored} if isinstance(ignored, list) else set()

    vars_ = env_cfg.get("vars") or []
    if not isinstance(vars_, list):
        raise GenerationError("env-vars.yaml: vars must be a list")

    supported: dict[str, dict[str, Any]] = {}
    for item in vars_:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        supported[name] = item

    services = manifest.get("services") or []
    scan_roots = {
        str(svc.get("path", "")).strip()
        for svc in services
        if isinstance(svc, dict) and str(svc.get("path", "")).strip()
    }
    if (repo_root / "victoriametrics").exists():
        scan_roots.add("victoriametrics")
    references = collect_env_references(
        repo_root,
        env_example=env_example,
        scan_roots=sorted(scan_roots) if scan_roots else None,
    )

    undocumented = sorted(
        name for name in references if name not in supported and name not in ignored_set
    )
    if undocumented:
        raise GenerationError(
            "undocumented env vars detected in repo sources: " + ", ".join(undocumented)
        )

    if not (repo_root / env_example).exists():
        raise GenerationError(f"env_example file not found: {env_example}")

    env_example_values = parse_env_example(repo_root, env_example)

    missing_from_env_example = sorted(
        name
        for name, item in supported.items()
        if bool(item.get("in_env_example", True)) and name not in env_example_values
    )
    if missing_from_env_example:
        raise GenerationError(
            f"{env_example} is missing supported env vars: " + ", ".join(missing_from_env_example)
        )

    for name, item in supported.items():
        if not bool(item.get("in_env_example", True)):
            continue
        expected_default = str(item.get("default", ""))
        actual_default = env_example_values[name]
        if actual_default != expected_default:
            raise GenerationError(
                f"default mismatch for {name}: {env_example} has {actual_default!r}, "
                f"env-vars.yaml has {expected_default!r}"
            )

    return references


def render_env_matrix(*, repo_root: Path) -> tuple[str, str]:
    docs_cfg = _load_docs_cfg(repo_root)
    env_cfg = _load_env_vars(repo_root)

    _validate_env_vars_metadata(env_cfg)
    references = _validate_against_repo(repo_root=repo_root, env_cfg=env_cfg)

    env_example = str(env_cfg.get("env_example", ".env.example")).strip() or ".env.example"
    generated_dir = _docs_generated_dir(docs_cfg=docs_cfg)
    vars_ = env_cfg.get("vars") or []

    rows: list[list[str]] = []
    for item in vars_:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        used_in = sorted((references.get(name, set()) - {env_example}))
        rows.append(
            [
                f"`{name}`",
                _normalize_default(str(item.get("default", ""))),
                format_file_refs(used_in),
                str(item.get("relevance", "")).strip() or "—",
            ]
        )

    body = render_markdown_table(["Variable", "Default", "Used in", "Relevance"], rows)

    content = "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Environment Matrix",
            "============================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory lists repository-supported environment variables across runtime, Docker, tests, and observability flows.",
            "It is generated from `harness/env-vars.yaml` plus repo scanning and fails generation if a referenced variable is undocumented.",
            "",
            body,
            "",
        ]
    )
    return f"{generated_dir}/env-matrix.md", content


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_env_matrix(repo_root=repo_root)
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
        print("generated-env-matrix-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-env-matrix-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
