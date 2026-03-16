from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import extract_repo_doc_refs, repo_relative


DEFAULT_HISTORICAL_GLOBS = (
    "docs/archive/**/*.md",
    "docs/plans/completed/**/*.md",
)

DEFAULT_HISTORICAL_CONTEXT_KEYWORDS = (
    "histor",
    "history",
    "completed",
    "archive",
    "superseded",
)

DEFAULT_ASSET_REFERENCE_GLOBS = (
    "victoriametrics/**/*.yaml",
    "victoriametrics/**/*.yml",
    "victoriametrics/**/*.json",
)

PATH_MENTION_PATTERN = re.compile(
    r"(README\\.md|ARCHITECTURE\\.md|(?:docs|specs|victoriametrics)/[A-Za-z0-9_./-]+\\.[A-Za-z0-9_.-]+)"
)

@dataclass(frozen=True)
class AssetReference:
    source_path: str
    target_path: str


@dataclass(frozen=True)
class HistoricalReferenceIssue:
    source_path: str
    target_path: str
    line: str


@dataclass(frozen=True)
class DocGardenAnalysis:
    compatibility_redirects: list[str]
    stale_asset_references: list[AssetReference]
    historical_reference_issues: list[HistoricalReferenceIssue]


def _doc_garden_cfg(docs_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = docs_cfg.get("doc_garden") or {}
    return raw if isinstance(raw, dict) else {}


def _historical_globs(docs_cfg: dict[str, Any]) -> tuple[str, ...]:
    cfg = _doc_garden_cfg(docs_cfg)
    globs = cfg.get("historical_globs")
    if isinstance(globs, list) and all(isinstance(x, str) for x in globs):
        return tuple(str(x) for x in globs)
    return DEFAULT_HISTORICAL_GLOBS


def _historical_keywords(docs_cfg: dict[str, Any]) -> tuple[str, ...]:
    cfg = _doc_garden_cfg(docs_cfg)
    kw = cfg.get("historical_context_keywords")
    if isinstance(kw, list) and all(isinstance(x, str) for x in kw):
        return tuple(str(x) for x in kw)
    return DEFAULT_HISTORICAL_CONTEXT_KEYWORDS


def _asset_reference_globs(docs_cfg: dict[str, Any]) -> tuple[str, ...]:
    cfg = _doc_garden_cfg(docs_cfg)
    globs = cfg.get("asset_reference_globs")
    if isinstance(globs, list) and all(isinstance(x, str) for x in globs):
        return tuple(str(x) for x in globs)
    return DEFAULT_ASSET_REFERENCE_GLOBS


def iter_historical_docs(repo_root: Path, docs_cfg: dict[str, Any]) -> set[str]:
    historical: set[str] = set()
    for pattern in _historical_globs(docs_cfg):
        for path in repo_root.glob(pattern):
            if path.is_file():
                historical.add(repo_relative(repo_root, path))
    return historical


def find_compatibility_redirects(repo_root: Path) -> list[str]:
    redirects: list[str] = []
    for path in repo_root.glob("docs/**/*.md"):
        rel_path = repo_relative(repo_root, path)
        if rel_path.startswith("docs/generated/"):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        first_lines = "\n".join(content.splitlines()[:10])
        if re.search(r"^Compatibility redirect\\b", first_lines, re.MULTILINE):
            redirects.append(rel_path)
    return sorted(redirects)


def find_stale_asset_references(repo_root: Path, docs_cfg: dict[str, Any]) -> list[AssetReference]:
    stale: list[AssetReference] = []
    seen: set[tuple[str, str]] = set()
    for pattern in _asset_reference_globs(docs_cfg):
        for path in sorted(repo_root.glob(pattern)):
            if not path.is_file():
                continue
            rel_path = repo_relative(repo_root, path)
            matches = PATH_MENTION_PATTERN.findall(path.read_text(errors="ignore"))
            for target_path in sorted(set(matches)):
                if (repo_root / target_path).exists():
                    continue
                key = (rel_path, target_path)
                if key in seen:
                    continue
                seen.add(key)
                stale.append(AssetReference(rel_path, target_path))
    return stale


def find_historical_reference_issues(
    repo_root: Path,
    *,
    docs_cfg: dict[str, Any],
    active_docs: set[str],
) -> list[HistoricalReferenceIssue]:
    issues: list[HistoricalReferenceIssue] = []
    historical_docs = iter_historical_docs(repo_root, docs_cfg)
    keywords = tuple(k.lower() for k in _historical_keywords(docs_cfg))

    for rel_path in sorted(active_docs):
        path = repo_root / rel_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            for target in extract_repo_doc_refs(line):
                if target not in historical_docs:
                    continue
                line_lower = line.lower()
                if any(k in line_lower for k in keywords):
                    continue
                issues.append(HistoricalReferenceIssue(rel_path, target, line.strip()))
    return issues


def analyze_doc_garden(
    repo_root: Path,
    *,
    docs_cfg: dict[str, Any],
    active_docs: set[str],
) -> DocGardenAnalysis:
    return DocGardenAnalysis(
        compatibility_redirects=find_compatibility_redirects(repo_root),
        stale_asset_references=find_stale_asset_references(repo_root, docs_cfg),
        historical_reference_issues=find_historical_reference_issues(
            repo_root, docs_cfg=docs_cfg, active_docs=active_docs
        ),
    )
