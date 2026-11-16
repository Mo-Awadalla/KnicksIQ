"""Narrative scope and numeric gold at the private factual boundary."""

import re
from datetime import date, timedelta

import pytest
from app.conversation.facts import FactDesk
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services.analyst_tools import AnalystTools
from app.tests.support.factual_queries import lookup, text
from app.tests.support.narrative_seed import active_seed_release as active_seed_release
from sqlalchemy import select


async def query(question, state=None):
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        tools = AnalystTools(db, release, question, release.season, state or {})
        await tools.prepare()
        return tools, await lookup(tools)


async def test_opponent_performance_prompt_uses_only_matching_games(active_seed_release):
    tools, result = await query("How did they perform against Toronto?")
    matching = [game for game in tools.games if "TOR" in {game.home_team_id, game.away_team_id}]
    assert matching and len(matching) < len(tools.games)
    wins = sum(tools.score(game)[0] > tools.score(game)[1] for game in matching)
    claims = {claim.metric_id: claim for claim in result.claims}
    assert claims["wins"].value == wins
    assert claims["losses"].value == len(matching) - wins
    assert all(
        claim.game_ids is not None and set(claim.game_ids) == {game.id for game in matching}
        for claim in claims.values()
    )


async def test_back_to_back_count_requests_definition_instead_of_points(active_seed_release):
    tools, result = await query("How many back-to-backs did they win in February?")
    assert result.status == "ambiguous_entity"
    assert not result.claims and not result.evidence
    assert result.scope["clarification_reason"] == "ambiguous_metric"
    assert result.scope["date_start"] == "2026-02-01", result.scope
    assert result.scope["date_end"] == "2026-02-28"
    outcome = FactDesk(tools.season, {}, 12000, "back-to-back-definition")._outcome(tools, result)
    assert outcome["status"] == "ambiguous"
    alternatives = [choice.lower() for choice in outcome["choices"]]
    assert any(
        re.search(r"\b(?:second|2nd)\b", choice) and re.search(r"\b(?:game|night)\b", choice)
        for choice in alternatives
    )
    assert any(
        re.search(r"\b(?:both|two|2)\b", choice) and re.search(r"\b(?:games|nights|wins)\b", choice)
        for choice in alternatives
    )


async def test_ambiguous_narrative_requests_game_selection_without_receipts(active_seed_release):
    _, result = await query("What happened in the fourth quarter?")
    assert result.status == "ambiguous_entity"
    assert result.message
    assert not result.claims and not result.evidence


@pytest.mark.parametrize(
    "question",
    [
        "How did the lineup with Brunson look in the Knicks game?",
        "What if the Knicks made two more threes in that game?",
    ],
)
async def test_unscoped_lineup_and_counterfactual_questions_request_a_game(
    active_seed_release, question
):
    _, result = await query(question)
    assert result.status == "ambiguous_entity"
    assert not result.claims and not result.evidence


async def test_season_summary_reports_the_active_archive_totals(active_seed_release):
    _, result = await query("What happened in the Knicks season?")
    assert result.status == "ok"
    claims = {claim.metric_id: claim for claim in result.claims}
    assert {metric: claims[metric].value for metric in ("wins", "losses", "points", "margin")} == {
        "wins": 4,
        "losses": 1,
        "points": 564,
        "margin": 52,
    }
    assert all(claim.sample_size == 5 for claim in claims.values())
    assert all(
        claim.game_ids is not None and set(claim.game_ids) == {1, 2, 3, 4, 5}
        for claim in claims.values()
    )
    assert all(claim.release_id == "narrative-seed-test" for claim in claims.values())


async def test_follow_up_requires_verified_game_and_event_reference(active_seed_release):
    _, result = await query("What did Brunson do during it?")
    assert result.status == "ambiguous_entity"
    assert not result.claims and not result.evidence


async def test_specific_final_minutes_return_only_matching_event_receipts(active_seed_release):
    async with AsyncSessionLocal() as db:
        game = await db.get(Game, 1)
        assert game is not None
        day, game_id = game.game_date, game.id
    _, result = await query(f"What happened in the final two minutes on {day}?")
    assert result.status == "ok"
    assert result.evidence
    assert {item.game_id for item in result.evidence} == {game_id}
    rows = [row for item in result.evidence for row in item.metadata.get("rows", [])]
    assert rows
    for row in rows:
        assert row["period"] == 4
        minutes, seconds = map(int, row["clock"].split(":"))
        assert minutes * 60 + seconds <= 120


async def test_best_defensive_game_binds_lowest_points_allowed_before_retrieval(
    active_seed_release,
):
    tools, result = await query("Explain the Knicks' best defensive game.")
    best = min(tools.games, key=lambda game: tools.score(game)[1])
    assert result.status == "ok", result.scope
    assert str(tools.score(best)[1]) in text(result)
    assert str(best.game_date) in text(result)
    assert result.evidence
    assert all(item.game_id == best.id for item in result.evidence)
    claim = next(claim for claim in result.claims if claim.metric_id == "opponent_points")
    assert claim.value == tools.score(best)[1]
    assert claim.game_ids == [best.id]
    narrative = [
        item
        for item in result.evidence
        if item.metadata.get("document_collection") in {"reports", "possessions"}
    ]
    assert narrative
    assert all(item.game_id == best.id for item in narrative)
    desk = FactDesk(tools.season, {}, 12000, "narrative-registry-contract")
    outcome = desk._outcome(tools, result)
    assert outcome["status"] == "found"
    statements = [item["text"] for item in outcome["facts"]]
    assert claim.statement in statements
    assert any(statement.startswith("From ") for statement in statements)
    assert not any(statement.startswith("{") or ': {"' in statement for statement in statements)


@pytest.mark.parametrize(
    "question",
    [
        "How did the Knicks erase their largest deficit?",
        "What was the most damaging opponent run this season?",
        "What was the Knics biggest run?",
        "What was NY's worst collpase?",
    ],
)
async def test_season_run_superlative_preserves_scope_and_requests_metric(
    active_seed_release, question
):
    tools, result = await query(question)
    assert result.status == "ambiguous_entity"
    assert not result.claims and not result.evidence
    assert result.scope["clarification_reason"] == "ambiguous_metric"
    assert result.scope["data_version"] == "narrative-seed-test"
    assert result.scope["game_ids"] == []
    assert result.scope["date_start"] is None and result.scope["date_end"] is None
    assert tools.scope is not None
    assert {game.id for game in tools.selected_games(tools.scope)} == {1, 2, 3, 4, 5}
    outcome = FactDesk(tools.season, {}, 12000, "season-run-definition")._outcome(tools, result)
    message = outcome["message"].lower()
    assert re.search(r"\bseason\b", message)
    assert re.search(r"\b(?:rank\w*|across)\b", message)
    assert re.search(r"\b(?:window|interval)\b", message)
    assert not re.search(r"\b(?:which|choose|select|pick|name)\b.{0,30}\bgame\b", message)
    alternatives = [choice.lower() for choice in outcome["choices"]]
    assert any(
        re.search(r"\b(?:unanswered|consecutive)\b", choice)
        and re.search(r"\b(?:scor\w*|points?)\b", choice)
        for choice in alternatives
    )
    assert any(
        re.search(r"\b(?:net|margin)\b", choice) and re.search(r"\b(?:window|interval)\b", choice)
        for choice in alternatives
    )
    assert not any(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", choice) for choice in alternatives)


async def test_narrative_game_choices_disclose_truncated_dates(active_seed_release):
    async with AsyncSessionLocal() as db:
        release_id = (
            await db.execute(select(DatasetRelease.id).where(DatasetRelease.status == "active"))
        ).scalar_one()
        for offset in range(9):
            db.add(
                Game(
                    release_id=release_id,
                    nba_game_id=f"clarify-atl-{offset}",
                    season="2025-26",
                    game_date=date(2026, 3, 1) + timedelta(days=offset),
                    home_team_id="NYK",
                    away_team_id="ATL",
                    home_score=110,
                    away_score=100,
                    status="final",
                    season_type="regular",
                )
            )
        await db.commit()
    _, result = await query("Explain the Knicks game against Atlanta.")
    assert result.status == "ambiguous_entity"
    choices = " ".join(result.choices)
    assert len(result.choices) == 8
    assert "2026-03-01" in choices
    assert "2026-03-09" not in choices
