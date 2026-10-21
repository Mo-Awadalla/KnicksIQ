"""Private, fail-closed admission and counted collection for the frozen 120-case evaluation.

Admission is read-only and sends no completions. Every run uses one private,
durable goal; failed or partial runs cannot resume. Before each provider request
the collector revalidates its environment, monthly ledger, and conservative
endpoint-wide price snapshot. Captured observations still require independent
semantic and release gates.


"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.config import get_settings
from app.evaluation.release_runner import collect, digest, file_hash, load_contract
from app.evaluation.verification_adapter import MODEL, CountedRun
from app.evaluation.verification_budget import (
    SPENDING_DIRECTION_SHA256,
    VerificationBudget,
    current_ticket,
)
from app.services import analyst_budget
from app.services.release_evidence import evaluation_request_id

VERSION = "2025-26.20260928.1"
REVISION = "rev-20261020b"
BUNDLE_SHA256: str = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
DESIGNATED_KEY_SHA256 = "35d6d0521b6191980c586c6a7bb0b80721432ad53a68f6100f3d39e548029e8a"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MONTHLY_CUTOFF = Decimal("2")
MINIMUM_PROVIDER_MONTHLY_NUSD = 1_367_010_808
GOLD = "docs/release-evidence/evaluation-contract-20261021/expectations.json"
APPROVAL = "docs/release-evidence/evaluation-contract-20261021/evaluation-approval.json"
GOAL_ANCHOR = "guarded-original120-goal.json"
CONTRACT_SHA256 = "8da8be9d68a7111919d1e8d0d18d22da8bf8d3a7da34a7fe4688117cc37119f9"
FROZEN = {
    GOLD: CONTRACT_SHA256,
    APPROVAL: "8c4877d50b1aff3a58a52df720c0df3a63f415e6b161e7c28b7fc8b03ab5a289",
}
IDENTITY_FILES = {
    "manifest.json": "34e6ba6d8e8dcb57f124b800dac97431dcf3cb084bc9a8556efacc6ee5c8bc76",
    "qdrant_payloads.jsonl": "2331f5ef4f89cf37d029db923e9679e5dc74e3e04e1f1ad904adab381ab7de4d",
    "possession_chunks.jsonl": "4d125a4f0515ee19cccc534b35c37b91afd79dc72cdb4beb0798a6146271a00b",
    "archive_units.jsonl": "ad23f0cf90f21c0b94bba8e36e815d03a05afe60c224fc616b210b618a3051fd",
    "games_table.json": "7d5762d9d2a79616913cdb09784fff7f240db8954d196a9297acb935c443a7ab",
}
SERVING_CODE_SHA256 = {
    "app/services/rag_index.py": (
        "5482577b76fbec7491a6908eac0b30d0463d251caf025914050f58499efcb1b1"
    ),
    "app/services/qdrant_client.py": (
        "46f0cf3a5b6ba21e72a01fb09acd1b66041e8a37992b9df2ba0330e434bc53ba"
    ),
    "app/services/archive_units.py": (
        "399326fc83491ff03cd461ba2f5de902dd1f975c1f31fff1cf27c2fb39599f10"
    ),
    "app/services/possession_chunks.py": (
        "066462a902ae7ace846e33caae809fef7118f82144ddb66ec4c4540ee86bd4a8"
    ),
}
ROUTING_POLICY: dict[str, str | bool] = {
    "allow_fallbacks": True,
    "sort": "latency",
    "require_parameters": True,
}
COLLECTIONS = {
    base: base + "__2025_26_20260928_1__rev_20261020b"
    for base in ("knicks_possessions", "knicks_games", "knicks_box_scores", "knicks_reports")
}
IDENTITY_COUNTS = {
    "knicks_possessions": 15864,
    "knicks_games": 130,
    "knicks_box_scores": 2970,
    "knicks_reports": 101,
}
PLANNER_MAX_CALLS_PER_TURN = 3
_turn: ContextVar[dict | None] = ContextVar("guarded_release_turn", default=None)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def money(value: Any) -> Decimal:
    require(type(value) in {str, int, float, Decimal}, "Missing numeric accounting value")
    amount = Decimal(str(value))
    require(amount.is_finite() and amount >= 0, "Invalid accounting value")
    return amount


def nusd(value: Any) -> int:
    return int((money(value) * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))


def durable_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_bytes(path: Path, content: bytes) -> None:
    """Retain exact private wire bytes before interpreting a provider response."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class MonthlyLedger:
    """Read existing monthly authority; never initialize, reset, or mutate it."""

    def __init__(self, *, month: str, historical_floor: str):
        self.month = month
        self.key = "ai-budget:" + month
        self.floor = money(historical_floor)
        self.run_id: str | None = None

    async def read(self, owned: dict[str, str] | None = None) -> dict:
        require(self.month == f"{datetime.now(UTC):%Y-%m}", "UTC accounting month changed")
        redis = await analyst_budget._redis()
        require(redis is not None, "Real monthly Redis authority unavailable")
        assert redis is not None
        try:
            # MULTI snapshot: reject a missing/expiring ledger before normal reserve
            # can silently PERSIST it. Reservations may ONLY be this active turn's.
            async with redis.pipeline(transaction=True) as pipeline:
                pipeline.get(self.key)
                pipeline.ttl(self.key)
                pipeline.hgetall(self.key + ":reservations")
                pipeline.ttl(self.key + ":reservations")
                raw, ttl, reservations, reservation_ttl = await pipeline.execute()
            require(raw is not None and ttl == -1, "Missing or expiring real monthly ledger")
            total = money(raw.decode() if isinstance(raw, bytes) else raw)
            current = {
                (key.decode() if isinstance(key, bytes) else key): (
                    value.decode() if isinstance(value, bytes) else value
                )
                for key, value in reservations.items()
            }
            require(reservation_ttl in {-1, -2}, "Expiring normal reservations")
            active = owned or {}
            require(current == active, "Foreign or unresolved monthly reservations")
            require(
                nusd(self.floor) <= nusd(total) and total < MONTHLY_CUTOFF,
                "Historical charge floor or real $2 cutoff violated",
            )
            reserved = sum((money(value) for value in current.values()), Decimal(0))
            require(reserved <= total, "Reservations exceed monthly authority")
            require(total + reserved <= MONTHLY_CUTOFF, "Monthly reservations exceed the $2 cutoff")
            server = await redis.info("server")
            identity = server.get("run_id")
            require(isinstance(identity, str) and bool(identity), "Missing Redis server identity")
            if self.run_id is not None:
                require(identity == self.run_id, "Redis process identity changed during goal")
            return {
                "month": self.month,
                "key": self.key,
                "amount_usd": str(total),
                "reservations": current,
                "ttl": ttl,
                "redis_run_id": identity,
            }
        finally:
            await redis.aclose()


class NormalizedCandidateClient:
    """Add normalization checks while reusing the full stored-identity validator."""

    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def scroll(self, **kwargs):
        points, offset = self.client.scroll(**kwargs)
        if kwargs.get("with_vectors"):
            for point in points:
                vector = point.vector
                require(
                    isinstance(vector, list)
                    and len(vector) == 384
                    and all(
                        type(value) in {int, float} and math.isfinite(value) for value in vector
                    )
                    and abs(sum(value * value for value in vector) - 1) < 0.001,
                    "Stored candidate embedding is not normalized 384-dimensional data",
                )
        return points, offset


class Admission:
    def __init__(
        self,
        *,
        evidence_root: Path,
        artifact_dir: Path,
        bundle_path: Path,
        candidate_identity_dir: Path,
        api_key: str,
        ledger: MonthlyLedger,
    ):
        self.root = evidence_root.resolve()
        self.artifact_dir = artifact_dir
        self.bundle_path = bundle_path.resolve()
        self.identity_dir = candidate_identity_dir.resolve()
        self.api_key, self.ledger = api_key, ledger
        self.contract_sha256 = CONTRACT_SHA256
        self.cases = load_contract(self.root / GOLD, self.root / APPROVAL)["cases"]
        self.manifest = json.loads((self.identity_dir / "manifest.json").read_text())
        self.metadata_count = 0
        self.resource_binding: dict | None = None
        self.alias_binding: dict | None = None
        self.records: dict[str, list[dict]] | None = None

    def verify_inputs(self) -> None:
        for relative, expected in FROZEN.items():
            require(
                file_hash(self.root / relative) == expected,
                "Frozen contract or approval changed: " + relative,
            )
        require(
            file_hash(self.bundle_path) == BUNDLE_SHA256,
            "Approved dataset bundle changed",
        )
        for relative, expected in IDENTITY_FILES.items():
            require(
                file_hash(self.identity_dir / relative) == expected,
                "Candidate identity payload changed: " + relative,
            )
        for relative, expected in SERVING_CODE_SHA256.items():
            require(
                file_hash(self.root / "apps/api" / relative) == expected,
                "Candidate serving source differs from the verified tested commit: " + relative,
            )
        require(
            self.manifest["candidate_aliases"] == COLLECTIONS
            and self.manifest["data_version"] == VERSION
            and self.manifest["index_revision"] == REVISION
            and self.manifest["source"] == "cached_db_only"
            and self.manifest["games"] == 101
            and self.manifest["events"] == 46500
            and self.manifest["possession_chunks"] == 15864
            and self.manifest["archive_source_units"] == 49
            and self.manifest["qdrant_supporting_counts"]
            == {"knicks_games": 130, "knicks_box_scores": 2970, "knicks_reports": 101}
            and self.manifest["qdrant_upserted"] == 0
            and not self.manifest["aliases_promoted"]
            and not self.manifest["qdrant_reset"]
            and set(self.manifest["qdrant_reused_collections"]) == set(COLLECTIONS.values()),
            "Candidate namespace, source, or workload identity differs",
        )
        load_contract(self.root / GOLD, self.root / APPROVAL)

    def verify_settings(self, mode: str) -> None:
        settings = get_settings()
        require(
            settings.environment == "staging"
            and not settings.test_mode
            and not settings.seed_on_startup
            and settings.require_active_release
            and settings.dataset_season == "2025-26"
            and settings.ai_provider == "none"
            and not settings.ai_api_key
            and settings.ai_base_url.rstrip("/") == OPENROUTER_BASE_URL
            and settings.ai_chat_model == MODEL
            and settings.ai_reasoning_effort == "none"
            and settings.ai_request_timeout_seconds == 20
            and settings.openrouter_summary_model == MODEL
            and settings.openrouter_provider_route is None
            and settings.openrouter_max_prompt_price is None
            and settings.openrouter_max_completion_price is None
            and settings.openrouter_allowed_models == [MODEL]
            and settings.openrouter_monthly_cutoff_usd == 2
            and settings.analyst_evidence_loop_enabled
            and not settings.rag_archive_source_units_enabled
            and settings.rag_qdrant_enabled
            and settings.rag_qdrant_cloud_inference
            and settings.rag_hybrid_enabled
            and settings.rag_llm_planner_enabled
            and not settings.rag_reranker_enabled
            and not settings.rag_conditional_reranker_enabled
            and not settings.sentry_dsn
            and settings.rag_embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
            and settings.rag_qdrant_vector_size == 384
            and settings.rag_embedding_max_seq_length == 128
            and settings.analyst_max_model_calls == 6
            and settings.analyst_max_tool_rounds == 2
            and settings.analyst_input_tokens == 8000
            and settings.analyst_evidence_tokens == 6000
            and settings.analyst_deadline_seconds == 30
            and settings.analyst_investigation_seconds == 20
            and settings.analyst_call_reservation_usd == 0.01
            and settings.rag_generation_max_output_tokens == 500
            and settings.public_chat_rate_limit_per_minute == 10
            and settings.public_chat_rate_limit_per_day == 100
            and settings.analysis_shadow_sample_rate == 0.1
            and settings.analysis_answer_mode == ("llm_primary" if mode == "primary" else "shadow"),
            "Configuration differs from the isolated primary-release contract",
        )
        require(
            bool(settings.ip_hash_secret)
            and settings.ip_hash_secret != "development-only-change-me",
            "Established isolated staging client identity is missing",
        )
        for base, attribute in (
            ("knicks_games", "rag_qdrant_games_collection"),
            ("knicks_possessions", "rag_qdrant_possessions_collection"),
            ("knicks_box_scores", "rag_qdrant_box_scores_collection"),
            ("knicks_reports", "rag_qdrant_reports_collection"),
        ):
            require(
                getattr(settings, attribute) == COLLECTIONS[base],
                "Runtime does not use inactive physical candidate",
            )

    async def verify_resources(self, *, full: bool) -> dict:
        from app.core.db import AsyncSessionLocal
        from app.models.dataset_release import DatasetRelease
        from app.models.game import Game
        from app.services.qdrant_client import (
            PAYLOAD_INDEX_TYPES,
            UNIT_PAYLOAD_INDEX_TYPES,
            get_qdrant_client,
            qdrant_point_id,
            validate_candidate_collection,
            validate_candidate_identity,
        )

        settings = get_settings()
        database = urlsplit(settings.effective_db_url)
        require(
            database.scheme == "postgresql+asyncpg"
            and database.hostname in {"localhost", "127.0.0.1"}
            and database.port == 55500
            and database.path == "/knicksiq"
            and database.username == "knicksiq",
            "Wrong isolated PostgreSQL endpoint",
        )
        redis = urlsplit(settings.redis_url or "")
        require(
            redis.scheme == "redis"
            and redis.hostname in {"localhost", "127.0.0.1"}
            and redis.port == 56500
            and redis.path == "/0"
            and not redis.query
            and not redis.fragment,
            "Wrong isolated Redis endpoint",
        )
        qdrant_url = urlsplit(settings.qdrant_url or "")
        require(
            qdrant_url.scheme == "https"
            and bool(qdrant_url.hostname)
            and qdrant_url.port in {None, 443, 6333}
            and qdrant_url.username is None
            and qdrant_url.password is None
            and qdrant_url.path in {"", "/"}
            and not qdrant_url.query
            and not qdrant_url.fragment,
            "Candidate Qdrant must be the admitted HTTPS cloud endpoint",
        )
        async with AsyncSessionLocal() as db:
            identity = (
                await db.execute(
                    text(
                        "SELECT system_identifier::text, current_database(), current_user, "
                        "host(inet_server_addr()), inet_server_port() FROM pg_control_system()"
                    )
                )
            ).one()
            require(
                tuple(identity[1:3]) == ("knicksiq", "knicksiq")
                and isinstance(identity[0], str)
                and bool(identity[0])
                and isinstance(identity[3], str)
                and bool(identity[3])
                and type(identity[4]) is int
                and identity[4] == 5432,
                "Wrong PostgreSQL cluster or SQL identity",
            )
            release = (
                await db.execute(select(DatasetRelease).where(DatasetRelease.status == "active"))
            ).scalar_one()
            require(
                release.version == VERSION
                and release.validation_passed
                and release.manifest_sha256 == BUNDLE_SHA256,
                "Active dataset or approved bundle identity changed",
            )
            if full:
                games = list(
                    (
                        await db.execute(
                            select(Game)
                            .where(Game.release_id == release.id)
                            .order_by(Game.game_date)
                        )
                    ).scalars()
                )
                require(len(games) == 101, "Incomplete source game population")
                self.records = await self.expected_records(db, games)
        qdrant = get_qdrant_client()
        aliases = {item.alias_name: item.collection_name for item in qdrant.get_aliases().aliases}
        require(
            not any(target in aliases.values() for target in COLLECTIONS.values()),
            "Physical candidate replaced by an alias",
        )
        if self.alias_binding is not None:
            require(aliases == self.alias_binding, "Qdrant aliases changed during guarded goal")
        for base, target in COLLECTIONS.items():
            if full:
                assert self.records is not None
                require(
                    len(self.records[base]) == IDENTITY_COUNTS[base],
                    "Source-derived point coverage changed",
                )
                validate_candidate_identity(
                    target, VERSION, self.records[base], client=NormalizedCandidateClient(qdrant)
                )
            else:
                validate_candidate_collection(target, VERSION, IDENTITY_COUNTS[base], client=qdrant)
                info = qdrant.get_collection(target)
                for field, kind in {**PAYLOAD_INDEX_TYPES, **UNIT_PAYLOAD_INDEX_TYPES}.items():
                    index = info.payload_schema.get(field)
                    field_type = getattr(index, "data_type", None)
                    require(
                        index is not None and getattr(field_type, "value", field_type) == kind,
                        "Candidate payload filter descriptor changed",
                    )
                require(self.records is not None, "Missing full candidate point admission")
                assert self.records is not None
                expected = self.records[base][0]
                points = qdrant.retrieve(
                    collection_name=target,
                    ids=[qdrant_point_id(expected["id"])],
                    with_payload=True,
                    with_vectors=True,
                )
                require(
                    len(points) == 1
                    and points[0].payload == {**expected["payload"], "chunk_id": expected["id"]},
                    "Candidate point/source/embedding descriptor changed",
                )
                vector = points[0].vector
                require(
                    isinstance(vector, list)
                    and len(vector) == 384
                    and all(
                        (type(value) is int or type(value) is float) and math.isfinite(value)
                        for value in vector
                    ),
                    "Candidate probe point embedding changed",
                )
                assert isinstance(vector, list)
                typed_vector = cast(list[float], vector)
                require(
                    abs(sum(value * value for value in typed_vector) - 1) < 0.001,
                    "Candidate probe point embedding changed",
                )
        if full and not get_settings().rag_qdrant_cloud_inference:
            from app.services.embeddings import embed_texts

            vectors = await asyncio.to_thread(
                embed_texts, ["Jalen Brunson Knicks basketball points"]
            )
            require(
                len(vectors) == 1
                and len(vectors[0]) == 384
                and all(math.isfinite(value) for value in vectors[0])
                and abs(sum(value * value for value in vectors[0]) - 1) < 0.001,
                "Local embedding model unavailable, wrong-dimensional, or unnormalized",
            )
        result = {
            "postgres": {
                "system_identifier": identity[0],
                "database": identity[1],
                "user": identity[2],
                "server_address": identity[3],
                "server_port": identity[4],
                "runtime_host": database.hostname,
                "runtime_port": database.port,
            },
            "redis": {"runtime_host": redis.hostname, "runtime_port": redis.port, "database": 0},
            "qdrant_host": qdrant_url.hostname,
            "release_id": release.id,
            "data_version": VERSION,
            "bundle_sha256": BUNDLE_SHA256,
            "candidate_collections": COLLECTIONS,
            "candidate_identity_files": IDENTITY_FILES,
            "qdrant_aliases": aliases,
        }
        if self.resource_binding is not None:
            require(result == self.resource_binding, "Admitted resource identity changed")
        self.alias_binding = aliases
        return result

    async def expected_records(self, db, games) -> dict[str, list[dict]]:
        from app.services.archive_units import UNIT_RECIPE, build_archive_units, unit_search_text
        from app.services.rag_index import _embedding_text, _release_supporting_records

        # These helpers ONLY read DB rows. Do not call build_rag_artifacts or the
        # create/upsert/promote helpers during admission.
        settings = get_settings()
        canonical = (
            settings.rag_qdrant_games_collection,
            settings.rag_qdrant_box_scores_collection,
            settings.rag_qdrant_reports_collection,
        )
        supporting = await _release_supporting_records(db, games, VERSION)
        records = {
            base: supporting[physical]
            for base, physical in zip(
                ("knicks_games", "knicks_box_scores", "knicks_reports"), canonical, strict=True
            )
        }
        with (self.identity_dir / "qdrant_payloads.jsonl").open() as handle:
            records["knicks_possessions"] = [json.loads(line) for line in handle if line.strip()]
        units = await build_archive_units(db, games, VERSION)
        require(len(units) == 49, "Incomplete source-aware index population")
        for unit in units:
            target = (
                "knicks_games"
                if unit["payload"]["unit_type"]
                in {"multigame_aggregate", "game_scoring_comparison"}
                else "knicks_box_scores"
            )
            records[target].append(unit)
        for base, items in records.items():
            for record in items:
                document = (
                    _embedding_text(record)
                    if base == "knicks_possessions"
                    else unit_search_text(record["payload"])
                )
                record["payload"]["_index_embedding"] = {
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "mode": "cloud",
                    "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
                    "source_unit_schema": UNIT_RECIPE,
                }
        return records

    async def provider_metadata(self) -> dict:
        observed = {}
        started = time.monotonic()
        endpoints = (
            ("key", "key"),
            ("credits", "credits"),
            ("model", "models"),
            ("routes", "models/" + MODEL + "/endpoints"),
        )
        async with httpx.AsyncClient(follow_redirects=False, timeout=10, trust_env=False) as client:
            responses = await asyncio.gather(
                *(
                    client.get(
                        OPENROUTER_BASE_URL + "/" + endpoint,
                        headers={"Authorization": "Bearer " + self.api_key},
                    )
                    for _, endpoint in endpoints
                ),
                return_exceptions=True,
            )
        for (name, _), response in zip(endpoints, responses, strict=True):
            if isinstance(response, BaseException):
                raise response
            response.raise_for_status()
            body = response.json()
            require(isinstance(body, dict), "Malformed current provider metadata")
            data = body.get("data")
            if name == "model":
                require(isinstance(data, list), "Missing current model parameter catalog")
                models = [
                    item for item in data if isinstance(item, dict) and item.get("id") == MODEL
                ]
                require(len(models) == 1, "Exact current model metadata unavailable")
                observed[name] = models[0]
            else:
                require(isinstance(data, dict), "Malformed current provider metadata")
                observed[name] = data

        model = observed["model"]
        model_parameters = model.get("supported_parameters")
        required_parameters = {"temperature", "max_tokens", "response_format", "reasoning"}
        require(
            model.get("canonical_slug") == "deepseek/deepseek-v4.1-flash-20260910"
            and isinstance(model.get("reasoning"), dict)
            and model["reasoning"].get("mandatory") is False
            and isinstance(model_parameters, list)
            and required_parameters <= set(model_parameters)
            and (model.get("architecture") or {}).get("output_modalities") == ["text"],
            "Current model cannot admit the production text, JSON, and disabled-reasoning request",
        )
        route_data = observed["routes"]
        require(
            route_data.get("id") == MODEL and isinstance(route_data.get("endpoints"), list),
            "Missing current model endpoint prices",
        )

        price_fields = {
            "prompt",
            "completion",
            "request",
            "input_cache_read",
            "input_cache_write",
            "discount",
        }
        maximum_prompt = Decimal(0)
        maximum_completion = Decimal(0)
        maximum_request = Decimal(0)
        endpoint_snapshot = []
        active_provider_names = set()
        compatible_active_endpoints = 0

        def normalize_prices(prices: dict) -> tuple[dict, Decimal, Decimal, Decimal]:
            require(
                {"prompt", "completion"} <= prices.keys() and set(prices) <= price_fields,
                "Missing or unknown billable endpoint price fields",
            )
            rates = {name: money(value) for name, value in prices.items()}
            prompt = rates["prompt"] + max(
                rates.get("input_cache_read", Decimal(0)),
                rates.get("input_cache_write", Decimal(0)),
            )
            completion = rates["completion"]
            request = rates.get("request", Decimal(0))
            require(
                prompt > 0 and completion > 0 and rates.get("discount", Decimal(0)) <= 1,
                "Invalid endpoint price schedule",
            )
            return (
                {name: str(value) for name, value in rates.items()},
                prompt,
                completion,
                request,
            )

        routes = route_data["endpoints"]
        require(bool(routes), "No model endpoints are available for conservative pricing")
        seen_tags = set()
        for route in routes:
            require(
                isinstance(route, dict)
                and isinstance(route.get("tag"), str)
                and bool(route["tag"])
                and isinstance(route.get("provider_name"), str)
                and bool(route["provider_name"])
                and type(route.get("status")) is int,
                "Malformed provider endpoint identity",
            )
            tag = route["tag"]
            require(tag not in seen_tags, "Duplicate provider endpoint identity")
            seen_tags.add(tag)
            pricing = route.get("pricing")
            require(isinstance(pricing, dict), "Missing provider endpoint price schedule")
            assert isinstance(pricing, dict)
            base = {name: value for name, value in pricing.items() if name != "overrides"}
            normalized_base, prompt, completion, request = normalize_prices(base)
            maximum_prompt = max(maximum_prompt, prompt)
            maximum_completion = max(maximum_completion, completion)
            maximum_request = max(maximum_request, request)
            overrides = pricing.get("overrides", [])
            require(isinstance(overrides, list), "Malformed provider price overrides")
            assert isinstance(overrides, list)
            normalized_overrides = []
            for override in overrides:
                require(
                    isinstance(override, dict)
                    and {"utc_start", "utc_end"} <= override.keys()
                    and set(override) <= price_fields | {"utc_start", "utc_end"}
                    and all(type(override[key]) is int for key in ("utc_start", "utc_end"))
                    and all(
                        0 <= override[key] <= 2359
                        and override[key] // 100 < 24
                        and override[key] % 100 < 60
                        for key in ("utc_start", "utc_end")
                    ),
                    "Malformed provider time-dependent price override",
                )
                price_override = {
                    name: value
                    for name, value in override.items()
                    if name not in {"utc_start", "utc_end"}
                }
                normalized, prompt, completion, request = normalize_prices(price_override)
                maximum_prompt = max(maximum_prompt, prompt)
                maximum_completion = max(maximum_completion, completion)
                maximum_request = max(maximum_request, request)
                normalized_overrides.append(
                    {
                        "utc_start": override["utc_start"],
                        "utc_end": override["utc_end"],
                        "prices": normalized,
                    }
                )
            supported = route.get("supported_parameters") or []
            require(
                isinstance(supported, list) and all(isinstance(item, str) for item in supported),
                "Malformed provider endpoint parameter list",
            )
            endpoint_limits = {
                field: route.get(field)
                for field in ("context_length", "max_prompt_tokens", "max_completion_tokens")
            }
            require(
                all(
                    value is None or (type(value) is int and value > 0)
                    for value in endpoint_limits.values()
                ),
                "Malformed provider endpoint context/token limits",
            )
            if route["status"] == 0:
                active_provider_names.add(route["provider_name"])
                if required_parameters <= set(supported):
                    compatible_active_endpoints += 1
            endpoint_snapshot.append(
                {
                    "tag": tag,
                    "provider_name": route["provider_name"],
                    "status": route["status"],
                    "quantization": route.get("quantization"),
                    "supported_parameters": sorted(supported),
                    **endpoint_limits,
                    "pricing": {
                        "base": normalized_base,
                        "overrides": normalized_overrides,
                    },
                }
            )
        require(
            compatible_active_endpoints > 0,
            "No active provider endpoint supports the production request parameters",
        )
        endpoint_snapshot.sort(key=lambda item: item["tag"])
        price_snapshot = {
            "observed_at": datetime.now(UTC).isoformat(),
            "model": MODEL,
            "endpoint_count": len(endpoint_snapshot),
            "compatible_active_endpoint_count": compatible_active_endpoints,
            "active_provider_names": sorted(active_provider_names),
            "maximum_prompt_usd_per_token": str(maximum_prompt),
            "maximum_completion_usd_per_token": str(maximum_completion),
            "maximum_request_usd": str(maximum_request),
            "endpoints": endpoint_snapshot,
        }
        price_snapshot_sha256 = digest(price_snapshot)

        credits = observed["credits"]
        credit = money(credits.get("total_credits")) - money(credits.get("total_usage"))
        require(credit > 0, "Insufficient actual account credit")
        key = observed["key"]
        monthly = money(key.get("usage_monthly"))
        require(
            monthly >= Decimal(MINIMUM_PROVIDER_MONTHLY_NUSD) / 1_000_000_000
            and monthly < MONTHLY_CUTOFF
            and key.get("is_free_tier") is False
            and hashlib.sha256(self.api_key.encode()).hexdigest() == DESIGNATED_KEY_SHA256,
            "Wrong provider key identity, monthly floor, or $2 cutoff exhausted",
        )
        remaining = key.get("limit_remaining")
        if remaining is not None:
            credit = min(credit, money(remaining))
        require(credit > 0, "Insufficient remaining provider credit")
        result = {
            "observed_at": datetime.now(UTC).isoformat(),
            "fetch_elapsed_ms": round((time.monotonic() - started) * 1000),
            "key_sha256": hashlib.sha256(self.api_key.encode()).hexdigest(),
            "key": {
                field: key.get(field)
                for field in ("usage", "usage_monthly", "limit", "limit_remaining", "is_free_tier")
            },
            "remaining_account_credit_usd": str(credit),
            "model": {
                "canonical_slug": model["canonical_slug"],
                "reasoning": model["reasoning"],
                "supported_parameters": sorted(model_parameters),
                "output_modalities": model["architecture"]["output_modalities"],
            },
            "provider_routing": ROUTING_POLICY,
            "endpoint_price_snapshot": price_snapshot,
            "endpoint_price_snapshot_sha256": price_snapshot_sha256,
            "completion_requests": 0,
        }
        result["parameter_documentation"] = {
            "reasoning": "https://openrouter.ai/docs/guides/best-practices/reasoning-tokens",
            "routing": "https://openrouter.ai/docs/guides/routing/provider-selection",
            "reasoning_policy": (
                "The request uses the serving adapter's reasoning.enabled=false switch. "
                "Every listed endpoint price schedule, including time-dependent overrides, "
                "is retained and the maximum is used without relying on discounts."
            ),
        }
        self.metadata_count += 1
        path = self.artifact_dir / f"provider-metadata-{self.metadata_count:06d}.json"
        durable_json(path, result)
        result["metadata_sha256"] = file_hash(path)
        return result

    async def verify_environment(self, identity: dict) -> None:
        mode = identity["mode"]
        require(mode in {"primary", "shadow"}, "Unsupported evaluation workload mode")
        self.verify_inputs()
        self.verify_settings(mode)
        expected_ids = [
            evaluation_request_id(self.contract_sha256, mode, case["id"]) for case in self.cases
        ]
        from app.api.analysis import _sample_shadow

        require(
            identity["expectations_sha256"] == self.contract_sha256
            and identity["request_ids"] == expected_ids
            and identity["shadow_membership"]
            == (
                [_sample_shadow(identity, 0.1) for identity in expected_ids]
                if mode == "shadow"
                else []
            ),
            "Changed frozen case identities or fixed shadow membership",
        )
        self.resource_binding = await self.verify_resources(full=True)
        ledger = await self.ledger.read()
        metadata = await self.provider_metadata()
        monthly = money(metadata["key"]["usage_monthly"])
        require(
            nusd(monthly) >= MINIMUM_PROVIDER_MONTHLY_NUSD
            and money(ledger["amount_usd"]) >= monthly,
            "Provider monthly usage exceeds the read-only Redis ledger authority",
        )
        self.ledger.floor = max(self.ledger.floor, monthly)
        self.ledger.run_id = ledger["redis_run_id"]
        ledger = await self.ledger.read()
        durable_json(
            self.artifact_dir / "environment-admission.json",
            {
                "identity": identity,
                "resources": self.resource_binding,
                "ledger": ledger,
                "provider_metadata_sha256": metadata["metadata_sha256"],
                "endpoint_price_snapshot_sha256": metadata["endpoint_price_snapshot_sha256"],
                "status": "admitted_no_completion",
            },
        )

    async def verify_request(self, payload: dict, owned: dict[str, str]) -> dict:
        self.verify_inputs()
        mode = (_turn.get() or {}).get("mode")
        self.verify_settings("primary" if mode == "primary" else "shadow")
        await self.verify_resources(full=False)
        ledger = await self.ledger.read(owned)
        metadata = await self.provider_metadata()
        ledger = await self.ledger.read(owned)
        monthly = money(metadata["key"]["usage_monthly"])
        monthly_amount = money(ledger["amount_usd"])
        require(
            nusd(monthly) >= MINIMUM_PROVIDER_MONTHLY_NUSD
            and monthly_amount >= monthly
            and monthly_amount
            + sum((money(value) for value in ledger["reservations"].values()), Decimal(0))
            <= MONTHLY_CUTOFF,
            "Current provider charges or Redis reservations exceed verified authority",
        )
        settings = get_settings()
        expected_fields = {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "provider",
            "response_format",
            "reasoning",
        }
        require(
            set(payload) == expected_fields
            and payload.get("model") == MODEL
            and payload.get("temperature") == 0
            and type(payload.get("max_tokens")) is int
            and payload["max_tokens"] == settings.rag_generation_max_output_tokens
            and payload["provider"] == ROUTING_POLICY
            and payload["reasoning"] == {"enabled": False},
            "Actual payload differs from bounded production model/routing settings",
        )
        messages = payload.get("messages")
        require(
            isinstance(messages, list)
            and len(messages) == 2
            and [message.get("role") for message in messages] == ["system", "user"]
            and all(
                set(message) == {"role", "content"} and isinstance(message["content"], str)
                for message in messages
            ),
            "Actual payload is not bounded text-only analyst input",
        )
        response_format = payload.get("response_format")
        require(isinstance(response_format, dict), "Missing structured output contract")
        assert isinstance(response_format, dict)
        format_type = response_format.get("type")
        require(format_type in {"json_object", "json_schema"}, "Unbounded provider response format")
        assert format_type in {"json_object", "json_schema"}
        if format_type == "json_object":
            require(set(response_format) == {"type"}, "Unexpected JSON-object response options")
        assert isinstance(messages, list)
        parameters = {"temperature", "max_tokens", "response_format", "reasoning"}
        if format_type == "json_schema":
            parameters.add("structured_outputs")
        endpoint_snapshot = metadata["endpoint_price_snapshot"]
        model_parameters = set(metadata["model"]["supported_parameters"])
        require(
            parameters <= model_parameters,
            "Current model lacks actual request parameter support",
        )
        input_tokens = sum(len(message["content"].encode()) + 64 for message in messages)
        input_tokens += len(json.dumps(response_format, ensure_ascii=False).encode()) + 512
        output_tokens = payload["max_tokens"]
        compatible = []
        for endpoint in endpoint_snapshot["endpoints"]:
            if endpoint["status"] != 0 or not parameters <= set(endpoint["supported_parameters"]):
                continue
            context_length = endpoint.get("context_length")
            if type(context_length) is not int or input_tokens + output_tokens > context_length:
                continue
            if any(
                type(endpoint.get(field)) is int and needed > endpoint[field]
                for field, needed in (
                    ("max_prompt_tokens", input_tokens),
                    ("max_completion_tokens", output_tokens),
                )
            ):
                continue
            compatible.append(endpoint)
        require(
            bool(compatible),
            "No active endpoint admits this payload's parameters and context bound",
        )
        prompt_rate = money(endpoint_snapshot["maximum_prompt_usd_per_token"])
        completion_rate = money(endpoint_snapshot["maximum_completion_usd_per_token"])
        request_rate = money(endpoint_snapshot["maximum_request_usd"])
        bound = input_tokens * prompt_rate + output_tokens * completion_rate + request_rate
        require(
            bound > 0 and bound <= money(settings.analyst_call_reservation_usd),
            "Actual payload exceeds the normal analyst reservation",
        )
        require(
            money(metadata["remaining_account_credit_usd"]) >= bound
            and monthly + bound <= MONTHLY_CUTOFF
            and monthly_amount + bound <= MONTHLY_CUTOFF,
            "Actual provider funding or $2 monthly headroom unavailable",
        )
        return {
            "bound_nusd": nusd(bound),
            "provider_routing": ROUTING_POLICY,
            "price_snapshot_sha256": metadata["endpoint_price_snapshot_sha256"],
            "endpoint_price_snapshot": endpoint_snapshot,
            "metadata_sha256": metadata["metadata_sha256"],
            "input_token_bound": input_tokens,
            "output_token_bound": output_tokens,
            "ledger": ledger,
        }


class GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, session, delegate: httpx.AsyncBaseTransport | None):
        self.session = session
        self.delegate = delegate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        session = self.session
        turn = _turn.get()
        require(turn is not None, "Provider request has no exact bound evaluation turn")
        assert turn is not None
        prepared = turn.pop("prepared", None)
        require(isinstance(prepared, dict), "Provider request lacks verified payload bounds")
        assert isinstance(prepared, dict)
        require(
            request.method == "POST"
            and str(request.url) == f"{OPENROUTER_BASE_URL}/chat/completions"
            and request.headers.get("authorization") == f"Bearer {session.api_key}"
            and request.headers.get("content-type", "").split(";")[0] == "application/json",
            "Actual outbound request differs from verified provider identity",
        )
        payload = json.loads(request.content)
        require(
            isinstance(payload, dict)
            and digest(payload) == prepared["payload_sha256"]
            and payload.get("model") == MODEL
            and payload.get("provider") == ROUTING_POLICY
            and prepared["provider_routing"] == ROUTING_POLICY,
            "Actual outbound request differs from verified payload/identity",
        )
        ticket = current_ticket.get()
        require(type(ticket) is int, "Missing exact counted provider ticket")
        assert isinstance(ticket, int)
        with session.budget._connect() as db:
            price_row = db.execute(
                "SELECT snapshot FROM guard_price_snapshots WHERE sha256=?",
                (prepared["price_snapshot_sha256"],),
            ).fetchone()
            require(price_row is not None, "Missing durable endpoint price snapshot")
            assert price_row is not None
            endpoint_snapshot = json.loads(price_row[0])
            require(
                digest(endpoint_snapshot) == prepared["price_snapshot_sha256"]
                and endpoint_snapshot == prepared["endpoint_price_snapshot"],
                "Endpoint price snapshot changed before provider transmission",
            )
            pending = db.execute(
                "SELECT stage, amount FROM calls WHERE id=? AND status='pending'", (ticket,)
            ).fetchone()
            require(
                ticket is not None and pending == (session.stage, prepared["bound_nusd"]),
                "Missing exact task-bound counted journal reservation",
            )
            row = {
                "journal_ticket": ticket,
                "case_id": turn["case_id"],
                "request_id": turn["request_id"],
                "mode": session.mode,
                "stage": session.stage,
                "model": MODEL,
                "provider": None,
                "provider_routing": prepared["provider_routing"],
                "price_snapshot_sha256": prepared["price_snapshot_sha256"],
                "normal_reservation_id": prepared["normal_reservation_id"],
                "bound_nusd": prepared["bound_nusd"],
                "payload_sha256": prepared["payload_sha256"],
                "metadata_sha256": prepared["metadata_sha256"],
                "provider_key_sha256": hashlib.sha256(session.api_key.encode()).hexdigest(),
                "journal_binding": session.binding,
                "status": "pending",
                "transmission_started_at": datetime.now(UTC).isoformat(),
            }
            db.execute("INSERT INTO guard_receipts VALUES (?, ?, NULL)", (ticket, json.dumps(row)))
        turn["last_ticket"] = ticket
        reservation = turn["reservations"][prepared["normal_reservation_id"]]
        reservation["tickets"].append(ticket)
        with session.budget._connect() as db:
            db.execute(
                "UPDATE guard_normal SET receipt=? WHERE identity=?",
                (json.dumps(reservation), prepared["normal_reservation_id"]),
            )
        durable_json(
            session.run_dir / f"request-{ticket:06d}.json",
            {
                "payload": payload,
                "join": row,
                "input_token_bound": prepared["input_token_bound"],
                "output_token_bound": prepared["output_token_bound"],
            },
        )
        # Each counted adapter closes its client. Never let that close another
        # concurrently transmitting turn's production connection pool.
        delegate = self.delegate or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        try:
            response = await delegate.handle_async_request(request)
            response.request = request
            await response.aread()
            durable_bytes(session.run_dir / f"response-{ticket:06d}.body", response.content)
            row["raw_response_sha256"] = hashlib.sha256(response.content).hexdigest()
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict):
                choices = body.get("choices")
                row["finish_reason"] = (
                    choices[0].get("finish_reason")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                    else None
                )
            require(
                isinstance(body, dict)
                and body.get("error") is None
                and body.get("model") == MODEL
                and isinstance(body.get("provider"), str)
                and body["provider"] in endpoint_snapshot["active_provider_names"]
                and isinstance(body.get("id"), str)
                and bool(body["id"]),
                "Missing/mismatched provider generation identity",
            )
            row["provider"] = body["provider"]
            require(isinstance(body.get("usage"), dict), "Missing provider usage receipt")
            cost = nusd(body["usage"].get("cost"))
            row.update(
                reported_cost_nusd=cost,
                provider_generation_id=body["id"],
                usage=body["usage"],
                response_sha256=digest(body),
            )
            with session.budget._connect() as db:
                db.execute(
                    "UPDATE guard_receipts SET receipt=?, generation=? WHERE ticket=?",
                    (json.dumps(row), body["id"], ticket),
                )
            if cost > prepared["bound_nusd"]:
                session.failed("provider_cost_above_bound")
                try:
                    await session.retain_actual_cost(turn, reservation)
                finally:
                    # The journal records actual spend and stops even if Redis
                    # retention itself becomes unavailable.
                    session.budget.settle(ticket, cost)
            for field, limit in (
                ("prompt_tokens", prepared["input_token_bound"]),
                ("completion_tokens", prepared["output_token_bound"]),
            ):
                tokens = body["usage"].get(field)
                if tokens is not None:
                    require(
                        type(tokens) is int and tokens >= 0 and tokens <= limit,
                        "Provider usage exceeds actual payload token bound",
                    )
            require(cost <= prepared["bound_nusd"], "Provider cost exceeds verified bound")
            choices = body.get("choices")
            require(
                isinstance(choices, list)
                and bool(choices)
                and isinstance(choices[0], dict)
                and isinstance(choices[0].get("message"), dict)
                and isinstance(choices[0]["message"].get("content"), str)
                and bool(choices[0]["message"]["content"]),
                "Missing provider completion content",
            )
            assert isinstance(choices, list)
            reasoning_details = body["usage"].get("completion_tokens_details")
            if isinstance(reasoning_details, dict) and "reasoning_tokens" in reasoning_details:
                require(
                    type(reasoning_details["reasoning_tokens"]) is int
                    and reasoning_details["reasoning_tokens"] == 0,
                    "Provider ignored the admitted disabled-reasoning parameter",
                )
            require(
                choices[0]["message"].get("reasoning") is None
                or choices[0]["message"].get("reasoning") == "",
                "Provider returned unadmitted billable reasoning",
            )
            row.update(
                status="settled",
                provider_generation_id=body["id"],
                cost_nusd=cost,
                usage=body["usage"],
                response_sha256=digest(body),
                completed_at=datetime.now(UTC).isoformat(),
            )
            with session.budget._connect() as db:
                db.execute(
                    "UPDATE guard_receipts SET receipt=?, generation=? WHERE ticket=?",
                    (json.dumps(row), body["id"], ticket),
                )
            return response
        except BaseException as exc:
            row.update(status="uncertain", error_type=type(exc).__name__)
            with session.budget._connect() as db:
                db.execute(
                    "UPDATE guard_receipts SET receipt=? WHERE ticket=?", (json.dumps(row), ticket)
                )
            reservation["uncertain"] = True
            raise
        finally:
            if self.delegate is None:
                await delegate.aclose()

    async def aclose(self) -> None:
        if self.delegate is not None:
            await self.delegate.aclose()


class TurnBinding:
    def __init__(self, app, session):
        self.app, self.session = app, session

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/analysis/query":
            return await self.app(scope, receive, send)
        chunks = []
        while True:
            message = await receive()
            require(message["type"] == "http.request", "Interrupted original workload request")
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        raw = b"".join(chunks)
        body = json.loads(raw)
        request_id = dict(scope["headers"]).get(b"x-request-id", b"").decode()
        case = self.session.cases.get(request_id)
        require(
            case is not None
            and body.get("turn_id") == request_id
            and body.get("question") == case["question"]
            and body.get("context", []) == case.get("context", [])
            and body.get("season") == "2025-26"
            and body.get("expected_revision") == 0,
            "HTTP request differs from exact frozen case identity",
        )
        assert case is not None
        self.session.execution.check()
        token = _turn.set(
            {
                "case_id": case["id"],
                "request_id": request_id,
                "mode": self.session.mode,
                "reservations": {},
                "normal_objects": {},
                "calls": 0,
            }
        )
        consumed = False

        async def replay_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        try:
            await self.app(scope, replay_receive, send)
        finally:
            _turn.reset(token)


def validate_counted_receipt_joins(
    budget: VerificationBudget, binding: str, receipts: list[dict]
) -> None:
    """Join counted stages and durable endpoint-price snapshots."""
    require(
        all(row["status"] == "settled" for row in receipts),
        "Unjoined case/provider journal entries",
    )
    rows = {row["journal_ticket"]: row for row in receipts}
    with budget._connect() as db:
        price_snapshots = {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT sha256, snapshot FROM guard_price_snapshots")
        }
    calls = budget.snapshot()["calls"]
    for call in calls:
        joined = rows.get(call["id"])
        expected_mode = "shadow" if call["stage"] == "load" else call["stage"]
        price_sha = joined.get("price_snapshot_sha256") if joined is not None else None
        price_snapshot = price_snapshots.get(price_sha) if isinstance(price_sha, str) else None
        require(
            joined is not None
            and call["status"] == "settled"
            and joined["cost_nusd"] == call["amount_nusd"]
            and type(joined["bound_nusd"]) is int
            and 0 <= joined["cost_nusd"] <= joined["bound_nusd"]
            and joined["stage"] == call["stage"]
            and joined["mode"] == expected_mode
            and joined["journal_binding"] == binding
            and joined["provider_routing"] == ROUTING_POLICY
            and joined["model"] == MODEL
            and isinstance(price_snapshot, dict)
            and digest(price_snapshot) == price_sha
            and joined["provider"] in price_snapshot.get("active_provider_names", []),
            "Missing/mismatched counted case/provider cost join",
        )
    require(
        len(rows) == len(receipts) == len(calls),
        "Uncounted provider receipt in durable goal",
    )


class GuardedSession:
    """Bind existing normal reservations, counted transport, and original HTTP cases."""

    def __init__(
        self,
        *,
        admission,
        budget: VerificationBudget,
        ledger: MonthlyLedger,
        api_key: str,
        mode: str,
        run_dir: Path,
        provider_transport=None,
        stage: str | None = None,
        cases: list[dict] | None = None,
        request_ids: list[str] | None = None,
    ):
        self.admission, self.budget = admission, budget
        self.api_key, self.mode, self.run_dir = api_key, mode, run_dir
        self.stage = stage or mode
        self.accounting_lock = asyncio.Lock()
        self.reservations: dict[str, dict] = {}
        self.base_ledger = ledger
        session = self

        class SessionLedger:
            def __getattr__(self, name):
                return getattr(ledger, name)

            async def read(self, _owned=None):
                async with session.accounting_lock:
                    return await ledger.read(session.owned())

        self.ledger = SessionLedger()
        admission.ledger = self.ledger
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        bound_cases = admission.cases if cases is None else cases
        bound_ids = (
            request_ids
            if request_ids is not None
            else [
                evaluation_request_id(admission.contract_sha256, mode, case["id"])
                for case in bound_cases
            ]
        )
        require(
            len(bound_cases) == len(bound_ids) == len(set(bound_ids)),
            "Duplicate or incomplete HTTP case identities",
        )
        self.cases = dict(zip(bound_ids, bound_cases, strict=True))
        with budget._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS guard_receipts ("
                "ticket INTEGER PRIMARY KEY REFERENCES calls(id), "
                "receipt TEXT NOT NULL, generation TEXT UNIQUE)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS guard_normal ("
                "identity TEXT PRIMARY KEY, receipt TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS guard_price_snapshots ("
                "sha256 TEXT PRIMARY KEY, snapshot TEXT NOT NULL)"
            )
            self.binding = db.execute("SELECT binding FROM identity").fetchone()[0]
        self.execution = CountedRun(
            api_key=api_key,
            budget=budget,
            verify_environment=admission.verify_environment,
            verify_request=self.verify_request,
            transport=GuardedTransport(self, provider_transport),
        )
        self.execution.failed = self.failed
        self.revalidate: Callable[[], dict] | None = None
        adapter_factory = self.execution.adapter

        def diagnosed_adapter(stage, reasoning_effort):
            adapter = adapter_factory(stage, reasoning_effort)
            generate = adapter.generate

            async def diagnosed_generate(*, system, user):
                try:
                    return await generate(system=system, user=user)
                except BaseException as exc:
                    self.record_protocol_failure(exc)
                    raise

            adapter.generate = diagnosed_generate
            return adapter

        self.execution.adapter = diagnosed_adapter

    def record_protocol_failure(self, exc: BaseException) -> None:
        turn = _turn.get()
        ticket = turn.get("last_ticket") if turn is not None else None
        if ticket is None:
            return
        assert turn is not None
        receipt = next((row for row in self.receipts() if row["journal_ticket"] == ticket), {})
        errors = []
        if isinstance(exc, ValidationError):
            errors = [
                {"loc": list(item["loc"]), "type": item["type"]}
                for item in exc.errors(
                    include_url=False, include_context=False, include_input=False
                )
            ]
        durable_json(
            self.run_dir / f"protocol-failure-{ticket:06d}.json",
            {
                "journal_ticket": ticket,
                "request_id": turn["request_id"],
                "error_type": type(exc).__name__,
                "errors": errors,
                "finish_reason": receipt.get("finish_reason"),
                "raw_response_sha256": receipt.get("raw_response_sha256"),
            },
        )

    def owned(self) -> dict[str, str]:
        return {
            identity: str(record["amount"])
            for identity, record in self.reservations.items()
            if not record["settled"]
        }

    def failed(self, error: str) -> None:
        self.execution.failure = error
        with self.budget._connect() as db:
            db.execute("UPDATE identity SET stopped=1")

    async def retain_actual_cost(self, turn: dict, reservation: dict) -> None:
        rows = {row["journal_ticket"]: row for row in self.receipts()}
        actual = [
            rows[ticket].get("reported_cost_nusd", rows[ticket].get("cost_nusd"))
            for ticket in reservation["tickets"]
        ]
        require(
            all(type(value) is int and value >= 0 for value in actual),
            "Provider exposure lost its request/cost join",
        )
        amount = 0
        for value in actual:
            assert isinstance(value, int)
            amount += value
        reservation["uncertain"] = True
        reservation["retained_actual_cost_nusd"] = amount
        identity = reservation["identity"]
        with self.budget._connect() as db:
            db.execute(
                "UPDATE guard_normal SET receipt=? WHERE identity=?",
                (json.dumps(reservation), identity),
            )
        normal = turn["normal_objects"][identity]
        async with self.accounting_lock:
            retained = await normal.retain_at_least(float(Decimal(amount) / 1_000_000_000))
            reservation["amount"] = str(money(retained))
            with self.budget._connect() as db:
                db.execute(
                    "UPDATE guard_normal SET receipt=? WHERE identity=?",
                    (json.dumps(reservation), identity),
                )

    def receipts(self) -> list[dict]:
        with self.budget._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT receipt FROM guard_receipts ORDER BY ticket")
            ]

    def validate_receipt_joins(self) -> None:
        validate_counted_receipt_joins(self.budget, self.binding, self.receipts())

    def record_price_snapshot(self, bounds: dict) -> None:
        snapshot = bounds["endpoint_price_snapshot"]
        snapshot_sha256 = bounds["price_snapshot_sha256"]
        require(
            digest(snapshot) == snapshot_sha256,
            "Endpoint price snapshot hash does not match provider admission",
        )
        with self.budget._connect() as db:
            existing = db.execute(
                "SELECT snapshot FROM guard_price_snapshots WHERE sha256=?",
                (snapshot_sha256,),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO guard_price_snapshots VALUES (?, ?)",
                    (snapshot_sha256, json.dumps(snapshot, sort_keys=True)),
                )
            else:
                require(
                    json.loads(existing[0]) == snapshot,
                    "Endpoint price snapshot journal binding changed",
                )

    async def verify_request(self, payload: dict) -> int:
        self.execution.check()
        if self.revalidate is not None:
            self.revalidate()
        turn = _turn.get()
        require(
            turn is not None and turn["mode"] == self.mode and not turn.get("prepared"),
            "Missing exact request/case binding",
        )
        assert turn is not None
        from app.api.analysis import _sample_shadow

        require(
            self.mode != "shadow" or _sample_shadow(turn["request_id"], 0.1),
            "Unselected fixed shadow case attempted a provider call",
        )
        # Optional planners use separate reservations outside the analyst-loop call limit.
        maximum_calls = get_settings().analyst_max_model_calls + PLANNER_MAX_CALLS_PER_TURN
        require(turn["calls"] < maximum_calls, "Original per-case request cap exceeded")
        owned = self.owned()
        bounds = await self.admission.verify_request(payload, owned)
        self.record_price_snapshot(bounds)
        bound = bounds["bound_nusd"]
        require(
            type(bound) is int and 0 < bound <= nusd(get_settings().analyst_call_reservation_usd),
            "Payload exceeds actual normal per-call reservation",
        )
        snapshot = self.budget.snapshot()
        with self.budget._connect() as db:
            stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
            historical_amount = stored["historical_floor_nusd"]
        require(
            snapshot["inherited_calls"] == [],
            "Unexpected inherited provider exposure",
        )
        require(
            type(historical_amount) is int and historical_amount >= nusd(self.ledger.floor),
            "Missing aggregate historical goal accounting",
        )
        require(
            historical_amount + sum(row["amount_nusd"] for row in snapshot["calls"]) + bound
            <= 2_000_000_000,
            "Aggregate historical goal + actual payload exceeds $2",
        )
        candidates = [
            (identity, record)
            for identity, record in turn["reservations"].items()
            if not record["settled"]
            and record["used"] < record["slots"]
            and not record["uncertain"]
        ]
        preferred_identity = turn.get("preferred_normal_reservation_id")
        if preferred_identity is not None:
            candidates = [
                candidate for candidate in candidates if candidate[0] == preferred_identity
            ]
        require(bool(candidates), "No actual normal analyst reservation for outbound payload")
        identity, reservation = candidates[0]
        require(
            bound <= nusd(reservation["amount"]) // reservation["slots"],
            "Outbound bound exceeds actual normal reservation slot",
        )
        reservation["used"] += 1
        turn["calls"] += 1
        turn["prepared"] = {
            **bounds,
            "normal_reservation_id": identity,
            "payload_sha256": digest(payload),
        }
        return bound

    @contextmanager
    def installed(self):
        from app import main
        from app.services import analyst_loop, report_llm

        session = self
        original_factory = main.create_app
        original_reservation = analyst_loop.BudgetReservation
        original_sync = report_llm.OpenAICompatibleLLMAdapter._generate_sync
        original_generate = report_llm.OpenAICompatibleLLMAdapter.generate

        class BoundReservation(analyst_budget.BudgetReservation):
            def __init__(self, normal: analyst_budget.BudgetReservation, record: dict):
                super().__init__(normal.key, normal.identity, normal.amount)
                self.normal, self.record = normal, record

            @classmethod
            async def reserve(cls, amount):
                try:
                    async with session.accounting_lock:
                        return await cls._reserve(amount)
                except BaseException as exc:
                    session.failed(type(exc).__name__)
                    raise

            @classmethod
            async def _reserve(cls, amount):
                session.execution.check()
                turn = _turn.get()
                require(turn is not None, "Unbound normal analyst reservation")
                assert turn is not None
                await session.base_ledger.read(session.owned())
                unit = money(get_settings().analyst_call_reservation_usd)
                slots = money(amount) / unit
                require(
                    slots == int(slots) and 0 < slots <= 6, "Unbounded normal reservation slots"
                )
                normal = await original_reservation.reserve(amount)
                require(
                    normal is not None and normal.key == session.ledger.key,
                    "Normal monthly admission unavailable",
                )
                assert normal is not None
                record = {
                    "identity": normal.identity,
                    "request_id": turn["request_id"],
                    "case_id": turn["case_id"],
                    "amount": str(money(amount)),
                    "slots": int(slots),
                    "used": 0,
                    "tickets": [],
                    "settled": False,
                    "uncertain": False,
                }
                turn["reservations"][normal.identity] = record
                session.reservations[normal.identity] = record
                turn["normal_objects"][normal.identity] = normal
                with session.budget._connect() as db:
                    db.execute(
                        "INSERT INTO guard_normal VALUES (?, ?)",
                        (normal.identity, json.dumps(record)),
                    )
                return cls(normal, record)

            async def settle(self, reported_cost):
                try:
                    async with session.accounting_lock:
                        await self._settle(reported_cost)
                except BaseException as exc:
                    session.failed(type(exc).__name__)
                    raise

            async def _settle(self, _reported_cost):
                record = self.record
                rows = {row["journal_ticket"]: row for row in session.receipts()}
                if record["uncertain"] or any(
                    rows.get(ticket, {}).get("status") != "settled" for ticket in record["tickets"]
                ):
                    record["uncertain"] = True
                else:
                    cost = sum(rows[ticket]["cost_nusd"] for ticket in record["tickets"])
                    # Receipt has already been durably joined before releasing any
                    # normal reservation. Never trust the loop's rounded/unknown sum.
                    await self.normal.settle(float(Decimal(cost) / 1_000_000_000))
                    turn = _turn.get()
                    require(turn is not None, "Lost normal settlement case binding")
                    assert turn is not None
                    record["settled"] = True
                    await session.base_ledger.read(session.owned())
                    record["cost_nusd"] = cost
                with session.budget._connect() as db:
                    db.execute(
                        "UPDATE guard_normal SET receipt=? WHERE identity=?",
                        (json.dumps(record), self.normal.identity),
                    )

        def denied_sync(*_args, **_kwargs):
            session.failed("uncounted_provider_path")
            raise RuntimeError("Uncounted provider path denied in guarded workload")

        async def denied_generate(*_args, **_kwargs):
            return denied_sync()

        def guarded_app():
            app = original_factory()
            app.add_middleware(TurnBinding, session=session)
            return app

        try:
            main.create_app = guarded_app
            analyst_loop.BudgetReservation = BoundReservation
            report_llm.OpenAICompatibleLLMAdapter._generate_sync = denied_sync
            report_llm.OpenAICompatibleLLMAdapter.generate = denied_generate
            # Install the raw classmethod descriptor, not its bound method view.
            yield
        finally:
            main.create_app = original_factory
            analyst_loop.BudgetReservation = original_reservation
            report_llm.OpenAICompatibleLLMAdapter._generate_sync = original_sync
            report_llm.OpenAICompatibleLLMAdapter.generate = original_generate


def admitted_binding_sha(stored: dict) -> str:
    identity = {
        field: value
        for field, value in stored.items()
        if field not in {"resources", "redis_run_id", "historical_floor_nusd"}
    }
    return digest(identity)


def validate_admitted_goal(goal: Path, budget: VerificationBudget, binding: dict) -> dict:
    """Join the one admitted artifact to its immutable counted journal."""
    with budget._connect() as db:
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        identity = db.execute("SELECT binding FROM identity").fetchone()[0]
    artifact = json.loads((goal / "goal-binding.json").read_text())
    snapshot = budget.snapshot()
    require(
        artifact == {"binding_sha256": identity, **stored}
        and admitted_binding_sha(stored) == identity
        and all(
            stored.get(field) == json.loads(json.dumps(value)) for field, value in binding.items()
        )
        and set(stored) == set(binding) | {"resources", "redis_run_id", "historical_floor_nusd"}
        and type(stored["historical_floor_nusd"]) is int
        and stored["historical_floor_nusd"] >= MINIMUM_PROVIDER_MONTHLY_NUSD
        and isinstance(stored["resources"], dict)
        and isinstance(stored["redis_run_id"], str)
        and snapshot["inherited_calls"] == [],
        "Admitted artifact, owner binding, monthly floor, or counted inventory changed",
    )
    return stored


def goal_context(root: Path, goal: Path, args) -> tuple[MonthlyLedger, dict, Path]:
    root, goal = root.resolve(), goal.resolve()
    require(
        goal.is_relative_to(root) and goal != root, "Artifacts must remain in private evidence root"
    )
    ledger = MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}",
        historical_floor=str(Decimal(MINIMUM_PROVIDER_MONTHLY_NUSD) / 1_000_000_000),
    )
    return ledger, goal_binding(root, ledger), root / GOAL_ANCHOR


def goal_binding(root: Path, ledger: MonthlyLedger) -> dict:
    for relative, expected in FROZEN.items():
        require(
            file_hash(root / relative) == expected, "Frozen admission input mismatch: " + relative
        )
    settings = get_settings()
    return {
        "frozen_inputs": FROZEN,
        "dataset_bundle_sha256": BUNDLE_SHA256,
        "candidate_identity_sha256": IDENTITY_FILES,
        "candidate_collections": COLLECTIONS,
        "candidate_version": VERSION,
        "candidate_revision": REVISION,
        "serving_code_sha256": SERVING_CODE_SHA256,
        "model": MODEL,
        "provider": "openrouter",
        "provider_routing": ROUTING_POLICY,
        "provider_key_sha256": DESIGNATED_KEY_SHA256,
        "utc_month": ledger.month,
        "minimum_provider_monthly_nusd": MINIMUM_PROVIDER_MONTHLY_NUSD,
        "monthly_cutoff_nusd": 2_000_000_000,
        "spending_direction_sha256": SPENDING_DIRECTION_SHA256,
        "guarded_cli_sha256": file_hash(Path(__file__)),
        "runner_sha256": file_hash(Path(__file__).with_name("release_runner.py")),
        "load_harness_sha256": file_hash(Path(__file__).with_name("guarded_load.py")),
        "load_stress_sha256": file_hash(
            Path(__file__).resolve().parents[4] / "tools/release/stress.py"
        ),
        "load_request_cap": 66,
        "verification_budget_sha256": file_hash(Path(__file__).with_name("verification_budget.py")),
        "verification_adapter_sha256": file_hash(
            Path(__file__).with_name("verification_adapter.py")
        ),
        "client_identity_sha256": hashlib.sha256(settings.ip_hash_secret.encode()).hexdigest(),
        "runtime_settings_sha256": digest(
            settings.model_dump(
                exclude={
                    "analysis_answer_mode",
                    "db_url",
                    "redis_url",
                    "qdrant_url",
                    "ai_api_key",
                    "openrouter_api_key",
                    "qdrant_api_key",
                    "admin_api_key",
                    "ip_hash_secret",
                }
            )
        ),
    }


async def run(args) -> None:
    root, goal = args.evidence_root.resolve(), args.goal_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(root.stat().st_mode & 0o777 == 0o700, "Evidence root must be private mode 0700")
    require(
        goal.is_relative_to(root) and goal != root, "Artifacts must remain in private evidence root"
    )
    bundle_path = args.bundle_path.resolve()
    identity_dir = args.candidate_identity_dir.resolve()
    require(
        bundle_path.is_file() and identity_dir.is_dir(), "Required candidate input file is missing"
    )
    for relative, expected in FROZEN.items():
        require(
            file_hash(root / relative) == expected, "Frozen admission input mismatch: " + relative
        )
    require(
        file_hash(args.spending_direction.resolve()) == SPENDING_DIRECTION_SHA256,
        "Missing exact owner spending direction",
    )
    settings = get_settings()
    key = settings.openrouter_api_key
    require(isinstance(key, str) and key.startswith("sk-or-"), "Missing designated OpenRouter key")
    assert isinstance(key, str)
    require(
        hashlib.sha256(key.encode()).hexdigest() == DESIGNATED_KEY_SHA256,
        "Provider key differs from owner-designated identity",
    )
    ledger, binding, anchor_path = goal_context(root, goal, args)
    binding_sha = digest(binding)
    from app.api.analysis import _sample_shadow

    contract = load_contract(root / GOLD, root / APPROVAL)
    shadow_ids = [
        evaluation_request_id(FROZEN[GOLD], "shadow", case["id"]) for case in contract["cases"]
    ]
    selected = sum(_sample_shadow(identity, 0.1) for identity in shadow_ids)
    identity = {
        "mode": args.mode,
        "expectations_sha256": FROZEN[GOLD],
        "request_ids": [
            evaluation_request_id(FROZEN[GOLD], args.mode, case["id"]) for case in contract["cases"]
        ],
        "shadow_membership": [_sample_shadow(identity, 0.1) for identity in shadow_ids]
        if args.mode == "shadow"
        else [],
    }
    if args.action == "admit":
        require(
            not anchor_path.exists(), "An admitted goal already exists; new attempts are forbidden"
        )
        goal.mkdir(mode=0o700, exist_ok=False)
        admission = Admission(
            evidence_root=root,
            artifact_dir=goal,
            bundle_path=bundle_path,
            candidate_identity_dir=identity_dir,
            api_key=key,
            ledger=ledger,
        )
        await admission.verify_environment(identity)
        assert admission.resource_binding is not None
        binding["resources"] = admission.resource_binding
        binding["redis_run_id"] = ledger.run_id
        current = await ledger.read()
        binding["historical_floor_nusd"] = nusd(current["amount_usd"])
        anchor = {
            "goal_dir": str(goal),
            "binding_sha256": binding_sha,
            "policy": "One aggregate goal; no resume/retry or reset after uncertainty",
        }
        durable_json(anchor_path, anchor)
        path = goal / "goal.sqlite"
        VerificationBudget.create(path, binding=binding_sha, shadow_selected=selected)
        budget = VerificationBudget(path, binding=binding_sha)
        budget.apply_spending_direction(args.spending_direction.resolve())
        with budget._connect() as db:
            db.execute("CREATE TABLE guard_goal (binding TEXT NOT NULL)")
            db.execute("INSERT INTO guard_goal VALUES (?)", (json.dumps(binding),))
            db.execute("CREATE TABLE guard_runs (mode TEXT PRIMARY KEY, status TEXT NOT NULL)")
        durable_json(goal / "goal-binding.json", {"binding_sha256": binding_sha, **binding})
        print(
            json.dumps(
                {
                    "status": "admitted_no_completion",
                    "shadow_selected": selected,
                    "completion_requests": 0,
                }
            )
        )
        return

    require(goal.stat().st_mode & 0o777 == 0o700, "Admitted goal must remain private mode 0700")
    path = goal / "goal.sqlite"
    anchor = json.loads(anchor_path.read_text())
    require(
        anchor["goal_dir"] == str(goal) and anchor["binding_sha256"] == binding_sha,
        "Collection does not use the admitted aggregate goal",
    )
    require(path.is_file(), "Run admit once before counted collection; no restart bypass")
    budget = VerificationBudget(path, binding=binding_sha)
    admitted = validate_admitted_goal(goal, budget, binding)
    require(
        nusd(ledger.floor) <= admitted["historical_floor_nusd"],
        "Admitted monthly floor lowered",
    )
    require(
        budget.request_cap("smoke") == 9
        and budget.request_cap("primary") == 720
        and budget.request_cap("shadow") == 6 * selected
        and budget.request_cap("load") == 66,
        "Frozen phase/request caps changed",
    )
    require(
        not budget.snapshot()["stopped"]
        and budget.snapshot()["spending_direction_sha256"] == SPENDING_DIRECTION_SHA256,
        "Stopped or unapproved aggregate goal",
    )
    with budget._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        for field, value in binding.items():
            require(
                stored[field] == json.loads(json.dumps(value)),
                "Aggregate goal input binding changed",
            )
        ledger.run_id = stored["redis_run_id"]
        ledger.floor = Decimal(stored["historical_floor_nusd"]) / 1_000_000_000
        require(
            not db.execute("SELECT 1 FROM guard_runs WHERE status != 'complete'").fetchone(),
            "Interrupted or failed phase cannot resume",
        )
        db.execute("INSERT INTO guard_runs VALUES (?, 'started')", (args.mode,))
    run_dir = goal / args.mode
    admission = Admission(
        evidence_root=root,
        artifact_dir=run_dir,
        bundle_path=bundle_path,
        candidate_identity_dir=identity_dir,
        api_key=key,
        ledger=ledger,
    )
    admission.resource_binding = stored["resources"]
    admission.alias_binding = stored["resources"]["qdrant_aliases"]
    session = GuardedSession(
        admission=admission,
        budget=budget,
        ledger=ledger,
        api_key=key,
        mode=args.mode,
        run_dir=run_dir,
    )
    session.revalidate = lambda: validate_admitted_goal(
        goal, budget, goal_context(root, goal, args)[1]
    )
    status = "failed"
    try:
        with session.installed():
            result = await collect(
                root / GOLD,
                root / APPROVAL,
                run_dir / "observations.json",
                args.mode,
                execution=session.execution,
            )
        admission.verify_inputs()
        await ledger.read()
        session.validate_receipt_joins()
        status = "complete"
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "mode": args.mode,
                    "observations": len(result["observations"]),
                    "paid_requests": result["paid_requests"],
                }
            )
        )
    except BaseException as exc:
        session.failed(type(exc).__name__)
        raise
    finally:
        with budget._connect() as db:
            db.execute("UPDATE guard_runs SET status=? WHERE mode=?", (status, args.mode))
            snapshots = [
                {"sha256": row[0], "snapshot": json.loads(row[1])}
                for row in db.execute(
                    "SELECT sha256, snapshot FROM guard_price_snapshots ORDER BY rowid"
                )
            ]
        durable_json(
            run_dir / "execution-summary.json",
            {
                "status": status,
                "mode": args.mode,
                "calls": session.receipts(),
                "accounting": budget.snapshot(),
                "endpoint_price_snapshots": snapshots,
                "semantic_release_gate": "not_scored_or_approved",
            },
        )


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["admit", "collect"])
    parser.add_argument("--mode", required=True, choices=["primary", "shadow"])
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--goal-dir", required=True, type=Path)
    parser.add_argument("--bundle-path", required=True, type=Path)
    parser.add_argument("--candidate-identity-dir", required=True, type=Path)
    parser.add_argument("--key-env-file", type=Path)
    parser.add_argument("--staging-env-file", type=Path)
    parser.add_argument(
        "--spending-direction",
        type=Path,
        default=Path(__file__).resolve().parents[4]
        / "docs/release-evidence/evaluation-contract-20261021/owner-spending-direction.json",
    )
    args = parser.parse_args()
    try:
        for relative, expected in FROZEN.items():
            require(
                file_hash(args.evidence_root.resolve() / relative) == expected,
                "Frozen admission input mismatch: " + relative,
            )
        require(
            file_hash(args.spending_direction.resolve()) == SPENDING_DIRECTION_SHA256,
            "Missing exact owner spending direction",
        )
        if args.key_env_file is not None or args.staging_env_file is not None:
            from dotenv import dotenv_values

            if args.key_env_file is not None:
                key = dotenv_values(args.key_env_file).get("OPENROUTER_API_KEY")
                require(
                    isinstance(key, str) and bool(key), "Provider key file is missing its value"
                )
                assert isinstance(key, str)
                os.environ["OPENROUTER_API_KEY"] = key
            if args.staging_env_file is not None:
                secret = dotenv_values(args.staging_env_file).get("KNICKSIQ_STAGING_IP_HASH_SECRET")
                require(
                    isinstance(secret, str) and bool(secret),
                    "Staging environment lacks established client identity",
                )
                assert isinstance(secret, str)
                os.environ["IP_HASH_SECRET"] = secret
            get_settings.cache_clear()
        asyncio.run(run(args))
    except BaseException as exc:
        # Exception text may contain credential-bearing URLs or headers.
        print(
            json.dumps({"status": "denied_or_stopped", "error_type": type(exc).__name__}),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
