"""Analyst calculations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from app.models.game import Game
from app.services.evidence_contracts import ToolResult
from app.services.query_policy import season_type_label
from app.services.query_resolution import ResolvedQuery

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools

METRICS = (
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
    if "appearance" not in tools.question.lower():
        games = scope.window(games)
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
        rows = [(s, p) for s, p in all_rows if s.minutes > 0]
        rows = scope.window(rows)
        if not rows:
            if unknown:
                missing = True
            continue
        count = len(rows)
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
        statement = (
            f"{name}: {value:.1f} {unit} across {count} observed appearances in the "
            f"{tools.release.season} {_archive_phase([game_map[s.game_id] for s, _ in rows])}."
        )
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric=f"{metric}:{aggregation}",
                value=value,
                unit=unit,
                games=[game_map[s.game_id] for s, _ in rows],
                evidence=receipts,
                statement=statement,
                scope=scope,
                sample=count,
                denominator=count if aggregation == "average" else None,
                limitations=limitations,
                window={
                    "date_start": str(games[0].game_date),
                    "date_end": str(games[-1].game_date),
                }
                if games
                else None,
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
    asks_average = bool(
        re.search(r"\b(?:average|averaged|averaging|per game|ppg)\b", tools.question, re.I)
    )
    asks_total = bool(re.search(r"\btotal\b", tools.question, re.I))
    evidence = [tools.receipt(g) for g in games]
    groups: list[list[Game]] = [games]
    if scope.opponent_id and scope.season_type is None:
        phases = sorted({g.season_type for g in games})
        if len(phases) > 1:
            groups.append([g for g in games if g.season_type == "regular"])
            groups.append([g for g in games if g.season_type == "playoffs"])
            groups = [group for group in groups if group]
    claims = []
    for index, group in enumerate(groups):
        wins = sum(tools.score(g)[0] > tools.score(g)[1] for g in group)
        points = sum(tools.score(g)[0] for g in group)
        margin = sum(tools.score(g)[0] - tools.score(g)[1] for g in group)
        phase = _phase_label(group)
        opponent = f" against {tools.team_label(scope.opponent_id)}" if scope.opponent_id else ""
        # A one-game population is a result, so name the opponent and score rather than
        # leaving an unqualified aggregate that cannot answer an explanation follow-up.
        game_line = f" ({_game_line(tools, group[0])})" if len(group) == 1 else ""
        values: dict[str, float | int] = {"wins": wins, "losses": len(group) - wins}
        if index == 0:
            if aggregation == "average" or asks_average:
                values["points_per_game"] = points / len(group)
                values["margin_per_game"] = margin / len(group)
            if aggregation == "total" or asks_total:
                values["points"] = points
                values["margin"] = margin
        prefix = "Knicks (all phases)" if phase == "all phases" else f"Knicks {phase}"
        breakdown = ""
        if index == 0 and scope.opponent_id and len(groups) > 1:
            parts = []
            for other in groups[1:]:
                wins_other = sum(tools.score(g)[0] > tools.score(g)[1] for g in other)
                parts.append(f"{_phase_label(other)} {wins_other}-{len(other) - wins_other}")
            breakdown = " (" + ", ".join(parts) + ")"
        group_evidence = evidence if group is games else [tools.receipt(g) for g in group]
        for metric, value in values.items():
            label = metric.replace("_", " ")
            claims.append(
                tools.claim(
                    subject="team:NYK",
                    metric=metric,
                    value=value,
                    unit=label,
                    games=group,
                    evidence=group_evidence,
                    scope=scope,
                    sample=len(group),
                    denominator=len(group) if metric.endswith("_per_game") else None,
                    eligibility={"game": "archived Knicks game"},
                    statement=(
                        f"{prefix} {label}: {value} over {len(group)} archived games"
                        f"{opponent}{breakdown}{game_line}."
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
