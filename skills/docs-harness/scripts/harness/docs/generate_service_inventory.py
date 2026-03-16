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


def _docs_generated_dir(*, docs_cfg: dict[str, Any]) -> str:
    generated_dir = docs_cfg.get("generated_dir")
    if isinstance(generated_dir, str) and generated_dir.strip():
        return generated_dir.strip().rstrip("/")
    return "docs/generated"


def _service_hub_dir(*, docs_cfg: dict[str, Any]) -> str:
    hub = docs_cfg.get("service_hub_dir")
    if isinstance(hub, str) and hub.strip():
        return hub.strip().rstrip("/")
    return "docs/services"


def _c4_l3_dir(*, docs_cfg: dict[str, Any]) -> str:
    c4 = docs_cfg.get("c4") or {}
    if isinstance(c4, dict):
        l3 = c4.get("l3_dir")
        if isinstance(l3, str) and l3.strip():
            return l3.strip().rstrip("/")
    return "docs/architecture/c4/services"


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


def render_service_inventory(*, repo_root: Path) -> tuple[str, str]:
    docs_cfg = _load_docs_cfg(repo_root)
    manifest = _load_manifest(repo_root)

    generated_dir = _docs_generated_dir(docs_cfg=docs_cfg)
    hub_dir = _service_hub_dir(docs_cfg=docs_cfg)
    l3_dir = _c4_l3_dir(docs_cfg=docs_cfg)

    services = manifest.get("services") or []
    if not isinstance(services, list):
        raise GenerationError("manifest.yaml: services must be a list")

    rows: list[list[str]] = []
    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = str(svc.get("id", "")).strip()
        if not sid:
            continue
        openapi = str(svc.get("openapi", "")).strip() or "—"
        if openapi != "—":
            openapi = f"`{openapi}`"

        rows.append(
            [
                f"`{sid}`",
                f"`{str(svc.get('kind', '')).strip() or 'service'}`",
                f"`{str(svc.get('path', '')).strip()}`",
                f"`{str(svc.get('compose_service', '')).strip()}`",
                f"`{hub_dir}/{sid}/index.md`",
                openapi,
                f"`{l3_dir}/{sid}/l3-components.md`",
            ]
        )

    body = render_markdown_table(
        ["Service", "Kind", "Path", "Compose", "Docs hub", "OpenAPI", "C4 L3"],
        rows,
    )

    content = "\n".join(
        [
            GENERATED_HEADER,
            "",
            "Generated Service Inventory",
            "===========================",
            "",
            "Scope",
            "-----",
            "",
            "This inventory is generated from `harness/manifest.yaml` and provides a stable index of services, their docs hubs, and contracts.",
            "It supports the docs-harness reachability model and makes service additions mechanically visible in review.",
            "",
            body,
            "",
        ]
    )

    return f"{generated_dir}/service-inventory.md", content


def build_document(*, repo_root: Path) -> GeneratedDocument:
    rel_path, content = render_service_inventory(repo_root=repo_root)
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
        print("generated-service-inventory-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-service-inventory-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

