from __future__ import annotations

import re

import pytest
from app.services.analyst_fallback import fallback_claims
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.test_metric_authority import _claims, _deterministic, _seed, _tools

GAMES = [
    ("2025-11-01", "NYK", "BOS", 80, 70),
    ("2025-11-05", "DET", "NYK", 70, 90),
    ("2025-11-09", "NYK", "MIA", 100, 90),
    ("2025-11-13", "CHI", "NYK", 100, 110),
]


async def test_exploratory_subset_cannot_answer_season_average(db_session):
    release = await _seed(
        db_session,
        [("2026-01-01", "NYK", "BOS", 80, 70), ("2026-02-01", "NYK", "DET", 120, 110)],
    )
    tools, loop = await _tools(db_session, release, "What was the Knicks' average scoring?")
    loop.results.append(
        await tools.execute(
            ToolCall(
                name="get_team_stats", question="What was the Knicks' average scoring in January?"
            )
        )
    )
    result = await loop.fallback("Review failed.")
    claim = _claims(result)["points_per_game"][0]
    assert claim["value"] == 100
    assert claim["sample_size"] == 2


async def test_grouped_comparison_preserves_shared_last_two_games(db_session):
    release = await _seed(db_session, GAMES)
    tools, _, result = await _deterministic(
        db_session, release, "Compare home and away scoring over the last 2 games."
    )
    claims = _claims(result)["points_per_game"]
    by_group = {claim["eligibility"]["comparison_group"]: claim for claim in claims}
    assert by_group["home"]["value"] == 100
    assert by_group["away"]["value"] == 110
    assert by_group["away"]["sample_size"] == 1
    expected = {game.id for game in tools.games[-2:]}
    assert {game_id for claim in claims for game_id in claim["game_ids"]} == expected


async def test_narrowed_leaderboard_cannot_answer_the_season(db_session):
    release = await _seed(
        db_session,
        [
            ("2026-01-05", "NYK", "BOS", 100, 90),
            ("2026-01-10", "NYK", "DET", 100, 90),
            ("2026-02-05", "NYK", "MIA", 100, 90),
            ("2026-02-10", "NYK", "CHI", 100, 90),
        ],
        box={
            "Jalen Brunson": [
                (30, 20, 10, 0, 0),
                (30, 20, 1, 0, 0),
                (30, 20, 0, 0, 0),
                (30, 20, 0, 0, 0),
            ],
            "Karl-Anthony Towns": [
                (30, 20, 0, 0, 0),
                (30, 20, 2, 0, 0),
                (30, 20, 9, 0, 0),
                (30, 20, 9, 0, 0),
            ],
        },
    )
    question = "Who led the Knicks in assists this season?"
    tools, loop = await _tools(db_session, release, question)
    loop.results.append(
        await tools.execute(
            ToolCall(name="get_player_stats", question="Who led the Knicks in assists in January?")
        )
    )
    january = loop.results[-1]
    names: set[str] = set()
    for claim in january.claims:
        value = claim.value
        assert isinstance(value, dict), value
        name = value["name"]
        assert isinstance(name, str), name
        names.add(name)
    assert names == {"Jalen Brunson"}
    # January ranks a subset of the season, so it never answers the season ask.
    assert fallback_claims(loop) == []
    result = await loop.fallback("Review failed.")
    leaders = _claims(result)["assists:leader"]
    assert {claim["value"]["name"] for claim in leaders} == {"Karl-Anthony Towns"}
    assert "Jalen Brunson led" not in result["answer"]


async def test_compound_total_and_average_keep_independent_aggregations(db_session):
    release = await _seed(db_session, GAMES)
    _, _, result = await _deterministic(
        db_session, release, "What were the Knicks' total points and average margin this season?"
    )
    claims = _claims(result)
    assert claims["points"][0]["value"] == 380
    assert claims["points"][0]["denominator"] is None
    assert claims["margin_per_game"][0]["value"] == 12.5


async def test_pronoun_threshold_counts_inherited_player_appearances(db_session):
    release = await _seed(
        db_session,
        GAMES[:3],
        box={"Jalen Brunson": [(36, 30, 5, 1, 3), (36, 20, 5, 1, 3), (36, 26, 5, 1, 3)]},
    )
    _, _, first = await _deterministic(db_session, release, "What was Brunson's average points?")
    tools = AnalystTools(
        db_session,
        release,
        "And how many games did he score at least 25?",
        release.season,
        first["state"],
    )
    await tools.prepare()
    result = await AnalystLoop(tools, []).run(allow_model=False)
    claim = _claims(result)["points:threshold"][0]
    assert claim["value"] == 2
    assert claim["denominator"] == 3
    assert claim["subject_id"].startswith("player:")


async def test_recent_appearance_comparison_ignores_storage_order(db_session):
    release = await _seed(
        db_session,
        GAMES[:3],
        box={"Jalen Brunson": [(36, 10, 5, 1, 3), (36, 20, 5, 1, 3), (36, 30, 5, 1, 3)]},
    )
    tools, loop = await _tools(
        db_session,
        release,
        "Compare Brunson's scoring in the last 2 games with his season average.",
    )
    tools.rows.reverse()
    result = await loop.run(allow_model=False)
    recent = next(claim for claim in _claims(result)["points:average"] if claim["sample_size"] == 2)
    assert recent["value"] == 25
    assert recent["game_ids"] == sorted(game.id for game in tools.games[-2:])


async def test_partial_comparison_delivers_missing_group_explanation(db_session):
    release = await _seed(
        db_session,
        GAMES,
        box={
            "Mikal Bridges": [
                (35, 10, 1, 0, 0),
                (35, 12, 1, 2, 4),
                (35, 14, 1, 0, 0),
                (35, 16, 1, 1, 2),
            ]
        },
    )
    _, _, result = await _deterministic(
        db_session, release, "Compare Mikal Bridges' three-point percentage at home and away."
    )
    claim = _claims(result)["three_pointers_made:percentage"][0]
    assert claim["value"] == pytest.approx(50)
    assert result["outcome"] == "answer"
    assert result["degraded"] is True
    assert "home" in result["answer"].lower()
    assert re.search(r"undefined|no .*attempt|zero .*attempt", result["answer"], re.IGNORECASE)
