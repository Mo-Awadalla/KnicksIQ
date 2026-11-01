"""Team comparisons answer the stat the question names, one scalar fact per group.

Each case drives the comparison fixture archive through the deterministic path, so a
defensive ask that returns points scored, a total ask folded into a mean, or a group
reported without its considered population fails here.
"""

from __future__ import annotations

import pytest
from app.tests.test_analyst_comparisons import _by_group, _claims, _game_ids, _run


async def test_defense_comparison_reports_points_allowed(db_session):
    tools, _, result = await _run(
        db_session, "Compare the Knicks' defense at home and on the road."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert scope.comparison.team_metric == "points_allowed_per_game"

    assert set(_claims(result)) == {"points_allowed_per_game"}
    grouped = _by_group(_claims(result)["points_allowed_per_game"])
    assert grouped["home"]["value"] == pytest.approx(513 / 5)
    assert grouped["away"]["value"] == pytest.approx(279 / 3)
    assert grouped["home"]["game_ids"] == _game_ids(
        tools, "2025-11-01", "2025-11-10", "2025-11-15", "2026-01-20", "2026-06-10"
    )
    assert grouped["away"]["game_ids"] == _game_ids(tools, "2025-11-05", "2026-02-10", "2026-02-20")


async def test_total_request_keeps_a_total_points_fact(db_session):
    tools, _, result = await _run(
        db_session, "Compare the Knicks' total points at home and on the road."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert scope.comparison.team_metric == "points"

    assert set(_claims(result)) == {"points"}
    grouped = _by_group(_claims(result)["points"])
    assert grouped["home"]["value"] == 544
    assert grouped["away"]["value"] == 308
    # A total is not given a per-game denominator it never claimed.
    assert grouped["home"]["denominator"] is None
    assert grouped["home"]["sample_size"] == 5 and grouped["away"]["sample_size"] == 3
    assert grouped["home"]["eligibility"]["considered_games"] == 5
