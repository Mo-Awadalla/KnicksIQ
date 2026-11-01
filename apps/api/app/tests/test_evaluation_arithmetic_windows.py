"""Windows and deltas: the appearances a claim names, and the windows it compares.

A windowed average must cite exactly its declared window, a recent-minus-prior delta
splits the subject's real appearances under the release policy, and a named
current/baseline pair is recomputed on both sides. A recipe that needs the release
projection blocks when it is absent instead of crediting its own subset.
"""

from __future__ import annotations

from app.services.analyst_discovery import discover
from app.services.analyst_rankings import streaks
from app.tests.support.evaluation_archive import POLICY, _appearances, _discovery_tools, _tools
from app.tests.support.evaluation_mapping import _calculated, _mapping, _resolve


async def test_recent_average_must_cite_the_declared_window(db_session, tmp_path) -> None:
    tools = await _discovery_tools(db_session)
    assert tools.scope is not None
    brunson = next(player for _, player in tools.rows if player.full_name == "Jalen Brunson")
    appearances = _appearances(tools, brunson.id)
    prior = appearances[:4]
    mapping = _mapping(tools, tmp_path)
    claim = tools.claim(
        subject=f"player:{brunson.id}",
        metric="points:average",
        value=8.0,
        unit="points per appearance",
        games=[game for game, _ in prior],
        evidence=[tools.receipt(game, stat, player) for game, (stat, player) in prior],
        statement="Jalen Brunson: 8.0 points per appearance across 4 recent appearances.",
        scope=tools.scope,
        sample=4,
        denominator=4,
        eligibility=POLICY,
        window={"kind": "recent"},
    )
    resolution = _resolve(mapping, tools, claim)
    assert "calculation_scope_mismatch" in resolution.problems
    assert not resolution.resolved


async def test_discovery_claims_recompute_from_the_population(db_session, tmp_path) -> None:
    tools = await _discovery_tools(db_session)
    assert tools.scope is not None
    result = discover(tools, tools.scope, tools.considered_games(tools.scope))
    assert result.status == "ok" and result.claims
    calculated = _calculated(list(tools.claims.values()))
    metrics = {claim.metric_id for claim in calculated}
    assert {"points:delta", "points:qualifier_rank"} <= metrics
    assert "true_shooting_percentage:average" in metrics
    mapping = _mapping(tools, tmp_path)
    recipes = set()
    for claim in calculated:
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (claim.metric_id, resolution.problems)
        assert resolution.unverified == (), (claim.metric_id, resolution.unverified)
        recipes.add(resolution.recipe)
    assert {"appearance_delta", "qualifier_rank"} <= recipes
    assert "box_true_shooting" in recipes


async def test_recent_minus_prior_delta_uses_the_declared_appearances(db_session, tmp_path) -> None:
    tools = await _discovery_tools(db_session)
    assert tools.scope is not None
    discover(tools, tools.scope, tools.considered_games(tools.scope))
    delta = next(claim for claim in tools.claims.values() if claim.metric_id == "points:delta")
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, delta)
    assert resolution.problems == () and resolution.unverified == ()
    assert resolution.recipe == "appearance_delta"
    window = delta.window
    assert window is not None
    restated = delta.model_copy(update={"window": {**window, "last_n": 9}})
    broken = _resolve(mapping, tools, restated)
    assert broken.problems
    assert not broken.resolved


async def test_window_delta_recomputes_both_windows(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points per game did Brunson average?")
    assert tools.scope is not None
    games = tools.considered_games(tools.scope)
    current, baseline = games[:4], games[4:]
    brunson = next(player for _, player in tools.rows if player.full_name == "Jalen Brunson")
    appearances = _appearances(tools, brunson.id)

    def mean(selection) -> float:
        wanted = {game.id for game in selection}
        rows = [stat for game, (stat, _) in appearances if game.id in wanted]
        return sum(stat.points for stat in rows) / len(rows)

    evidence = [tools.receipt(game, stat, player) for game, (stat, player) in appearances]
    claim = tools.claim(
        subject=f"player:{brunson.id}",
        metric="points:delta",
        value=mean(current) - mean(baseline),
        unit="points per appearance",
        games=current + baseline,
        evidence=evidence,
        statement="Current window against the baseline window.",
        scope=tools.scope,
        sample=len(current),
        denominator=len(current),
        window={
            "current": [game.id for game in current],
            "baseline": [game.id for game in baseline],
        },
    )
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == (), resolution.problems
    assert resolution.recipe == "window_delta"
    swapped = tools.claim(
        subject=f"player:{brunson.id}",
        metric="points:delta",
        value=mean(baseline) - mean(current),
        unit="points per appearance",
        games=current + baseline,
        evidence=evidence,
        statement="Current window against the baseline window.",
        scope=tools.scope,
        sample=len(current),
        denominator=len(current),
        window={
            "current": [game.id for game in current],
            "baseline": [game.id for game in baseline],
        },
    )
    broken = _resolve(mapping, tools, swapped)
    assert "calculation_arithmetic_mismatch" in broken.problems


async def test_whole_population_recipe_blocks_without_a_projection(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "When was the longest losing streak?")
    assert tools.scope is not None
    result = streaks(tools, tools.scope, tools.considered_games(tools.scope))
    (claim,) = [item for item in result.claims if item.metric_id == "losing_streak_length"]
    mapping = _mapping(tools, tmp_path, projections=False)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.unverified == ("calculation_population_snapshot_missing",)
    assert not resolution.resolved
