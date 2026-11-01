"""Team-game arithmetic: records, score margins, periods and bench points.

Every number here is rebuilt from the cited game or box rows; a recorded numerator is
only ever a second opinion that must agree with the rows.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    EXPANSION_MISMATCH,
    GAME,
    MISSING_FIELDS,
    PLAYER,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SUBJECT_MISMATCH,
    UNSUPPORTED,
    ClaimView,
    Proof,
    blocked,
    declaration,
    invalid,
    number,
    same,
    team_of,
    team_score,
    tolerance,
)

GAME_TOTALS = {
    "points": "own",
    "points_allowed": "other",
    "margin": "margin",
    "margin:total": "margin",
}
GAME_MEANS = {
    "points_per_game": "own",
    "points_allowed_per_game": "other",
    "margin_per_game": "margin",
    "margin:average": "margin",
}
GAME_METRICS = frozenset({"wins", "losses", "games", *GAME_TOTALS, *GAME_MEANS})
BENCH_POINTS = "bench_points_per_team_game"
GAME_SCORE = "game_score"
SCORELINE = (
    "nba_game_id",
    "game_date",
    "home_team_id",
    "away_team_id",
    "home_score",
    "away_score",
)


def prove_game(view: ClaimView, rows: list[dict[str, Any]], collections: list[str]) -> Proof:
    if view.metric == GAME_SCORE:
        return _scoreline(view, rows)
    return _game(view, rows)


def prove_bench(view: ClaimView, rows: list[dict[str, Any]], collections: list[str]) -> Proof:
    return _bench(view, rows, collections)


def prove_period(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    return _period(view, rows)


def _scoreline(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    """One pinned game's final score: the cited game row's own annotated fields."""
    if team_of(view.subject) is None:
        return invalid((SUBJECT_MISMATCH,))
    if len(rows) != 1:
        return blocked(UNSUPPORTED)
    if not isinstance(view.value, dict) or set(view.value) != set(SCORELINE):
        return invalid((ARITHMETIC_MISMATCH,), "game_scoreline")
    row = rows[0]
    problems = [
        ARITHMETIC_MISMATCH
        for field in SCORELINE
        if not _field_matches(view.value.get(field), row.get(field))
    ]
    if view.sample_size is not None and int(view.sample_size) != 1:
        problems.append(POPULATION_MISMATCH)
    if view.denominator is not None:
        # A scoreline is an identity, so it never carries a per-unit denominator.
        problems.append(POPULATION_MISMATCH)
    if problems:
        return invalid(problems, "game_scoreline")
    return Proof("verified", "game_scoreline")


def _field_matches(recorded: Any, expected: Any) -> bool:
    if number(recorded) and number(expected):
        return abs(float(recorded) - float(expected)) <= 1e-9
    return recorded == expected


def _component(component: str, pair: tuple[float, float]) -> float:
    own, other = pair
    return {"own": own, "other": other}.get(component, own - other)


def _scores(rows: list[dict[str, Any]], team: str) -> list[tuple[float, float]] | None:
    pairs = [team_score(row, team) for row in rows]
    if any(pair is None for pair in pairs):
        return None
    return [pair for pair in pairs if pair is not None]


def _game(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    team = team_of(view.subject)
    if team is None:
        return invalid((SUBJECT_MISMATCH,))
    pairs = _scores(rows, team)
    if pairs is None:
        return invalid((SUBJECT_MISMATCH,))
    count = len(pairs)
    if view.metric in {"wins", "losses"}:
        wins = sum(1 for own, other in pairs if own > other)
        expected = float(wins if view.metric == "wins" else count - wins)
        recipe = "game_result_count"
        problems, reason = declaration(count, view.denominator, view.sample_size, mean=False)
    elif view.metric == "games":
        if view.sample_size is not None and int(view.sample_size) != count:
            return blocked(UNSUPPORTED)
        expected = float(count)
        recipe = "game_count"
        problems, reason = declaration(count, view.denominator, view.sample_size, mean=False)
    else:
        mean = view.metric in GAME_MEANS
        component = GAME_TOTALS.get(view.metric) or GAME_MEANS.get(view.metric)
        if component is None:
            return blocked(UNSUPPORTED)
        total = sum(_component(component, pair) for pair in pairs)
        recipe = "game_score_mean" if mean else "game_score_total"
        if view.numerator is not None and abs(float(view.numerator) - total) > 1e-9:
            return invalid((ARITHMETIC_MISMATCH,), recipe)
        problems, reason = declaration(count, view.denominator, view.sample_size, mean=mean)
        expected = total / count if mean else total
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems, recipe)
    if not same(view.value, expected, tolerance(view.decimals)):
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    return Proof("verified", recipe)


def _period(view: ClaimView, rows: list[dict[str, Any]]) -> Proof:
    team = team_of(view.subject)
    if team is None or any(row.get("team_id") != team for row in rows):
        return invalid((SUBJECT_MISMATCH,))
    recipe = "period_points_mean"
    if len({row.get("period") for row in rows}) != 1:
        return invalid((EXPANSION_MISMATCH,), recipe)
    if any(not number(row.get("points")) for row in rows):
        return blocked(MISSING_FIELDS)
    total = sum(float(row["points"]) for row in rows)
    if view.numerator is not None and abs(float(view.numerator) - total) > 1e-9:
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    problems, reason = declaration(len(rows), view.denominator, view.sample_size, mean=True)
    if reason:
        return blocked(reason)
    if problems:
        return invalid(problems, recipe)
    if not same(view.value, total / len(rows), tolerance(view.decimals)):
        return invalid((ARITHMETIC_MISMATCH,), recipe)
    return Proof("verified", recipe)


def _bench(view: ClaimView, rows: list[dict[str, Any]], collections: list[str]) -> Proof:
    """Bench points per team game, rebuilt from the group's games and its bench rows."""
    team = team_of(view.subject)
    if team is None:
        return invalid((SUBJECT_MISMATCH,))
    games = [row for row, kind in zip(rows, collections, strict=True) if kind == GAME]
    players = [row for row, kind in zip(rows, collections, strict=True) if kind == PLAYER]
    if _scores(games, team) is None:
        return invalid((SUBJECT_MISMATCH,))
    if any(row.get("team_id") not in (None, team) for row in players):
        return invalid((SUBJECT_MISMATCH,))
    bench = [row for row in players if row.get("starter") is False]
    if any(not number(row.get("minutes")) for row in bench):
        return blocked(MISSING_FIELDS)
    observed = [row for row in bench if float(row["minutes"]) > 0]
    if any(not number(row.get("points")) for row in observed):
        return blocked(MISSING_FIELDS)
    points = sum(float(row["points"]) for row in observed)
    if not games:
        return invalid((POPULATION_MISMATCH,), BENCH_POINTS)
    # The sample is the observed appearances the numerator sums; the denominator is every
    # team game in the group, including the games the bench did not score in.
    if view.sample_size is None or view.denominator is None:
        return blocked(POPULATION_UNVERIFIED)
    if int(view.sample_size) != len(observed) or abs(float(view.denominator) - len(games)) > 1e-9:
        return invalid((POPULATION_MISMATCH,), BENCH_POINTS)
    if view.numerator is not None and abs(float(view.numerator) - points) > 1e-9:
        return invalid((ARITHMETIC_MISMATCH,), BENCH_POINTS)
    if not same(view.value, points / len(games), tolerance(view.decimals)):
        return invalid((ARITHMETIC_MISMATCH,), BENCH_POINTS)
    return Proof("verified", BENCH_POINTS)
