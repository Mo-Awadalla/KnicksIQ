"""Configuration checks for the llm_primary preflight. Secrets are never reported."""

from __future__ import annotations

import re
from typing import Any

from preflight.common import Context, env_value

REQUIRED_ENV = (
    "DB_URL",
    "REDIS_URL",
    "ENVIRONMENT",
    "REQUIRE_ACTIVE_RELEASE",
    "IP_HASH_SECRET",
    "AI_PROVIDER",
    "AI_BASE_URL",
    "AI_API_KEY",
    "AI_CHAT_MODEL",
    "AI_REQUEST_TIMEOUT_SECONDS",
    "OPENROUTER_ALLOWED_MODELS",
    "OPENROUTER_MONTHLY_CUTOFF_USD",
    "ANALYSIS_ANSWER_MODE",
    "ANALYST_EVIDENCE_LOOP_ENABLED",
    "ANALYSIS_SHADOW_SAMPLE_RATE",
    "CORS_ORIGINS",
    "PUBLIC_WEB_ORIGIN",
    "TRUSTED_HOSTS",
    "SENTRY_DSN",
)
SENTRY_DSN = re.compile(r"^https://[^@\s/]+@[^/\s]+/\d+$")


def check_required_env(ctx: Context) -> None:
    missing = [name for name in REQUIRED_ENV if not env_value(name)]
    ctx.add(
        "env.required",
        not missing,
        "all required variables are present"
        if not missing
        else "missing or blank variables: " + ", ".join(missing),
        {"required": list(REQUIRED_ENV), "missing": missing},
    )


def check_settings(ctx: Context) -> None:
    from app.core.config import Settings

    try:
        ctx.settings = Settings()
    except Exception as exc:  # noqa: BLE001 - pydantic error shape is not stable enough
        locations = []
        for item in getattr(exc, "errors", lambda: [])():
            location = ".".join(str(part) for part in item.get("loc", ()))
            locations.append(f"{location}: {item.get('msg', 'invalid')}")
        ctx.settings_error = "; ".join(locations) or type(exc).__name__
        ctx.add("env.parse", False, "settings rejected: " + ctx.settings_error, {})
        return
    ctx.add("env.parse", True, "settings parsed", {})


def check_mode(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.mode", False, "settings unavailable", {})
        return
    actual = ctx.settings.analysis_answer_mode
    expected = ctx.args.expected_mode
    ctx.add(
        "env.mode",
        actual == expected,
        f"configured {actual}, expected {expected}",
        {"configured": actual, "expected": expected},
    )


def check_evidence_loop(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.evidence_loop", False, "settings unavailable", {})
        return
    enabled = bool(ctx.settings.analyst_evidence_loop_enabled)
    ctx.add(
        "env.evidence_loop",
        enabled,
        "evidence loop enabled" if enabled else "evidence loop is disabled",
        {"enabled": enabled},
    )


# Provider name to the host its base URL must point at.
KNOWN_PROVIDERS = {"openrouter": "openrouter.ai", "opencode-go": "opencode.ai/inference/go"}


def check_provider(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.provider", False, "settings unavailable", {})
        return
    settings = ctx.settings
    problems = []
    if settings.ai_provider.lower() not in KNOWN_PROVIDERS:
        problems.append(f"AI_PROVIDER is not one of {sorted(KNOWN_PROVIDERS)}")
    elif KNOWN_PROVIDERS[settings.ai_provider.lower()] not in settings.ai_base_url:
        problems.append("AI_BASE_URL does not match AI_PROVIDER")
    if not settings.ai_base_url.startswith("https://"):
        problems.append("AI_BASE_URL is not HTTPS")
    if not settings.ai_chat_model.strip():
        problems.append("AI_CHAT_MODEL is blank")
    if not settings.ai_api_key:
        problems.append("AI_API_KEY is absent")
    ctx.add(
        "env.provider",
        not problems,
        "; ".join(problems) or f"{settings.ai_provider} provider configured with a key",
        {
            "provider": settings.ai_provider,
            "base_url_host": settings.ai_base_url.split("/")[2]
            if "://" in settings.ai_base_url
            else "",
            "chat_model": settings.ai_chat_model,
            "api_key_present": bool(settings.ai_api_key),
        },
    )


def check_allowlist(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.allowlist", False, "settings unavailable", {})
        return
    settings = ctx.settings
    allowed = settings.openrouter_allowed_models
    problems = []
    if not allowed:
        problems.append("allowlist is empty")
    if any(not item.strip() for item in allowed):
        problems.append("allowlist contains a blank entry")
    if "*" in allowed:
        problems.append("allowlist contains a wildcard")
    if len(set(allowed)) != len(allowed):
        problems.append("allowlist contains duplicates")
    if settings.ai_chat_model not in allowed:
        problems.append("chat model is not allowlisted")
    summary_model = (settings.openrouter_summary_model or "").strip()
    if summary_model and summary_model not in allowed:
        problems.append("summary model is not allowlisted")
    review_model = (settings.analyst_review_model or "").strip()
    if review_model and review_model not in allowed:
        problems.append("review model is not allowlisted")
    ctx.add(
        "env.allowlist",
        not problems,
        "; ".join(problems) or "chat, summary and review models are allowlisted",
        {
            "allowed_models": allowed,
            "chat_model": settings.ai_chat_model,
            "review_model": review_model or settings.ai_chat_model,
        },
    )


def check_timeouts(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.timeouts", False, "settings unavailable", {})
        return
    settings = ctx.settings
    request = float(settings.ai_request_timeout_seconds)
    deadline = float(settings.analyst_deadline_seconds)
    problems = []
    if request <= 0:
        problems.append("AI_REQUEST_TIMEOUT_SECONDS must be positive")
    if deadline <= 0 or deadline > 30:
        problems.append("analyst deadline must be in (0, 30]")
    if request > deadline:
        problems.append("request timeout exceeds the analyst deadline")
    ctx.add(
        "env.timeouts",
        not problems,
        "; ".join(problems) or f"request timeout {request:g}s within deadline {deadline:g}s",
        {"request_timeout_seconds": request, "analyst_deadline_seconds": deadline},
    )


def check_cutoff(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.cutoff", False, "settings unavailable", {})
        return
    cutoff = float(ctx.settings.openrouter_monthly_cutoff_usd)
    expected = float(ctx.args.expected_cutoff)
    problems = []
    if cutoff <= 0:
        problems.append("cutoff must be positive")
    if abs(cutoff - expected) > 1e-9:
        problems.append(f"configured {cutoff:g}, expected {expected:g}")
    ctx.add(
        "env.cutoff",
        not problems,
        "; ".join(problems) or f"monthly cutoff {cutoff:g} USD",
        {"cutoff_usd": cutoff, "expected_usd": expected},
    )


def check_shadow_rate(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.shadow_rate", False, "settings unavailable", {})
        return
    rate = float(ctx.settings.analysis_shadow_sample_rate)
    problems = []
    if not 0.0 <= rate <= 1.0:
        problems.append("rate must be in 0..1")
    if ctx.settings.analysis_answer_mode == "shadow" and rate <= 0:
        problems.append("shadow mode with a zero sample rate")
    ctx.add(
        "env.shadow_rate",
        not problems,
        "; ".join(problems) or f"sample rate {rate:g}",
        {"rate": rate, "mode": ctx.settings.analysis_answer_mode},
    )


def check_cors(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.cors", False, "settings unavailable", {})
        return
    settings = ctx.settings
    origins = list(settings.cors_origins)
    problems = []
    if not origins:
        problems.append("no origins")
    if "*" in origins:
        problems.append("wildcard origin")
    if any(origin.endswith("/") for origin in origins):
        problems.append("origin has a trailing slash")
    if any(not origin.startswith("https://") for origin in origins):
        problems.append("non-HTTPS origin")
    if settings.public_web_origin not in origins:
        problems.append("PUBLIC_WEB_ORIGIN is not in CORS_ORIGINS")
    if settings.public_web_origin.endswith("/"):
        problems.append("PUBLIC_WEB_ORIGIN has a trailing slash")
    ctx.add(
        "env.cors",
        not problems,
        "; ".join(problems) or "public origin is the only configured origin",
        {"origins": origins, "public_web_origin": settings.public_web_origin},
    )


def check_trusted_hosts(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.trusted_hosts", False, "settings unavailable", {})
        return
    settings = ctx.settings
    hosts = list(settings.trusted_hosts)
    problems = []
    if not hosts:
        problems.append("no trusted hosts")
    if "*" in hosts:
        problems.append("wildcard trusted host")
    if any("://" in host or "/" in host for host in hosts):
        problems.append("trusted host contains a scheme or path")
    if ctx.args.api_host not in hosts:
        problems.append(f"{ctx.args.api_host} is not trusted")
    ctx.add(
        "env.trusted_hosts",
        not problems,
        "; ".join(problems) or f"{ctx.args.api_host} is trusted",
        {"trusted_hosts": hosts, "api_host": ctx.args.api_host},
    )


def check_sentry(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.sentry", False, "settings unavailable", {})
        return
    dsn = ctx.settings.sentry_dsn or ""
    ok = bool(SENTRY_DSN.match(dsn))
    ctx.add(
        "env.sentry",
        ok,
        "DSN is present and format-valid"
        if ok
        else "SENTRY_DSN is absent or not a valid HTTPS DSN",
        {"present": bool(dsn), "format_valid": ok},
    )


def check_ip_hash(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.ip_hash_secret", False, "settings unavailable", {})
        return
    secret = ctx.settings.ip_hash_secret or ""
    problems = []
    if secret == "development-only-change-me":
        problems.append("development default")
    if len(secret) < 32:
        problems.append("shorter than 32 characters")
    ctx.add(
        "env.ip_hash_secret",
        not problems,
        "; ".join(problems) or "non-default secret of sufficient length",
        {"length": len(secret), "is_default": secret == "development-only-change-me"},
    )


def check_environment(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.environment", False, "settings unavailable", {})
        return
    production = ctx.settings.is_production
    ctx.add(
        "env.environment",
        production,
        "production environment" if production else "not a production environment",
        {"environment": ctx.settings.environment},
    )


def check_require_release(ctx: Context) -> None:
    if ctx.settings is None:
        ctx.add("env.require_release", False, "settings unavailable", {})
        return
    required = bool(ctx.settings.require_active_release)
    ctx.add(
        "env.require_release",
        required,
        "active release required" if required else "active release is not required",
        {"require_active_release": required},
    )


ENV_CHECKS: tuple[tuple[str, Any], ...] = (
    ("env.mode", check_mode),
    ("env.evidence_loop", check_evidence_loop),
    ("env.provider", check_provider),
    ("env.allowlist", check_allowlist),
    ("env.timeouts", check_timeouts),
    ("env.cutoff", check_cutoff),
    ("env.shadow_rate", check_shadow_rate),
    ("env.cors", check_cors),
    ("env.trusted_hosts", check_trusted_hosts),
    ("env.sentry", check_sentry),
    ("env.ip_hash_secret", check_ip_hash),
    ("env.environment", check_environment),
    ("env.require_release", check_require_release),
)
