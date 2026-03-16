from __future__ import annotations

from pathlib import Path

from common import GenerationError, parse_generator_args, run_generation
from generate_doc_gardening_report import build_document as build_doc_gardening_report
from generate_doc_inventory import build_document as build_doc_inventory
from generate_env_matrix import build_document as build_env_matrix
from generate_generated_index import build_document as build_generated_index
from generate_service_inventory import build_document as build_service_inventory


def generate_documents(*, repo_root: Path, check: bool) -> list[str]:
    errors: list[str] = []
    documents = []

    builders = [
        ("service inventory", build_service_inventory),
        ("env matrix", build_env_matrix),
        ("doc gardening report", build_doc_gardening_report),
        ("generated index", build_generated_index),
        # Doc inventory must be last so it can observe the other generated artifacts.
        ("doc inventory", build_doc_inventory),
    ]
    for label, builder in builders:
        try:
            documents.append(builder(repo_root=repo_root))
        except (GenerationError, FileNotFoundError) as e:
            errors.append(f"{label}: {e}")

    errors.extend(run_generation(repo_root=repo_root, documents=documents, check=check))
    return errors


def main() -> int:
    args = parse_generator_args()
    repo_root = Path(args.repo_root).resolve()
    errors = generate_documents(repo_root=repo_root, check=bool(args.check))
    if errors:
        print("generated-docs-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-docs-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
