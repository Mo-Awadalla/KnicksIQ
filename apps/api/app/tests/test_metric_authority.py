"""Metric and population authority cases for the deterministic analyst path.

Every case drives the real seam: `resolve_query` through `AnalystTools.prepare`,
`AnalystLoop.run(allow_model=False)` for deterministic delivery, or
`AnalystTools.execute` for a model tool call. Fixtures are written so each case fails
on the previous behaviour:

* grouped three-point percentage with unequal attempts is not made threes per
  appearance, and a total request stays a total,
* a named-player threshold counts player appearances, never team scores,
* win and loss margin cutoffs require the requested outcome,
* a zero-match cutoff still cites the considered population,
* a zero-attempt percentage is undefined coverage, not zero,
* compound average points plus average margin delivers both measures,
* conflicting model paraphrases cannot replace the requested stat, window or
  aggregation,
* every tied extreme and tied leader survives deterministic delivery beyond six and
  beyond thirty ties.
"""

from __future__ import annotations

import pytest
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from sqlalchemy import select

_SEED_COUNT = 0


async def _seed(
    db_session,
    games: list[tuple[str, str, str, int, int]],
    *,
    box: dict[str, list[tuple[int, int, int, int, int]]] | None = None,
    team: list[tuple[int, int, int, int, int, int]] | None = None,
    periods: dict[int, list[int]] | None = None,
) -> DatasetRelease:
    """Seed one release. `box` rows are minutes, points, assists, 3PM, 3PA per game.

    `team` rows are FGM, FGA, 3PM, 3PA, points, turnovers per game for the Knicks.
    """
    global _SEED_COUNT
    _SEED_COUNT += 1
    release = DatasetRelease(
        version=f"metric-authority-test-{_SEED_COUNT}",
        season="2025-26",
        source="test",
        manifest_sha256=f"{_SEED_COUNT:064x}",
        validation_passed=True,
        status="active",
    )
    db_session.add(release)
    await db_session.flush()
    players = {
        player.full_name: player
        for player in (await db_session.execute(select(Player))).scalars().all()
    }
    for index, (day, home, away, home_score, away_score) in enumerate(games):
        game = Game(
            release_id=release.id,
            nba_game_id=f"authority-{_SEED_COUNT}-{index}",
            season="2025-26",
            game_date=__import__("datetime").date.fromisoformat(day),
            home_team_id=home,
            away_team_id=away,
            home_score=home_score,
            away_score=away_score,
            status="final",
            season_type="regular",
            data_status="analysis_ready",
            source_name="test",
            source_game_id=f"authority-{_SEED_COUNT}-{index}",
        )
        db_session.add(game)
        await db_session.flush()
        for name, rows in (box or {}).items():
            minutes, points, assists, made, attempted = rows[index]
            db_session.add(
                PlayerGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    player_id=players[name].id,
                    team_id="NYK",
                    starter=True,
                    minutes=minutes,
                    points=points,
                    assists=assists,
                    three_pointers_made=made,
                    three_pointers_attempted=attempted,
                )
            )
        if team is not None:
            fgm, fga, tpm, tpa, points, turnovers = team[index]
            db_session.add(
                TeamGameStat(
                    release_id=release.id,
                    game_id=game.id,
                    team_id="NYK",
                    points=points,
                    field_goals_made=fgm,
                    field_goals_attempted=fga,
                    three_pointers_made=tpm,
                    three_pointers_attempted=tpa,
                    free_throws_made=0,
                    free_throws_attempted=0,
                    turnovers=turnovers,
                )
            )
        for period, series in (periods or {}).items():
            db_session.add(
                PeriodScore(
                    release_id=release.id,
                    game_id=game.id,
                    team_id="NYK",
                    period=period,
                    points=series[index],
                )
            )
    await db_session.commit()
    return release


async def _tools(
    db_session, release: DatasetRelease, question: str
) -> tuple[AnalystTools, AnalystLoop]:
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    loop = AnalystLoop(tools, [])
    loop.request_id = "metric-authority-test"
    return tools, loop


async def _deterministic(db_session, release: DatasetRelease, question: str):
    tools, loop = await _tools(db_session, release, question)
    return tools, loop, await loop.run(allow_model=False)


def _claims(result) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for citation in result["citations"]:
        claim = citation["metadata"].get("claim")
        if claim:
            grouped.setdefault(claim["metric_id"], []).append(claim)
    return grouped


def _ids(tools: AnalystTools, *days: str) -> list[int]:
    wanted = set(days)
    return sorted(game.id for game in tools.games if game.game_date.isoformat() in wanted)


# Unequal three-point attempts across home and away, so only aggregate makes divided by
# aggregate attempts can produce the two percentages.
_GROUP_GAMES = [
    ("2025-11-01", "NYK", "BOS", 110, 100),
    ("2025-11-05", "NYK", "DET", 108, 101),
    ("2025-11-09", "MIA", "NYK", 99, 105),
    ("2025-11-13", "CHI", "NYK", 97, 103),
]
_GROUP_BOX = {
    "Mikal Bridges": [
        (35, 18, 2, 4, 10),
        (35, 12, 3, 2, 4),
        (35, 14, 2, 1, 1),
        (35, 11, 4, 3, 5),
    ]
}


async def test_grouped_three_point_percentage_uses_weighted_attempts(client, monkeypatch):
    from app.core.config import get_settings
    from app.core.db import AsyncSessionLocal
    from app.tests.support.analytics_workflows import ask, grouped

    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "deterministic")
    async with AsyncSessionLocal() as db:
        release = await _seed(db, _GROUP_GAMES, box=_GROUP_BOX)
        version = release.version
    result = await ask(
        client, "Compare Mikal Bridges' three-point percentage at home and away.", version
    )
    by_group = grouped(result, "three_pointers_made:percentage")
    assert set(by_group) == {"home", "away"}
    # Six makes in fourteen attempts versus four in six, not an average of game percentages.
    assert by_group["home"]["value"] == pytest.approx(42.857142857)
    assert by_group["away"]["value"] == pytest.approx(66.666666667)
    assert (
        by_group["home"]["eligibility"]["made"],
        by_group["home"]["eligibility"]["attempted"],
    ) == (6, 14)
    assert (
        by_group["away"]["eligibility"]["made"],
        by_group["away"]["eligibility"]["attempted"],
    ) == (4, 6)
    assert all(claim["release_id"] == version for claim in by_group.values())


async def test_grouped_total_points_stays_a_total(db_session):
    release = await _seed(db_session, _GROUP_GAMES, box=_GROUP_BOX)
    tools, _, result = await _deterministic(
        db_session, release, "Compare Mikal Bridges' total points at home and away."
    )
    assert tools.scope is not None and tools.scope.comparison is not None
    assert tools.scope.comparison.aggregation == "total"
    claims = _claims(result)["points:total"]
    by_group = {claim["eligibility"]["comparison_group"]: claim for claim in claims}
    assert by_group["home"]["value"] == 30
    assert by_group["away"]["value"] == 25


_THRESHOLD_GAMES = [
    ("2025-11-01", "NYK", "BOS", 100, 95),  # narrow win
    ("2025-11-05", "NYK", "DET", 95, 100),  # narrow loss
    ("2025-11-09", "NYK", "CHI", 120, 95),  # wide win
]


async def test_player_threshold_counts_qualifying_appearances(db_session):
    release = await _seed(
        db_session,
        _THRESHOLD_GAMES,
        box={"Jalen Brunson": [(36, 30, 5, 1, 3), (36, 20, 5, 1, 3), (36, 26, 5, 1, 3)]},
    )
    tools, _, result = await _deterministic(
        db_session, release, "How many games did Brunson score at least 25?"
    )
    assert tools.scope is not None and tools.scope.operation == "player_threshold"
    claim = _claims(result)["points:threshold"][0]
    assert claim["value"] == 2
    assert claim["denominator"] == 3
    assert claim["subject_id"] == f"player:{tools.scope.player_ids[0]}"
    assert claim["game_ids"] == _ids(tools, "2025-11-01", "2025-11-05", "2025-11-09")
    assert claim["eligibility"]["qualifying_game_ids"] == _ids(tools, "2025-11-01", "2025-11-09")
    assert "games" not in _claims(result)


async def test_margin_thresholds_require_the_requested_outcome(db_session):
    release = await _seed(db_session, _THRESHOLD_GAMES)
    tools, _, win_result = await _deterministic(
        db_session, release, "How many games did the Knicks win by fewer than 10?"
    )
    win_claim = _claims(win_result)["games"][0]
    assert win_claim["value"] == 1
    assert win_claim["denominator"] == 3
    assert win_claim["game_ids"] == _ids(tools, "2025-11-01")

    loss_result = None
    tools, _ = await _tools(
        db_session, release, "How many games did the Knicks lose by fewer than 10?"
    )
    loop = AnalystLoop(tools, [])
    loss_result = await loop.run(allow_model=False)
    loss_claim = _claims(loss_result)["games"][0]
    assert loss_claim["value"] == 1
    assert loss_claim["denominator"] == 3
    assert loss_claim["eligibility"]["subject"] == "deficit"
    assert loss_claim["game_ids"] == _ids(tools, "2025-11-05")


async def test_zero_match_threshold_claim_cites_the_population(db_session):
    release = await _seed(db_session, _THRESHOLD_GAMES)
    _, _, result = await _deterministic(
        db_session, release, "How many games did the Knicks score at least 200?"
    )
    claim = _claims(result)["games"][0]
    assert claim["value"] == 0
    assert claim["denominator"] == 3
    assert claim["supporting_evidence_ids"]
    assert "0 of 3" in result["answer"]
    assert result["citations"]
    assert result["outcome"] == "answer" and result["refused"] is False


_RATIO_GAMES = [
    ("2025-11-01", "NYK", "BOS", 100, 95),
    ("2025-11-05", "NYK", "DET", 105, 100),
    ("2025-11-09", "NYK", "CHI", 110, 99),
]


async def test_zero_attempt_percentage_is_undefined_coverage(db_session):
    release = await _seed(
        db_session,
        _RATIO_GAMES,
        box={
            "Mikal Bridges": [(35, 10, 2, 0, 0), (35, 8, 2, 0, 0), (35, 12, 3, 0, 0)],
            "Karl-Anthony Towns": [(34, 10, 2, 0, 3), (34, 8, 2, 0, 3), (34, 12, 3, 0, 3)],
        },
    )
    bridges, _, undefined = await _deterministic(
        db_session, release, "What was Mikal Bridges' three-point percentage?"
    )
    assert "three_pointers_made:percentage" not in _claims(undefined)
    assert "undefined" in undefined["answer"].lower()
    assert "attempt" in undefined["answer"].lower()
    assert undefined["refused"] is False

    towns, _ = await _tools(
        db_session, release, "What was Karl-Anthony Towns' three-point percentage?"
    )
    measured = await AnalystLoop(towns, []).run(allow_model=False)
    claim = _claims(measured)["three_pointers_made:percentage"][0]
    assert claim["value"] == 0
    assert claim["sample_size"] == 3


async def test_compound_average_points_and_margin_deliver_both_measures(db_session):
    release = await _seed(db_session, _THRESHOLD_GAMES)
    tools, _, result = await _deterministic(
        db_session, release, "What were the Knicks' average points and average margin this season?"
    )
    assert tools.scope is not None
    assert len(getattr(tools.scope, "requested_measures", ())) == 2
    claims = _claims(result)
    assert claims["points_per_game"][0]["value"] == pytest.approx(315 / 3, abs=0.05)
    assert claims["margin_per_game"][0]["value"] == pytest.approx(25 / 3, abs=0.05)
    assert "points" in result["answer"] and "margin" in result["answer"]


async def test_operation_implied_total_cannot_become_a_model_average(db_session):
    release = await _seed(db_session, _THRESHOLD_GAMES)
    tools, _ = await _tools(
        db_session, release, "How many points did the Knicks score this season?"
    )
    result = await tools.execute(
        ToolCall(name="get_team_stats", question=tools.question, aggregation="average")
    )
    claims = {claim.metric_id: claim for claim in result.claims}
    assert "points_per_game" not in claims
    assert claims["points"].value == 315
    assert claims["points"].denominator is None


async def test_conflicting_model_stat_and_window_paraphrase_cannot_override(db_session):
    release = await _seed(
        db_session,
        [
            ("2025-11-01", "NYK", "BOS", 100, 95),
            ("2025-11-05", "NYK", "DET", 105, 100),
            ("2025-11-09", "NYK", "CHI", 110, 99),
            ("2025-11-13", "NYK", "MIA", 99, 101),
        ],
        box={
            "Jalen Brunson": [
                (36, 10, 5, 1, 3),
                (36, 20, 5, 1, 3),
                (36, 30, 5, 1, 3),
                (36, 40, 5, 1, 3),
            ]
        },
    )
    tools, _ = await _tools(
        db_session, release, "What was Jalen Brunson's average scoring in the first 3 games?"
    )
    assert tools.scope is not None
    assert tools.scope.relative_game_position == "first"
    assert tools.scope.aggregation == "average"
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question="What is Jalen Brunson's true shooting percentage in the last 3 games?",
            aggregation="total",
        )
    )
    claims = {claim.metric_id: claim for claim in result.claims}
    assert "true_shooting_percentage" not in claims
    claim = claims["points:average"]
    assert claim.value == pytest.approx(20)
    assert claim.game_ids == _ids(tools, "2025-11-01", "2025-11-05", "2025-11-09")


_SPLIT_GAMES = [
    ("2025-11-01", "NYK", "BOS", 100, 90),
    ("2025-11-05", "NYK", "DET", 105, 95),
    ("2025-11-09", "NYK", "CHI", 80, 90),
]
_SPLIT_TEAM = [
    (40, 90, 8, 25, 100, 11),
    (40, 90, 9, 25, 105, 12),
    (30, 80, 12, 24, 80, 14),
]


async def test_result_split_keeps_three_point_specificity(db_session):
    release = await _seed(db_session, _SPLIT_GAMES, team=_SPLIT_TEAM)
    _, _, result = await _deterministic(
        db_session, release, "Did the Knicks shoot better from three in wins or losses?"
    )
    claims = _claims(result)
    assert "field_goal_percentage" not in claims
    by_result = {
        claim["filters"]["game_result"]: claim for claim in claims["three_pointers_made:percentage"]
    }
    assert by_result["win"]["value"] == pytest.approx(100 * 17 / 50)
    assert by_result["loss"]["value"] == pytest.approx(100 * 12 / 24)
    assert result["outcome"] == "answer"


async def test_result_split_margin_keeps_both_outcomes(db_session):
    release = await _seed(db_session, _SPLIT_GAMES)
    tools, _, result = await _deterministic(
        db_session, release, "Compare the Knicks' average point differential in wins and losses."
    )
    assert tools.scope is not None and tools.scope.operation == "result_split"
    claims = _claims(result)["margin:average"]
    by_result = {claim["filters"]["game_result"]: claim for claim in claims}
    assert set(by_result) == {"win", "loss"}
    assert by_result["win"]["value"] == pytest.approx(10)
    assert by_result["loss"]["value"] == pytest.approx(-10)
    assert by_result["win"]["denominator"] == 2 and by_result["loss"]["denominator"] == 1


async def test_every_tied_leader_survives_deterministic_delivery(db_session):
    players = [
        "Jalen Brunson",
        "Julius Randle",
        "OG Anunoby",
        "Donte DiVincenzo",
        "Josh Hart",
        "Precious Achiuwa",
        "Karl-Anthony Towns",
        "Mikal Bridges",
    ]
    release = await _seed(
        db_session,
        [("2025-11-01", "NYK", "BOS", 100, 90)],
        box={name: [(30, 5, 10, 0, 1)] for name in players},
    )
    _, _, result = await _deterministic(db_session, release, "Who led the Knicks in assists?")
    claims = _claims(result)["assists:leader"]
    assert len(claims) == 8
    assert {claim["value"]["name"] for claim in claims} == set(players)
    assert result["outcome"] == "answer"


async def test_every_tied_extreme_survives_beyond_thirty(db_session):
    games = [(f"2025-10-{day:02d}", "NYK", "BOS", 100, 80 + day) for day in range(1, 32)]
    release = await _seed(db_session, games)
    tools, _, result = await _deterministic(
        db_session, release, "What was their highest-scoring game?"
    )
    claims = _claims(result)["points"]
    delivered = {game_id for claim in claims for game_id in (claim["game_ids"] or [])}
    assert delivered == {game.id for game in tools.games}
    assert len(claims) == 31
    assert result["outcome"] == "answer"
    assert tools.release.season in result["answer"] or "points" in result["answer"]


async def test_first_quarter_scoring_uses_period_rows(db_session):
    release = await _seed(
        db_session,
        [
            ("2025-11-01", "NYK", "BOS", 100, 90),
            ("2025-11-05", "NYK", "DET", 105, 100),
        ],
        periods={1: [28, 30], 4: [25, 26]},
    )
    tools, _, result = await _deterministic(
        db_session, release, "What was the Knicks' average first-quarter scoring?"
    )
    assert tools.scope is not None and tools.scope.operation == "period_scoring"
    claim = _claims(result)["period:points"][0]
    assert claim["filters"]["periods"] == [1]
    assert claim["value"] == pytest.approx(29)
    assert claim["denominator"] == 2


async def test_zero_turnover_ratio_is_undefined_coverage(db_session):
    release = await _seed(
        db_session,
        [("2025-11-01", "NYK", "BOS", 100, 90), ("2025-11-05", "NYK", "DET", 105, 100)],
        box={"Jalen Brunson": [(36, 20, 8, 1, 3), (36, 18, 6, 1, 3)]},
    )
    _, _, result = await _deterministic(
        db_session, release, "What was Jalen Brunson's assist-to-turnover ratio?"
    )
    assert "assist_turnover_ratio" not in _claims(result)
    assert "undefined" in result["answer"].lower()
    assert result["refused"] is False
