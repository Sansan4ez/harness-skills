from __future__ import annotations

from pathlib import Path
from typing import Any

from common import GenerationError, extract_repo_doc_refs, load_yaml, repo_relative
from doc_garden import analyze_doc_garden
from generate_all import generate_documents


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


def _index_roots(repo_root: Path, docs_cfg: dict[str, Any]) -> set[str]:
    roots: set[str] = set()
    entrypoint = str(docs_cfg.get("entrypoint", "")).strip()
    if entrypoint:
        roots.add(entrypoint)

    domain_indexes = docs_cfg.get("domain_indexes") or {}
    if isinstance(domain_indexes, dict):
        for v in domain_indexes.values():
            if isinstance(v, str) and v.strip():
                roots.add(v.strip())

    # Optional but common conventions.
    if (repo_root / "docs/generated/index.md").exists():
        roots.add("docs/generated/index.md")
    if (repo_root / "specs/index.md").exists():
        roots.add("specs/index.md")

    return roots


def _active_docs(repo_root: Path, docs_cfg: dict[str, Any]) -> set[str]:
    active = set(_index_roots(repo_root, docs_cfg))

    service_hub_dir = docs_cfg.get("service_hub_dir")
    if isinstance(service_hub_dir, str) and (repo_root / service_hub_dir).exists():
        for path in (repo_root / service_hub_dir).glob("*/index.md"):
            active.add(repo_relative(repo_root, path))

    if (repo_root / "docs/architecture/c4/index.md").exists():
        active.add("docs/architecture/c4/index.md")

    return active


def _extract_existing_refs(repo_root: Path, rel_path: str) -> set[str]:
    if not rel_path.endswith(".md"):
        # Reachability graph expands only through Markdown docs.
        return set()
    content = (repo_root / rel_path).read_text(encoding="utf-8", errors="ignore")
    refs: set[str] = set()
    for match in extract_repo_doc_refs(content):
        path = repo_root / match
        if path.exists() and path.is_file():
            refs.add(match)
    return refs


def _assert_required_indexes_exist(repo_root: Path, docs_cfg: dict[str, Any], errors: list[str]) -> None:
    entrypoint = str(docs_cfg.get("entrypoint", "")).strip()
    if not entrypoint:
        errors.append("harness/docs.yaml: missing entrypoint")
    elif not (repo_root / entrypoint).exists():
        errors.append(f"missing docs entrypoint: {entrypoint}")

    domain_indexes = docs_cfg.get("domain_indexes") or {}
    if not isinstance(domain_indexes, dict) or not domain_indexes:
        errors.append("harness/docs.yaml: domain_indexes must be a non-empty map")
        return

    for key, value in domain_indexes.items():
        if not isinstance(value, str) or not value.strip():
            errors.append(f"domain_indexes.{key} must be a non-empty string path")
            continue
        p = value.strip()
        if not (repo_root / p).exists():
            errors.append(f"missing domain index: {p}")


def _assert_required_service_docs_exist(
    repo_root: Path, docs_cfg: dict[str, Any], manifest: dict[str, Any], errors: list[str]
) -> None:
    hub_dir = docs_cfg.get("service_hub_dir")
    if not isinstance(hub_dir, str) or not hub_dir.strip():
        return
    hub_dir = hub_dir.strip().rstrip("/")

    services = manifest.get("services") or []
    if not isinstance(services, list):
        errors.append("harness/manifest.yaml: services must be a list")
        return

    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = str(svc.get("id", "")).strip()
        if not sid:
            continue
        doc_path = f"{hub_dir}/{sid}/index.md"
        if not (repo_root / doc_path).exists():
            errors.append(f"missing service docs hub: {doc_path}")


def _assert_required_c4_docs_exist(
    repo_root: Path, docs_cfg: dict[str, Any], manifest: dict[str, Any], errors: list[str]
) -> None:
    c4 = docs_cfg.get("c4") or {}
    if not isinstance(c4, dict):
        return
    l1 = str(c4.get("l1", "")).strip()
    l2 = str(c4.get("l2", "")).strip()
    l3_dir = str(c4.get("l3_dir", "")).strip().rstrip("/")
    if l1 and not (repo_root / l1).exists():
        errors.append(f"missing C4 L1 doc: {l1}")
    if l2 and not (repo_root / l2).exists():
        errors.append(f"missing C4 L2 doc: {l2}")

    if l3_dir:
        services = manifest.get("services") or []
        if isinstance(services, list):
            for svc in services:
                if not isinstance(svc, dict):
                    continue
                sid = str(svc.get("id", "")).strip()
                if not sid:
                    continue
                l3 = f"{l3_dir}/{sid}/l3-components.md"
                if not (repo_root / l3).exists():
                    errors.append(f"missing C4 L3 doc: {l3}")


def _assert_no_broken_internal_refs(repo_root: Path, errors: list[str]) -> None:
    for base in ("docs", "specs"):
        if not (repo_root / base).exists():
            continue
        for path in (repo_root / base).rglob("*.md"):
            rel_path = repo_relative(repo_root, path)
            content = path.read_text(encoding="utf-8", errors="ignore")
            for match in extract_repo_doc_refs(content):
                target = repo_root / match
                if target.exists():
                    continue
                errors.append(f"broken internal ref: {rel_path} -> {match}")


def _assert_all_docs_are_reachable(
    repo_root: Path, *, roots: set[str], errors: list[str]
) -> None:
    reachable: set[str] = set()
    frontier = list(sorted(roots))

    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        if not (repo_root / current).exists():
            continue
        reachable.add(current)
        frontier.extend(sorted(_extract_existing_refs(repo_root, current) - reachable))

    expected: set[str] = set()
    if (repo_root / "docs").exists():
        expected |= {
            repo_relative(repo_root, path)
            for path in (repo_root / "docs").rglob("*.md")
        }
    if (repo_root / "specs").exists():
        expected |= {
            repo_relative(repo_root, path)
            for path in (repo_root / "specs").rglob("*")
            if path.is_file()
        }

    missing = sorted(expected - reachable)
    if missing:
        errors.append("unreachable docs/specs from indexes: " + ", ".join(missing))


def verify(*, repo_root: Path) -> list[str]:
    errors: list[str] = []

    try:
        docs_cfg = _load_docs_cfg(repo_root)
        manifest = _load_manifest(repo_root)
    except GenerationError as e:
        return [str(e)]

    _assert_required_indexes_exist(repo_root, docs_cfg, errors)
    _assert_required_service_docs_exist(repo_root, docs_cfg, manifest, errors)
    _assert_required_c4_docs_exist(repo_root, docs_cfg, manifest, errors)
    _assert_no_broken_internal_refs(repo_root, errors)

    rules = docs_cfg.get("rules") or {}
    require_reachability = bool(rules.get("require_reachability", False)) if isinstance(rules, dict) else False
    if require_reachability:
        _assert_all_docs_are_reachable(repo_root, roots=_index_roots(repo_root, docs_cfg), errors=errors)

    analysis = analyze_doc_garden(
        repo_root, docs_cfg=docs_cfg, active_docs=_active_docs(repo_root, docs_cfg)
    )
    if analysis.compatibility_redirects:
        errors.append(
            "compatibility redirects remain: " + ", ".join(analysis.compatibility_redirects)
        )
    if analysis.stale_asset_references:
        rendered = ", ".join(
            f"{x.source_path} -> {x.target_path}" for x in analysis.stale_asset_references
        )
        errors.append("stale asset references detected: " + rendered)
    if analysis.historical_reference_issues:
        rendered = ", ".join(
            f"{x.source_path} -> {x.target_path}" for x in analysis.historical_reference_issues
        )
        errors.append("historical docs used as active sources: " + rendered)

    errors.extend(generate_documents(repo_root=repo_root, check=True))
    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    # Allow overriding repo-root for fixture tests and agent usage.
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(repo_root))
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()

    errors = verify(repo_root=repo_root)
    if errors:
        print("docs-harness-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("docs-harness-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
