from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceProfile:
    name: str
    requires_openapi: bool
    traceability_enabled: bool
    docs_enabled: bool = True
    http_smoke_enabled: bool = False
    notes: str = ""


BUILTIN_PROFILES: dict[str, ServiceProfile] = {
    "fastapi": ServiceProfile(
        name="fastapi",
        requires_openapi=True,
        traceability_enabled=True,
        http_smoke_enabled=True,
        notes="HTTP/OpenAPI and smoke checks are enabled by default.",
    ),
    "worker": ServiceProfile(
        name="worker",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="Worker services participate in docs and observability, but HTTP/OpenAPI checks stay opt-in.",
    ),
    "service": ServiceProfile(
        name="service",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="Generic service profile keeps non-HTTP services in the harness without forcing protocol-specific checks.",
    ),
    "typescript": ServiceProfile(
        name="typescript",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="TypeScript services start with docs-only support in v1; contract and smoke checks are opt-in.",
    ),
    "javascript": ServiceProfile(
        name="javascript",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="JavaScript services start with docs-only support in v1; contract and smoke checks are opt-in.",
    ),
    "go": ServiceProfile(
        name="go",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="Go services start with docs-only support in v1; contract and smoke checks are opt-in.",
    ),
    "rust": ServiceProfile(
        name="rust",
        requires_openapi=False,
        traceability_enabled=False,
        http_smoke_enabled=False,
        notes="Rust services start with docs-only support in v1; contract and smoke checks are opt-in.",
    ),
}


def resolve_profile(kind: str) -> tuple[ServiceProfile, str | None]:
    normalized = str(kind or "").strip().lower() or "service"
    profile = BUILTIN_PROFILES.get(normalized)
    if profile is not None:
        return profile, None
    fallback = BUILTIN_PROFILES["service"]
    return (
        fallback,
        f"unknown service kind '{normalized}' uses generic '{fallback.name}' profile; "
        "HTTP/OpenAPI enforcement is disabled by default",
    )


def profile_for_service(service: dict[str, Any]) -> tuple[ServiceProfile, str | None]:
    return resolve_profile(str(service.get("kind", "")))


def should_validate_openapi(service: dict[str, Any]) -> bool:
    profile, _ = profile_for_service(service)
    if profile.requires_openapi:
        return True
    return bool(str(service.get("openapi", "")).strip())


def should_plan_http_smoke(service: dict[str, Any]) -> bool:
    profile, _ = profile_for_service(service)
    health_url = str(service.get("health_url", "")).strip()
    if not health_url:
        return False
    if profile.http_smoke_enabled:
        return True
    return True


def profile_summary(service: dict[str, Any]) -> dict[str, Any]:
    profile, warning = profile_for_service(service)
    summary = asdict(profile)
    summary["kind"] = str(service.get("kind", "")).strip() or profile.name
    summary["service"] = str(service.get("id", "")).strip()
    if warning:
        summary["warning"] = warning
    return summary
