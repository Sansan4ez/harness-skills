from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from checks import (
    app_compose_files,
    health_timeout_seconds,
    load_baseline,
    pull_request_label,
    smoke_artifacts_dir,
    stack_compose_file,
)


def workflow_context(*, repo_root: Path) -> dict[str, object]:
    baseline = load_baseline(repo_root)
    stack_file = stack_compose_file(baseline)
    app_files = app_compose_files(baseline)
    return {
        "pr_label": pull_request_label(baseline),
        "health_timeout_seconds": health_timeout_seconds(baseline),
        "stack_compose_file": stack_file,
        "stack_compose_args": f"-f {shlex.quote(stack_file)}",
        "app_compose_files": app_files,
        "app_compose_args": " ".join(f"-f {shlex.quote(path)}" for path in app_files),
        "artifacts_dir": smoke_artifacts_dir(baseline),
        "required_on": list((baseline.get("smoke") or {}).get("required_on") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--github-output")
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    payload = workflow_context(repo_root=repo_root)

    if args.github_output:
        lines = [
            f"pr_label={payload['pr_label']}",
            f"health_timeout_seconds={payload['health_timeout_seconds']}",
            f"stack_compose_file={payload['stack_compose_file']}",
            f"stack_compose_args={payload['stack_compose_args']}",
            f"app_compose_args={payload['app_compose_args']}",
            f"artifacts_dir={payload['artifacts_dir']}",
            "required_on=" + json.dumps(payload["required_on"]),
        ]
        Path(args.github_output).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
