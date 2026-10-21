"""HTTP and in-process behavior probes for the llm_primary preflight."""

from __future__ import annotations

import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from preflight.common import OVERALL_QUESTION, PRIMARY_QUESTION, Context, selected

REGULAR_SEASON = "regular"


async def fetch_team_record(ctx: Context, *, season_type: str | None) -> tuple[int, int]:
    """Count the active release's Knicks record for one phase, or every phase."""
    cached = ctx.db_record if season_type == REGULAR_SEASON else ctx.db_overall_record
    if cached is not None:
        return cached
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(ctx.settings.effective_db_url)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          count(*) FILTER (
                            WHERE (g.home_team_id = 'NYK' AND g.home_score > g.away_score)
                               OR (g.away_team_id = 'NYK' AND g.away_score > g.home_score)
                          ) AS wins,
                          count(*) FILTER (
                            WHERE (g.home_team_id = 'NYK' AND g.home_score < g.away_score)
                               OR (g.away_team_id = 'NYK' AND g.away_score < g.home_score)
                          ) AS losses
                        FROM games AS g
                        JOIN dataset_releases AS r
                          ON r.id = g.release_id
                         AND r.status = 'active'
                         AND r.validation_passed IS TRUE
                        WHERE (
                          CAST(:season_type AS text) IS NULL
                          OR g.season_type::text = :season_type
                        )
                        """
                    ),
                    {"season_type": season_type},
                )
            ).one()
        record = (int(row.wins), int(row.losses))
        if season_type == REGULAR_SEASON:
            ctx.db_record = record
        else:
            ctx.db_overall_record = record
        return record
    finally:
        await engine.dispose()


def claim_metrics(body: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for citation in body.get("citations") or []:
        metadata = citation.get("metadata") or {}
        claim = metadata.get("claim") or {}
        metric = claim.get("metric_id")
        if metric in {"wins", "losses"}:
            values[metric] = claim.get("value")
    return values


def answer_has_record(answer: str, wins: int, losses: int) -> bool:
    return str(wins) in answer and str(losses) in answer


def answer_states_phase(answer: str) -> bool:
    """A season-level answer must name the regular season it reports."""
    return bool(re.search(r"\bregular season\b", answer, re.IGNORECASE))


def record_matches(
    body: dict[str, Any], expected: tuple[int, int], season_type: str | None
) -> bool:
    answer = body.get("answer") or ""
    return (
        claim_metrics(body) == {"wins": expected[0], "losses": expected[1]}
        and answer_has_record(answer, *expected)
        and (season_type != REGULAR_SEASON or answer_states_phase(answer))
    )


async def post_question(client: Any, question: str) -> tuple[int, dict[str, Any], float]:
    started = time.monotonic()
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "season": "2025-26",
            "turn_id": "preflight-" + uuid.uuid4().hex,
            "expected_revision": 0,
        },
    )
    elapsed = (time.monotonic() - started) * 1000
    try:
        body = response.json() if response.status_code == 200 else {}
    except ValueError:
        body = {}
    return response.status_code, body, elapsed


async def check_target_live(ctx: Context, client: Any) -> None:
    response = await client.get("/health/live")
    body = response.json() if response.status_code == 200 else {}
    ok = response.status_code == 200 and body.get("status") == "ok"
    ctx.add(
        "target.live",
        ok,
        f"HTTP {response.status_code}, status {body.get('status')!r}",
        {"status_code": response.status_code},
    )


async def check_target_ready(ctx: Context, client: Any) -> None:
    response = await client.get("/health/ready")
    body = response.json() if response.content else {}
    failures = list(body.get("required_failures") or [])
    version = body.get("data_version")
    db_version = None
    if ctx.settings is not None:
        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(ctx.settings.effective_db_url)
            try:
                async with engine.connect() as connection:
                    row = (
                        await connection.execute(
                            text(
                                "SELECT version FROM dataset_releases "
                                "WHERE status = 'active' AND validation_passed IS TRUE"
                            )
                        )
                    ).first()
                    db_version = row.version if row else None
            finally:
                await engine.dispose()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"database probe failed: {type(exc).__name__}")
    ok = (
        response.status_code == 200
        and body.get("status") == "ready"
        and not failures
        and bool(version)
        and db_version is not None
        and version == db_version
    )
    ctx.add(
        "target.ready",
        ok,
        f"HTTP {response.status_code}, status {body.get('status')!r}, "
        f"data_version {version!r}, required_failures {failures}",
        {
            "status_code": response.status_code,
            "data_version": version,
            "db_active_version": db_version,
            "required_failures": failures,
            "optional_dependencies": body.get("optional_dependencies"),
        },
    )


async def check_target_cors(ctx: Context, client: Any) -> None:
    origin = ctx.settings.public_web_origin
    response = await client.options(
        "/analysis/query",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    allowed = response.headers.get("access-control-allow-origin")
    ok = response.status_code in {200, 204} and allowed == origin
    ctx.add(
        "target.cors",
        ok,
        f"HTTP {response.status_code}, allow-origin {allowed!r}, expected {origin!r}",
        {"status_code": response.status_code, "allow_origin": allowed, "expected": origin},
    )


async def check_target_trusted_host(ctx: Context, client: Any) -> None:
    response = await client.get("/health/live", headers={"Host": "untrusted.invalid"})
    ok = response.status_code == 400
    ctx.add(
        "target.trusted_host",
        ok,
        f"untrusted host returned HTTP {response.status_code}",
        {"status_code": response.status_code},
    )


async def check_kill_switch(ctx: Context, client: Any) -> None:
    regular = await fetch_team_record(ctx, season_type=REGULAR_SEASON)
    overall = await fetch_team_record(ctx, season_type=None)
    status, body, elapsed = await post_question(client, PRIMARY_QUESTION)
    overall_status, overall_body, overall_elapsed = await post_question(client, OVERALL_QUESTION)
    metrics = claim_metrics(body)
    overall_metrics = claim_metrics(overall_body)
    warnings = body.get("warnings") or []
    ok = (
        status == 200
        and overall_status == 200
        and body.get("llm_validated") is False
        and body.get("degraded") is True
        and bool(body.get("citations"))
        and record_matches(body, regular, REGULAR_SEASON)
        and not answer_has_record(body.get("answer") or "", *overall)
        and overall_body.get("llm_validated") is False
        and overall_body.get("degraded") is True
        and bool(overall_body.get("citations"))
        and record_matches(overall_body, overall, None)
        and any("Model or budget unavailable" in warning for warning in warnings)
    )
    ctx.add(
        "kill_switch",
        ok,
        "deterministic mode returned cited facts for both record scopes"
        if ok
        else "deterministic probe failed its phase, factual or mode assertions",
        {
            "status_code": status,
            "latency_ms": round(elapsed, 1),
            "llm_validated": body.get("llm_validated"),
            "degraded": body.get("degraded"),
            "citations": len(body.get("citations") or []),
            "warnings": warnings,
            "claim_metrics": metrics,
            "db_record": {"wins": regular[0], "losses": regular[1], "season_type": REGULAR_SEASON},
            "overall_status_code": overall_status,
            "overall_latency_ms": round(overall_elapsed, 1),
            "overall_claim_metrics": overall_metrics,
            "db_overall_record": {
                "wins": overall[0],
                "losses": overall[1],
                "season_type": "all phases",
            },
            "answer": body.get("answer"),
            "overall_answer": overall_body.get("answer"),
        },
    )


class _FailingAdapter:
    def __init__(self, attempts: list[float]) -> None:
        self.attempts = attempts
        self.max_tokens = 500
        self.timeout_seconds = 20.0
        self.response_schema: dict[str, Any] | None = None
        self.last_metadata: dict[str, Any] = {}

    async def generate(self, *, system: str, user: str) -> str:  # noqa: ARG002
        self.attempts.append(time.monotonic())
        raise RuntimeError("injected provider failure")


async def check_provider_failure(ctx: Context, client: Any) -> None:
    from app.services import analyst_provider

    regular = await fetch_team_record(ctx, season_type=REGULAR_SEASON)
    overall = await fetch_team_record(ctx, season_type=None)
    attempts: list[float] = []
    original = analyst_provider.get_llm_adapter
    analyst_provider.get_llm_adapter = lambda **kwargs: _FailingAdapter(attempts)
    try:
        status, body, elapsed = await post_question(client, PRIMARY_QUESTION)
        overall_status, overall_body, overall_elapsed = await post_question(
            client, OVERALL_QUESTION
        )
    finally:
        analyst_provider.get_llm_adapter = original
    metrics = claim_metrics(body)
    overall_metrics = claim_metrics(overall_body)
    warnings = body.get("warnings") or []
    ok = (
        status == 200
        and overall_status == 200
        and len(attempts) >= 2
        and body.get("llm_validated") is False
        and bool(body.get("citations"))
        and record_matches(body, regular, REGULAR_SEASON)
        and not answer_has_record(body.get("answer") or "", *overall)
        and overall_body.get("llm_validated") is False
        and bool(overall_body.get("citations"))
        and record_matches(overall_body, overall, None)
        and bool(warnings)
    )
    ctx.add(
        "provider_failure",
        ok,
        "provider exception degraded to cited facts for both record scopes"
        if ok
        else "provider failure probe failed its phase, factual or degradation assertions",
        {
            "status_code": status,
            "latency_ms": round(elapsed, 1),
            "provider_attempts": len(attempts),
            "llm_validated": body.get("llm_validated"),
            "citations": len(body.get("citations") or []),
            "warnings": warnings,
            "claim_metrics": metrics,
            "db_record": {"wins": regular[0], "losses": regular[1], "season_type": REGULAR_SEASON},
            "overall_status_code": overall_status,
            "overall_latency_ms": round(overall_elapsed, 1),
            "overall_claim_metrics": overall_metrics,
            "db_overall_record": {
                "wins": overall[0],
                "losses": overall[1],
                "season_type": "all phases",
            },
            "answer": body.get("answer"),
            "overall_answer": overall_body.get("answer"),
        },
    )


@asynccontextmanager
async def in_process_client(ctx: Context, mode: str | None):
    import os

    from app.core.config import get_settings
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    previous = os.environ.get("ANALYSIS_ANSWER_MODE")
    if mode is not None:
        os.environ["ANALYSIS_ANSWER_MODE"] = mode
    get_settings.cache_clear()
    app = create_app()
    base_url = f"https://{ctx.args.api_host}"
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url=base_url, timeout=60.0) as client:
                yield client
    finally:
        if mode is not None:
            if previous is None:
                os.environ.pop("ANALYSIS_ANSWER_MODE", None)
            else:
                os.environ["ANALYSIS_ANSWER_MODE"] = previous
        get_settings.cache_clear()


@asynccontextmanager
async def remote_client(ctx: Context):
    import httpx

    async with httpx.AsyncClient(base_url=ctx.args.base_url, timeout=60.0) as client:
        yield client


async def guarded(ctx: Context, check_id: str, fn) -> None:
    if not selected(ctx, check_id):
        return
    try:
        await fn()
    except Exception as exc:  # noqa: BLE001 - a probe crash is a failed check, never a traceback
        ctx.add(check_id, False, f"probe crashed: {type(exc).__name__}", {})


async def run_target_checks(ctx: Context, client: Any, *, in_process: bool) -> None:
    await guarded(ctx, "target.live", lambda: check_target_live(ctx, client))
    await guarded(ctx, "target.ready", lambda: check_target_ready(ctx, client))
    await guarded(ctx, "target.cors", lambda: check_target_cors(ctx, client))
    await guarded(ctx, "target.trusted_host", lambda: check_target_trusted_host(ctx, client))
    if in_process:
        await guarded(ctx, "provider_failure", lambda: check_provider_failure(ctx, client))
    elif selected(ctx, "provider_failure"):
        ctx.skip(
            "provider_failure",
            "remote target cannot inject a provider failure; run the in-process preflight",
        )


async def run_kill_switch(ctx: Context) -> None:
    if not selected(ctx, "kill_switch"):
        return
    if ctx.args.base_url:
        ctx.skip(
            "kill_switch",
            "remote target cannot be restarted in deterministic mode by this script",
        )
        return
    try:
        async with in_process_client(ctx, "deterministic") as client:
            await check_kill_switch(ctx, client)
    except Exception as exc:  # noqa: BLE001
        ctx.add("kill_switch", False, f"probe crashed: {type(exc).__name__}", {})
