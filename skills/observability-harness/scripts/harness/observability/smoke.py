from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from checks import (
    health_timeout_seconds,
    iter_selected_services,
    load_baseline,
    load_manifest,
    load_signals_cfg,
    observability_dir,
    smoke_artifacts_dir,
    smoke_signals_for_service,
)
from common import GenerationError


def _sanitize_service_id(service_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in service_id)


def _plan_runs(
    *,
    repo_root: Path,
    service_filter: str,
    artifacts_dir: str | None,
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    manifest = load_manifest(repo_root)
    baseline = load_baseline(repo_root)
    signals_cfg = load_signals_cfg(repo_root)
    smoke_script = repo_root / observability_dir(baseline) / "smoke_test.sh"
    if not smoke_script.exists():
        raise GenerationError(f"missing smoke script: {smoke_script.relative_to(repo_root)}")

    selected = iter_selected_services(manifest=manifest, service_filter=service_filter)
    plans: list[dict[str, Any]] = []
    skipped: list[str] = []
    artifacts_root = (
        artifacts_dir.strip().rstrip("/") if artifacts_dir else smoke_artifacts_dir(baseline)
    )
    timeout_seconds = health_timeout_seconds(baseline)
    for svc in selected:
        service_id = str(svc.get("id", "")).strip()
        health_url = str(svc.get("health_url", "")).strip()
        if not health_url:
            skipped.append(service_id)
            continue
        otel_service_name = str(svc.get("otel_service_name", "")).strip() or service_id
        smoke_errors, smoke_signals = smoke_signals_for_service(
            signals_cfg=signals_cfg,
            service_id=service_id,
        )
        if smoke_errors:
            raise GenerationError("; ".join(smoke_errors))
        report_file = None
        if artifacts_root:
            report_file = f"{artifacts_root}/{_sanitize_service_id(service_id)}.txt"
        plans.append(
            {
                "service": service_id,
                "health_url": health_url,
                "otel_service_name": otel_service_name,
                "compose_service": str(svc.get("compose_service", "")).strip(),
                "script": smoke_script.relative_to(repo_root).as_posix(),
                "command": ["bash", smoke_script.relative_to(repo_root).as_posix()],
                "report_file": report_file,
                "signals": smoke_signals,
                "health_timeout_seconds": timeout_seconds,
            }
        )

    if service_filter != "all" and not plans:
        raise GenerationError(f"service {service_filter} does not expose health_url for smoke")
    return plans, skipped, artifacts_root


def _serialize_payload(*, payload: dict[str, Any], output_format: str) -> str:
    if output_format == "yaml":
        return yaml.safe_dump(payload, sort_keys=True)
    return json.dumps(payload, indent=2, sort_keys=True)


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--service", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        plans, skipped, artifacts_root = _plan_runs(
            repo_root=repo_root,
            service_filter=str(args.service),
            artifacts_dir=str(args.artifacts_dir or ""),
        )
    except GenerationError as e:
        payload = {
            "ok": False,
            "errors": [str(e)],
            "planned_runs": [],
            "skipped_services": [],
            "artifacts_dir": None,
        }
        print(_serialize_payload(payload=payload, output_format=str(args.output_format)))
        return 2

    warnings: list[str] = []
    if not plans:
        warnings.append("no services with health_url found for observability smoke; treating smoke as no-op")

    results: list[dict[str, Any]] = []
    if not args.dry_run and plans:
        if artifacts_root:
            (repo_root / artifacts_root).mkdir(parents=True, exist_ok=True)
        for plan in plans:
            env = os.environ.copy()
            env["APP_HEALTH_URL"] = plan["health_url"]
            env["SERVICE_NAME"] = plan["otel_service_name"]
            env["SMOKE_HEALTH_TIMEOUT_SECONDS"] = str(plan["health_timeout_seconds"])
            env["SMOKE_METRIC_SIGNAL"] = str(plan["signals"]["metric"])
            env["SMOKE_LOG_SIGNAL"] = str(plan["signals"]["log"])
            env["SMOKE_TRACE_SIGNAL"] = str(plan["signals"]["trace"])
            if plan["report_file"]:
                env["SMOKE_REPORT_FILE"] = str((repo_root / plan["report_file"]).resolve())
            proc = subprocess.run(
                plan["command"],
                cwd=repo_root,
                env=env,
                text=True,
                check=False,
            )
            results.append(
                {
                    "service": plan["service"],
                    "returncode": proc.returncode,
                    "report_file": plan["report_file"],
                }
            )

    ok = args.dry_run or all(result["returncode"] == 0 for result in results)
    payload = {
        "ok": ok,
        "planned_runs": plans,
        "results": results,
        "skipped_services": skipped,
        "artifacts_dir": artifacts_root,
        "warnings": warnings,
    }
    print(_serialize_payload(payload=payload, output_format=str(args.output_format)))
    return 0 if ok else 1


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
