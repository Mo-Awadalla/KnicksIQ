"""Private, fail-closed original120 admission and counted collection.

Run ``admit`` once into a new private goal directory, then ``collect`` for primary
and shadow against that SAME goal. Admission is read-only: it does not initialize
Redis, build indexes, promote aliases, modify the ordinary API, or send completions.
Each collection re-admits current resources and every outbound payload rechecks
metadata and monthly authority. Failed/partial runs cannot be resumed. Captured
observations still require the unchanged independent semantic/release gates.
An explicit, exact owner-authorized successor uses its own exclusive anchor;
it inherits every counted request/charge and retains all original normal holds.
Without both successor flags, the original no-new-attempt rule remains unchanged.

The Docker socket is used ONLY for the fixed GET inspect whitelist below. A :ro
socket mount does not itself restrict daemon permissions; never mount it in the
ordinary API/web. This module performs no generic Docker calls or mutations.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any
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
REVISION = "source-support-20261003-ac5018b"
ROUTE = "morph/fp8"
PROVIDER = "Morph"
DESIGNATED_KEY_SHA256 = "b7258467823ff020470e6b01d5db23ea96fbad0f97701e3565f4f46ac05acb26"
MONTHLY_CUTOFF = Decimal("2")
NETWORK = "0d6a0006ed2a9185eff9933e8e2c81245a661554aa9b688cbb8afc13ac0babb1"
NETWORK_NAME = "knicksiq-local-staging_default"
EGRESS_NETWORK = "47227176f716f2c54ef2a024a316e2c558d8c13a7c470ef40a9cde56f0e55630"
EGRESS_NETWORK_NAME = "knicksiq-local-staging_browser"
RESOURCES = {
    "postgres": (
        "6ca6a3aa5b1403841a6284e7ab92295fc2e0f170d172d6e331863e8779d004a8",
        "knicksiq-local-staging-postgres-1",
        5432,
    ),
    "redis": (
        "7034818f2d7dfc9e2ac091bd8a062a2e50cd0dca0c630e84f0d06e640ff84360",
        "knicksiq-local-staging-redis-1",
        6379,
    ),
    "qdrant": (
        "713cc3a80d2f69903bc6520b3f44d2ea0ad3d23b819c92735081f51096928718",
        "knicksiq-qdrant-release-20261003",
        6333,
    ),
}
POSTGRES_SYSTEM_ID = "7692066323950968866"
GOLD = "source-support-20261003/gold-review/frozen-expectations.json"
APPROVAL = "source-support-20261003/gold-review/evaluation-approval.json"
HISTORY = "release-execution-20261003/historical-accounting.json"
CANDIDATE = "release-execution-20261003/candidate-index"
GOAL_ANCHOR = "release-execution-20261003/guarded-original120-goal.json"
SUCCESSOR_AUTHORIZATION_SHA256 = "ad46e2cd9ce9b1bbd4142d6f156da6f81ca9c3e9d3c9ef956bb9dad067ba8dce"
# Read-only owner safety inventory accompanying this one exact authorization.
SUCCESSOR_MONTHLY_FLOOR_NUSD = 372_507_682
KNOWN_COST_AUTHORIZATION_SHA256 = "327a6cc2e080c223858cca75b87402416c813eacb0e8528f85592793e74f9e0c"
PRIOR_PROBE = (
    "docker-staging-20261002/claim-value-format-20261002/review-format-fix/run-1/probe.json"
)
SOURCES = {
    "bundle": (
        "2025-26/reliability-approved-20260928.json.gz",
        "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b",
    ),
    "trajectories": (
        "source-support-20261003/derived-source/e2e-final/approved/derived-scoring-events.jsonl",
        "4baa15e256e050d713cb2d397a1ce0022390b116c4cff80ba368bf0079912174",
    ),
    "source_review": (
        "source-support-20261003/derived-source/e2e-final/approved/derived-source-review.json",
        "2229ca1f1b352059bbcc3b34b469aa8c0b1432f275a3198f5add98b341dfca33",
    ),
    "comparisons": (
        "source-support-20261003/measure-comparisons/e2e-verified/approved/measure-comparisons.json",
        "4ff9bfc6977c622b85e2074291dbf22addb9128203d2ee76338c5715456ab68b",
    ),
}
FROZEN = {
    GOLD: "60184f109dd9d9f3cb1a68adf6d39f477711324792a4ff6aa75b12fd8eb15dfe",
    APPROVAL: "4b685a6836f10585fe4284833ffc20c2ce589200ae3efd7f87838b7a99a7e867",
    HISTORY: "8049c1ecd70507ca3d1c8491595402d794aa9885269689ceb2f634f0257fe825",
    PRIOR_PROBE: "1e6802cc9daa80a1cab8df18101183b0b1f42f58ca24a129c46679ec3d70d4b7",
    CANDIDATE + "/manifest.json": (
        "0f41080ae853c125ea1c388977eac774a9f0117a0a9b5c29337f9dcc1cdc0515"
    ),
    CANDIDATE + "/preparation-receipt.json": (
        "6bc71611cc99ffb5fdcf41b3a1aef33c2880062fe3d5dbaf517ae3b397821189"
    ),
    CANDIDATE
    + "/qdrant_payloads.jsonl": "2331f5ef4f89cf37d029db923e9679e5dc74e3e04e1f1ad904adab381ab7de4d",
    CANDIDATE
    + "/archive_units.jsonl": "8175ec4ea95f6c5005bd7c49f34c21bfc8ce15b5500176cc41656b2b5221e8b3",
    "source-support-20261003/source-units/cohort-inputs.json": (
        "d3f1ab15468b1b5abf21d091142f111623b77ad087396f6810478ccb8c0eedb8"
    ),
    **{path: sha for path, sha in SOURCES.values()},
}
COLLECTIONS = {
    base: base + "__2025_26_20260928_1__source_support_20261003_ac5018b"
    for base in ("knicks_possessions", "knicks_games", "knicks_box_scores", "knicks_reports")
}
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
    """Read existing monthly authority; never initialize/reconcile/reset it."""

    def __init__(
        self, *, month: str, historical_floor: str, retained: dict[str, str] | None = None
    ):
        self.month = month
        self.key = "ai-budget:" + month
        self.floor = money(historical_floor)
        self.run_id: str | None = None
        self.retained = dict(retained or {})

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
            require(
                not (self.retained.keys() & active.keys()), "Retained hold reused by active turn"
            )
            require(
                current == {**self.retained, **active},
                "Unresolved, changed retained, or foreign monthly reservations",
            )
            require(
                nusd(self.floor) <= nusd(total) and total < MONTHLY_CUTOFF,
                "Historical charge floor or real $2 cutoff violated",
            )
            require(
                sum((money(value) for value in current.values()), Decimal(0)) <= total,
                "Reservations exceed monthly authority",
            )
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
                    "Stored candidate embedding is not normalized local 384-dimensional data",
                )
        return points, offset


class Admission:
    def __init__(
        self, *, evidence_root: Path, artifact_dir: Path, api_key: str, ledger: MonthlyLedger
    ):
        self.root, self.artifact_dir = evidence_root.resolve(), artifact_dir
        self.api_key, self.ledger = api_key, ledger
        self.contract_sha256 = FROZEN[GOLD]
        self.cases = load_contract(self.root / GOLD, self.root / APPROVAL)["cases"]
        self.manifest = json.loads((self.root / CANDIDATE / "manifest.json").read_text())
        self.receipt = json.loads((self.root / CANDIDATE / "preparation-receipt.json").read_text())
        self.metadata_count = 0
        self.resource_binding: dict | None = None
        self.alias_binding: dict | None = None
        self.records: dict[str, list[dict]] | None = None

    def verify_inputs(self) -> None:
        for relative, expected in FROZEN.items():
            require(
                file_hash(self.root / relative) == expected,
                "Frozen source/contract/approval evidence changed: " + relative,
            )
        require(
            self.receipt["source_hashes"] == {key: sha for key, (_, sha) in SOURCES.items()},
            "Comparison/archive source identity changed",
        )
        require(
            self.manifest["candidate_aliases"] == COLLECTIONS
            and self.manifest["data_version"] == VERSION
            and self.manifest["index_revision"] == REVISION
            and not self.manifest["aliases_promoted"]
            and not self.manifest["qdrant_reset"]
            and self.manifest["games"] == 101
            and self.manifest["events"] == 46500
            and self.manifest["archive_source_units"] == 184,
            "Candidate namespace or original workload coverage differs",
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
            and settings.ai_chat_model == MODEL
            and settings.openrouter_monthly_cutoff_usd == 2
            and settings.ai_reasoning_effort is None
            and settings.analyst_evidence_loop_enabled
            and settings.rag_archive_source_units_enabled
            and settings.rag_qdrant_enabled
            and not settings.rag_qdrant_cloud_inference
            and not settings.rag_llm_planner_enabled
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
            and settings.public_chat_rate_limit_per_minute == 10
            and settings.public_chat_rate_limit_per_day == 100
            and settings.analysis_shadow_sample_rate == 0.1
            and settings.analysis_answer_mode == ("llm_primary" if mode == "primary" else "shadow"),
            "Configuration differs from isolated original release contract",
        )
        require(
            os.environ.get("HF_HUB_OFFLINE") == "1"
            and os.environ.get("TRANSFORMERS_OFFLINE") == "1",
            "Local embedding admission forbids model downloads or cloud fallback",
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
        require(
            settings.openrouter_allowed_models in ([], [MODEL]), "Foreign provider/model allowlist"
        )

    async def docker_identity(self) -> dict:
        """Hard GET-only, exact inspect endpoints; no generic daemon request seam."""
        # Docker's container network mode inherits PostgreSQL's hostname.
        # The controller supplies this verifier's full daemon identity at exec.
        own = os.environ.get("KNICKSIQ_VERIFIER_CONTAINER_ID", "")
        require(
            re.fullmatch(r"[a-f0-9]{64}", own) is not None,
            "Missing exact controller-bound verifier container identity",
        )
        endpoints = {"/networks/" + NETWORK}
        endpoints.add("/networks/" + EGRESS_NETWORK)
        endpoints.update(
            "/containers/" + identity + "/json" for identity, _, _ in RESOURCES.values()
        )
        endpoints.add("/containers/" + own + "/json")
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock", retries=0)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            follow_redirects=False,
            timeout=5,
            trust_env=False,
        ) as client:

            async def inspect(path: str) -> dict:
                require(path in endpoints, "Docker inspect endpoint not authorized")
                response = await client.get(path)
                response.raise_for_status()
                return response.json()

            network = await inspect("/networks/" + NETWORK)
            require(
                network["Id"] == NETWORK and network["Name"] == NETWORK_NAME,
                "Wrong isolated Docker network",
            )
            result = {}
            for role, (identity, name, _) in RESOURCES.items():
                item = await inspect("/containers/" + identity + "/json")
                attached = item["NetworkSettings"]["Networks"].get(NETWORK_NAME, {})
                require(
                    item["Id"] == identity
                    and item["Name"] == "/" + name
                    and item["State"]["Running"]
                    and attached.get("NetworkID") == NETWORK
                    and bool(attached.get("IPAddress")),
                    "Wrong or inactive isolated Docker resource",
                )
                result[role] = {
                    "container_id": identity,
                    "image_id": item["Image"],
                    "address": attached["IPAddress"],
                }
            verifier = await inspect("/containers/" + own + "/json")
            shared_postgres = verifier["HostConfig"]["NetworkMode"] in {
                "container:" + RESOURCES["postgres"][0],
                "container:" + RESOURCES["postgres"][1],
            }
            attachments = verifier["NetworkSettings"]["Networks"]
            isolated_egress = (
                set(attachments) == {NETWORK_NAME, EGRESS_NETWORK_NAME}
                and attachments[NETWORK_NAME]["NetworkID"] == NETWORK
                and attachments[EGRESS_NETWORK_NAME]["NetworkID"] == EGRESS_NETWORK
            )
            require(
                verifier["Id"] == own
                and verifier["State"]["Running"]
                and (shared_postgres or isolated_egress),
                "Verifier is not bound to exact isolated resource and egress networks",
            )
            if isolated_egress:
                egress = await inspect("/networks/" + EGRESS_NETWORK)
                require(
                    egress["Id"] == EGRESS_NETWORK
                    and egress["Name"] == EGRESS_NETWORK_NAME
                    and not egress["Internal"],
                    "Wrong verifier-only outbound network",
                )
            result["postgres"]["sql_address"] = (
                "127.0.0.1" if shared_postgres else result["postgres"]["address"]
            )
            result["verifier"] = {
                "container_id": own,
                "image_id": verifier["Image"],
                "network_mode": verifier["HostConfig"]["NetworkMode"],
                "egress_network_id": EGRESS_NETWORK if isolated_egress else None,
            }
            # Docker environment arrays can contain secrets; never persist them.
            return result

    async def verify_resources(self, *, full: bool) -> dict:
        from app.core.db import AsyncSessionLocal
        from app.models.comparison_source import ComparisonSource
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
        resources = await self.docker_identity()
        database = urlsplit(settings.effective_db_url)
        require(
            database.scheme == "postgresql+asyncpg"
            and database.hostname == resources["postgres"]["sql_address"]
            and database.port == 5432
            and database.path == "/knicksiq"
            and database.username == "knicksiq",
            "Wrong isolated SQL connection",
        )
        for role, url in (
            ("redis", settings.redis_url or ""),
            ("qdrant", settings.qdrant_url or ""),
        ):
            parsed = urlsplit(url)
            require(
                parsed.scheme == ("redis" if role == "redis" else "http")
                and parsed.hostname in {RESOURCES[role][1], resources[role]["address"]}
                and parsed.port == RESOURCES[role][2]
                and not parsed.query
                and not parsed.fragment
                and parsed.path in ({"/14"} if role == "redis" else {"", "/"}),
                "Runtime endpoint is not the exact admitted Docker resource",
            )
        async with AsyncSessionLocal() as db:
            identity = (
                await db.execute(
                    text(
                        "SELECT system_identifier::text, current_database(), current_user, "
                        "host(inet_server_addr()) FROM pg_control_system()"
                    )
                )
            ).one()
            require(
                tuple(identity)
                == (
                    POSTGRES_SYSTEM_ID,
                    "knicksiq",
                    "knicksiq",
                    resources["postgres"]["sql_address"],
                ),
                "Wrong PostgreSQL cluster/SQL identity",
            )
            release = (
                await db.execute(select(DatasetRelease).where(DatasetRelease.status == "active"))
            ).scalar_one()
            source = await db.get(ComparisonSource, release.id)
            require(
                release.id == self.receipt["release_id"]
                and release.version == VERSION
                and release.validation_passed
                and release.manifest_sha256 == SOURCES["bundle"][1]
                and source is not None
                and source.bundle_sha256 == SOURCES["bundle"][1]
                and source.source_sha256 == SOURCES["comparisons"][1]
                and source.source_review_sha256 == SOURCES["source_review"][1]
                and source.trajectories_sha256 == SOURCES["trajectories"][1]
                and source.facts_sha256 == self.receipt["source_facts_sha256"]
                and source.bindings_sha256 == self.receipt["source_bindings_sha256"],
                "Active archive/comparison source identity changed",
            )
            assert source is not None
            require(
                hashlib.sha256(source.facts_json.encode()).hexdigest() == source.facts_sha256
                and hashlib.sha256(source.bindings_json.encode()).hexdigest()
                == source.bindings_sha256,
                "Stored comparison facts/bindings differ from their proof",
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
            not any(target in aliases for target in COLLECTIONS.values()),
            "Physical candidate replaced by an alias",
        )
        if self.alias_binding is not None:
            require(aliases == self.alias_binding, "Qdrant aliases changed during guarded goal")
        counts = {
            "knicks_possessions": 15864,
            "knicks_games": 265,
            "knicks_box_scores": 2970,
            "knicks_reports": 101,
        }
        for base, target in COLLECTIONS.items():
            if full:
                assert self.records is not None
                require(
                    len(self.records[base]) == counts[base], "Source-derived point coverage changed"
                )
                validate_candidate_identity(
                    target, VERSION, self.records[base], client=NormalizedCandidateClient(qdrant)
                )
            else:
                validate_candidate_collection(target, VERSION, counts[base], client=qdrant)
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
                require(
                    abs(
                        sum(value * value for value in vector if isinstance(value, (int, float)))
                        - 1
                    )
                    < 0.001,
                    "Candidate probe point embedding changed",
                )
        if full:
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
            "docker": resources,
            "postgres_system_id": POSTGRES_SYSTEM_ID,
            "release_id": self.receipt["release_id"],
            "data_version": VERSION,
            "source_hashes": self.receipt["source_hashes"],
            "candidate_collections": COLLECTIONS,
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
        with (self.root / CANDIDATE / "qdrant_payloads.jsonl").open() as handle:
            records["knicks_possessions"] = [json.loads(line) for line in handle if line.strip()]
        units = await build_archive_units(db, games, VERSION)
        require(len(units) == 184, "Incomplete source-aware index population")
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
                    "mode": "local",
                    "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
                    "source_unit_schema": UNIT_RECIPE,
                }
        return records

    async def provider_metadata(self) -> dict:
        observed = {}
        async with httpx.AsyncClient(follow_redirects=False, timeout=10, trust_env=False) as client:
            for name, endpoint in (
                ("key", "key"),
                ("credits", "credits"),
                ("model", "models"),
                ("routes", "models/" + MODEL + "/endpoints"),
            ):
                response = await client.get(
                    "https://openrouter.ai/api/v1/" + endpoint,
                    headers={"Authorization": "Bearer " + self.api_key},
                )
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
        require(
            model.get("canonical_slug") == "deepseek/deepseek-v4.1-flash-20260910"
            and isinstance(model.get("reasoning"), dict)
            and model["reasoning"].get("mandatory") is False
            and "reasoning" in (model.get("supported_parameters") or [])
            and (model.get("architecture") or {}).get("output_modalities") == ["text"],
            "Current model cannot admit explicitly disabled reasoning and bounded text output",
        )
        routes = observed["routes"]
        require(
            routes.get("id") == MODEL and isinstance(routes.get("endpoints"), list),
            "Missing pinned model routes",
        )
        matches = [item for item in routes["endpoints"] if item.get("tag") == ROUTE]
        require(len(matches) == 1, "Pinned provider endpoint unavailable")
        route = matches[0]
        require(
            route.get("model_id") == MODEL
            and route.get("provider_name") == PROVIDER
            and route.get("quantization") == "fp8"
            and route.get("status") == 0,
            "Provider/model/quantization identity changed",
        )
        pricing = route.get("pricing")
        require(
            isinstance(pricing, dict)
            and {"prompt", "completion"} <= pricing.keys()
            and set(pricing)
            <= {
                "prompt",
                "completion",
                "request",
                "input_cache_read",
                "input_cache_write",
                "discount",
            },
            "Missing or unknown billable provider pricing fields",
        )
        rates = {key: money(value) for key, value in pricing.items()}
        require(rates.get("discount", Decimal(0)) == 0, "Unbounded provider discount semantics")
        require(rates["prompt"] > 0 and rates["completion"] > 0, "Unverified paid route pricing")
        credits = observed["credits"]
        credit = money(credits.get("total_credits")) - money(credits.get("total_usage"))
        require(credit > 0, "Insufficient actual account credit")
        key = observed["key"]
        monthly = money(key.get("usage_monthly"))
        require(
            monthly < MONTHLY_CUTOFF and key.get("is_free_tier") is False,
            "Wrong key tier or provider UTC-month cutoff exhausted",
        )
        remaining = key.get("limit_remaining")
        if remaining is not None:
            credit = min(credit, money(remaining))
        result = {
            "observed_at": datetime.now(UTC).isoformat(),
            "key_sha256": hashlib.sha256(self.api_key.encode()).hexdigest(),
            "key": {
                field: key.get(field)
                for field in ("usage", "usage_monthly", "limit", "limit_remaining", "is_free_tier")
            },
            "remaining_account_credit_usd": str(credit),
            "route": route,
            "model": model,
            "completion_requests": 0,
        }
        result["parameter_documentation"] = {
            "reasoning": "https://openrouter.ai/docs/guides/best-practices/reasoning-tokens",
            "routing": "https://openrouter.ai/docs/guides/routing/provider-selection",
            "reasoning_policy": (
                "Unified reasoning.enabled=false; model is not mandatory, and selected "
                "endpoint advertises reasoning support. All visible output remains billed "
                "and bounded by actual max_tokens."
            ),
        }
        self.metadata_count += 1
        path = self.artifact_dir / f"provider-metadata-{self.metadata_count:06d}.json"
        durable_json(path, result)
        result["metadata_sha256"] = file_hash(path)
        return result

    async def verify_environment(self, identity: dict) -> None:
        mode = identity["mode"]
        require(mode in {"primary", "shadow"}, "Unsupported original workload mode")
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
            "Changed original case identities or fixed 10% shadow membership",
        )
        self.resource_binding = await self.verify_resources(full=True)
        ledger = await self.ledger.read()
        metadata = await self.provider_metadata()
        require(
            money(ledger["amount_usd"]) >= money(metadata["key"]["usage_monthly"]),
            "Provider monthly charges are not fully reconciled into Redis",
        )
        self.ledger.run_id = ledger["redis_run_id"]
        durable_json(
            self.artifact_dir / "environment-admission.json",
            {
                "identity": identity,
                "resources": self.resource_binding,
                "ledger": ledger,
                "provider_metadata_sha256": metadata["metadata_sha256"],
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
        route = metadata["route"]
        require(
            set(payload)
            <= {
                "model",
                "messages",
                "temperature",
                "max_tokens",
                "provider",
                "response_format",
                "reasoning",
            }
            and payload.get("model") == MODEL
            and payload.get("temperature") == 0
            and type(payload.get("max_tokens")) is int
            and 0 < payload["max_tokens"] <= 1200,
            "Actual payload has unbounded/foreign parameters",
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
        assert isinstance(messages, list)
        require("reasoning" not in payload, "Unbounded reasoning override")
        # Unified enabled=false is the documented disable switch. Unlike an
        # unsupported effort='none', it does not invent an accepted effort level.
        # Seal BEFORE payload hashing, counted reservation, or transmission.
        payload["reasoning"] = {"enabled": False}
        parameters = {"temperature", "max_tokens", "response_format", "reasoning"}
        format_type = payload["response_format"].get("type")
        require(format_type in {"json_object", "json_schema"}, "Unbounded provider response format")
        if format_type == "json_schema":
            parameters.add("structured_outputs")
        require(
            parameters <= set(route.get("supported_parameters") or [])
            and parameters <= set(metadata["model"].get("supported_parameters") or []),
            "Current model/provider lacks actual parameter support",
        )
        # UTF-8 bytes upper-bound text tokens; account separately for message and
        # schema framing. No inferred chars/4 ratio and no optimistic cache credit.
        input_tokens = sum(len(message["content"].encode()) + 64 for message in messages)
        input_tokens += (
            len(json.dumps(payload["response_format"], ensure_ascii=False).encode()) + 512
        )
        output_tokens = payload["max_tokens"]
        require(
            type(route.get("context_length")) is int
            and input_tokens + output_tokens <= route["context_length"],
            "Provider context bound exceeded",
        )
        for field, needed in (
            ("max_prompt_tokens", input_tokens),
            ("max_completion_tokens", output_tokens),
        ):
            limit = route.get(field)
            require(
                limit is None or (type(limit) is int and needed <= limit),
                "Provider token limit incompatible",
            )
        rates = {key: money(value) for key, value in route["pricing"].items()}
        prompt_rate = rates["prompt"] + max(
            rates.get("input_cache_read", Decimal(0)), rates.get("input_cache_write", Decimal(0))
        )
        bound = (
            input_tokens * prompt_rate
            + output_tokens * rates["completion"]
            + rates.get("request", Decimal(0))
        )
        require(
            bound > 0 and bound <= money(get_settings().analyst_call_reservation_usd),
            "Actual payload exceeds normal analyst reservation",
        )
        require(
            money(ledger["amount_usd"]) >= money(metadata["key"]["usage_monthly"])
            and money(metadata["remaining_account_credit_usd"]) >= bound
            and money(metadata["key"]["usage_monthly"]) + bound <= MONTHLY_CUTOFF,
            "Actual provider funding/monthly headroom unavailable",
        )
        # This dict is the one the existing adapter transmits. Seal the route after
        # reading fresh bounds, with no fallback/model router or parameter ignore.
        payload["provider"] = {
            "only": [ROUTE],
            "order": [ROUTE],
            "allow_fallbacks": False,
            "require_parameters": True,
            "quantizations": ["fp8"],
            "max_price": {
                "prompt": float(rates["prompt"] * 1_000_000),
                "completion": float(rates["completion"] * 1_000_000),
                "request": float(rates.get("request", Decimal(0))),
            },
        }
        return {
            "bound_nusd": nusd(bound),
            "route": ROUTE,
            "provider": PROVIDER,
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
        require(
            turn is not None and turn.get("prepared") is not None,
            "Uncounted provider transport invocation",
        )
        assert turn is not None
        prepared = turn.pop("prepared")
        require(
            request.method == "POST"
            and str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
            and request.headers.get("authorization") == "Bearer " + session.api_key
            and digest(json.loads(request.content)) == prepared["payload_sha256"],
            "Actual outbound request differs from verified payload/identity",
        )
        with session.budget._connect() as db:
            ticket = current_ticket.get()
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
                "provider": prepared["provider"],
                "route": prepared["route"],
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
                "payload": json.loads(request.content),
                "join": row,
                "input_token_bound": prepared.get("input_token_bound"),
                "output_token_bound": prepared.get("output_token_bound"),
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
                and body.get("provider") == prepared["provider"]
                and isinstance(body.get("id"), str)
                and bool(body["id"]),
                "Missing/mismatched provider generation identity",
            )
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
                    await session.retain_known_cost(turn, reservation)
                finally:
                    # The existing journal records the actual amount and stops
                    # even if Redis retention itself becomes unavailable.
                    session.budget.settle(ticket, cost)
            for field, limit in (
                ("prompt_tokens", prepared.get("input_token_bound")),
                ("completion_tokens", prepared.get("output_token_bound")),
            ):
                tokens = body["usage"].get(field)
                if tokens is not None:
                    require(
                        type(tokens) is int and tokens >= 0 and (limit is None or tokens <= limit),
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
        if self.session.subject_namespace:
            scope = {**scope, "client": (self.session.subject_clients[request_id], 12345)}
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
    """Join counted stages independently of their HTTP answer mode."""
    require(
        all(row["status"] == "settled" for row in receipts),
        "Unreconciled case/provider journal joins",
    )
    rows = {row["journal_ticket"]: row for row in receipts}
    calls = budget.snapshot()["calls"]
    for call in calls:
        joined = rows.get(call["id"])
        expected_mode = "shadow" if call["stage"] == "load" else call["stage"]
        require(
            joined is not None
            and call["status"] == "settled"
            and joined["cost_nusd"] == call["amount_nusd"]
            and joined["stage"] == call["stage"]
            and joined["mode"] == expected_mode
            and joined["journal_binding"] == binding,
            "Missing/mismatched counted case/provider cost join",
        )
    require(
        len(rows) == len(receipts) == len(calls),
        "Foreign provider receipt without journal call",
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
            self.binding = db.execute("SELECT binding FROM identity").fetchone()[0]
            stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
            self.subject_namespace = self.binding if stored.get("successor") else None
        self.subject_clients = (
            {
                request_id: (
                    f"guarded-successor-{self.subject_namespace}-load"
                    if self.stage == "load"
                    else f"guarded-successor-{self.subject_namespace}-{index + 1}"
                )
                for index, request_id in enumerate(bound_ids)
            }
            if self.subject_namespace
            else {}
        )
        self.execution = CountedRun(
            api_key=api_key,
            budget=budget,
            verify_environment=admission.verify_environment,
            verify_request=self.verify_request,
            transport=GuardedTransport(self, provider_transport),
        )
        self.execution.failed = self.failed
        self.execution.subject_namespace = self.subject_namespace
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

    async def retain_known_cost(self, turn: dict, reservation: dict) -> None:
        rows = {row["journal_ticket"]: row for row in self.receipts()}
        known = [
            rows[ticket].get("reported_cost_nusd", rows[ticket].get("cost_nusd"))
            for ticket in reservation["tickets"]
        ]
        require(
            all(type(value) is int and value >= 0 for value in known),
            "Known provider exposure lost its reservation join",
        )
        amount = 0
        for value in known:
            assert isinstance(value, int)
            amount += value
        reservation["uncertain"] = True
        reservation["known_cost_nusd"] = amount
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
        require(turn["calls"] < 6, "Original per-case request cap exceeded")
        owned = self.owned()
        bounds = await self.admission.verify_request(payload, owned)
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
            snapshot["inherited_calls"] == stored.get("successor", {}).get("calls", []),
            "Successor inherited exposure changed before transmission",
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
        from app.services import analyst_loop, analyst_sessions, report_llm

        session = self
        original_factory = main.create_app
        original_reservation = analyst_loop.BudgetReservation
        original_sync = report_llm.OpenAICompatibleLLMAdapter._generate_sync
        original_generate = report_llm.OpenAICompatibleLLMAdapter.generate
        original_begin_descriptor = analyst_sessions.SessionTurn.__dict__["begin"]
        original_begin = analyst_sessions.SessionTurn.begin

        async def bound_begin(
            cls: type[analyst_sessions.SessionTurn],
            token: str | None,
            turn_id: str,
            revision: int,
            request: dict[str, Any],
        ) -> analyst_sessions.SessionTurn:
            turn = _turn.get()
            if session.subject_namespace and turn is not None:
                require(turn_id == turn["request_id"], "Unbound successor session identity")
                internal_turn_id = "guarded-successor:" + session.subject_namespace + ":" + turn_id
                return await original_begin(token, internal_turn_id, revision, request)
            return await original_begin(token, turn_id, revision, request)

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
            raise RuntimeError("Uncounted/legacy provider path denied in guarded workload")

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
            setattr(analyst_sessions.SessionTurn, "begin", classmethod(bound_begin))
            yield
        finally:
            main.create_app = original_factory
            analyst_loop.BudgetReservation = original_reservation
            report_llm.OpenAICompatibleLLMAdapter._generate_sync = original_sync
            report_llm.OpenAICompatibleLLMAdapter.generate = original_generate
            setattr(analyst_sessions.SessionTurn, "begin", original_begin_descriptor)


def successor_lineage(
    root: Path, goal: Path, authorization: Path | None, predecessor_goal: Path | None
) -> dict | None:
    """Authenticate the stopped predecessor without opening it for modification."""
    require(
        (authorization is None) == (predecessor_goal is None),
        "Successor requires both explicit authorization and predecessor goal",
    )
    if authorization is None:
        return None
    assert predecessor_goal is not None
    authorization_sha = file_hash(authorization.resolve())
    if authorization_sha == KNOWN_COST_AUTHORIZATION_SHA256:
        return known_cost_lineage(root, goal, authorization, predecessor_goal)
    require(
        authorization_sha == SUCCESSOR_AUTHORIZATION_SHA256,
        "Successor authorization differs from exact owner safety choice",
    )
    approved = json.loads(authorization.read_text())
    require(
        approved["user_safety_choice"] == "New counted live attempt"
        and approved["preserve_all_predecessor_charges_and_reservations"] is True
        and approved["original_case_and_request_limits_remain"] is True
        and approved["monthly_cutoff_usd_remains"] == "2"
        and approved["expected_frozen_contract_sha256"] == FROZEN[GOLD],
        "Successor authorization changes preserved accounting or frozen contract",
    )
    predecessor = predecessor_goal.resolve()
    authorized_predecessor = root / Path(approved["predecessor_goal"]).relative_to("/evidence")
    require(
        predecessor == authorized_predecessor.resolve()
        and predecessor.is_relative_to(root)
        and predecessor != root
        and predecessor != goal,
        "Successor substitutes or reuses predecessor goal",
    )
    journal = predecessor / "goal.sqlite"
    require(
        file_hash(journal) == approved["predecessor_journal_sha256"],
        "Stopped predecessor journal differs from owner-authorized SHA",
    )
    anchor = json.loads((root / GOAL_ANCHOR).read_text())
    artifact = json.loads((predecessor / "goal-binding.json").read_text())
    require(
        anchor["goal_dir"] == str(predecessor)
        and anchor["binding_sha256"] == artifact["binding_sha256"],
        "Predecessor differs from immutable original aggregate anchor",
    )
    from app.api.analysis import _sample_shadow

    cases = load_contract(root / GOLD, root / APPROVAL)["cases"]
    selected = sum(
        _sample_shadow(evaluation_request_id(FROZEN[GOLD], "shadow", case["id"]), 0.1)
        for case in cases
    )
    db = sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True)
    try:
        require(
            db.execute("SELECT binding, stopped FROM identity").fetchall()
            == [(artifact["binding_sha256"], 1)],
            "Authorized predecessor is not the stopped bound original goal",
        )
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        require(
            {"binding_sha256": artifact["binding_sha256"], **stored} == artifact
            and stored["frozen_inputs"] == FROZEN
            and stored["monthly_cutoff_nusd"] == 2_000_000_000,
            "Predecessor source/contract/accounting binding differs",
        )
        require(
            dict(db.execute("SELECT name, request_cap FROM stages"))
            == {"smoke": 9, "primary": 720, "shadow": 6 * selected, "load": 66},
            "Predecessor original phase/request ceilings changed",
        )
        require(
            db.execute("SELECT sha256 FROM spending_direction").fetchall()
            == [(SPENDING_DIRECTION_SHA256,)],
            "Predecessor lacks retained original spending direction",
        )
        phases = dict(db.execute("SELECT mode, status FROM guard_runs"))
        require(
            "failed" in phases.values() and "started" not in phases.values(),
            "Predecessor phase is not actually stopped",
        )
        calls = [
            dict(zip(("id", "stage", "amount_nusd", "status", "error"), row, strict=True))
            for row in db.execute("SELECT id, stage, amount, status, error FROM calls ORDER BY id")
        ]
        require(
            bool(calls)
            and all(
                row["status"] in {"settled", "failed"}
                and type(row["amount_nusd"]) is int
                and row["amount_nusd"] >= 0
                for row in calls
            ),
            "Predecessor has missing or in-flight counted exposure",
        )
        receipts = [
            json.loads(row[0])
            for row in db.execute("SELECT receipt FROM guard_receipts ORDER BY ticket")
        ]
        normal = [
            json.loads(row[0])
            for row in db.execute("SELECT receipt FROM guard_normal ORDER BY identity")
        ]
        joined = {row["journal_ticket"]: row for row in receipts}
        require(
            len(joined) == len(receipts) == len(calls),
            "Predecessor counted receipt inventory differs",
        )
        normals = {row["identity"]: row for row in normal}
        for call in calls:
            receipt = joined.get(call["id"], {})
            reservation = normals.get(receipt.get("normal_reservation_id"), {})
            require(
                receipt.get("journal_binding") == artifact["binding_sha256"]
                and receipt.get("stage") == call["stage"]
                and call["id"] in reservation.get("tickets", [])
                and (
                    receipt.get("status") == "settled"
                    and receipt.get("cost_nusd") == call["amount_nusd"]
                    if call["status"] == "settled"
                    else receipt.get("status") == "uncertain"
                ),
                "Predecessor request/cost/normal reservation joins differ",
            )
        retained = {row["identity"]: row["amount"] for row in normal if row["settled"] is False}
        require(
            len(retained) == 2 and all(money(value) > 0 for value in retained.values()),
            "Predecessor retained normal hold inventory differs",
        )
    finally:
        db.close()
    require(
        file_hash(journal) == approved["predecessor_journal_sha256"],
        "Predecessor journal changed while reading lineage",
    )
    return {
        "authorization_sha256": SUCCESSOR_AUTHORIZATION_SHA256,
        "predecessor_goal": approved["predecessor_goal"],
        "predecessor_journal_sha256": approved["predecessor_journal_sha256"],
        "predecessor_binding_sha256": artifact["binding_sha256"],
        "predecessor_binding": stored,
        "calls": calls,
        "receipts": receipts,
        "normal_reservations": normal,
        "retained_reservations": retained,
        "authoritative_monthly_floor_nusd": SUCCESSOR_MONTHLY_FLOOR_NUSD,
    }


def successor_anchor(root: Path, lineage: dict | None) -> Path:
    anchor = root / GOAL_ANCHOR
    if lineage is None:
        return anchor
    identity = lineage["authorization_sha256"]
    if identity == KNOWN_COST_AUTHORIZATION_SHA256:
        identity += "-" + lineage["predecessor_journal_sha256"]
    else:
        require(identity == SUCCESSOR_AUTHORIZATION_SHA256, "Foreign successor authorization")
    return anchor.with_name("guarded-counted-successor-" + identity + ".json")


def evidence_goal(root: Path, declared: str) -> Path:
    relative = Path(declared).relative_to("/evidence")
    goal = (root / relative).resolve()
    require(
        goal.is_relative_to(root) and goal != root and ".." not in relative.parts,
        "Substituted ancestor evidence path",
    )
    return goal


def admitted_binding_sha(stored: dict) -> str:
    # Admission seals identity before adding inspected resources and the actual
    # Redis admission floor. Retain that historical convention for old journals.
    identity = {
        key: value for key, value in stored.items() if key not in {"resources", "redis_run_id"}
    }
    identity["historical_floor_nusd"] = 72_217_900
    return digest(identity)


def admission_seal(stored: dict) -> dict:
    return {
        "monthly_floor_nusd": stored["historical_floor_nusd"],
        "resources_sha256": digest(stored["resources"]),
        "redis_run_id": stored["redis_run_id"],
    }


def protocol_sources() -> dict[str, str]:
    services = Path(__file__).resolve().parent.parent / "services"
    return {
        name: file_hash(services / name)
        for name in ("analyst_loop.py", "evidence_contracts.py", "analyst_tools.py")
    }


def stage_limits(selected: int) -> dict[str, tuple[int, int]]:
    return {
        "smoke": (9, 100_000_000),
        "primary": (720, 500_000_000),
        "shadow": (6 * selected, 500_000_000),
        "load": (66, 660_000_000),
    }


def target_resources(resources: dict) -> dict:
    return {
        **resources,
        "docker": {
            name: value for name, value in resources.get("docker", {}).items() if name != "verifier"
        },
    }


def validate_protocol_stop(
    goal: Path,
    stored: dict,
    fresh: list[dict],
    receipts: list[dict],
    normal: list[dict],
    phases: dict,
) -> list[dict]:
    """Require settled local financial joins and durable typed-protocol evidence."""
    joined = {row["journal_ticket"]: row for row in receipts}
    normals = {row["identity"]: row for row in normal}
    require(
        bool(fresh) and len(joined) == len(receipts) == len(fresh) and len(normals) == len(normal),
        "Missing or duplicate fresh financial provenance",
    )
    tickets = [ticket for row in normal for ticket in row["tickets"]]
    require(
        sorted(tickets) == sorted(row["id"] for row in fresh) and len(tickets) == len(set(tickets)),
        "Fresh normal ticket inventory differs",
    )
    for reservation in normal:
        require(
            reservation["settled"] is True
            and reservation["uncertain"] is False
            and type(reservation.get("cost_nusd")) is int
            and type(reservation.get("slots")) is int
            and 0 < reservation["slots"] <= 6
            and reservation.get("used") == len(reservation["tickets"]) <= reservation["slots"]
            and money(reservation["amount"]) == Decimal("0.01") * reservation["slots"]
            and 0 <= reservation["cost_nusd"] <= nusd(reservation["amount"])
            and reservation["cost_nusd"]
            == sum(joined[ticket]["cost_nusd"] for ticket in reservation["tickets"]),
            "New normal reservation is held, uncertain or incompletely settled",
        )
    for call in fresh:
        receipt = joined.get(call["id"], {})
        reservation = normals.get(receipt.get("normal_reservation_id"), {})
        require(
            call["status"] == "settled"
            and call["error"] is None
            and receipt.get("status") == "settled"
            and receipt.get("cost_nusd") == receipt.get("reported_cost_nusd") == call["amount_nusd"]
            and type(receipt.get("bound_nusd")) is int
            and 0 <= call["amount_nusd"] <= receipt["bound_nusd"]
            and receipt["bound_nusd"] > 0
            and receipt.get("journal_binding") == admitted_binding_sha(stored)
            and receipt.get("stage") == call["stage"]
            and receipt.get("mode") == ("shadow" if call["stage"] == "load" else call["stage"])
            and call["id"] in reservation.get("tickets", [])
            and reservation.get("request_id") == receipt.get("request_id")
            and reservation.get("case_id") == receipt.get("case_id")
            and receipt.get("model") == stored["model"]
            and receipt.get("provider") == PROVIDER
            and receipt.get("route") == stored["route"]
            and receipt.get("provider_key_sha256") == stored["provider_key_sha256"],
            "Fresh provider cost, bound, identity or normal joins differ",
        )
        directory = goal / call["stage"]
        raw_path = directory / f"response-{call['id']:06d}.body"
        raw = raw_path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == receipt.get("raw_response_sha256")
            and raw_path.stat().st_mode & 0o777 == 0o600,
            "Fresh private wire evidence differs",
        )
        body = json.loads(raw)
        require(
            isinstance(body["id"], str)
            and bool(body["id"])
            and body["id"] == receipt.get("provider_generation_id")
            and body["model"] == stored["model"]
            and body["provider"] == PROVIDER
            and nusd(body["usage"]["cost"]) == call["amount_nusd"]
            and digest(body) == receipt.get("response_sha256")
            and body["choices"][0].get("finish_reason") == receipt.get("finish_reason"),
            "Fresh wire generation/cost differs from settled receipt",
        )
        request = json.loads((directory / f"request-{call['id']:06d}.json").read_text())
        require(
            digest(request["payload"]) == receipt.get("payload_sha256")
            and all(
                request["join"].get(key) == value
                for key, value in receipt.items()
                if key in request["join"] and key != "status"
            ),
            "Fresh private request provenance differs",
        )
    failures = []
    for stage, status in phases.items():
        if status != "failed":
            continue
        local = [call for call in fresh if call["stage"] == stage]
        require(bool(local), "Failed stage has no fresh settled protocol call")
        ticket = local[-1]["id"]
        receipt = joined[ticket]
        path = goal / stage / f"protocol-failure-{ticket:06d}.json"
        diagnosis = json.loads(path.read_text())
        require(
            diagnosis.get("journal_ticket") == ticket
            and diagnosis.get("request_id") == receipt["request_id"]
            and diagnosis.get("raw_response_sha256") == receipt["raw_response_sha256"]
            and diagnosis.get("finish_reason") == receipt.get("finish_reason")
            and diagnosis.get("error_type") == "ValidationError"
            and isinstance(diagnosis.get("errors"), list)
            and bool(diagnosis["errors"])
            and all(
                isinstance(error.get("loc"), list) and isinstance(error.get("type"), str)
                for error in diagnosis["errors"]
            ),
            "Stopped stage lacks exact private typed-protocol diagnosis",
        )
        summary = json.loads((goal / stage / "execution-summary.json").read_text())
        require(
            summary["status"] == "failed"
            and summary["mode"] == receipt["mode"]
            and summary["calls"] == receipts
            and summary["accounting"]["calls"] == fresh,
            "Stopped protocol stage summary differs from local journal",
        )
        failures.append(
            {
                "journal_ticket": ticket,
                "stage": stage,
                "diagnosis_sha256": file_hash(path),
                "raw_response_sha256": receipt["raw_response_sha256"],
            }
        )
    require(bool(failures), "Predecessor is not an actual failed protocol stage")
    return failures


def known_cost_lineage(root: Path, goal: Path, authorization: Path, predecessor_goal: Path) -> dict:
    approved = json.loads(authorization.read_text())
    from app.api.analysis import _sample_shadow

    cases = load_contract(root / GOLD, root / APPROVAL)["cases"]
    selected = sum(
        _sample_shadow(evaluation_request_id(FROZEN[GOLD], "shadow", case["id"]), 0.1)
        for case in cases
    )
    limits = stage_limits(selected)
    require(
        approved["schema_version"] == 1
        and approved["user_safety_choice"] == "Finish original live tests"
        and approved["preserve_all_predecessor_charges_and_reservations"] is True
        and approved["original_case_and_request_limits_remain"] is True
        and approved["stop_on_any_new_financial_uncertainty"] is True
        and approved["deploy_or_alias_promotion_authorized"] is False
        and approved["monthly_cutoff_usd_remains"] == "2"
        and approved["expected_frozen_contract_sha256"] == FROZEN[GOLD]
        and approved["prior_authorization_sha256"] == SUCCESSOR_AUTHORIZATION_SHA256
        and approved["request_caps"] == {name: cap for name, (cap, _) in limits.items()}
        and type(approved["minimum_verified_monthly_authority_nusd"]) is int
        and approved["minimum_verified_monthly_authority_nusd"] >= 372_549_812,
        "Known-cost grant changes preserved owner limits or stop policy",
    )
    original = evidence_goal(root, approved["original_goal"])
    initial = evidence_goal(root, approved["initial_predecessor_goal"])
    predecessor = predecessor_goal.resolve()
    require(
        predecessor.is_relative_to(root) and predecessor not in {root, goal, original},
        "Known-cost successor substitutes or reuses a predecessor",
    )
    expected_fixed = goal_binding(
        root, MonthlyLedger(month=f"{datetime.now(UTC):%Y-%m}", historical_floor="0.0722179")
    )
    source_fields = {
        "guarded_cli_sha256",
        "runner_sha256",
        "load_harness_sha256",
        "verification_budget_sha256",
        "verification_adapter_sha256",
        "historical_floor_nusd",
    }
    seen: set[Path] = set()

    def lineage_for(node: dict) -> dict:
        return {
            "authorization_sha256": KNOWN_COST_AUTHORIZATION_SHA256,
            "predecessor_goal": "/evidence/" + node["goal"].relative_to(root).as_posix(),
            "predecessor_journal_sha256": node["journal_sha256"],
            "predecessor_binding_sha256": node["binding_sha256"],
            "predecessor_binding": node["stored"],
            "calls": node["calls"],
            "receipts": node["receipts"],
            "normal_reservations": node["normal_reservations"],
            "retained_reservations": approved["retained_original_reservations"],
            "authoritative_monthly_floor_nusd": approved["minimum_verified_monthly_authority_nusd"],
            "fresh_calls": node["fresh_calls"],
            "ancestor_journals": node["ancestor_journals"],
            "protocol_failures": node["protocol_failures"],
            "initial_predecessor_goal": approved["initial_predecessor_goal"],
            "initial_predecessor_journal_sha256": approved["initial_predecessor_journal_sha256"],
            "original_goal": approved["original_goal"],
            "original_journal_sha256": approved["original_journal_sha256"],
            "request_caps": approved["request_caps"],
        }

    def read_ancestor(path: Path, expected_sha: str | None = None) -> dict:
        require(path not in seen and path != goal, "Cycle or substituted ancestor in lineage")
        seen.add(path)
        journal = path / "goal.sqlite"
        journal_sha = file_hash(journal)
        if path == original:
            require(journal_sha == approved["original_journal_sha256"], "Original journal changed")
        if path == initial:
            require(
                journal_sha == approved["initial_predecessor_journal_sha256"],
                "Initial known-cost predecessor journal changed",
            )
        require(expected_sha is None or journal_sha == expected_sha, "Ancestor journal SHA differs")
        artifact_path = path / "goal-binding.json"
        artifact_sha = file_hash(artifact_path)
        artifact = json.loads(artifact_path.read_text())
        db = sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True)
        try:
            require(
                db.execute("SELECT binding, stopped FROM identity").fetchall()
                == [(artifact["binding_sha256"], 1)],
                "Ancestor is not the actual stopped bound goal",
            )
            stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
            require(
                artifact == {"binding_sha256": artifact["binding_sha256"], **stored}
                and admitted_binding_sha(stored) == artifact["binding_sha256"]
                and all(
                    stored.get(field) == json.loads(json.dumps(value))
                    for field, value in expected_fixed.items()
                    if field not in source_fields
                ),
                "Ancestor artifact, source-independent binding or identity differs",
            )
            if (
                stored.get("successor", {}).get("authorization_sha256")
                == KNOWN_COST_AUTHORIZATION_SHA256
            ):
                require(
                    stored.get("admission") == admission_seal(stored),
                    "Ancestor admitted floor, resources or Redis identity changed",
                )
            require(
                {
                    name: (cap, cost)
                    for name, cap, cost in db.execute(
                        "SELECT name, request_cap, cost_cap FROM stages"
                    )
                }
                == limits
                and db.execute("SELECT sha256 FROM spending_direction").fetchall()
                == [(SPENDING_DIRECTION_SHA256,)],
                "Ancestor frozen stage limits or spending direction changed",
            )
            phases = dict(db.execute("SELECT mode, status FROM guard_runs"))
            require(
                "failed" in phases.values()
                and "started" not in phases.values()
                and all(status in {"failed", "complete"} for status in phases.values()),
                "Ancestor phase is not actually stopped",
            )
            fresh = [
                dict(zip(("id", "stage", "amount_nusd", "status", "error"), row, strict=True))
                for row in db.execute(
                    "SELECT id, stage, amount, status, error FROM calls ORDER BY id"
                )
            ]
            inherited = [
                dict(zip(("id", "stage", "amount_nusd", "status", "error"), row, strict=True))
                for row in VerificationBudget._inherited(db)
            ]
            receipt_rows = [
                (ticket, json.loads(raw), generation)
                for ticket, raw, generation in db.execute(
                    "SELECT ticket, receipt, generation FROM guard_receipts ORDER BY ticket"
                )
            ]
            normal_rows = [
                (identity, json.loads(raw))
                for identity, raw in db.execute(
                    "SELECT identity, receipt FROM guard_normal ORDER BY identity"
                )
            ]
            require(
                all(
                    row["journal_ticket"] == ticket
                    and (path == original or row.get("provider_generation_id") == generation)
                    for ticket, row, generation in receipt_rows
                )
                and all(row["identity"] == identity for identity, row in normal_rows),
                "Ancestor SQLite receipt or reservation keys differ from private provenance",
            )
            receipts = [row for _, row, _ in receipt_rows]
            normal = [row for _, row in normal_rows]
        finally:
            db.close()
        require(
            journal_sha == file_hash(journal) and artifact_sha == file_hash(artifact_path),
            "Immutable ancestor changed while reading",
        )
        own_lineage = stored.get("successor")
        anchor = json.loads(successor_anchor(root, own_lineage).read_text())
        require(
            anchor["goal_dir"] == str(path)
            and anchor["binding_sha256"] == artifact["binding_sha256"],
            "Ancestor differs from its own exclusive admitted anchor",
        )
        require(
            all(
                type(call["id"]) is int
                and call["id"] > 0
                and type(call["amount_nusd"]) is int
                and call["amount_nusd"] >= 0
                and call["stage"] in limits
                for call in fresh + inherited
            ),
            "Invalid ancestor counted exposure",
        )
        ancestor_calls, ancestor_receipts, ancestor_normal, journals = [], [], [], []
        initial_seen = path == initial
        if path == original:
            require(
                not own_lineage and not inherited and bool(fresh),
                "Substituted original chain root",
            )
            joined = {row["journal_ticket"]: row for row in receipts}
            normals = {row["identity"]: row for row in normal}
            require(
                len(joined) == len(receipts) == len(fresh) and len(normals) == len(normal),
                "Original provenance contains duplicates or omissions",
            )
            for call in fresh:
                receipt = joined.get(call["id"], {})
                require(
                    call["status"] in {"settled", "failed"}
                    and receipt.get("journal_binding") == artifact["binding_sha256"]
                    and receipt.get("stage") == call["stage"]
                    and call["id"]
                    in normals.get(receipt.get("normal_reservation_id"), {}).get("tickets", [])
                    and (
                        receipt.get("status") == "settled"
                        and receipt.get("cost_nusd") == call["amount_nusd"]
                        if call["status"] == "settled"
                        else receipt.get("status") == "uncertain"
                    ),
                    "Original owner-authorized financial joins differ",
                )
            retained = {row["identity"]: row["amount"] for row in normal if row["settled"] is False}
            require(
                retained == approved["retained_original_reservations"]
                and len(retained) == 2
                and sorted(retained.values()) == ["0.02", "0.03"],
                "Original retained hold identity or amounts changed",
            )
            failures = []
        else:
            require(isinstance(own_lineage, dict), "Foreign non-successor ancestor")
            parent = read_ancestor(
                evidence_goal(root, own_lineage["predecessor_goal"]),
                own_lineage["predecessor_journal_sha256"],
            )
            ancestor_calls = parent["calls"]
            ancestor_receipts = parent["receipts"]
            ancestor_normal = parent["normal_reservations"]
            journals = parent["ancestor_journals"]
            require(
                inherited == ancestor_calls
                and own_lineage["predecessor_binding_sha256"] == parent["binding_sha256"]
                and own_lineage["predecessor_binding"] == parent["stored"]
                and own_lineage["calls"] == ancestor_calls
                and own_lineage["receipts"] == ancestor_receipts
                and own_lineage["normal_reservations"] == ancestor_normal
                and own_lineage["retained_reservations"]
                == approved["retained_original_reservations"]
                and stored["redis_run_id"] == parent["stored"]["redis_run_id"]
                and target_resources(stored["resources"])
                == target_resources(parent["stored"]["resources"]),
                "Ancestor inherited rows, provenance, holds or target resources changed",
            )
            if path == initial:
                require(
                    parent["goal"] == original
                    and own_lineage["authorization_sha256"] == SUCCESSOR_AUTHORIZATION_SHA256,
                    "Initial stop is not the original authorized successor",
                )
            else:
                require(
                    parent["initial_seen"] and own_lineage == lineage_for(parent),
                    "Descendant does not belong to this exact owner-granted chain",
                )
            failures = validate_protocol_stop(path, stored, fresh, receipts, normal, phases)
            initial_seen = initial_seen or parent["initial_seen"]
        all_calls = ancestor_calls + fresh
        all_receipts = ancestor_receipts + receipts
        all_normal = ancestor_normal + normal
        generations = [
            row["provider_generation_id"]
            for row in all_receipts
            if row.get("provider_generation_id") is not None
        ]
        require(
            len({call["id"] for call in all_calls}) == len(all_calls)
            and len({row["journal_ticket"] for row in all_receipts}) == len(all_receipts)
            and len({row["identity"] for row in all_normal}) == len(all_normal)
            and len(generations) == len(set(generations))
            and all(
                sum(call["stage"] == stage for call in all_calls) <= cap
                for stage, (cap, _) in limits.items()
            ),
            "Duplicate ancestor provenance or exhausted original stage inventory",
        )
        if path == initial:
            require(
                sum(call["stage"] == "primary" for call in all_calls)
                == approved["inherited_primary_requests_at_authorization"],
                "Initial owner-authorized primary inventory differs",
            )
        return {
            "goal": path,
            "journal_sha256": journal_sha,
            "binding_sha256": artifact["binding_sha256"],
            "stored": stored,
            "fresh_calls": fresh,
            "calls": all_calls,
            "receipts": all_receipts,
            "normal_reservations": all_normal,
            "initial_seen": initial_seen,
            "protocol_failures": failures,
            "ancestor_journals": journals
            + [
                {
                    "goal": "/evidence/" + path.relative_to(root).as_posix(),
                    "journal_sha256": journal_sha,
                    "binding_sha256": artifact["binding_sha256"],
                }
            ],
        }

    node = read_ancestor(predecessor)
    require(node["initial_seen"], "Predecessor is not a descendant of the granted initial stop")
    require(file_hash(authorization) == KNOWN_COST_AUTHORIZATION_SHA256, "Owner grant changed")
    return lineage_for(node)


def validate_admitted_goal(goal: Path, budget: VerificationBudget, binding: dict) -> dict:
    """Join the current artifact and journal to the recomputed owner/pred/source pair."""
    with budget._connect() as db:
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        identity = db.execute("SELECT binding FROM identity").fetchone()[0]
    artifact = json.loads((goal / "goal-binding.json").read_text())
    require(
        artifact == {"binding_sha256": identity, **stored}
        and admitted_binding_sha(stored) == identity
        and all(
            stored.get(field) == json.loads(json.dumps(value))
            for field, value in binding.items()
            if field != "historical_floor_nusd"
        )
        and set(stored) == set(binding) | {"resources", "redis_run_id"}
        and type(stored["historical_floor_nusd"]) is int,
        "Current admitted artifact, owner/pred pair or source changed",
    )
    require(
        budget.snapshot()["inherited_calls"] == binding.get("successor", {}).get("calls", []),
        "Current ancestral counted inventory changed",
    )
    lineage = binding.get("successor", {})
    if lineage.get("authorization_sha256") == KNOWN_COST_AUTHORIZATION_SHA256:
        with budget._connect() as db:
            actual_limits = {
                name: (cap, cost)
                for name, cap, cost in db.execute("SELECT name, request_cap, cost_cap FROM stages")
            }
        require(
            stored["admission"] == admission_seal(stored)
            and actual_limits == stage_limits(lineage["request_caps"]["shadow"] // 6)
            and stored["historical_floor_nusd"]
            >= max(
                lineage["authoritative_monthly_floor_nusd"],
                lineage["predecessor_binding"]["historical_floor_nusd"]
                + sum(row["amount_nusd"] for row in lineage["fresh_calls"]),
            ),
            "Admitted floor, resources, Redis identity or frozen limits changed",
        )
    return stored


def goal_context(root: Path, goal: Path, args) -> tuple[MonthlyLedger, dict, Path]:
    lineage = successor_lineage(
        root,
        goal,
        getattr(args, "successor_authorization", None),
        getattr(args, "predecessor_goal", None),
    )
    minimum = (
        max(
            lineage["authoritative_monthly_floor_nusd"],
            lineage["predecessor_binding"]["historical_floor_nusd"]
            + sum(call["amount_nusd"] for call in lineage.get("fresh_calls", lineage["calls"])),
        )
        if lineage
        else 72_217_900
    )
    ledger = MonthlyLedger(
        month=f"{datetime.now(UTC):%Y-%m}",
        historical_floor=str(Decimal(minimum) / 1_000_000_000),
        retained=lineage["retained_reservations"] if lineage else None,
    )
    binding = goal_binding(root, ledger)
    anchor = root / GOAL_ANCHOR
    if lineage:
        predecessor = lineage["predecessor_binding"]
        source_fields = {
            "guarded_cli_sha256",
            "runner_sha256",
            "load_harness_sha256",
            "verification_budget_sha256",
            "verification_adapter_sha256",
            "historical_floor_nusd",
        }
        for field, value in binding.items():
            if field not in source_fields:
                require(
                    predecessor[field] == json.loads(json.dumps(value)),
                    "Successor changes original fixed contract: " + field,
                )
        ledger.run_id = predecessor["redis_run_id"]
        binding["successor"] = lineage
        anchor = successor_anchor(root, lineage)
        if lineage["authorization_sha256"] == KNOWN_COST_AUTHORIZATION_SHA256:
            binding["protocol_sources"] = protocol_sources()
            artifact_path = goal / "goal-binding.json"
            if artifact_path.is_file():
                binding["admission"] = json.loads(artifact_path.read_text())["admission"]
    return ledger, binding, anchor


def goal_binding(root: Path, ledger: MonthlyLedger) -> dict:
    history = json.loads((root / HISTORY).read_text())
    require(
        history["provider_calls"] == 22
        and history["ledger_floor_usd"] == "0.0722179"
        and history["retained_unknown_usd"] == "0.07205728",
        "Retained historical accounting identity changed",
    )
    return {
        "frozen_inputs": FROZEN,
        "model": MODEL,
        "route": ROUTE,
        "provider_key_sha256": DESIGNATED_KEY_SHA256,
        "utc_month": ledger.month,
        "docker_resources": RESOURCES,
        "network_id": NETWORK,
        "postgres_system_id": POSTGRES_SYSTEM_ID,
        "historical_provider_calls": 22,
        "historical_floor_nusd": nusd(history["ledger_floor_usd"]),
        "historical_uncertainty_nusd": nusd(history["retained_unknown_usd"]),
        "historical_probe_sha256": FROZEN[PRIOR_PROBE],
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
        "client_identity_sha256": hashlib.sha256(
            get_settings().ip_hash_secret.encode()
        ).hexdigest(),
        "runtime_settings_sha256": digest(
            get_settings().model_dump(
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
    require(
        goal.is_relative_to(root) and goal != root, "Artifacts must remain in private evidence root"
    )
    # Frozen files are checked before importing DB clients or opening sockets.
    for relative, expected in FROZEN.items():
        require(
            file_hash(root / relative) == expected, "Frozen admission input mismatch: " + relative
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
            not anchor_path.exists(),
            "This authorization/workload already has an aggregate goal; "
            "no duplicate successor, journal reset, or new attempt bypass",
        )
        goal.mkdir(mode=0o700, parents=True, exist_ok=False)
        admission = Admission(evidence_root=root, artifact_dir=goal, api_key=key, ledger=ledger)
        await admission.verify_environment(identity)
        assert admission.resource_binding is not None
        binding["resources"] = admission.resource_binding
        binding["redis_run_id"] = ledger.run_id
        # Redis authority, not the retained historical floor, establishes current
        # spend. Retain any extra existing charges as part of this goal's history.
        current = await ledger.read()
        binding["historical_floor_nusd"] = nusd(current["amount_usd"])
        if (
            binding.get("successor", {}).get("authorization_sha256")
            == KNOWN_COST_AUTHORIZATION_SHA256
        ):
            require(
                target_resources(binding["resources"])
                == target_resources(binding["successor"]["predecessor_binding"]["resources"]),
                "Fresh admission changed original target resources",
            )
            binding["admission"] = admission_seal(binding)
            binding_sha = admitted_binding_sha(binding)
        durable_json(
            anchor_path,
            {
                "goal_dir": str(goal),
                "binding_sha256": binding_sha,
                "policy": "One aggregate goal; no resume/retry or reset after uncertainty",
            },
        )
        path = goal / "goal.sqlite"
        VerificationBudget.create(
            path,
            binding=binding_sha,
            shadow_selected=selected,
            inherited_calls=binding.get("successor", {}).get("calls"),
        )
        budget = VerificationBudget(path, binding=binding_sha)
        direction = args.spending_direction.resolve()
        budget.apply_spending_direction(direction)
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
    path = goal / "goal.sqlite"
    anchor = json.loads(anchor_path.read_text())
    require(
        anchor["goal_dir"] == str(goal) and anchor["binding_sha256"] == binding_sha,
        "Collection does not use the admitted aggregate goal",
    )
    require(
        path.is_file(), "Run admit once before counted collection; no fresh journal/restart bypass"
    )
    budget = VerificationBudget(path, binding=binding_sha)
    admitted = validate_admitted_goal(goal, budget, binding)
    require(
        nusd(ledger.floor) <= admitted["historical_floor_nusd"], "Admitted monthly floor lowered"
    )
    require(
        budget.snapshot()["inherited_calls"] == binding.get("successor", {}).get("calls", []),
        "Successor inherited counted request inventory changed",
    )
    require(
        budget.request_cap("smoke") == 9
        and budget.request_cap("primary") == 720
        and budget.request_cap("shadow") == 6 * selected
        and budget.request_cap("load") == 66,
        "Original phase/request caps changed",
    )
    require(
        not budget.snapshot()["stopped"]
        and budget.snapshot()["spending_direction_sha256"] is not None,
        "Stopped or unapproved aggregate goal",
    )
    with budget._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        stored = json.loads(db.execute("SELECT binding FROM guard_goal").fetchone()[0])
        for field in binding:
            if field != "historical_floor_nusd":
                require(
                    stored[field] == json.loads(json.dumps(binding[field])),
                    "Aggregate goal input binding changed",
                )
        ledger.run_id = stored["redis_run_id"]
        ledger.floor = Decimal(stored["historical_floor_nusd"]) / 1_000_000_000
        require(
            not db.execute("SELECT 1 FROM guard_runs WHERE status != 'complete'").fetchone(),
            "Interrupted/failed phase cannot resume",
        )
        db.execute("INSERT INTO guard_runs VALUES (?, 'started')", (args.mode,))
    run_dir = goal / args.mode
    admission = Admission(evidence_root=root, artifact_dir=run_dir, api_key=key, ledger=ledger)
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
                    "historical_provider_calls": 22,
                }
            )
        )
    except BaseException as exc:
        session.failed(type(exc).__name__)
        raise
    finally:
        with budget._connect() as db:
            db.execute("UPDATE guard_runs SET status=? WHERE mode=?", (status, args.mode))
        durable_json(
            run_dir / "execution-summary.json",
            {
                "status": status,
                "mode": args.mode,
                "historical_provider_calls": 22,
                "calls": session.receipts(),
                "accounting": budget.snapshot(),
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
    parser.add_argument("--successor-authorization", type=Path)
    parser.add_argument("--predecessor-goal", type=Path)
    parser.add_argument("--key-env-file", type=Path)
    parser.add_argument("--staging-env-file", type=Path)
    parser.add_argument(
        "--spending-direction",
        type=Path,
        default=Path(__file__).resolve().parents[4]
        / "docs/release-evidence/implementation-20261001/confirmed-spending-direction.json",
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
            "Missing exact retained owner spending direction",
        )
        if args.key_env_file is not None or args.staging_env_file is not None:
            from dotenv import dotenv_values

            if args.key_env_file is not None:
                key = dotenv_values(args.key_env_file).get("OPENROUTER_API_KEY")
                require(isinstance(key, str) and bool(key), "Designated dotenv lacks provider key")
                assert isinstance(key, str)
                os.environ["OPENROUTER_API_KEY"] = key
            if args.staging_env_file is not None:
                secret = dotenv_values(args.staging_env_file).get("KNICKSIQ_STAGING_IP_HASH_SECRET")
                require(
                    isinstance(secret, str) and bool(secret),
                    "Staging dotenv lacks established client identity",
                )
                assert isinstance(secret, str)
                os.environ["IP_HASH_SECRET"] = secret
            get_settings.cache_clear()
        asyncio.run(run(args))
    except BaseException as exc:
        # HTTP/DB exception text may contain credential-bearing URLs or headers.
        # Private receipts contain safe identity/joins; never print provider bodies.
        print(
            json.dumps({"status": "denied_or_stopped", "error_type": type(exc).__name__}),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
