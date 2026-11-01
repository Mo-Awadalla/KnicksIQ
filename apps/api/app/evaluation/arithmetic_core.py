"""Shared vocabulary for independent claim arithmetic over verified row snapshots.

Three inputs stay separate on purpose. The claim states what it measured and which
population and policy it says it used. The cited row snapshots are what the response's
own evidence registry proves. The population snapshot is the mapping's verified SQL
projection of the whole release, and it is only ever an independent oracle for
recomputation: it is never treated as an issued receipt.

A recipe that needs the whole population blocks when that snapshot is absent instead of
crediting the claim from its own citations, which can only ever prove the part of the
population the answer chose to show.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard

GAME = "games"
PLAYER = "player_game_stats"
TEAM = "team_game_stats"
PERIOD = "period_scores"

HOME_TEAM = "NYK"

# The release qualifier policy, held here independently of the producer: a claim that
# restates one of these numbers differently has not used the release's own policy.
MINIMUM_APPEARANCES = 4
TRUE_SHOOTING_MINIMUM_FGA = 5

# Reasons: the claim cannot be recomputed, so it earns no credit and fails nothing.
MISSING_FIELDS = "calculation_fields_unavailable"
UNSUPPORTED = "unsupported_recipe"
POPULATION_SNAPSHOT_MISSING = "calculation_population_snapshot_missing"
POPULATION_UNVERIFIED = "calculation_population_unverified"
WINDOW_UNVERIFIED = "calculation_window_unverified"
ELIGIBILITY_UNVERIFIED = "calculation_eligibility_unverified"

# Problems: the claim states something the verified rows contradict.
ARITHMETIC_MISMATCH = "calculation_arithmetic_mismatch"
POPULATION_MISMATCH = "calculation_population_mismatch"
SCOPE_MISMATCH = "calculation_scope_mismatch"
EXPANSION_MISMATCH = "calculation_expansion_mismatch"
SUBJECT_MISMATCH = "calculation_subject_mismatch"
ELIGIBILITY_MISMATCH = "calculation_eligibility_mismatch"

Status = Literal["verified", "invalid", "unverifiable"]


@dataclass(frozen=True)
class Proof:
    status: Status
    recipe: str | None = None
    problems: tuple[str, ...] = ()
    reason: str | None = None
    # A population recipe proves its numbers from the mapping's whole-release snapshot,
    # so its claim may cite that snapshot while naming only the matching subset.
    population_cited: bool = False


@dataclass(frozen=True)
class ClaimView:
    """The attribution a claim asserts about itself, read without trusting its numbers."""

    metric: str
    value: Any
    subject: str | None = None
    game_ids: tuple[int, ...] = ()
    window: dict[str, Any] | None = None
    eligibility: dict[str, Any] = field(default_factory=dict)
    baseline_claim_ids: tuple[str, ...] = ()
    sample_size: int | None = None
    denominator: float | None = None
    decimals: int | None = None
    numerator: float | None = None
    made: float | None = None
    attempted: float | None = None
    # The mapped name of a ``player:<runtime id>`` subject, when the mapping knows it.
    player_name: str | None = None


@dataclass(frozen=True)
class PopulationRow:
    """One row of the mapping's verified projection, never a citation."""

    canonical_id: str
    collection: str
    game_id: int
    player_id: int | None
    row: dict[str, Any]


@dataclass(frozen=True)
class Population:
    """The whole-release projection, indexed for independent recomputation."""

    games: dict[int, PopulationRow] = field(default_factory=dict)
    game_by_nba: dict[str, int] = field(default_factory=dict)
    box: tuple[PopulationRow, ...] = ()
    team: tuple[PopulationRow, ...] = ()
    periods: tuple[PopulationRow, ...] = ()

    def present(self) -> bool:
        return bool(self.games)

    def gap(self, *, box: bool = False) -> str | None:
        """Why this projection cannot answer a recipe, or None when it can.

        A recipe that needs the release games — or, for box-score arithmetic, the
        per-appearance rows — blocks on a snapshot that does not carry them. It must
        never fall back to the subset of the population an answer chose to cite.
        """
        if not self.present():
            return POPULATION_SNAPSHOT_MISSING
        if box and not self.box:
            return POPULATION_SNAPSHOT_MISSING
        return None

    def order(self, game_id: int) -> tuple[str, str] | None:
        row = self.games.get(int(game_id))
        return None if row is None else game_order(row.row)

    def ordered(self, game_ids: Iterable[int]) -> list[int] | None:
        """The given games in archive order, or None when one of them cannot be placed."""
        placed: list[tuple[tuple[str, str], int]] = []
        for game_id in game_ids:
            key = self.order(game_id)
            if key is None:
                return None
            placed.append((key, int(game_id)))
        placed.sort()
        return [game_id for _, game_id in placed]

    def cited_game_ids(self, rows: list[dict[str, Any]]) -> tuple[int, ...] | None:
        """The runtime game each cited snapshot belongs to, or None when it cannot say."""
        found: list[int] = []
        for row in rows:
            key = row.get("nba_game_id")
            game_id = self.game_by_nba.get(str(key)) if key is not None else None
            if game_id is None:
                return None
            found.append(int(game_id))
        return tuple(found)

    def appearances(
        self, player_id: int | None, game_ids: Iterable[int] | None = None
    ) -> tuple[PopulationRow, ...] | None:
        """One player's observed appearances in archive order, zero-minute rows dropped."""
        if player_id is None or not self.box:
            return None
        wanted = None if game_ids is None else {int(item) for item in game_ids}
        picked: list[tuple[tuple[str, str], PopulationRow]] = []
        for row in self.box:
            if row.player_id is None or int(row.player_id) != int(player_id):
                continue
            if wanted is not None and row.game_id not in wanted:
                continue
            observed = appeared(row.row)
            if observed is None:
                return None
            if not observed:
                continue
            key = self.order(row.game_id)
            if key is None:
                return None
            picked.append((key, row))
        picked.sort(key=lambda item: item[0])
        return tuple(row for _, row in picked)

    def box_in(self, game_ids: Iterable[int]) -> tuple[PopulationRow, ...]:
        wanted = {int(item) for item in game_ids}
        return tuple(row for row in self.box if row.game_id in wanted)


@dataclass(frozen=True)
class WindowCheck:
    """The result of proving that cited rows are exactly the window a claim names."""

    problems: tuple[str, ...] = ()
    reason: str | None = None


def tolerance(decimals: int | None) -> float:
    return 0.5 * 10**-decimals + 1e-9 if decimals is not None and 0 <= decimals <= 4 else 1e-6


def number(value: Any) -> TypeGuard[int | float]:
    """A recorded number; ``bool`` is never one, so a flag never reads as a count."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def integer(value: Any) -> int | None:
    """An exact integer from a recorded number, or None when the value is not one."""
    if not number(value) or not float(value).is_integer():
        return None
    return int(value)


def same(value: Any, expected: float, slack: float) -> bool:
    return number(value) and abs(float(value) - expected) <= slack


def counts_as(declared: Any, expected: int) -> bool:
    """Whether a declared sample or denominator is the recomputed population size."""
    return same(declared, float(expected), 1e-9)


def blocked(reason: str) -> Proof:
    return Proof("unverifiable", None, (), reason)


def invalid(problems: Iterable[str], recipe: str | None = None) -> Proof:
    return Proof("invalid", recipe, tuple(dict.fromkeys(problems)))


def population_invalid(problems: Iterable[str], recipe: str) -> Proof:
    """A whole-population recipe's problems, which still cites that population."""
    proof = invalid(problems, recipe)
    return Proof(proof.status, proof.recipe, proof.problems, population_cited=True)


def policy_problems(eligibility: dict[str, Any]) -> tuple[list[str], str | None]:
    """The qualifier policy a claim declares, held to the release's own constants."""
    problems: list[str] = []
    for key, expected in (
        ("minimum_appearances", MINIMUM_APPEARANCES),
        ("prior_minimum_appearances", MINIMUM_APPEARANCES),
        ("true_shooting_minimum_fga_per_appearance", TRUE_SHOOTING_MINIMUM_FGA),
    ):
        declared = eligibility.get(key)
        if declared is None:
            continue
        value = integer(declared)
        if value is None:
            return [ELIGIBILITY_MISMATCH], None
        if value != expected:
            problems.append(ELIGIBILITY_MISMATCH)
    appearance = eligibility.get("appearance")
    if appearance is not None and str(appearance).replace(" ", "") != "minutes>0":
        problems.append(ELIGIBILITY_MISMATCH)
    return problems, None


def team_of(subject: str | None) -> str | None:
    kind, _, team = (subject or "").partition(":")
    return team if kind == "team" and team else None


def player_of(subject: str | None) -> int | None:
    """The runtime player id a ``player:<id>`` subject names, exactly once."""
    kind, _, rest = (subject or "").partition(":")
    if kind != "player" or not rest:
        return None
    try:
        return int(rest)
    except ValueError:
        return None


def team_score(row: dict[str, Any], team: str = HOME_TEAM) -> tuple[float, float] | None:
    """``(own, other)`` final score for one team, or None when the row cannot say."""
    home, away = row.get("home_score"), row.get("away_score")
    if not number(home) or not number(away):
        return None
    own, other = float(home), float(away)
    if row.get("home_team_id") == team:
        return own, other
    if row.get("away_team_id") == team:
        return other, own
    return None


def game_order(row: dict[str, Any]) -> tuple[str, str] | None:
    day, nba_game_id = row.get("game_date"), row.get("nba_game_id")
    if not isinstance(day, str) or not day or nba_game_id is None:
        return None
    return day, str(nba_game_id)


def appeared(row: dict[str, Any]) -> bool | None:
    """Whether one box row is an appearance; None when its minutes cannot be read."""
    minutes = row.get("minutes")
    if not number(minutes):
        return None
    return float(minutes) > 0


def declared_ids(value: Any) -> tuple[int, ...] | None:
    """Runtime game ids from a claim's own eligibility record; None when not integers."""
    if value is None or not isinstance(value, list):
        return None
    found: list[int] = []
    for item in value:
        game_id = integer(item)
        if game_id is None:
            return None
        found.append(game_id)
    return tuple(found)


def declaration(
    count: int,
    denominator: float | None,
    sample_size: int | None,
    *,
    mean: bool,
    extra: tuple[float, ...] = (),
) -> tuple[list[str], str | None]:
    """The declared sample and denominator against the recomputed population size."""
    if sample_size is None:
        return [], POPULATION_UNVERIFIED
    if int(sample_size) != count:
        return [POPULATION_MISMATCH], None
    if mean and denominator is None:
        return [], POPULATION_UNVERIFIED
    if denominator is not None:
        allowed = (float(count), *extra)
        if not any(abs(float(denominator) - value) <= 1e-9 for value in allowed):
            return [POPULATION_MISMATCH], None
    return [], None


def aggregation_suffix(metric: str) -> tuple[str, str | None]:
    """Split one metric id into its stat and its aggregation, when it names one."""
    for suffix in (":average", ":total"):
        if metric.endswith(suffix):
            return metric[: -len(suffix)], suffix[1:]
    return metric, None
