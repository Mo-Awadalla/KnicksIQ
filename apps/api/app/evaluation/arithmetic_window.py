"""Catalog windows: the release games each one names, and the membership they imply.

A windowed claim is only proved when the rows it cites are exactly the window it
declared. The window itself is read from the catalog's own vocabulary — the season
types, the month label, the last-n count in archive games — and resolved against the
mapping's verified projection of the whole release, never against the claim's own
subset.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_core import (
    ELIGIBILITY_MISMATCH,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SCOPE_MISMATCH,
    SUBJECT_MISMATCH,
    WINDOW_UNVERIFIED,
    ClaimView,
    Population,
    WindowCheck,
    integer,
    player_of,
)

MEMBERSHIP_WINDOWS = frozenset(
    {"recent", "prior", "regular_season", "playoffs", "full_archive", "last_n", "month"}
)


def check_window_membership(
    view: ClaimView, rows: list[dict[str, Any]], population: Population
) -> WindowCheck | None:
    """Prove the cited rows of a windowed average are exactly the window it names."""
    window = view.window
    if not isinstance(window, dict) or window.get("kind") not in MEMBERSHIP_WINDOWS:
        return None
    if not view.metric.endswith(":average"):
        return None
    subject = player_of(view.subject)
    if subject is None:
        return WindowCheck((SUBJECT_MISMATCH,))
    missing = population.gap(box=True)
    if missing:
        return WindowCheck(reason=missing)
    appearances = population.appearances(subject)
    if appearances is None:
        return WindowCheck(reason=POPULATION_UNVERIFIED)
    kind = window.get("kind")
    if kind in {"recent", "prior"}:
        count, problems, reason = recent_window(view, window)
        if reason:
            return WindowCheck(reason=reason)
        if problems:
            return WindowCheck(tuple(problems))
        if len(appearances) < count:
            return WindowCheck((POPULATION_MISMATCH,))
        expected = appearances[-count:] if kind == "recent" else appearances[:-count]
    else:
        game_ids, reason = window_games(window, population)
        if reason:
            return WindowCheck(reason=reason)
        wanted = {int(game_id) for game_id in game_ids}
        expected = [row for row in appearances if row.game_id in wanted]
    cited = population.cited_game_ids(rows)
    if cited is None:
        return WindowCheck(reason=POPULATION_UNVERIFIED)
    ordered = population.ordered(cited)
    if ordered is None:
        return WindowCheck(reason=POPULATION_UNVERIFIED)
    expected_ids = [row.game_id for row in expected]
    problems: list[str] = []
    if list(ordered) != expected_ids:
        problems.append(SCOPE_MISMATCH)
    if set(view.game_ids) != set(expected_ids):
        problems.append(SCOPE_MISMATCH)
    return WindowCheck(tuple(dict.fromkeys(problems)))


def window_games(window: dict[str, Any], population: Population) -> tuple[list[int], str | None]:
    """The release games one catalog window names, in archive order."""
    kind = window.get("kind")
    ordered = population.ordered(list(population.games))
    if ordered is None:
        return [], POPULATION_UNVERIFIED
    if kind == "full_archive":
        return ordered, None
    if kind == "regular_season":
        return [game for game in ordered if season_type(game, population) == "regular"], None
    if kind == "playoffs":
        return [
            game for game in ordered if season_type(game, population) in {"play_in", "playoffs"}
        ], None
    if kind == "month":
        label = window.get("label")
        if not isinstance(label, str) or len(label) != 7:
            return [], WINDOW_UNVERIFIED
        return [
            game
            for game in ordered
            if str(population.games[game].row.get("game_date"))[:7] == label
        ], None
    if kind == "last_n":
        count = integer(window.get("last_n"))
        if count is None or count < 1 or window.get("unit") != "archive_games":
            return [], WINDOW_UNVERIFIED
        return ordered[-count:], None
    return [], WINDOW_UNVERIFIED


def recent_window(view: ClaimView, window: dict[str, Any]) -> tuple[int, list[str], str | None]:
    """The claim's declared recent window, with the window and policy records agreeing."""
    raw = window.get("last_n")
    if raw is not None and integer(raw) is None:
        return 0, [], WINDOW_UNVERIFIED
    recorded = integer(raw) if raw is not None else None
    declared = view.eligibility.get("recent_window")
    policy = integer(declared) if declared is not None else None
    count = recorded if recorded is not None else policy
    if count is None or count < 1:
        return 0, [], WINDOW_UNVERIFIED
    if recorded is not None and policy is not None and recorded != policy:
        return count, [ELIGIBILITY_MISMATCH], None
    if declared is not None and policy is None:
        return count, [ELIGIBILITY_MISMATCH], None
    return count, [], None


def season_type(game_id: int, population: Population) -> str | None:
    return population.games[game_id].row.get("season_type")
