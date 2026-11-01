"""Capture real hybrid archive-tool retrieval without model wording."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.evaluation.narrative_benchmark import (
    PROFILE_SETTINGS,
    NarrativeBenchmark,
    NarrativeError,
    digest,
    implementation_sha256,
)
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services.analyst_tools import AnalystTools
from app.services.embeddings import embedding_profile
from app.services.evidence_contracts import ToolCall
from app.services.query_resolution import ResolvedQuery
from app.services.release_bundle import canonical_json

SCHEMA = "narrative-retrieval-observations-v1"


def _loopback(value: str) -> bool:
    host = urlsplit(value).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def _verify_profile(benchmark: NarrativeBenchmark) -> None:
    settings = get_settings()
    if settings.ai_provider.lower() not in {"none", "mock", "disabled"}:
        raise NarrativeError("Narrative tool collection must disable model providers")
    if settings.ai_api_key or settings.sentry_dsn:
        raise NarrativeError("Narrative collection must not inherit live credentials")
    if not _loopback(str(settings.db_url)):
        raise NarrativeError("Narrative collection requires an owned loopback database")
    if not settings.qdrant_url or not _loopback(settings.qdrant_url):
        raise NarrativeError("Narrative collection requires owned loopback Qdrant")
    current = {name: getattr(settings, name) for name in PROFILE_SETTINGS}
    if current != benchmark.profile["settings"]:
        raise NarrativeError("Current retrieval settings differ from frozen profile")
    if embedding_profile() != benchmark.profile["query_embedding"]:
        raise NarrativeError("Current embedding weights differ from frozen profile")
    if benchmark.profile.get("implementation_sha256") != implementation_sha256():
        raise NarrativeError("Current retrieval implementation differs from the frozen profile")


def _write(stream: Any, value: dict[str, Any]) -> bytes:
    raw = canonical_json(value) + b"\n"
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
    return raw


async def collect_narrative(
    benchmark: NarrativeBenchmark,
    db: AsyncSession,
    output: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    _verify_profile(benchmark)
    run_id = run_id or uuid.uuid4().hex
    if not run_id or any(character.isspace() for character in run_id):
        raise NarrativeError("Invalid narrative run identity")

    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.version == benchmark.version,
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
        )
    ).scalar_one()
    output.parent.mkdir(parents=True, exist_ok=True)
    rolling = hashlib.sha256()
    records = 0

    with output.open("xb") as stream:
        _write(
            stream,
            {
                "kind": "manifest",
                "schema": SCHEMA,
                "run_id": run_id,
                "identity_sha256": benchmark.identity_sha256,
                "identity": benchmark.identity,
                "case_ids": [case.id for case in benchmark.cases],
                "paid_wording_requests": 0,
            },
        )
        for case in benchmark.cases:
            request_id = f"narrative-{run_id}-{case.id}"
            request = case.request(request_id)
            try:
                game = (
                    await db.execute(
                        select(Game).where(
                            Game.release_id == release.id,
                            Game.season == case.season,
                            Game.game_date == date.fromisoformat(case.game_date),
                            Game.home_team_id.in_(["NYK", case.opponent_id]),
                            Game.away_team_id.in_(["NYK", case.opponent_id]),
                        )
                    )
                ).scalar_one()
                if game.id != case.game_id or game.nba_game_id != case.nba_game_id:
                    raise NarrativeError("Live SQL game differs from pinned source")
                scope = ResolvedQuery(
                    intent="search_archive",
                    team_ids=["NYK", case.opponent_id],
                    opponent_id=case.opponent_id,
                    game_ids=[game.id],
                    date_start=game.game_date,
                    date_end=game.game_date,
                    periods=[case.period],
                    data_version=release.version,
                )
                call = ToolCall(name="search_archive", question=case.question)
                tools = AnalystTools(db, release, case.question, case.season, {})
                tools.request_id = request_id
                result = await tools.search(call, scope, [game])
                if len(tools.retrieval_traces) != 1:
                    raise NarrativeError("Tool did not emit exactly one retrieval trace")
                observed = {
                    "status": result.status,
                    "trace": tools.retrieval_traces[0],
                    "evidence": [
                        {
                            "evidence_id": item.evidence_id,
                            "document_id": item.metadata.get("document_id"),
                            "point_id": item.metadata.get("point_id"),
                            "payload_sha256": item.metadata.get("payload_sha256"),
                            "game_id": item.game_id,
                        }
                        for item in result.evidence
                    ],
                }
            except Exception as exc:
                observed = {
                    "status": "dependency_failure",
                    "error_type": type(exc).__name__,
                    "trace": None,
                    "evidence": [],
                }
            record = {
                "kind": "case",
                "schema": SCHEMA,
                "identity_sha256": benchmark.identity_sha256,
                "input": request,
                "input_sha256": digest(request),
                "output": observed,
                "output_sha256": digest(observed),
            }
            rolling.update(_write(stream, record))
            records += 1
        _write(
            stream,
            {
                "kind": "complete",
                "schema": SCHEMA,
                "run_id": run_id,
                "identity_sha256": benchmark.identity_sha256,
                "records": records,
                "records_sha256": rolling.hexdigest(),
            },
        )
    return {
        "schema": SCHEMA,
        "identity_sha256": benchmark.identity_sha256,
        "cases_recorded": records,
        "observations_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "paid_wording_requests": 0,
    }
