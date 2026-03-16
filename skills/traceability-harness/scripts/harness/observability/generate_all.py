from __future__ import annotations

from pathlib import Path

from common import parse_generator_args, run_generation
from generate_alert_catalog import build_document as build_alert_catalog
from generate_alert_execution_inventory import (
    build_document as build_alert_execution_inventory,
)
from generate_dashboard_index import build_document as build_dashboard_index
from generate_signal_inventory import build_document as build_signal_inventory


def generate_documents(*, repo_root: Path, check: bool) -> list[str]:
    documents = [
        build_signal_inventory(repo_root=repo_root),
        build_dashboard_index(repo_root=repo_root),
        build_alert_catalog(repo_root=repo_root),
        build_alert_execution_inventory(repo_root=repo_root),
    ]
    return run_generation(repo_root=repo_root, documents=documents, check=check)


def main() -> int:
    args = parse_generator_args()
    repo_root = Path(args.repo_root).resolve()
    errors = generate_documents(repo_root=repo_root, check=bool(args.check))
    if errors:
        print("generated-observability-docs-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-observability-docs-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
