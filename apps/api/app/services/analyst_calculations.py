"""Analyst calculations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from app.models.game import Game
from app.services.evidence_contracts import ToolResult
from app.services.population_facts import score_threshold_count
from app.services.query_policy import season_type_label
from app.services.query_resolution import ResolvedQuery
from app.services.query_text import is_record_request

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

_STORED_METRICS = (
    "points",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "three_pointers_made",
    "plus_minus",
    "minutes",
)
_DERIVED_METRICS = ("three_point_percentage", "starts", "double_doubles")


class _MetricSurface(tuple[str, ...]):
    """Player calculation surface accepted by the dispatch and leader gates.

    ``METRICS`` doubles as the payload field list for stored box-score receipts, and the
    derived metrics have no stored column. They are accepted members without being
    iterated as receipt fields.
    """

    def __contains__(self, value: object) -> bool:
        return super().__contains__(value) or value in _DERIVED_METRICS


METRICS = _MetricSurface(_STORED_METRICS)


def _phase_label(games: list[Game]) -> str:
    """The phase actually covered by a population; never claims more than the games show."""
    types = {g.season_type for g in games}
    return season_type_label(types.pop()) if len(types) == 1 else "all phases"


def _archive_phase(games: list[Game]) -> str:
    types = {g.season_type for g in games}
    if types == {"regular"}:
        return "regular season"
    if types == {"playoffs"}:
        return "playoffs"
    if types == {"regular", "playoffs"}:
        return "regular season and playoffs"
    return "archive"


def _opponent(tools: AnalystTools, game: Game) -> str:
    return game.away_team_id if game.home_team_id == "NYK" else game.home_team_id


def _game_line(tools: AnalystTools, game: Game) -> str:
    nyk, opp = tools.score(game)
    venue = "vs" if game.home_team_id == "NYK" else "at"
    return f"{nyk}-{opp} {venue} {tools.team_label(_opponent(tools, game))} on {game.game_date}"


def _extreme_kind(question: str) -> str | None:
    q = question.lower()
    if re.search(r"\b(?:worst|biggest|largest|heaviest)\s+(?:loss|defeat|blowout)\b", q):
        return "loss_margin"
    if re.search(r"\b(?:biggest|best|largest|most lopsided)\s+(?:win|victory|blowout)\b", q):
        return "win_margin"
    if re.search(
        r"\b(?:highest|most)[- ]scoring\b|\bmost points (?:in a game|scored)\b"
        r"|\bhighest (?:point total|points)\b",
        q,
    ):
        return "game_points"
    return None


def player(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game], metric: str, aggregation: str
) -> ToolResult:
    game_map = {g.id: g for g in games}
    claims, evidence = [], []
    missing = False
    team_row_games = {s.game_id for s, _ in tools.rows}
    for player_id in scope.player_ids:
        all_rows = [
            (s, p) for s, p in tools.rows if s.player_id == player_id and s.game_id in game_map
        ]
        # A game with other NYK player rows but no row for this player is an observed DNP,
        # not a coverage gap. Only a game with no NYK player rows at all is unknown.
        absent = sorted(set(game_map) - {s.game_id for s, _ in all_rows})
        unknown = [game_id for game_id in absent if game_id not in team_row_games]
        did_not_appear = [game_id for game_id in absent if game_id in team_row_games]
        rows = sorted(
            [(s, p) for s, p in all_rows if s.minutes > 0],
            key=lambda row: (
                game_map[row[0].game_id].game_date,
                game_map[row[0].game_id].nba_game_id,
            ),
        )
        rows = scope.window(rows)
        if not rows:
            if unknown:
                missing = True
            continue
        count = len(rows)
        attempts = 0
        if metric == "double_doubles":
            aggregation = "total"
            value = sum(
                sum(
                    getattr(s, key) >= 10
                    for key in ("points", "rebounds", "assists", "steals", "blocks")
                )
                >= 2
                for s, _ in rows
            )
        elif metric == "three_point_percentage":
            aggregation = "percentage"
            attempts = sum(s.three_pointers_attempted for s, _ in rows)
            if not attempts:
                if unknown:
                    missing = True
                continue
            value = sum(s.three_pointers_made for s, _ in rows) / attempts * 100
        elif metric == "starts":
            aggregation = "total"
            value = sum(bool(s.starter) for s, _ in rows)
        else:
            value = sum(getattr(s, metric) for s, _ in rows)
        if aggregation == "average":
            value /= count
        receipts = [tools.receipt(game_map[s.game_id], s, p) for s, p in rows]
        evidence.extend(receipts)
        limitations = ["Only observed appearances in the available archive."]
        if did_not_appear:
            limitations.append(
                "The player did not appear in some selected games; those games are excluded."
            )
        if unknown:
            missing = True
            limitations.append(
                "Some selected games lack all Knicks player rows; coverage is incomplete."
            )
        name = rows[0][1].full_name
        unit = f"{metric} per appearance" if aggregation == "average" else metric
        observed_games = [game_map[s.game_id] for s, _ in rows]
        statement = (
            f"{name}: {value:.1f} {unit} across {count} observed appearances in "
            f"{tools.scope_label(scope, observed_games)}."
        )
        if metric == "three_point_percentage":
            statement = (
                f"{name}: {value:.1f}% from three, "
                f"{sum(s.three_pointers_made for s, _ in rows)} makes in {attempts} attempts "
                f"across {count} observed appearances in "
                f"{tools.scope_label(scope, observed_games)}."
            )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=metric
                if metric in {"three_point_percentage", "starts"}
                else f"{metric}:{aggregation}",
                value=value,
                unit=unit,
                games=[game_map[s.game_id] for s, _ in rows],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=count,
                denominator=attempts
                if metric == "three_point_percentage"
                else count
                if aggregation == "average"
                else None,
                limitations=limitations,
                window={
                    "date_start": str(game_map[rows[0][0].game_id].game_date),
                    "date_end": str(game_map[rows[-1][0].game_id].game_date),
                },
            )
        )
    if not claims:
        if missing:
            message = "No player rows at all for the scoped games; coverage is incomplete."
        else:
            names = sorted({p.full_name for _, p in tools.rows if p.id in scope.player_ids})
            message = (
                f"{', '.join(names)} did not appear in the scoped archived games."
                if names
                else "No observed appearances."
            )
        return ToolResult(
            status="incomplete_coverage" if missing else "no_matching_results",
            message=message,
            claims=[],
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )
    return ToolResult(
        status="incomplete_coverage" if missing else "ok",
        message="Calculated from all applicable database rows; retrieval is not the denominator.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )


def team(
    tools: AnalystTools,
    scope: ResolvedQuery,
    games: list[Game],
    aggregation: Literal["average", "total"] = "total",
) -> ToolResult:
    games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
    extreme = _extreme_kind(tools.question)
    if extreme and games:
        if extreme == "loss_margin":
            game = min(
                games, key=lambda g: (tools.score(g)[0] - tools.score(g)[1], g.game_date, g.id)
            )
            value = tools.score(game)[1] - tools.score(game)[0]
            phrase = f"{_phase_label(games)} worst loss by margin was {value} points"
        elif extreme == "win_margin":
            game = max(
                games, key=lambda g: (tools.score(g)[0] - tools.score(g)[1], g.game_date, g.id)
            )
            value = tools.score(game)[0] - tools.score(game)[1]
            phrase = f"{_phase_label(games)} biggest win by margin was {value} points"
        else:
            game = max(games, key=lambda g: (tools.score(g)[0], g.game_date, g.id))
            value = tools.score(game)[0]
            phrase = f"{_phase_label(games)} highest-scoring game was {value} points"
        receipt = tools.receipt(game)
        claim = tools.claim(
            subject="team:NYK",
            metric=f"{extreme}:extreme",
            value=value,
            unit="points",
            games=[game],
            evidence=[receipt],
            scope=scope,
            sample=1,
            denominator=None,
            eligibility={"game": "archived Knicks game", "selection": "extreme"},
            limitations=["Single-game extreme; selection does not establish improvement."],
            statement=f"Knicks {phrase}: {_game_line(tools, game)}.",
        )
        return ToolResult(
            status="ok",
            message="Archive team extreme.",
            claims=[claim],
            evidence=[receipt],
            scope=scope.model_dump(mode="json"),
        )
    games = scope.window(games)
    evidence = [tools.receipt(g) for g in games]
    denominator = None
    eligibility: dict[str, object] = {"game": "archived Knicks game"}
    threshold_description = ""
    threshold_count = score_threshold_count(tools.question, games)
    if threshold_count is not None:
        eligibility["score_predicate"] = threshold_count.predicate
        eligibility["matching_game_ids"] = list(threshold_count.matching_game_ids)
        threshold_description = (
            f" with {'opponent' if threshold_count.opponent_score else 'NYK'} points "
            f"{threshold_count.threshold.symbol} {threshold_count.threshold.value:g}"
        )
        values: dict[str, float | int] = {"games:count": threshold_count.value}
    else:
        wins = sum(tools.score(g)[0] > tools.score(g)[1] for g in games)
        points = sum(tools.score(g)[0] for g in games)
        margin = sum(tools.score(g)[0] - tools.score(g)[1] for g in games)
        # An elliptical follow-up inherits the topic; its own wording carries only scope.
        question = (tools.topic or tools.question).lower()
        requested_aggregations = set(scope.requested_aggregations) or (
            {scope.aggregation} if scope.aggregation else set()
        )
        compound_total_average = (
            scope.metric == "points" and {"average", "total"} <= requested_aggregations
        )
        if compound_total_average:
            # Preserve the PR compound naming while single-request team averages use
            # the native ``points:average`` metric.
            values = {"points": points, "points_per_game": points / len(games)}
        elif is_record_request(question):
            values = {"wins": wins, "losses": len(games) - wins}
        elif re.search(r"\bhow many\b.*\b(?:win|wins|won)\b", question):
            values = {"wins": wins}
        elif re.search(r"\bhow many\b.*\b(?:lose|losses|lost)\b", question):
            values = {"losses": len(games) - wins}
        elif re.search(r"\bhow many games\b", question):
            values = {"games:count": len(games)}
        elif re.search(r"\b(average|per game|points allowed)\b", question):
            metric = (
                "margin"
                if "margin" in question
                else "points_allowed"
                if re.search(r"\b(allow(?:ed)?|opponents?)\b", question)
                else "points"
            )
            total = (
                sum(tools.score(g)[1] for g in games)
                if metric == "points_allowed"
                else margin
                if metric == "margin"
                else points
            )
            denominator = len(games)
            values = {f"{metric}:average": total / denominator}
        elif not requested_aggregations and aggregation == "average":
            # The PR tool contract keeps per-game claims under their historical names
            # when the caller chooses an average without the question naming one.
            denominator = len(games)
            values = {
                "wins": wins,
                "losses": len(games) - wins,
                "points_per_game": points / denominator,
                "margin_per_game": margin / denominator,
            }
        elif not requested_aggregations and aggregation == "total":
            values = {
                "wins": wins,
                "losses": len(games) - wins,
                "points": points,
                "margin": margin,
            }
        elif scope.metric == "points":
            values = {"points": points}
        elif "margin" in question:
            values = {"margin": margin}
        else:
            values = {"wins": wins, "losses": len(games) - wins}
    claims = []
    for metric, value in values.items():
        claims.append(
            tools.claim(
                subject="team:NYK",
                metric=metric,
                value=value,
                unit=metric,
                games=games,
                evidence=evidence,
                scope=scope,
                sample=len(games),
                denominator=denominator,
                eligibility=eligibility,
                statement=(
                    f"Knicks {metric}{threshold_description}: {value} "
                    f"over {len(games)} archived games "
                    f"in {tools.scope_label(scope, games)}."
                ),
            )
        )
    return ToolResult(
        status="ok",
        message="Archive team totals.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
