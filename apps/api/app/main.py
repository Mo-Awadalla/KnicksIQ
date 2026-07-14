"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.types import Event, Hint
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings = get_settings()
    logger = get_logger("knicksiq.api")
    configure_logging()
    logger.info(
        "knicksiq.api.starting",
        environment=settings.environment,
        test_mode=settings.test_mode,
    )

    if settings.seed_on_startup:
        raise RuntimeError(
            "SEED_ON_STARTUP is no longer supported; run migrations and load a release offline"
        )

    yield

    logger.info("knicksiq.api.stopping")
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.sentry_dsn:
        import sentry_sdk  # type: ignore[import-not-found]

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.05,
            send_default_pii=False,
            max_request_body_size="never",
            before_send=_scrub_sentry_event,
        )
    app = FastAPI(
        title="KnicksIQ API",
        description="KnicksIQ FastAPI backend — Knicks postgame intelligence platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    if settings.is_production:
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def production_headers(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.monotonic()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        elapsed_ms = (time.monotonic() - started) * 1000
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        latency_bucket = (
            "lt_100ms"
            if elapsed_ms < 100
            else "lt_1s"
            if elapsed_ms < 1000
            else "lt_4s"
            if elapsed_ms < 4000
            else "gte_4s"
        )
        feature = (
            "analyst"
            if request.url.path == "/analysis/query"
            else "archive"
            if request.url.path.startswith(("/archive", "/games", "/reports"))
            else "operational"
        )
        get_logger("knicksiq.aggregate").info(
            "aggregate.request",
            feature=feature,
            outcome="success" if response.status_code < 400 else "error",
            latency_bucket=latency_bucket,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "invalid_request", "message": "Request validation failed"},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        message = str(exc.detail) if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": f"http_{exc.status_code}", "message": message},
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        get_logger("knicksiq.api").exception(
            "knicksiq.api.unhandled",
            request_id=getattr(request.state, "request_id", None),
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Internal server error"},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    app.include_router(api_router)
    return app


def _scrub_sentry_event(event: Event, hint: Hint) -> Event:  # noqa: ARG001
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("headers", None)
        request.pop("cookies", None)
        request.pop("env", None)
    event.pop("user", None)
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            for breadcrumb in values:
                if isinstance(breadcrumb, dict):
                    breadcrumb.pop("data", None)
                    breadcrumb.pop("message", None)
    return event


app = create_app()
