#!/usr/bin/env python3

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "skills"
SOURCE_DIRS = ("harness", "scripts/harness")
REFERENCE_FILES = (
    ("harness/CONTRACT.md", "references/contract.md"),
    ("harness/VERSIONING.md", "references/versioning.md"),
    ("harness/LANGUAGE-SUPPORT.md", "references/language-support.md"),
)
SKILLS = ("docs-harness", "traceability-harness", "observability-harness")


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def export() -> None:
    for skill_name in SKILLS:
        skill_root = SKILLS_ROOT / skill_name
        for rel in SOURCE_DIRS:
            source = ROOT / rel
            target = skill_root / rel
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

        references_dir = skill_root / "references"
        _reset_dir(references_dir)
        for source_rel, target_rel in REFERENCE_FILES:
            source = ROOT / source_rel
            target = skill_root / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


if __name__ == "__main__":
    export()
