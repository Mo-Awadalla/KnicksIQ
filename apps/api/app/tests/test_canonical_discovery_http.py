"""Local pre-admission discovery via HTTP/SQL/Redis, specified before code."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.game import Game
from app.services import analyst_loop, analyst_tools
from app.services.archive_units import build_archive_units
from app.services.comparison_sources import import_comparison_source
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, CLOSEST, SHA
from app.tests.test_player_intelligence import _seed_release_stats
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

QUESTIONS = Path(__file__).resolve().parents[1] / "evaluation/questions.jsonl"
QUESTIONS_SHA = "a546b99c36fedb59a475479016b0338fe113c4478d5165c4a5073d144ffdf482"


def configure(monkeypatch, mode):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", 1)
    monkeypatch.setattr(settings, "rag_qdrant_enabled", True)
    attempts = {"provider": 0, "dense": 0, "reservations": 0}

    def provider_denied():
        attempts["provider"] += 1
        raise AssertionError("No provider is authorized in this HTTP probe")

    def dense_denied(**_kwargs):
        attempts["dense"] += 1
        raise AssertionError("Pre-admission discovery must remain local")

    async def reserve_denied(*_args, **_kwargs):
        attempts["reservations"] += 1
        raise AssertionError("Pre-admission discovery cannot reserve paid requests")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", provider_denied)
    monkeypatch.setattr(analyst_tools, "search_archive_vectors", dense_denied)
    monkeypatch.setattr(analyst_loop.AnalystLoop, "reserve", reserve_denied)
    return attempts


def save(tmp_path, name, value):
    directory = Path(os.environ.get("KNICKSIQ_DISCOVERY_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{name}.json").open("x") as artifact:
        json.dump(value, artifact, indent=2)


async def exchange(http, payload):
    with capture_turn() as capture:
        response = await http.post("/analysis/query", json=payload)
    with capture_turn() as replay_capture:
        replay = await http.post("/analysis/query", json=payload)
    conflict = await http.post("/analysis/query", json={**payload, "question": "Changed input"})
    return {
        "request": payload,
        "http_status": response.status_code,
        "response": response.json(),
        "capture": capture,
        "replay_status": replay.status_code,
        "replay": replay.json(),
        "replay_capture": replay_capture,
        "conflict_status": conflict.status_code,
    }


def assert_search(receipt):
    assert receipt["http_status"] == receipt["replay_status"] == 200
    assert receipt["replay"] == receipt["response"]
    assert receipt["conflict_status"] == 409
    assert receipt["replay_capture"]["searches"] == []
    searches = receipt["capture"]["searches"]
    local = [s for s in searches if s.get("purpose") == "canonical_discovery"]
    assert len(local) == 1
    search = local[0]
    assert search["status"] == "ok"
    assert search["dense_evidence_ids"] == [] and not search["dense_failed"]
    assert len(search["candidate_evidence_ids"]) <= 20
    assert search["returned_evidence_ids"] == search["candidate_evidence_ids"][:5]
    assert all(e["release_id"] == search["release"] for e in search["evidence"])
    for item in search["evidence"]:
        if item["game_id"] is not None:
            assert item["game_id"] in search["filters"]["game_ids"]
        elif item["metadata"]["unit_type"] == "multigame_aggregate":
            assert set(item["metadata"]["game_ids"]) <= set(search["filters"]["game_ids"])
        else:
            assert item["metadata"]["unit_type"] == "player_identity"
            assert set(item["metadata"]["player_ids"]) <= set(search["filters"]["player_ids"])
    return search


async def test_original_cohort_records_real_local_discovery(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    attempts = configure(monkeypatch, "disabled")
    async with AsyncSessionLocal() as db:
        loaded = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        proof_path = os.environ.get("KNICKSIQ_DISCOVERY_COMPARISON_INPUTS")
        if proof_path:
            proof = json.loads(Path(proof_path).read_text())
            await import_comparison_source(
                db,
                **{name: Path(path) for name, path in proof["paths"].items()},
                expected_hashes=proof["expected_hashes"],
            )
        if os.environ.get("KNICKSIQ_DISCOVERY_ARTIFACT_DIR"):
            games = list(
                (
                    await db.execute(select(Game).where(Game.release_id == loaded.release_id))
                ).scalars()
            )
            units = await build_archive_units(db, games, loaded.version)
            directory = Path(os.environ["KNICKSIQ_DISCOVERY_ARTIFACT_DIR"])
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "archive_units.jsonl").open("x") as artifact:
                for unit in units:
                    artifact.write(json.dumps(unit, sort_keys=True) + "\n")
    before = QUESTIONS.read_bytes()
    assert hashlib.sha256(before).hexdigest() == QUESTIONS_SHA
    rows = [json.loads(line) for line in before.splitlines() if line.strip()]
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.125")
    receipts = []
    for index, case in enumerate(rows):
        async with AsyncClient(
            transport=ASGITransport(client._transport.app, client=(f"192.0.2.{index + 1}", 12345)),
            base_url="http://test",
        ) as http:
            receipt = await exchange(
                http,
                {
                    "question": case["question"],
                    "season": "2025-26",
                    "context": case.get("context", []),
                    "turn_id": f"discovery-cohort-{index}",
                    "expected_revision": 0,
                },
            )
        receipt["case_id"] = case["id"]
        receipts.append(receipt)
        save(tmp_path, f"cohort-{case['id']}", receipt)
    semantic = [
        (case, receipt)
        for case, receipt in zip(rows, receipts, strict=True)
        if case["answerable"] and case["expected_route"] == "retrieval_rag"
    ]
    final = {
        "scope": "local engineering probe; no approved labels or relevance score",
        "questions_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(),
        "case_count": len(receipts),
        "semantic_count": len(semantic),
        "attempts": attempts,
        "budget_after": (await local_redis.get(key)).decode(),
    }
    save(tmp_path, "cohort-summary", final)
    assert len(receipts) == 120 and len(semantic) == 50
    for case, receipt in semantic:
        search = assert_search(receipt)
        if proof_path and case["id"] == "single_game_narrative-006":
            ranked_refs = {
                ref
                for evidence in search["evidence"]
                if evidence["evidence_id"] in search["returned_evidence_ids"]
                for ref in evidence["metadata"].get("canonical_sources", [])
            }
            assert {f"game:{identity}" for identity in CLOSEST} <= ranked_refs
    assert QUESTIONS.read_bytes() == before
    assert attempts == {"provider": 0, "dense": 0, "reservations": 0}
    assert final["budget_after"] == "0.125"


@pytest.mark.parametrize("mode", ["llm_primary", "shadow"])
@pytest.mark.parametrize(
    ("question", "context", "search_identity"),
    [
        ("How did JB play in that game?", [], "Jalen Brunson"),
        (
            "What happened next?",
            [
                {"role": "user", "content": "How did the Knicks lose the lead against Boston?"},
                {"role": "assistant", "content": "Boston took control during a second-half run."},
            ],
            "BOS",
        ),
    ],
)
async def test_discovery_does_not_supply_a_missing_game(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    mode,
    question,
    context,
    search_identity,
):
    attempts = configure(monkeypatch, mode)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await local_redis.set(key, "0.125")
    receipt = await exchange(
        client,
        {
            "question": question,
            "context": context,
            "turn_id": f"discovery-missing-{mode}-{search_identity.split()[0]}",
        },
    )
    receipt.update(attempts=attempts, budget_after=(await local_redis.get(key)).decode())
    save(tmp_path, f"missing-{mode}-{search_identity.split()[0]}", receipt)
    search = assert_search(receipt)
    assert search["returned_evidence_ids"]
    assert search_identity in search["query"]
    assert receipt["response"]["route"] == "clarification"
    assert receipt["response"]["citations"] == []
    assert attempts == {"provider": 0, "dense": 0, "reservations": 0}
    assert receipt["budget_after"] == "0.125"


async def test_failed_discovery_retains_required_clarification(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    attempts = configure(monkeypatch, "llm_primary")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)

    async def failed(*_args, **_kwargs):
        raise RuntimeError("Synthetic SQL dependency failure")

    monkeypatch.setattr(analyst_tools, "search_archive_lexical", failed)
    receipt = await exchange(
        client, {"question": "How did JB play in that game?", "turn_id": "discovery-failed"}
    )
    receipt["attempts"] = attempts
    save(tmp_path, "dependency-failed", receipt)
    search = receipt["capture"]["searches"][0]
    assert search["purpose"] == "canonical_discovery"
    assert search["status"] == "dependency_failure"
    assert search["returned_evidence_ids"] == search["candidate_evidence_ids"] == []
    assert receipt["response"]["route"] == "clarification"
    assert receipt["response"]["citations"] == []
    assert receipt["response"]["degraded"]
    assert attempts == {"provider": 0, "dense": 0, "reservations": 0}


async def test_cancelled_discovery_releases_turn_for_exact_retry(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    attempts = configure(monkeypatch, "llm_primary")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    original = analyst_tools.search_archive_lexical
    entered = asyncio.Event()

    async def interrupted(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(analyst_tools, "search_archive_lexical", interrupted)
    payload = {"question": "How did JB play in that game?", "turn_id": "discovery-cancelled"}
    task = asyncio.create_task(client.post("/analysis/query", json=payload))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cancelled_lease_count = len(await local_redis.keys("analyst:*:lease"))
    monkeypatch.setattr(analyst_tools, "search_archive_lexical", original)
    receipt = await exchange(client, payload)
    receipt.update(
        attempts=attempts,
        previous_request_cancelled=True,
        cancelled_lease_count=cancelled_lease_count,
    )
    save(tmp_path, "cancelled-retry", receipt)
    assert_search(receipt)
    assert receipt["response"]["route"] == "clarification"
    assert receipt["response"]["citations"] == []
    assert receipt["response"]["state_committed"]
    assert attempts == {"provider": 0, "dense": 0, "reservations": 0}


@pytest.mark.parametrize("scenario", ["slow_source", "invalid_source", "slow_lexical"])
async def test_source_preparation_and_lexical_failure_boundaries(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    scenario,
):
    attempts = configure(monkeypatch, "disabled")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    original_units = analyst_tools.build_archive_units
    original_lexical = analyst_tools.search_archive_lexical

    async def source(*args, **kwargs):
        if scenario == "slow_source":
            await asyncio.sleep(2.05)
        if scenario == "invalid_source":
            raise ValueError("Synthetic source integrity failure")
        return await original_units(*args, **kwargs)

    async def lexical(*args, **kwargs):
        if scenario == "slow_lexical":
            await asyncio.sleep(2.05)
        return await original_lexical(*args, **kwargs)

    monkeypatch.setattr(analyst_tools, "build_archive_units", source)
    monkeypatch.setattr(analyst_tools, "search_archive_lexical", lexical)
    receipt = await exchange(
        client,
        {
            "question": "What was the Knicks record this season?",
            "turn_id": f"preparation-boundary-{scenario}",
        },
    )
    save(tmp_path, f"preparation-boundary-{scenario}", receipt)
    assert receipt["http_status"] == receipt["replay_status"] == 200
    assert receipt["replay"] == receipt["response"]
    assert receipt["conflict_status"] == 409
    if scenario == "slow_source":
        assert_search(receipt)
        claims = {
            citation["metadata"]["claim"]["metric_id"]: citation["metadata"]["claim"]["value"]
            for citation in receipt["response"]["citations"]
            if citation["type"] == "verified_claim"
        }
        assert claims == {"wins": 3, "losses": 0}
    else:
        search = receipt["capture"]["searches"][0]
        assert search["status"] == "dependency_failure"
        assert search["error_type"] == (
            "ValueError" if scenario == "invalid_source" else "TimeoutError"
        )
        assert receipt["response"]["citations"] == []
        assert receipt["response"]["degraded"]
    assert attempts["provider"] == attempts["dense"] == 0
