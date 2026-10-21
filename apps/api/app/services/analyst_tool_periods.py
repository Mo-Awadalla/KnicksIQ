"""get_period_scoring handler: quarter, half and overtime scoring from period_scores.

Coverage is enforced before any arithmetic. A game contributes only when both teams have
complete Q1-Q4 rows and those rows add up to the final score; anything else is reported as
a gap, never as zeros. Overtime periods are numbered 5+ and stay out of Q4 and the second
half. Halves are Q1+Q2 and Q3+Q4.

Claims are consolidated on purpose: the provider input budget leaves room for a few claims,
so one phase report carries every period, half and extreme, and one game claim carries the
per-game rows a narrative answer needs.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.models.box_score import PeriodScore
from app.services.analyst_period_calculations import (
    extreme as pick_extreme,
)
from app.services.analyst_period_calculations import (
    label,
    opponent,
    period_view,
    phase_groups,
    phase_label,
    requested_periods,
    result,
    team_name,
    venue,
)
from app.services.evidence_contracts import Evidence, ToolResult
from sqlalchemy import select

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from app.services.query_resolution import ResolvedQuery


async def _load_periods(
    tools: AnalystTools, games: list[Game]
) -> dict[int, dict[str, dict[int, int]]]:
    if not games:
        return {}
    rows = (
        await tools.db.execute(
            select(PeriodScore).where(
                PeriodScore.release_id == tools.release.id,
                PeriodScore.game_id.in_([game.id for game in games]),
            )
        )
    ).scalars()
    grouped: dict[int, dict[str, dict[int, int]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        grouped[row.game_id][row.team_id][row.period] = row.points
    return grouped


def _evidence(tools: AnalystTools, game: Game, view: dict[str, Any]) -> Evidence:
    identity = f"{tools.release.version}:periods:game:{game.id}"
    if identity in tools.evidence:
        return tools.evidence[identity]
    metadata = {
        "game_id": game.id,
        "date": str(game.game_date),
        "season_type": game.season_type,
        "home": game.home_team_id,
        "away": game.away_team_id,
        "home_score": game.home_score,
        "away_score": game.away_score,
        **view,
    }
    evidence = Evidence(
        evidence_id=identity,
        release_id=tools.release.version,
        game_id=game.id,
        text=json.dumps(metadata, sort_keys=True),
        source_name=game.source_name,
        source_url=game.source_url,
        metadata=metadata,
    )
    tools.evidence[identity] = evidence
    return evidence


def _period_values(
    views: list[tuple[Game, dict[str, Any]]], periods: list[int], phase: str, *, detail: bool
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for period in periods:
        pairs = [
            (game, view["periods"][str(period)])
            for game, view in views
            if str(period) in view["periods"]
        ]
        if not pairs:
            continue
        count = len(pairs)
        points = sum(pair[0] for _, pair in pairs)
        opponent_points = sum(pair[1] for _, pair in pairs)
        wins = sum(pair[0] > pair[1] for _, pair in pairs)
        ties = sum(pair[0] == pair[1] for _, pair in pairs)
        best = pick_extreme(pairs, lambda entry: entry[1][0], highest=True)
        worst = pick_extreme(pairs, lambda entry: entry[1][0], highest=False)
        value: dict[str, Any] = {
            "games": count,
            "pts": points,
            "ppg": round(points / count, 2),
            "opp_pts": opponent_points,
            "opp_ppg": round(opponent_points / count, 2),
            "diff": points - opponent_points,
            "diff_pg": round((points - opponent_points) / count, 2),
            "wins": wins,
            "ties": ties,
            "losses": count - wins - ties,
        }
        if detail:
            value["best"] = _compact_ref(best[0], period, best[1]) if best else None
            value["worst"] = _compact_ref(worst[0], period, worst[1]) if worst else None
        values[f"{label(period)} {phase}"] = value
    return values


def _halves_value(tools: AnalystTools, views: list[tuple[Game, dict[str, Any]]]) -> dict[str, Any]:
    count = len(views)
    first = sum(view["first_half"][0] for _, view in views)
    first_opp = sum(view["first_half"][1] for _, view in views)
    second = sum(view["second_half"][0] for _, view in views)
    second_opp = sum(view["second_half"][1] for _, view in views)
    led = [entry for entry in views if entry[1]["halftime_lead"] > 0]
    trailed = [entry for entry in views if entry[1]["halftime_lead"] < 0]
    comebacks = [entry for entry in trailed if tools.score(entry[0])[0] > tools.score(entry[0])[1]]
    blown = [entry for entry in led if tools.score(entry[0])[0] < tools.score(entry[0])[1]]
    largest_comeback = pick_extreme(
        comebacks, lambda entry: -entry[1]["halftime_lead"], highest=True
    )
    largest_blown = pick_extreme(blown, lambda entry: entry[1]["halftime_lead"], highest=True)

    def halftime_ref(entry: tuple[Game, dict[str, Any]] | None) -> dict[str, Any] | None:
        if entry is None:
            return None
        game, view = entry
        return {
            "date": str(game.game_date),
            "opp": team_name(opponent(game)),
            "margin": abs(view["halftime_lead"]),
            "half": view["first_half"],
            "final": list(tools.score(game)),
        }

    return {
        "h1_pts": first,
        "h1_ppg": round(first / count, 2),
        "h1_opp_pts": first_opp,
        "h1_opp_ppg": round(first_opp / count, 2),
        "h1_diff": first - first_opp,
        "h2_pts": second,
        "h2_ppg": round(second / count, 2),
        "h2_opp_pts": second_opp,
        "h2_opp_ppg": round(second_opp / count, 2),
        "h2_diff": second - second_opp,
        "led": len(led),
        "tied": count - len(led) - len(trailed),
        "trailed": len(trailed),
        "comebacks": len(comebacks),
        "blown": len(blown),
        "largest_comeback": halftime_ref(largest_comeback),
        "largest_blown": halftime_ref(largest_blown),
    }


def _extremes_value(
    views: list[tuple[Game, dict[str, Any]]], periods: list[int], phase: str
) -> dict[str, Any]:
    entries = [
        (game, period, view["periods"][str(period)])
        for game, view in views
        for period in periods
        if str(period) in view["periods"]
    ]
    if not entries:
        return {}
    definitions = (
        ("best_scoring", lambda entry: entry[2][0], True),
        ("worst_scoring", lambda entry: entry[2][0], False),
        ("best_differential", lambda entry: entry[2][0] - entry[2][1], True),
        ("worst_differential", lambda entry: entry[2][0] - entry[2][1], False),
    )
    values: dict[str, Any] = {}
    for name, key, highest in definitions:
        chosen = pick_extreme(entries, key, highest=highest)
        if chosen is not None:
            game, period, pair = chosen
            values[name] = _compact_ref(game, period, pair)
    return values


def _compact_ref(game: Game, period: int, pair: list[int]) -> dict[str, Any]:
    return {
        "p": label(period),
        "date": str(game.game_date),
        "opp": team_name(opponent(game)),
        "venue": venue(game),
        "nyk": pair[0],
        "opp_pts": pair[1],
        "diff": pair[0] - pair[1],
    }


def _short_phase(phase: str) -> str:
    return {
        "regular": "reg",
        "regular season": "reg",
        "play_in": "play-in",
        "play-in": "play-in",
        "playoffs": "playoffs",
    }.get(phase, phase)


def _digest(
    tools: AnalystTools,
    groups: list[tuple[str, str, list[str], list[Game]]],
    periods: list[int],
    views: dict[int, dict[str, Any]],
    ordered: list[tuple[Game, dict[str, Any]]],
    selected: list[Game],
    gaps: list[dict[str, Any]],
    half_question: bool,
    include_periods: bool,
    extremes_wanted: bool,
) -> str:
    phase_scope = phase_label([name for _, _, phases, _ in groups for name in phases])
    multi_phase = len({name for _, _, names, _ in groups for name in names}) > 1
    compact_games = len(views) <= 10
    parts = [f"{phase_scope.capitalize()}, {len(views)} of {len(selected)} games."]
    if gaps:
        parts.append(f"{len(gaps)} coverage gaps excluded, not zero-point games.")
    opponents = {opponent(game) for game in selected}
    if len(opponents) == 1:
        parts.append(f"Opponent: {team_name(next(iter(opponents)))}.")
    if compact_games and multi_phase:
        counts = {
            name: sum(1 for game in selected if game.season_type == name)
            for name in dict.fromkeys(name for _, _, names, _ in groups for name in names)
        }
        listed = ", ".join(f"{count} {_short_phase(name)}" for name, count in counts.items())
        parts.append(f"Phases: {listed}.")
    for _phase_metric, phase, _, group_games in groups:
        group_views = [(game, views[game.id]) for game in group_games if game.id in views]
        if not group_views:
            continue
        if include_periods and not (compact_games and multi_phase):
            for period in periods:
                pairs = [
                    (game, view["periods"][str(period)])
                    for game, view in group_views
                    if str(period) in view["periods"]
                ]
                if not pairs:
                    continue
                count = len(pairs)
                points = sum(pair[0] for _, pair in pairs)
                opponent_points = sum(pair[1] for _, pair in pairs)
                wins = sum(pair[0] > pair[1] for _, pair in pairs)
                ties = sum(pair[0] == pair[1] for _, pair in pairs)
                text = (
                    f"{_short_phase(phase)} {label(period)}: {points} pts "
                    f"({round(points / count, 2)}/g), opp {opponent_points} "
                    f"({round(opponent_points / count, 2)}), diff "
                    f"{points - opponent_points:+d}, {wins}-{ties}-{count - wins - ties}."
                )
                if len(views) > 10 and extremes_wanted:
                    best = pick_extreme(pairs, lambda entry: entry[1][0], highest=True)
                    worst = pick_extreme(pairs, lambda entry: entry[1][0], highest=False)
                    if best:
                        text += (
                            f" Best {best[1][0]}-{best[1][1]} vs {team_name(opponent(best[0]))} "
                            f"{best[0].game_date};"
                        )
                    if worst:
                        text += (
                            f" worst {worst[1][0]}-{worst[1][1]} at "
                            f"{team_name(opponent(worst[0]))} "
                            f"{worst[0].game_date}."
                        )
                parts.append(text)
        if len(periods) == 2 and not (compact_games and multi_phase):
            first, second = periods
            first_pairs = [
                view["periods"][str(first)]
                for _, view in group_views
                if str(first) in view["periods"]
            ]
            second_pairs = [
                view["periods"][str(second)]
                for _, view in group_views
                if str(second) in view["periods"]
            ]
            if first_pairs and second_pairs:
                first_pts = sum(pair[0] for pair in first_pairs)
                second_pts = sum(pair[0] for pair in second_pairs)
                first_ppg = first_pts / len(first_pairs)
                second_ppg = second_pts / len(second_pairs)
                parts.append(
                    f"{_short_phase(phase)} {label(first)} vs {label(second)}: "
                    f"{first_pts - second_pts:+d} pts, {first_ppg - second_ppg:+.2f}/g."
                )
        if half_question:
            halves = _halves_value(tools, group_views)
            text = (
                f"{phase} halves: H1 {halves['h1_ppg']}-{halves['h1_opp_ppg']}/g, "
                f"H2 {halves['h2_ppg']}-{halves['h2_opp_ppg']}/g; H2 vs H1 "
                f"{halves['h2_ppg'] - halves['h1_ppg']:+.2f}/g, "
                f"{halves['h2_pts'] - halves['h1_pts']:+d} pts; led {halves['led']}, "
                f"trailed {halves['trailed']}; comebacks {halves['comebacks']}, blown "
                f"{halves['blown']}."
            )
            for key, wording in (
                ("largest_comeback", "largest comeback"),
                ("largest_blown", "largest lead lost"),
            ):
                item = halves[key]
                if item:
                    text += f" {wording} {item['margin']} vs {item['opp']} {item['date']}."
            parts.append(text)
    if len(views) <= 10:
        parts.extend(
            _game_row(
                tools,
                game,
                view,
                periods,
                half_question=half_question,
                multi_phase=len({name for _, _, names, _ in groups for name in names}) > 1,
            )
            for game, view in ordered
        )
    elif extremes_wanted:
        for _, phase, _, group_games in groups:
            group_views = [(game, views[game.id]) for game in group_games if game.id in views]
            if not group_views:
                continue
            extremes = _extremes_value(group_views, periods, phase)
            for key, wording in (
                ("best_differential", "best diff"),
                ("worst_differential", "worst diff"),
            ):
                item = extremes.get(key)
                if item:
                    parts.append(
                        f"{_short_phase(phase)} {wording}: {item['nyk']}-"
                        f"{item['opp_pts']} ({item['diff']:+d}) {item['venue']} vs "
                        f"{item['opp']} {item['date']} ({item['p']})."
                    )
    return " ".join(parts)


def _report_claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    groups: list[tuple[str, str, list[str], list[Game]]],
    periods: list[int],
    views: dict[int, dict[str, Any]],
    ordered: list[tuple[Game, dict[str, Any]]],
    selected: list[Game],
    gaps: list[dict[str, Any]],
    evidence: list[Evidence],
) -> Any:
    phase_scope = phase_label([name for _, _, phases, _ in groups for name in phases])
    half_question = bool(re.search(r"\b(half|halftime|halves)\b", tools.question, re.I))
    digest = _digest(
        tools,
        groups,
        periods,
        views,
        ordered,
        selected,
        gaps,
        half_question,
        len(views) > 10 or bool(scope.periods),
        bool(
            re.search(r"\b(best|worst|highest|lowest|most|fewest|biggest)\b", tools.question, re.I)
        ),
    )
    return tools.claim(
        subject="team:NYK",
        metric="period_report",
        value=digest,
        unit="period scoring",
        games=selected,
        evidence=evidence,
        scope=scope.model_copy(update={"periods": periods}),
        sample=len(views),
        denominator=len(selected),
        eligibility={"source": "period_scores"},
        statement=(
            f"{phase_scope.capitalize()} period report, {len(views)} of {len(selected)} games."
        ),
    )


def _game_row(
    tools: AnalystTools,
    game: Game,
    view: dict[str, Any],
    periods: list[int],
    *,
    half_question: bool,
    multi_phase: bool,
) -> str:
    chosen = [period for period in periods if str(period) in view["periods"]] or [
        int(period) for period in view["periods"]
    ]
    scores = " ".join(
        f"{label(period)} {view['periods'][str(period)][0]}-"
        f"{view['periods'][str(period)][1]} "
        f"({view['periods'][str(period)][0] - view['periods'][str(period)][1]:+d})"
        for period in chosen
    )
    text = f"{game.game_date:%m-%d} {venue(game)[0]}"
    if multi_phase and game.season_type == "playoffs":
        text += " p"
    if not (half_question and len(periods) > 1):
        text += f": {scores}"
    if half_question:
        text += (
            f"; half {view['first_half'][0]}-{view['first_half'][1]}, "
            f"2H {view['second_half'][0]}-{view['second_half'][1]}"
        )
    text += (
        f"; {view['final'][0]}-{view['final'][1]} {result(game, tools)} "
        f"({view['final'][0] - view['final'][1]:+d})"
    )
    return text


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    if not games:
        return ToolResult(
            status="no_matching_results", message="No archived games match this scope."
        )
    groups = phase_groups(tools, scope, games)
    if not groups:
        return ToolResult(
            status="no_matching_results",
            message="No regular-season games match this scope; the archive has other phases only.",
            scope=scope.model_dump(mode="json"),
        )
    selected = [game for _, _, _, group_games in groups for game in group_games]
    raw = await _load_periods(tools, selected)
    views: dict[int, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = []
    for game in selected:
        view, gap = period_view(tools, game, raw.get(game.id, {}))
        if view is not None:
            views[game.id] = view
        elif gap is not None:
            gaps.append(gap)
    ordered = [(game, views[game.id]) for game in selected if game.id in views]
    covered_evidence = [_evidence(tools, game, view) for game, view in ordered]
    available = sorted({int(period) for view in views.values() for period in view["periods"]})
    periods = requested_periods(scope, call.question, available)
    phase_scope = phase_label([name for _, _, phases, _ in groups for name in phases])
    claims: list[Any] = [
        _report_claim(
            tools, scope, groups, periods, views, ordered, selected, gaps, covered_evidence
        )
    ]
    message = "Period scoring computed from period_scores; overtime is separate from Q4 and halves."
    if gaps:
        message += " Some selected games lack complete rows and are reported as coverage gaps."
    return ToolResult(
        status="incomplete_coverage" if gaps else "ok",
        message=message,
        claims=claims,
        evidence=covered_evidence,
        scope={
            "release": tools.release.version,
            "periods": [label(period) for period in periods],
            "phase": phase_scope,
            "games_covered": len(views),
            "games_selected": len(selected),
        },
    )
