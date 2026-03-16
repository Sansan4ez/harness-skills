from __future__ import annotations

from pathlib import Path

from common import GenerationError, parse_generator_args, run_generation
from generate_http_endpoints_inventory import build_document as build_http_endpoints


def generate_documents(*, repo_root: Path, check: bool) -> list[str]:
    errors: list[str] = []
    documents = []

    builders = [
        ("http endpoints inventory", build_http_endpoints),
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
        print("generated-traceability-docs-check: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("generated-traceability-docs-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

