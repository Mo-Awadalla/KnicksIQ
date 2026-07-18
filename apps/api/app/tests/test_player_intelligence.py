"""Release isolation and public player analytics contract."""

import json
from datetime import UTC, date, datetime

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.generated_stat_fact import GeneratedStatFact
from app.models.player import Player
from app.services.player_analytics import (
    _parse_plan,
    _resolve_players,
    _window_limitation,
    answer_player_question,
)
from basketball_core.analytics import AnalyticsOperation
from sqlalchemy import select


async def _seed_release_stats(db_session) -> tuple[DatasetRelease, Player]:
    release = DatasetRelease(
        version="analytics-test",
        season="2025-26",
        source="test",
        manifest_sha256="a" * 64,
        validation_passed=True,
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(release)
    await db_session.flush()
    player = (
        await db_session.execute(select(Player).where(Player.full_name == "Jalen Brunson"))
    ).scalar_one()
    towns = (
        await db_session.execute(select(Player).where(Player.full_name == "Karl-Anthony Towns"))
    ).scalar_one()
    for index, (minutes, points) in enumerate(((34.0, 20), (0.0, 0), (36.0, 30)), start=1):
        game = Game(
            release_id=release.id,
            nba_game_id=f"analytics-{index}",
            season="2025-26",
            game_date=date(2026, 1, index),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=110 + index,
            away_score=100,
            status="final",
            season_type="regular",
            source_name="test",
            source_game_id=f"analytics-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=player.id,
                team_id="NYK",
                minutes=minutes,
                points=points,
                field_goals_attempted=10,
            )
        )
        db_session.add(
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=towns.id,
                team_id="NYK",
                minutes=32,
                points=15 + index,
                rebounds=10,
                assists=3,
                turnovers=1,
                three_pointers_made=1,
                three_pointers_attempted=4,
                field_goals_attempted=12,
            )
        )
    await db_session.commit()
    return release, player


async def test_last_appearances_exclude_zero_minute_rows_and_keep_receipts(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="What did Jalen Brunson average in his last 2 appearances?",
        season="2025-26",
    )
    assert answer is not None
    payload = answer.analytics
    assert payload["status"] == "complete"
    result = payload["results"][0]
    assert result["type"] == "aggregate"
    assert result["sample_size"] == 2
    assert result["raw_values"]["points"] == 25
    assert len(result["source_game_ids"]) == 2
    assert all(citation["metadata"]["result_id"] == result["id"] for citation in answer.citations)


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


async def test_common_discovery_window_uses_precomputed_release_catalog(db_session) -> None:
    release, player = await _seed_release_stats(db_session)
    db_session.add(
        GeneratedStatFact(
            release_id=release.id,
            fingerprint="f" * 64,
            fact_type="window_leader",
            player_ids_json=json.dumps([player.nba_player_id]),
            stat_keys_json=json.dumps(["points"]),
            timeframe_json=json.dumps(
                {"kind": "regular_season", "label": "2025-26 regular season"}
            ),
            statement="Jalen Brunson had the catalog's notable scoring line.",
            result_json=json.dumps({"value": 25}),
            source_game_ids_json=json.dumps(["analytics-1", "analytics-3"]),
            sample_size=2,
            total_score=0.75,
            score_components_json=json.dumps({"magnitude": 0.3}),
            detector_version="player-intelligence-v1",
            data_through=date(2026, 1, 3),
        )
    )
    await db_session.commit()
    answer = await answer_player_question(
        db_session,
        question="What was notable about Jalen Brunson's points this season?",
        season="2025-26",
    )
    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["type"] == "notable_facts"
    assert result["facts"][0]["fingerprint"] == "f" * 64
    assert len(result["source_game_ids"]) == 2


async def test_invalid_and_word_number_windows_are_typed_without_fallback(db_session) -> None:
    await _seed_release_stats(db_session)
    invalid = await answer_player_question(
        db_session,
        question="What did JB average over his last 0 games?",
        season="2025-26",
    )
    assert invalid is not None
    assert invalid.analytics["status"] == "limited"
    assert invalid.analytics["results"] == []
    assert _window_limitation("last negative five") is not None

    word_number = await answer_player_question(
        db_session,
        question="What did JB average over his last five appearances?",
        season="2025-26",
    )
    assert word_number is not None
    assert word_number.analytics["status"] == "limited"
    assert word_number.analytics["plan"]["timeframe"]["last_n"] == 5


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


async def test_totals_averages_percentages_ratios_and_triple_doubles(db_session) -> None:
    await _seed_release_stats(db_session)
    total = await answer_player_question(
        db_session,
        question="How many points did JB score this season?",
        season="2025-26",
    )
    assert total is not None
    total_result = total.analytics["results"][0]
    assert total.analytics["plan"]["aggregation_mode"] == "total"
    assert total_result["raw_values"]["points"] == 50

    average = await answer_player_question(
        db_session,
        question="What did JB average per game in points this season?",
        season="2025-26",
    )
    assert average is not None
    assert average.analytics["results"][0]["raw_values"]["points"] == 25

    plan = _parse_plan(
        "KAT three point percentage and assist-to-turnover ratio plus triple-doubles",
        [],
    )
    assert {
        "three_point_percentage",
        "assist_turnover_ratio",
        "triple_doubles",
    }.issubset(plan.stats)


async def test_association_operation_precedes_outcome_filters_and_parses_plus(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="Did JB scoring 30 plus points cause the Knicks to win?",
        season="2025-26",
    )
    assert answer is not None
    plan = answer.analytics["plan"]
    assert plan["operations"] == [AnalyticsOperation.OUTCOME_ASSOCIATION.value]
    assert "outcome" not in plan["filters"]
    result = answer.analytics["results"][0]
    assert result["threshold"] == 30
    assert any("not causation" in warning for warning in result["warnings"])


async def test_availability_separates_appearances_from_archive_coverage(db_session) -> None:
    await _seed_release_stats(db_session)
    answer = await answer_player_question(
        db_session,
        question="How many games did Jalen Brunson appear in this season?",
        season="2025-26",
    )
    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["appearances"] == 2
    assert result["requested_team_games"] == 3
    assert answer.analytics["coverage"]["covered_game_count"] == 3
    assert answer.analytics["coverage"]["expected_game_count"] == 3
    assert len(result["source_game_ids"]) == 3


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


async def test_month_all_star_and_explicit_date_windows_parse_deterministically(db_session) -> None:
    await _seed_release_stats(db_session)
    january = _parse_plan("JB points in January", [])
    assert january.timeframe.start_date == "2026-01-01"
    assert january.timeframe.end_date == "2026-01-31"
    before = _parse_plan("JB points before All-Star", [])
    assert before.timeframe.end_date == "2026-02-11"
    after = _parse_plan("JB points after the All-Star break", [])
    assert after.timeframe.start_date == "2026-02-19"
    explicit = _parse_plan("JB points from 2026-01-01 through 2026-01-03", [])
    assert explicit.timeframe.start_date == "2026-01-01"
    assert explicit.timeframe.end_date == "2026-01-03"


async def test_default_leaderboard_is_knicks_only_and_false_team_premise_is_limited(
    db_session,
) -> None:
    release, _ = await _seed_release_stats(db_session)
    game = (await db_session.execute(select(Game).order_by(Game.id).limit(1))).scalar_one()
    opponent = Player(
        nba_player_id=999001,
        full_name="Kevin Durant",
        team_id="BOS",
        position="F",
        jersey_number="7",
    )
    db_session.add(opponent)
    await db_session.flush()
    db_session.add(
        PlayerGameStat(
            release_id=release.id,
            game_id=game.id,
            player_id=opponent.id,
            team_id="BOS",
            minutes=40,
            points=60,
            field_goals_attempted=25,
        )
    )
    await db_session.commit()

    leaders = await answer_player_question(
        db_session,
        question="Who led players in points this season?",
        season="2025-26",
    )
    assert leaders is not None
    entries = leaders.analytics["results"][0]["entries"]
    assert {entry["player_name"] for entry in entries} <= {
        "Jalen Brunson",
        "Karl-Anthony Towns",
    }

    false_premise = await answer_player_question(
        db_session,
        question="What did Knicks player Kevin Durant average in points?",
        season="2025-26",
    )
    assert false_premise is not None
    assert false_premise.analytics["status"] == "limited"
    assert false_premise.analytics["results"] == []


async def test_hardest_opposing_player_ranks_cumulative_plus_minus(db_session) -> None:
    release, _ = await _seed_release_stats(db_session)
    games = list(
        (
            await db_session.execute(
                select(Game).where(Game.release_id == release.id).order_by(Game.game_date)
            )
        ).scalars()
    )
    tatum = Player(
        nba_player_id=999101,
        full_name="Jayson Tatum",
        team_id="BOS",
        position="F",
        jersey_number="0",
    )
    brown = Player(
        nba_player_id=999102,
        full_name="Jaylen Brown",
        team_id="BOS",
        position="F",
        jersey_number="7",
    )
    db_session.add_all([tatum, brown])
    await db_session.flush()
    for game, tatum_plus_minus, brown_plus_minus in zip(
        games,
        (None, 12, 5),
        (15, 1, -4),
        strict=True,
    ):
        stats = [
            PlayerGameStat(
                release_id=release.id,
                game_id=game.id,
                player_id=brown.id,
                team_id="BOS",
                minutes=36,
                plus_minus=brown_plus_minus,
            )
        ]
        if tatum_plus_minus is not None:
            stats.append(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=tatum.id,
                    team_id="BOS",
                    minutes=38,
                    plus_minus=tatum_plus_minus,
                )
            )
        db_session.add_all(stats)
    await db_session.commit()

    answer = await answer_player_question(
        db_session,
        question=(
            "Which player gave the Knicks the hardest time when he was on the court all season?"
        ),
        season="2025-26",
    )

    assert answer is not None
    result = answer.analytics["results"][0]
    assert result["entries"][0]["player_name"] == "Jayson Tatum"
    assert result["entries"][0]["raw_values"]["plus_minus"] == 17
    assert result["entries"][0]["sample_size"] == 2
    assert {citation["game_id"] for citation in answer.citations} == set(
        result["entries"][0]["source_game_ids"]
    )
    assert "cumulative plus-minus" in answer.answer.lower()

    explicit = await answer_player_question(
        db_session,
        question="Which opposing player had the most cumulative +/- against the Knicks?",
        season="2025-26",
    )

    assert explicit is not None
    explicit_leader = explicit.analytics["results"][0]["entries"][0]
    assert explicit_leader["player_name"] == "Jayson Tatum"
    assert explicit_leader["raw_values"]["plus_minus"] == 17
