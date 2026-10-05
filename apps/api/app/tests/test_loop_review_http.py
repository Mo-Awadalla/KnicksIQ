"""Final-review calculation eligibility through HTTP, SQL and isolated Redis."""

import gzip
import json

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.game import Game
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import SyntheticAdapter, configure, exchange
from app.tests.test_canonical_narrative_http import BUNDLE, SHA, request
from sqlalchemy import select


async def test_prior_shooting_cannot_answer_current_record(client, local_redis, monkeypatch):  # noqa: F811
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
    adapter = SyntheticAdapter(
        {
            "name": "get_team_stats",
            "question": "Compare the Knicks shooting percentage in January and February.",
        }
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    first = await exchange(
        client,
        local_redis,
        adapter,
        "prior-month-shooting",
        "Compare the Knicks shooting percentage in January and February.",
    )
    previous = first["response"]
    assert previous["citations"]

    class Unavailable:
        async def generate(self, **kwargs):
            raise RuntimeError("Isolated provider failure")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", Unavailable)
    response = await client.post(
        "/analysis/query",
        json={
            "question": "Compare the Knicks record in January and February.",
            "turn_id": "current-month-record",
            "session_token": previous["session_token"],
            "expected_revision": previous["revision"],
        },
    )
    assert response.status_code == 200
    claims = [c["metadata"]["claim"] for c in response.json()["citations"]]
    assert {c["window"]["comparison_group"] for c in claims} == {"January", "February"}
    assert all(set(c["value"]) == {"games", "wins", "losses"} for c in claims)


async def test_march_recent_comparison_has_full_season_operand(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    monkeypatch.setattr(settings, "rag_qdrant_enabled", False)
    raw = json.loads(gzip.decompress(BUNDLE.read_bytes()))["data"]
    games = {g["nba_game_id"]: g for g in raw["games"]}
    rows = sorted(
        [s for s in raw["player_game_stats"] if s["nba_player_id"] == 1628973 and s["minutes"] > 0],
        key=lambda s: (games[s["nba_game_id"]]["game_date"], s["nba_game_id"]),
    )
    march = [s for s in rows if games[s["nba_game_id"]]["game_date"].startswith("2026-03")][-5:]
    assert march and len(rows) > len(march)
    async with AsyncSessionLocal() as db:
        await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        ids = {g.nba_game_id: g.id for g in (await db.execute(select(Game))).scalars()}
    body, _ = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        "march-season",
        "Compare Brunson's last 5 games in March with his season average.",
    )
    claims = list(
        {
            c["metadata"]["claim"]["claim_id"]: c["metadata"]["claim"] for c in body["citations"]
        }.values()
    )
    for population in (march, rows):
        matched = [
            c
            for c in claims
            if c["metric_id"] == "points:average"
            and set(c["game_ids"]) == {ids[s["nba_game_id"]] for s in population}
        ]
        assert len(matched) == 1
        assert matched[0]["value"] == pytest.approx(
            sum(s["points"] for s in population) / len(population)
        )


@pytest.mark.parametrize(
    "question,omit,tied_count",
    [
        ("What was the Knicks highest-scoring game?", False, 2),
        ("What was the Knicks biggest win by margin?", False, 1),
        ("What was the Knicks highest-scoring game?", True, 2),
        ("What was the Knicks biggest win by margin?", True, 1),
        ("What was the Knicks biggest win by margin?", False, 2),
        ("What was the Knicks biggest win by margin?", False, 12),
    ],
)
async def test_primary_scalar_extrema_complete_selected_set(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    question,
    omit,
    tied_count,
    record_property,
):
    configure(monkeypatch)
    async with AsyncSessionLocal() as db:
        loaded = await load_release_bundle(db, BUNDLE, expected_sha256=SHA, activate=True)
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(
                        Game.release_id == loaded.release_id,
                        Game.home_team_id == "NYK",
                        Game.status == "final",
                    )
                    .order_by(Game.game_date, Game.nba_game_id)
                )
            )
            .scalars()
            .all()
        )
        # Both selection and scalar receipts read these active-release Game scores.
        # Do not mutate unrelated preexisting releases supplied by the client fixture.
        for game in games[:tied_count]:
            game.home_score, game.away_score = 250, 50
        await db.commit()

    class ExtremaAdapter(SyntheticAdapter):
        async def generate(self, *, system, user):
            payload = json.loads(user)
            result = json.loads(await super().generate(system=system, user=user))
            answer = (
                result.get("answer")
                if payload["schema"]["title"] == "Action"
                else result
                if payload["schema"]["title"] == "ProposedAnswer"
                else None
            )
            if omit and answer:
                answer["claims"] = answer["claims"][:-1]
                ids = {c["claim_id"] for c in answer["claims"]}
                answer["text"] = " ".join(
                    c["statement"] for c in payload["claims"] if c["claim_id"] in ids
                )
            return json.dumps(result)

    adapter = ExtremaAdapter({"name": "get_game_narrative", "question": question})
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(
        client,
        local_redis,
        adapter,
        f"extreme-{omit}-{tied_count}-{'margin' if 'margin' in question else 'score'}",
        question,
    )
    body = receipt["response"]
    assert receipt["status"] == 200
    if tied_count == 2 and "margin" in question and not omit:
        canonical = list(
            {
                claim["claim_id"]: claim
                for tool in receipt["capture"]["tools"]
                for claim in tool["result"]["claims"]
            }.values()
        )
        uses = [
            {
                "claim_id": claim["claim_id"],
                "displayed_value": claim["value"],
                "decimal_places": None,
            }
            for claim in canonical
        ]
        projected = [
            {key: value for key, value in claim.items() if value is not None} for claim in canonical
        ]
        for name, records in (("full", canonical), ("projected", projected)):
            required_json = json.dumps(
                {"claims": records, "claim_uses": uses},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            record_property(f"required_scalar_records_{name}_bytes", len(required_json.encode()))
    if tied_count == 1 or "margin" not in question:
        assert body["llm_validated"] is (not omit)
    claims = [c["metadata"]["claim"] for c in body["citations"]]
    expected_metrics = {"game_score", "margin"} if "margin" in question else {"game_score"}
    required = {(metric, g.id) for metric in expected_metrics for g in games[:tied_count]}
    assert {(c["metric_id"], c["game_ids"][0]) for c in claims} == required
    for item in adapter.inputs:
        supplied = item["user"]["claims"]
        if supplied:
            assert {(c["metric_id"], c["game_ids"][0]) for c in supplied} == required
    if body["llm_validated"]:
        assert any(p["user"]["schema"]["title"] == "AnswerReview" for p in adapter.inputs)
    if tied_count == 12:
        # An oversized selection still delivers every fact without a partial prompt.
        assert all(not p["user"]["claims"] for p in adapter.inputs)
        assert body["route"] == "factual_fallback"
