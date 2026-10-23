"""Player aliases, clarification, conversational context and public route contracts."""

from __future__ import annotations

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.player_analytics import answer_player_question
from app.services.player_intelligence.identity import _resolve_players
from app.services.player_intelligence.planning import _parse_plan
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import select


async def test_lately_requires_typed_clarification_and_context_completes_it(db_session) -> None:
    await _seed_release_stats(db_session)
    first = await answer_player_question(
        db_session,
        question="How has Jalen Brunson played lately?",
        season="2025-26",
    )
    assert first is not None
    assert first.analytics["status"] == "clarification_required"
    assert first.analytics["clarification"]["choices"][0]["value"] == "Use last 5 appearances"
    second = await answer_player_question(
        db_session,
        question="Use last 5 appearances",
        season="2025-26",
        context=[{"role": "user", "content": "How has Jalen Brunson played lately?"}],
    )
    assert second is not None
    assert second.analytics["status"] in {"complete", "limited"}
    assert second.analytics["plan"]["timeframe"]["unit"] == "appearances"


async def test_alias_resolution_collapses_repeats_and_keeps_distinct_comparisons(
    db_session,
) -> None:
    await _seed_release_stats(db_session)
    players = await db_session.execute(
        select(Player).where(Player.full_name.in_(["Jalen Brunson", "Karl-Anthony Towns"]))
    )
    archive_players = list(players.scalars())
    resolved, ambiguous = _resolve_players("Compare JB and KAT points", archive_players)
    assert ambiguous == []
    assert {player.full_name for player in resolved} == {
        "Jalen Brunson",
        "Karl-Anthony Towns",
    }
    repeated, ambiguous = _resolve_players("Compare KAT with Karl-Anthony Towns", archive_players)
    assert ambiguous == []
    assert [player.full_name for player in repeated] == ["Karl-Anthony Towns"]

    answer = await answer_player_question(
        db_session,
        question="Compare JB and KAT points",
        season="2025-26",
    )
    assert answer is not None
    assert answer.analytics["results"][0]["type"] == "player_comparison"
    assert len(answer.analytics["plan"]["players"]) == 2


async def test_fuzzy_name_uses_name_slots_and_does_not_match_ordinary_words(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="What did Brunsen average in points?",
        season="2025-26",
    )
    assert answer is not None
    assert answer.analytics["plan"]["players"][0]["full_name"] == "Jalen Brunson"

    ordinary = await answer_player_question(
        db_session,
        question="What was the Knicks record this season?",
        season="2025-26",
    )
    assert ordinary is None
    team_counterfactual = await answer_player_question(
        db_session,
        question="What if the Knicks had avoided turnovers against Toronto?",
        season="2025-26",
    )
    assert team_counterfactual is None

    towns = (
        await db_session.execute(select(Player).where(Player.full_name == "Karl-Anthony Towns"))
    ).scalar_one()
    collision_players = [
        towns,
        Player(nba_player_id=999002, full_name="Carmelo Anthony", team_id="BOS"),
        Player(nba_player_id=999003, full_name="Tari Eason", team_id="BOS"),
        Player(nba_player_id=999004, full_name="Anthony", team_id="NYK"),
    ]
    full_name, ambiguous = _resolve_players("Karl-Anthony Towns points", collision_players)
    assert ambiguous == []

    better = await answer_player_question(
        db_session,
        question="Who was better, JB or KAT?",
        season="2025-26",
    )
    assert better is not None
    assert better.analytics["status"] == "clarification_required"
    assert [player.full_name for player in full_name] == ["Karl-Anthony Towns"]
    season, ambiguous = _resolve_players("rank points this season", collision_players)
    assert season == []
    assert ambiguous == []


async def test_stacked_clarifications_preserve_original_entities_and_window(db_session) -> None:
    await _seed_release_stats(db_session)
    context = [
        {"role": "user", "content": "Who was better lately, JB or KAT?"},
        {"role": "assistant", "content": "What should lately mean?"},
        {"role": "user", "content": "Use last 5 appearances"},
        {"role": "assistant", "content": "Which measure should decide who was better?"},
    ]
    answer = await answer_player_question(
        db_session,
        question="Use points",
        season="2025-26",
        context=context,
    )
    assert answer is not None
    assert answer.analytics["plan"]["timeframe"]["last_n"] == 5
    assert len(answer.analytics["plan"]["players"]) == 2


async def test_pronoun_follow_up_inherits_entity_and_window_but_replaces_stat(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="What about his rebounds?",
        season="2025-26",
        context=[
            {
                "role": "user",
                "content": "What did KAT average in points over his last 2 appearances?",
            },
            {"role": "assistant", "content": "KAT averaged 17.5 points."},
        ],
    )
    assert answer is not None
    assert answer.analytics["plan"]["stats"] == ["rebounds"]
    assert answer.analytics["plan"]["timeframe"]["last_n"] == 2
    assert answer.analytics["plan"]["players"][0]["full_name"] == "Karl-Anthony Towns"


async def test_better_rebounding_uses_named_metric_without_clarifying(db_session):
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="Who had the better rebounding season, Towns or Brunson?",
        season="2025-26",
    )
    assert answer is not None
    assert answer.analytics["status"] != "clarification_required"
    assert answer.analytics["plan"]["stats"] == ["rebounds"]
    assert len(answer.analytics["results"][0]["groups"]) == 2


async def test_informal_player_opponent_summaries_resolve_aliases_and_preserve_scope(db_session):
    release, _ = await _seed_release_stats(db_session)
    games = list(
        (
            await db_session.execute(
                select(Game).where(Game.release_id == release.id).order_by(Game.id)
            )
        ).scalars()
    )
    games[0].away_team_id = "TOR"
    games[1].away_team_id = "TOR"
    await db_session.commit()
    kat = await answer_player_question(
        db_session, question="Tell me about KAT vs the Raps.", season="2025-26"
    )
    assert kat is not None
    assert kat.analytics["plan"]["filters"]["opponent"] == "TOR"
    assert kat.analytics["results"][0]["raw_values"] == {
        "points": 16.5,
        "rebounds": 10,
        "assists": 3,
    }
    assert "versus TOR" in kat.answer
    assert set(kat.analytics["results"][0]["source_game_ids"]) == {games[0].id, games[1].id}
    plan = _parse_plan("How did OG look vs the C's?", [])
    assert plan.filters["opponent"] == "BOS"
    assert plan.stats == ["points", "rebounds", "assists"]


async def test_mikal_typo_summary_reaches_public_player_route(db_session):
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    release, _ = await _seed_release_stats(db_session)
    player = (
        await db_session.execute(select(Player).where(Player.full_name == "Mikal Bridges"))
    ).scalar_one()
    game = (
        await db_session.execute(
            select(Game).where(Game.release_id == release.id).order_by(Game.id).limit(1)
        )
    ).scalar_one()
    game.away_team_id = "TOR"
    db_session.add(
        PlayerGameStat(
            release_id=release.id,
            game_id=game.id,
            player_id=player.id,
            team_id="NYK",
            minutes=30,
            points=17,
            rebounds=4,
            assists=3,
        )
    )
    await db_session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/analysis/query",
            json={"question": "Did Mikal play well aginst Toronto?", "season": "2025-26"},
        )
    assert response.status_code == 200
    data = response.json()
    assert not data["refused"]
    assert data["analytics"]["results"][0]["raw_values"] == {
        "points": 17,
        "rebounds": 4,
        "assists": 3,
    }
    assert "Mikal Bridges" in data["answer"]
    assert "versus TOR" in data["answer"]
