from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


@dataclass(frozen=True)
class Surface:
    surface_id: str
    owner: str
    summary: str
    implementation_patterns: tuple[str, ...]
    ignore_patterns: tuple[str, ...]
    required_alignment_patterns: tuple[str, ...]


@dataclass(frozen=True)
class ReservedSurfaceCategory:
    category_id: str
    owner: str
    summary: str
    implementation_patterns: tuple[str, ...]
    ignore_patterns: tuple[str, ...]
    required_alignment_hint: tuple[str, ...]


def _normalize(paths: list[str]) -> set[str]:
    return {path.strip() for path in paths if path.strip()}


def _matches_pattern(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3])
    return PurePosixPath(path).match(pattern)


def _load_registry(*, repo_root: Path, rel_path: str) -> tuple[dict[str, Surface], dict[str, ReservedSurfaceCategory]]:
    path = repo_root / rel_path
    if not path.exists():
        raise FileNotFoundError(rel_path)

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel_path} must be a YAML object")
    if payload.get("version") != 1:
        raise ValueError(f"{rel_path}: version must be 1")

    surfaces_raw = payload.get("surfaces") or {}
    if not isinstance(surfaces_raw, dict) or not surfaces_raw:
        raise ValueError(f"{rel_path}: surfaces must be a non-empty map")

    surfaces: dict[str, Surface] = {}
    for surface_id, data in surfaces_raw.items():
        if not isinstance(data, dict):
            continue
        impl = data.get("implementation_patterns", [])
        required = data.get("required_alignment_patterns", [])
        if not isinstance(impl, list) or not impl:
            raise ValueError(f"{rel_path}: surfaces.{surface_id}.implementation_patterns must be a non-empty list")
        if not isinstance(required, list) or not required:
            raise ValueError(f"{rel_path}: surfaces.{surface_id}.required_alignment_patterns must be a non-empty list")

        ignore = data.get("ignore_patterns", [])
        if ignore and not isinstance(ignore, list):
            raise ValueError(f"{rel_path}: surfaces.{surface_id}.ignore_patterns must be a list")

        surfaces[str(surface_id)] = Surface(
            surface_id=str(surface_id),
            owner=str(data.get("owner", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            implementation_patterns=tuple(str(x).strip() for x in impl if str(x).strip()),
            ignore_patterns=tuple(str(x).strip() for x in ignore if str(x).strip()) if isinstance(ignore, list) else (),
            required_alignment_patterns=tuple(str(x).strip() for x in required if str(x).strip()),
        )

    reserved_raw = payload.get("reserved_categories") or {}
    reserved: dict[str, ReservedSurfaceCategory] = {}
    if isinstance(reserved_raw, dict):
        for category_id, data in reserved_raw.items():
            if not isinstance(data, dict):
                continue
            impl = data.get("implementation_patterns", [])
            if not isinstance(impl, list) or not impl:
                continue
            ignore = data.get("ignore_patterns", [])
            if ignore and not isinstance(ignore, list):
                raise ValueError(f"{rel_path}: reserved_categories.{category_id}.ignore_patterns must be a list")
            hint = data.get("required_alignment_hint", [])
            if hint and not isinstance(hint, list):
                raise ValueError(f"{rel_path}: reserved_categories.{category_id}.required_alignment_hint must be a list")

            reserved[str(category_id)] = ReservedSurfaceCategory(
                category_id=str(category_id),
                owner=str(data.get("owner", "")).strip(),
                summary=str(data.get("summary", "")).strip(),
                implementation_patterns=tuple(str(x).strip() for x in impl if str(x).strip()),
                ignore_patterns=tuple(str(x).strip() for x in ignore if str(x).strip()) if isinstance(ignore, list) else (),
                required_alignment_hint=tuple(str(x).strip() for x in hint if str(x).strip()) if isinstance(hint, list) else (),
            )

    return surfaces, reserved


def _changed_surface_ids(changed_files: set[str], surfaces: dict[str, Surface]) -> dict[str, set[str]]:
    matched: dict[str, set[str]] = {}
    for surface_id, surface in surfaces.items():
        hits: set[str] = set()
        for path in changed_files:
            if any(_matches_pattern(path, pattern) for pattern in surface.ignore_patterns):
                continue
            if any(_matches_pattern(path, pattern) for pattern in surface.implementation_patterns):
                hits.add(path)
        if hits:
            matched[surface_id] = hits
    return matched


def _detect_unregistered_surfaces(
    *,
    changed_files: set[str],
    matched_surfaces: dict[str, set[str]],
    reserved_categories: dict[str, ReservedSurfaceCategory],
) -> list[str]:
    if not reserved_categories:
        return []

    errors: list[str] = []
    covered_paths = {path for paths in matched_surfaces.values() for path in paths}
    for path in sorted(changed_files - covered_paths):
        for category in reserved_categories.values():
            if not any(_matches_pattern(path, pattern) for pattern in category.implementation_patterns):
                continue
            if any(_matches_pattern(path, pattern) for pattern in category.ignore_patterns):
                continue
            hint = "; ".join(category.required_alignment_hint) if category.required_alignment_hint else "add a surface registry entry"
            errors.append(
                f"unregistered surface change: {path} matches reserved category {category.category_id}; {hint}"
            )
            break
    return errors


def _load_changed_files(
    *,
    repo_root: Path,
    base_ref: str | None,
    head_ref: str | None,
    files: list[str] | None,
) -> set[str]:
    if files is not None:
        return _normalize(files)

    if not base_ref or not head_ref:
        raise ValueError("either --files or both --base-ref/--head-ref are required")

    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return _normalize(result.stdout.splitlines())


def check_contract_sync(*, changed_files: set[str], surfaces: dict[str, Surface], reserved: dict[str, ReservedSurfaceCategory]) -> list[str]:
    errors: list[str] = []
    matched_surfaces = _changed_surface_ids(changed_files, surfaces)

    for surface_id, surface_hits in matched_surfaces.items():
        surface = surfaces[surface_id]
        missing: list[str] = []
        for pattern in surface.required_alignment_patterns:
            if any(_matches_pattern(path, pattern) for path in changed_files):
                continue
            missing.append(pattern)
        if missing:
            errors.append(
                f"surface '{surface_id}' changes ({len(surface_hits)} file(s)) require aligned updates matching: "
                + ", ".join(missing)
            )

    errors.extend(
        _detect_unregistered_surfaces(
            changed_files=changed_files,
            matched_surfaces=matched_surfaces,
            reserved_categories=reserved,
        )
    )
    return errors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure implementation changes keep contract/tests/traceability aligned (surface registry)."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--registry", default="harness/surface-registry.yaml")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument(
        "--files",
        nargs="*",
        help="Explicit changed file list for local checks and unit tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()

    try:
        changed_files = _load_changed_files(
            repo_root=repo_root,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            files=args.files,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"traceability-contract-sync: failed to determine changed files: {exc}")
        return 1

    try:
        surfaces, reserved = _load_registry(repo_root=repo_root, rel_path=str(args.registry))
    except (FileNotFoundError, ValueError) as exc:
        print(f"traceability-contract-sync: invalid surface registry: {exc}")
        return 1

    errors = check_contract_sync(changed_files=changed_files, surfaces=surfaces, reserved=reserved)
    if errors:
        print("traceability-contract-sync: failed")
        print("changed files:")
        for path in sorted(changed_files):
            print(f"- {path}")
        for error in errors:
            print(f"- {error}")
        return 1

    print("traceability-contract-sync: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

