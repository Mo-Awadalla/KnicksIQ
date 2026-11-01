"""Whole-population arithmetic: threshold counts, streaks and leaderboards.

A claim that counts or ranks a population is recomputed from the mapping's verified
projection of the whole release, so it cannot pass by citing only the part of the
population that makes its own arithmetic true. A restated cutoff fails the count, a run
must be one of the tied runs, a leaderboard total must be the one its rows hold, and a
claim that restates its own population fails.
"""

from __future__ import annotations

from app.services.analyst_player_stats import leaderboard, player_threshold
from app.services.analyst_rankings import streaks
from app.services.analyst_team_splits import threshold_count
from app.tests.support.evaluation_archive import TIES, _appearances, _tools
from app.tests.support.evaluation_mapping import _mapping, _resolve


async def test_threshold_count_recomputes_from_the_whole_population(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did the Knicks score at least 120?")
    assert tools.scope is not None and tools.scope.threshold is not None
    result = threshold_count(tools, tools.scope, tools.considered_games(tools.scope))
    (claim,) = result.claims
    assert claim.metric_id == "games" and claim.value == 1
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.unverified == ()
    assert resolution.recipe == "team_threshold_count"
    assert resolution.resolved
    scores = [tools.score(game)[0] for game in tools.considered_games(tools.scope)]
    assert claim.value == sum(score >= 120 for score in scores)
    assert claim.denominator == len(scores)


async def test_zero_match_threshold_count_proves_zero(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did the Knicks score at least 140?")
    assert tools.scope is not None and tools.scope.threshold is not None
    result = threshold_count(tools, tools.scope, tools.considered_games(tools.scope))
    (claim,) = result.claims
    assert claim.value == 0 and claim.game_ids == []
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "team_threshold_count"
    assert resolution.resolved


async def test_a_restated_cutoff_fails_the_recomputed_count(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did the Knicks score at least 120?")
    assert tools.scope is not None and tools.scope.threshold is not None
    result = threshold_count(tools, tools.scope, tools.considered_games(tools.scope))
    (claim,) = result.claims
    mapping = _mapping(tools, tmp_path)
    restated = claim.model_copy(update={"eligibility": {**claim.eligibility, "threshold": 118}})
    resolution = _resolve(mapping, tools, restated)
    assert "calculation_scope_mismatch" in resolution.problems
    assert not resolution.resolved


async def test_leaderboard_total_recomputes_from_the_population(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "Who led the Knicks in assists?")
    assert tools.scope is not None
    result = leaderboard(tools, tools.scope)
    (claim,) = result.claims
    assert claim.metric_id == "assists:leader"
    assert claim.value == {"name": "Jalen Brunson", "total": 48}
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.unverified == ()
    assert resolution.recipe == "player_leaderboard"


async def test_a_leaderboard_that_does_not_lead_the_population_is_invalid(
    db_session, tmp_path
) -> None:
    tools = await _tools(db_session, "Who led the Knicks in assists?")
    assert tools.scope is not None
    result = leaderboard(tools, tools.scope)
    (claim,) = result.claims
    assert claim.value == {"name": "Jalen Brunson", "total": 48}
    brunson = next(player for _, player in tools.rows if player.full_name == "Jalen Brunson")
    appearances = _appearances(tools, brunson.id)
    mapping = _mapping(tools, tmp_path)
    # The subject really is the leader, but the displayed total is not what the rows hold.
    overstated = tools.claim(
        subject=f"player:{brunson.id}",
        metric="assists:leader",
        value={"name": "Jalen Brunson", "total": 54},
        unit="assists",
        games=[game for game, _ in appearances],
        evidence=[tools.receipt(game, stat, player) for game, (stat, player) in appearances],
        statement="Jalen Brunson led the Knicks in assists with 54 total.",
        scope=tools.scope,
        sample=len(appearances),
        denominator=len(appearances),
        operation="player_leaderboard",
        considered_game_ids=[game.id for game in tools.considered_games(tools.scope)],
    )
    resolution = _resolve(mapping, tools, overstated)
    assert "calculation_arithmetic_mismatch" in resolution.problems
    assert not resolution.resolved


async def test_player_threshold_counts_observed_appearances(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did Brunson score at least 25?")
    assert tools.scope is not None and tools.scope.operation == "player_threshold"
    result = player_threshold(tools, tools.scope)
    (claim,) = result.claims
    assert claim.metric_id == "points:threshold" and claim.value == 3
    assert claim.sample_size == 3 and claim.denominator == 8
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "player_threshold_count"


async def test_player_threshold_zero_counts_prove_zero(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did Brunson score at least 40?")
    assert tools.scope is not None and tools.scope.operation == "player_threshold"
    result = player_threshold(tools, tools.scope)
    (claim,) = result.claims
    assert claim.value == 0
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "player_threshold_count"


async def test_a_restated_player_population_fails(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many games did Brunson score at least 25?")
    assert tools.scope is not None
    result = player_threshold(tools, tools.scope)
    (claim,) = result.claims
    mapping = _mapping(tools, tmp_path)
    considered = list(claim.eligibility["considered_game_ids"])
    restated = claim.model_copy(
        update={
            "eligibility": {**claim.eligibility, "considered_game_ids": considered[:-1]},
        }
    )
    resolution = _resolve(mapping, tools, restated)
    assert "calculation_population_mismatch" in resolution.problems
    assert not resolution.resolved


async def test_streak_claims_recompute_from_the_chronological_population(
    db_session, tmp_path
) -> None:
    tools = await _tools(db_session, "When was the longest losing streak?")
    assert tools.scope is not None
    result = streaks(tools, tools.scope, tools.considered_games(tools.scope))
    claims = {claim.metric_id: claim for claim in result.claims}
    assert {"losing_streak", "losing_streak_length"} <= set(claims)
    assert claims["losing_streak_length"].value == 4
    mapping = _mapping(tools, tmp_path)
    length = _resolve(mapping, tools, claims["losing_streak_length"])
    assert length.problems == () and length.unverified == ()
    assert length.recipe == "streak_length"
    run = _resolve(mapping, tools, claims["losing_streak"])
    assert run.problems == () and run.unverified == ()
    assert run.recipe == "streak_run"


async def test_every_tied_run_is_reported_and_proved(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "When was the longest losing streak?", TIES)
    assert tools.scope is not None
    result = streaks(tools, tools.scope, tools.considered_games(tools.scope))
    claims = [claim for claim in result.claims if claim.metric_id == "losing_streak"]
    length = next(claim for claim in result.claims if claim.metric_id == "losing_streak_length")
    assert len(claims) == 2 and length.value == 4
    length_ids = length.game_ids
    assert length_ids is not None
    assert len(length_ids) == 8
    mapping = _mapping(tools, tmp_path)
    runs: list[tuple[int, ...]] = []
    for claim in claims:
        assert claim.game_ids is not None, claim.claim_id
        runs.append(tuple(claim.game_ids))
    assert {game for run in runs for game in run} == set(length_ids)
    assert len(set(runs)) == 2
    for claim in [*claims, length]:
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (claim.game_ids, resolution.problems)
        assert resolution.unverified == ()


async def test_a_streak_citing_the_opposite_run_is_invalid(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "When was the longest losing streak?", TIES)
    assert tools.scope is not None
    population = tools.considered_games(tools.scope)
    winning = [game for game in population[4:8]]
    claim = tools.claim(
        subject="team:NYK",
        metric="losing_streak",
        value=4,
        unit="games",
        games=winning,
        evidence=[tools.receipt(game) for game in winning],
        statement="A 4-game losing streak ran from 2025-11-09 through 2025-11-15.",
        scope=tools.scope,
        sample=len(population),
        denominator=None,
        operation="longest_losing_streak",
        considered_game_ids=[game.id for game in population],
    )
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert "calculation_scope_mismatch" in resolution.problems
    assert not resolution.resolved


async def test_a_changed_population_score_breaks_the_streak_length(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "When was the longest losing streak?")
    assert tools.scope is not None
    result = streaks(tools, tools.scope, tools.considered_games(tools.scope))
    length = next(claim for claim in result.claims if claim.metric_id == "losing_streak_length")
    assert length.value == 4
    # 2026-01-08 is inside no cited run; the mapping's projection says the Knicks lost it,
    # so the whole population holds a five-game run and the claim's four is wrong.
    mapping = _mapping(tools, tmp_path, overrides={"0022500007": {"away_score": 95}})
    assert mapping.population.present()
    resolution = _resolve(mapping, tools, length)
    assert "calculation_arithmetic_mismatch" in resolution.problems
    assert not resolution.resolved
