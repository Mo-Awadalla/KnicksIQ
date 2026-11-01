"""Ranks and leaderboards: the qualified population one subject is placed in.

A qualifier rank recomputes every qualified subject's window value under the release
qualifier policy — the appearance minimum, the true-shooting attempt minimum and the
home-team filter — then holds the claim's rank one to a value-and-nba-id tie break. A
leaderboard recomputes the same population's totals or averages and holds the subject
to the top of it, so a displayed number can never be larger than the rows that back it.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.arithmetic_box import aggregate, box_column, totals
from app.evaluation.arithmetic_core import (
    ARITHMETIC_MISMATCH,
    ELIGIBILITY_UNVERIFIED,
    EXPANSION_MISMATCH,
    HOME_TEAM,
    MINIMUM_APPEARANCES,
    MISSING_FIELDS,
    POPULATION_MISMATCH,
    POPULATION_UNVERIFIED,
    SCOPE_MISMATCH,
    SUBJECT_MISMATCH,
    TRUE_SHOOTING_MINIMUM_FGA,
    UNSUPPORTED,
    WINDOW_UNVERIFIED,
    ClaimView,
    Population,
    PopulationRow,
    Proof,
    appeared,
    blocked,
    counts_as,
    declared_ids,
    integer,
    invalid,
    number,
    player_of,
    policy_problems,
    population_invalid,
    same,
)
from app.evaluation.arithmetic_window import window_games

RANK_SUFFIX = ":qualifier_rank"
LEADER_SUFFIX = ":leader"
RANK_SLACK = 1e-6


def prove(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof | None:
    """One rank or leaderboard recipe, or None when this claim is not one."""
    if view.metric.endswith(RANK_SUFFIX):
        return _rank(view, rows, population)
    if view.metric.endswith(LEADER_SUFFIX):
        return _leaderboard(view, rows, population)
    return None


def _rank(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    window = view.window
    if not isinstance(window, dict):
        return blocked(WINDOW_UNVERIFIED)
    if view.sample_size is None:
        return blocked(POPULATION_UNVERIFIED)
    policy, reason = policy_problems(view.eligibility)
    if reason:
        return blocked(reason)
    if policy:
        return invalid(policy)
    subject = player_of(view.subject)
    if subject is None:
        return invalid((SUBJECT_MISMATCH,))
    missing = population.gap(box=True)
    if missing:
        return blocked(missing)
    stat = view.metric[: -len(RANK_SUFFIX)]
    game_ids, reason = window_games(window, population)
    if reason:
        return blocked(reason)
    values, reason = _qualified(game_ids, stat, population)
    if reason:
        return blocked(reason)
    if subject not in values:
        # The claim says its subject is a qualified rank-one subject in this window.
        return invalid((ARITHMETIC_MISMATCH,), "qualifier_rank")
    nba_ids: dict[int, int] = {}
    for player_id in values:
        nba_id = _nba_player_id(player_id, population)
        if nba_id is None:
            return blocked(POPULATION_UNVERIFIED)
        nba_ids[player_id] = nba_id
    problems: list[str] = []
    for other, value in values.items():
        if other == subject:
            continue
        if value > values[subject] + RANK_SLACK:
            problems.append(ARITHMETIC_MISMATCH)
        elif abs(value - values[subject]) <= RANK_SLACK and nba_ids[other] < nba_ids[subject]:
            problems.append(ARITHMETIC_MISMATCH)
    if integer(view.value) != 1:
        problems.append(ARITHMETIC_MISMATCH)
    if not counts_as(view.sample_size, len(values)) or not counts_as(view.denominator, len(values)):
        problems.append(POPULATION_MISMATCH)
    if set(view.game_ids) != set(game_ids):
        problems.append(SCOPE_MISMATCH)
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    covered = {
        row.game_id
        for player_id in values
        for row in population.appearances(player_id, game_ids) or ()
    }
    if set(cited) != covered:
        problems.append(EXPANSION_MISMATCH)
    if problems:
        return population_invalid(problems, "qualifier_rank")
    return Proof("verified", "qualifier_rank", population_cited=True)


def _qualified(
    game_ids: list[int], stat: str, population: Population
) -> tuple[dict[int, float], str | None]:
    """Every qualified subject's window value, exactly under the release qualifier policy."""
    grouped: dict[int, list[PopulationRow]] = {}
    for row in population.box_in(game_ids):
        team = row.row.get("team_id")
        if not isinstance(team, str):
            return {}, POPULATION_UNVERIFIED
        if team != HOME_TEAM:
            continue
        observed = appeared(row.row)
        if observed is None:
            return {}, POPULATION_UNVERIFIED
        if not observed:
            continue
        if row.player_id is None:
            return {}, POPULATION_UNVERIFIED
        grouped.setdefault(int(row.player_id), []).append(row)
    values: dict[int, float] = {}
    for player_id, appearances in grouped.items():
        if len(appearances) < MINIMUM_APPEARANCES:
            continue
        if stat == "true_shooting_percentage":
            attempts = totals([row.row for row in appearances], "field_goals_attempted")
            if attempts is None:
                return {}, MISSING_FIELDS
            if attempts[0] / len(appearances) < TRUE_SHOOTING_MINIMUM_FGA:
                continue
        value, reason = aggregate([row.row for row in appearances], stat)
        if reason:
            return {}, reason
        if value is None:
            # An undefined ratio is not a measured qualifier, so the subject is not ranked.
            continue
        values[player_id] = value
    return values, None


def _nba_player_id(player_id: int, population: Population) -> int | None:
    for row in population.box:
        if row.player_id is not None and int(row.player_id) == player_id:
            return integer(row.row.get("nba_player_id"))
    return None


def _leaderboard(view: ClaimView, rows: list[dict[str, Any]], population: Population) -> Proof:
    """Prove one leaderboard claim: the subject really leads the considered population."""
    eligibility = view.eligibility
    if view.sample_size is None or view.denominator is None:
        return blocked(POPULATION_UNVERIFIED)
    considered = declared_ids(eligibility.get("considered_game_ids"))
    if considered is None:
        return blocked(ELIGIBILITY_UNVERIFIED)
    subject = player_of(view.subject)
    if subject is None:
        return invalid((SUBJECT_MISMATCH,))
    missing = population.gap(box=True)
    if missing:
        return blocked(missing)
    column = box_column(view.metric[: -len(LEADER_SUFFIX)])
    if column is None:
        return blocked(UNSUPPORTED)
    if not isinstance(view.value, dict):
        return invalid((ARITHMETIC_MISMATCH,), "player_leaderboard")
    modes = [mode for mode in ("average", "total") if mode in view.value]
    if len(modes) != 1 or set(view.value) != {"name", modes[0]}:
        return invalid((ARITHMETIC_MISMATCH,), "player_leaderboard")
    mode = modes[0]
    grouped: dict[int, list[PopulationRow]] = {}
    for row in population.box_in(considered):
        team = row.row.get("team_id")
        if not isinstance(team, str):
            return blocked(POPULATION_UNVERIFIED)
        if team != HOME_TEAM:
            continue
        observed = appeared(row.row)
        if observed is None:
            return blocked(POPULATION_UNVERIFIED)
        if not observed:
            continue
        if row.player_id is None:
            return blocked(POPULATION_UNVERIFIED)
        if not number(row.row.get(column)):
            return blocked(MISSING_FIELDS)
        grouped.setdefault(int(row.player_id), []).append(row)
    if not grouped:
        return invalid((POPULATION_MISMATCH,), "player_leaderboard")
    ranked = {
        player_id: (
            sum(float(row.row[column]) for row in appearances) / len(appearances)
            if mode == "average"
            else sum(float(row.row[column]) for row in appearances)
        )
        for player_id, appearances in grouped.items()
    }
    best = max(ranked.values())
    leaders = [player_id for player_id, value in ranked.items() if abs(value - best) <= 1e-9]
    if subject not in leaders:
        # The claim is a leaderboard, so a subject that is not one of the leaders is wrong.
        return population_invalid([ARITHMETIC_MISMATCH], "player_leaderboard")
    if view.player_name is None:
        return blocked(POPULATION_UNVERIFIED)
    recomputed = ranked[subject]
    displayed = round(recomputed, 1) if mode == "average" else int(recomputed)
    appearances = grouped[subject]
    problems: list[str] = []
    if not same(view.value.get(mode), float(displayed), 1e-9):
        problems.append(ARITHMETIC_MISMATCH)
    if str(view.value.get("name")) != view.player_name:
        problems.append(SUBJECT_MISMATCH)
    if not counts_as(view.sample_size, len(appearances)) or not counts_as(
        view.denominator, len(appearances)
    ):
        problems.append(POPULATION_MISMATCH)
    games = {row.game_id for row in appearances}
    if set(view.game_ids) != games:
        problems.append(SCOPE_MISMATCH)
    cited = population.cited_game_ids(rows)
    if cited is None:
        return blocked(POPULATION_UNVERIFIED)
    if set(cited) != games:
        problems.append(EXPANSION_MISMATCH)
    if problems:
        return population_invalid(problems, "player_leaderboard")
    return Proof("verified", "player_leaderboard", population_cited=True)
