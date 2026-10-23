"""Approved player identity synchronization via bundle import and real HTTP."""

import gzip
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.models.player import Player
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_canonical_narrative_http import BUNDLE, SHA
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


async def test_pinned_roster_overrides_stale_metadata_and_reimports_identically(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("Canonical roster checks cannot construct a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    original_bundle = BUNDLE.read_bytes()
    expected = json.loads(gzip.decompress(original_bundle))["data"]["players"]
    by_nba_id = {p["nba_player_id"]: p for p in expected}
    attributes = ("full_name", "team_id", "position", "jersey_number")
    directory = Path(os.environ.get("KNICKSIQ_ROSTER_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    questions = [
        "Compare Brunson and Towns as scorers this season.",
        "Who had the better rebounding season, Towns or Hart?",
        "Compare Bridges' scoring before and after the All-Star break.",
        "Compare Mikal Bridges' scoring before and after the All-Star break.",
        "How many double-doubles did Towns have?",
        "What did Towns do in the biggest win?",
    ]
    phases = []
    for phase in range(2):
        async with AsyncSessionLocal() as db:
            if phase:
                towns = (
                    await db.execute(select(Player).where(Player.nba_player_id == 1626157))
                ).scalar_one()
                towns.full_name = "Stale cached Towns identity"
                await db.commit()
            before = [
                {
                    "id": p.id,
                    "nba_player_id": p.nba_player_id,
                    **{a: getattr(p, a) for a in attributes},
                }
                for p in (await db.execute(select(Player))).scalars()
                if p.nba_player_id in by_nba_id
            ]
            if not phase:
                await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=False)
                stored = {p.id: p for p in (await db.execute(select(Player))).scalars()}
                assert all(
                    all(getattr(stored[p["id"]], a) == p[a] for a in attributes) for p in before
                )
            await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
            roster = [
                {
                    "id": p.id,
                    "nba_player_id": p.nba_player_id,
                    **{a: getattr(p, a) for a in attributes},
                }
                for p in (await db.execute(select(Player).order_by(Player.nba_player_id))).scalars()
                if p.nba_player_id in by_nba_id
            ]
        observations = []
        for index, question in enumerate(questions):
            async with AsyncClient(
                transport=ASGITransport(
                    client._transport.app, client=(f"192.0.2.{phase * 10 + index + 1}", 12345)
                ),
                base_url="http://test",
            ) as http:
                payload = {
                    "question": question,
                    "turn_id": f"canonical-roster-phase-{phase}-case-{index}",
                }
                with capture_turn() as capture:
                    response = await http.post("/analysis/query", json=payload)
                replay = await http.post("/analysis/query", json=payload)
            observations.append(
                {
                    "request": payload,
                    "http_status": response.status_code,
                    "response": response.json(),
                    "capture": capture,
                    "replay": replay.json(),
                }
            )
        phases.append({"before": before, "after": roster, "observations": observations})
        with (directory / f"roster-phase-{phase}.json").open("x") as artifact:
            json.dump(phases[-1], artifact, indent=2)
    with (directory / "roster-result.json").open("x") as artifact:
        json.dump({"provider_attempts": attempts, "phase_count": len(phases)}, artifact, indent=2)
    assert BUNDLE.read_bytes() == original_bundle
    assert attempts == 0
    for phase in phases:
        assert len(phase["after"]) == len(expected)
        for player in phase["after"]:
            canonical = by_nba_id[player["nba_player_id"]]
            assert all(player[a] == canonical.get(a) for a in attributes)
        for receipt in phase["observations"]:
            assert receipt["http_status"] == 200
            body = receipt["response"]
            assert body["route"] != "clarification", body["answer"]
            assert body["citations"] and body["state_committed"]
            if "Bridges" in receipt["request"]["question"]:
                # Existing surname policy prefers the unique Knicks player.
                assert "Mikal Bridges" in body["answer"]
                assert "Miles Bridges" not in body["answer"]
            assert receipt["replay"] == body
            assert receipt["capture"]["turn"]["model_calls"] == 0
    assert phases[0]["after"] == phases[1]["after"]
    assert [r["response"]["answer"] for r in phases[0]["observations"]] == [
        r["response"]["answer"] for r in phases[1]["observations"]
    ]
