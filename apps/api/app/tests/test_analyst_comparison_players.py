"""Player comparisons: one shared appearance window and honest group coverage.

The comparison fixture puts Mikal Bridges' appearances on unequal dates and adds a later
zero-minute playoff row, so a window applied per group, dropped for the appearance basis,
or counting a DNP as an appearance changes the games, the values and the samples asserted
here. Donte DiVincenzo has box rows only in the Boston games, so the Toronto group has
team games without an observed appearance.
"""

from __future__ import annotations

import pytest
from app.tests.test_analyst_comparisons import _by_group, _claims, _game_ids, _run


async def test_shared_appearance_window_truncates_before_the_split(db_session):
    tools, _, result = await _run(
        db_session, "Compare Mikal Bridges' scoring at home and away over his last 2 appearances."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    spec = scope.comparison
    assert spec.measure == "player_metric" and spec.basis == "player_appearance"
    assert spec.filters.window is not None
    assert (spec.filters.window.position, spec.filters.window.count) == ("last", 2)

    grouped = _by_group(_claims(result)["points:average"])
    assert set(grouped) == {"home", "away"}
    home, away = grouped["home"], grouped["away"]
    # The last two observed appearances are one home and one road game; the later
    # zero-minute playoff row is not an appearance and consumes no window slot.
    assert home["game_ids"] == _game_ids(tools, "2026-01-20")
    assert away["game_ids"] == _game_ids(tools, "2026-02-20")
    assert home["value"] == pytest.approx(10.0) and away["value"] == pytest.approx(20.0)
    assert home["sample_size"] == 1 and away["sample_size"] == 1
    # The considered population is still every game each group selected.
    assert home["eligibility"]["considered_games"] == 5
    assert away["eligibility"]["considered_games"] == 3


async def test_shared_appearance_window_applies_before_the_opponent_split(db_session):
    tools, _, result = await _run(
        db_session,
        "Compare Mikal Bridges' scoring against Boston and Toronto over his last 3 appearances.",
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    assert [group.key for group in scope.comparison.groups] == ["BOS", "TOR"]

    grouped = _by_group(_claims(result)["points:average"])
    # The window is the player's last three appearances overall, so only the Toronto
    # game is still inside both the window and the group it belongs to.
    assert set(grouped) == {"TOR"}
    assert grouped["TOR"]["game_ids"] == _game_ids(tools, "2025-11-10")
    assert grouped["TOR"]["value"] == pytest.approx(10.0)
    answer = result["answer"].lower()
    assert "against bos" in answer and "no observed" in answer


async def test_player_group_without_observed_rows_is_reported_incomplete(db_session):
    tools, _, result = await _run(
        db_session, "Compare Donte DiVincenzo's scoring against Boston and Toronto."
    )
    scope = tools.scope
    assert scope is not None and scope.comparison is not None
    groups = {group.key: group for group in scope.comparison.groups}
    assert len(tools.comparison_populations(scope)[groups["TOR"].key]) == 2

    grouped = _by_group(_claims(result)["points:average"])
    assert set(grouped) == {"BOS"}
    assert grouped["BOS"]["sample_size"] == 2
    # The missing group is reported as unknown coverage, never as absence of play.
    answer = result["answer"].lower()
    assert "against tor" in answer and "no observed" in answer
    assert "does not show" in answer
