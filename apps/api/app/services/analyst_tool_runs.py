"""get_game_flow handler: sets of games plus the registry entry point.

Single-game claim construction lives in ``analyst_flow_claims``. This module ranks
runs, comebacks, deficits and lost leads across a selected game set and provides the
``run`` handler the registry calls.

Scope and phase
---------------
The dispatcher pins games to the active release and applies opponent, date, home /
road, result, season-type and period filters. Every claim names the game's phase
(regular season, play-in or playoffs). A set of games is summarized by the largest
single run, comeback, deficit and lost lead, with the game, period, clock and score
that produced it. No claim asserts a cause: the statements describe observed
sequence only. Games without play-by-play are reported as incomplete coverage, never
as an absence of the event.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from app.models.game_event import GameEvent
from app.services.analyst_flow import (
    GameFlow,
    Run,
    build_flow,
    phase,
    prefix,
    run_text,
    score_text,
    time_text,
)
from app.services.analyst_flow_claims import _claim, _receipt, _single_claims
from app.services.evidence_contracts import Evidence, ToolResult
from app.services.query_resolution import ResolvedQuery
from sqlalchemy import select

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall, VerifiedClaim


def _reduced_run_claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    flows: list[GameFlow],
    *,
    team: str,
    metric: str,
    intro: str,
    limitation: str,
) -> tuple[VerifiedClaim, list[Evidence]] | None:
    candidates: list[tuple[GameFlow, Run]] = []
    for flow in flows:
        for run in flow.runs:
            if (team == "NYK") != (run.team_id == "NYK"):
                continue
            candidates.append((flow, run))
    if not candidates:
        return None
    flow, run = max(
        candidates,
        key=lambda item: (
            item[1].points,
            -item[0].game.game_date.toordinal(),
            -item[1].start.sequence,
        ),
    )
    team_label = "NYK" if team == "NYK" else flow.opponent
    receipts = [
        _receipt(tools, flow.game, run.start),
        _receipt(tools, flow.game, run.end),
    ]
    result = "won" if flow.winner == "NYK" else "lost" if flow.winner == "OPP" else "tied"
    claim = _claim(
        tools,
        scope,
        [flow.game],
        subject=f"team:{team_label}",
        metric=metric,
        value=run.points,
        unit="points",
        statement=(
            f"{prefix(flow.game, flow.opponent)}: {intro} a {team_label} "
            f"{run.points}-0 run from {run_text(run)}; NYK {result} "
            f"{flow.final_nyk}-{flow.final_opp}."
        ),
        evidence=receipts,
        sample=len(flow.plays),
        limitation=limitation,
    )
    return claim, receipts


def _set_claims(
    tools: AnalystTools, scope: ResolvedQuery, flows: list[GameFlow]
) -> tuple[list[VerifiedClaim], list[Evidence]]:
    claims: list[VerifiedClaim] = []
    evidence: list[Evidence] = []
    for team, metric, intro in (
        ("NYK", "biggest_run", "the largest Knicks run in the selected games was"),
        ("OPP", "biggest_run", "the largest opponent run in the selected games was"),
    ):
        built = _reduced_run_claim(
            tools,
            scope,
            flows,
            team=team,
            metric=metric,
            intro=intro,
            limitation="A run is consecutive scoring plays; non-scoring events do not break it.",
        )
        if built:
            claims.append(built[0])
            evidence.extend(built[1])

    loss_flows = [flow for flow in flows if flow.winner == "OPP"]
    built = _reduced_run_claim(
        tools,
        scope,
        loss_flows,
        team="OPP",
        metric="biggest_run_in_loss",
        intro="the largest opponent run in a Knicks loss was",
        limitation="A run is consecutive scoring plays; this selection is limited to losses.",
    )
    if built:
        claims.append(built[0])
        evidence.extend(built[1])

    comebacks = [(flow, flow.comeback) for flow in flows if flow.comeback is not None]
    if comebacks:
        flow, comeback = max(
            comebacks,
            key=lambda item: (
                item[1].deficit,
                -item[0].game.game_date.toordinal(),
                -item[1].low.sequence,
            ),
        )
        game_prefix = prefix(flow.game, flow.opponent)
        receipts = [
            _receipt(tools, flow.game, comeback.low),
            _receipt(tools, flow.game, comeback.first_tie_or_lead),
        ]
        claims.append(
            _claim(
                tools,
                scope,
                [flow.game],
                subject="team:NYK",
                metric="largest_deficit_erased",
                value=comeback.deficit,
                unit="points",
                statement=(
                    f"{game_prefix}: the largest deficit erased in a win was "
                    f"{comeback.deficit} points at {time_text(comeback.low)} "
                    f"({score_text(comeback.low)}); NYK first tied or led at "
                    f"{time_text(comeback.first_tie_or_lead)} "
                    f"({score_text(comeback.first_tie_or_lead)}) and won "
                    f"{flow.final_nyk}-{flow.final_opp}, outscoring {flow.opponent} "
                    f"{comeback.nyk_points}-{comeback.opp_points} in that stretch."
                ),
                evidence=receipts,
                sample=len(flow.plays),
                limitation="The comeback window is the low point to the first tie or lead.",
            )
        )
        evidence.extend(receipts)
        if comeback.run is not None:
            run = comeback.run
            run_receipts = [
                _receipt(tools, flow.game, run.start),
                _receipt(tools, flow.game, run.end),
            ]
            claims.append(
                _claim(
                    tools,
                    scope,
                    [flow.game],
                    subject="team:NYK",
                    metric="largest_comeback_run",
                    value=run.points,
                    unit="points",
                    statement=(
                        f"{game_prefix}: within that comeback, NYK's biggest run was "
                        f"{run.points}-0 from {run_text(run)}."
                    ),
                    evidence=run_receipts,
                    sample=len(flow.plays),
                    limitation="The run is a consecutive scoring sequence inside the comeback.",
                )
            )
            evidence.extend(run_receipts)

    loss_deficits = sorted(
        ((flow.largest_lead_opp, flow) for flow in loss_flows if flow.largest_lead_opp > 0),
        key=lambda item: (-item[0], item[1].game.game_date, item[1].game.id),
    )
    if loss_deficits:
        top = loss_deficits[0][0]
        shown = [(value, flow) for value, flow in loss_deficits if value == top][:3]
        details: list[str] = []
        deficit_receipts: list[Evidence] = []
        go_receipts: list[Evidence] = []
        for value, flow in shown:
            play = flow.largest_lead_opp_play
            assert play is not None
            extra = ""
            if flow.go_ahead is not None:
                extra = (
                    f"; {flow.opponent} took the lead for good at "
                    f"{time_text(flow.go_ahead)} ({score_text(flow.go_ahead)})"
                )
                go_receipts.append(_receipt(tools, flow.game, flow.go_ahead))
            details.append(
                f"{phase(flow.game)} {flow.game.game_date} vs {flow.opponent} "
                f"({flow.final_nyk}-{flow.final_opp}): {value} points at "
                f"{time_text(play)} ({score_text(play)}){extra}"
            )
            deficit_receipts.append(_receipt(tools, flow.game, play))
        claim_receipts = deficit_receipts[:3]
        if len(claim_receipts) < 3:
            claim_receipts += go_receipts[: 3 - len(claim_receipts)]
        shown_games = [flow.game for _, flow in shown]
        amount = f"{top} point" if top == 1 else f"{top} points"
        claims.append(
            _claim(
                tools,
                scope,
                shown_games,
                subject="team:NYK",
                metric="largest_deficit_in_loss",
                value=top,
                unit="points",
                statement=(
                    f"Largest deficit in a Knicks loss across the selected games: {amount}. "
                    + "; ".join(details)
                    + "."
                ),
                evidence=claim_receipts,
                sample=sum(len(flow.plays) for flow in flows),
                limitation="A deficit in a loss is an observed margin, not a cause of the loss.",
            )
        )
        evidence.extend(deficit_receipts + go_receipts)

    blown = [(flow, flow.lost_lead) for flow in loss_flows if flow.lost_lead is not None]
    if blown:
        flow, lost = max(
            blown,
            key=lambda item: (
                item[1].lead,
                -item[0].game.game_date.toordinal(),
                -item[1].peak.sequence,
            ),
        )
        receipts = [
            _receipt(tools, flow.game, lost.peak),
            _receipt(tools, flow.game, lost.winner_go_ahead),
        ]
        claims.append(
            _claim(
                tools,
                scope,
                [flow.game],
                subject="team:NYK",
                metric="largest_lead_lost",
                value=lost.lead,
                unit="points",
                statement=(
                    f"{prefix(flow.game, flow.opponent)}: the largest lead lost was "
                    f"{lost.lead} points at {time_text(lost.peak)} "
                    f"({score_text(lost.peak)}); {flow.opponent} took the lead for good at "
                    f"{time_text(lost.winner_go_ahead)} "
                    f"({score_text(lost.winner_go_ahead)}) and NYK lost "
                    f"{flow.final_nyk}-{flow.final_opp}."
                ),
                evidence=receipts,
                sample=len(flow.plays),
                limitation="A lead lost is the peak lead; the winner's go-ahead is separate.",
            )
        )
        evidence.extend(receipts)

    return claims, evidence


async def _flow_for_games(
    tools: AnalystTools, scope: ResolvedQuery, games: list[Game]
) -> tuple[list[GameFlow], int]:
    if not games:
        return [], 0
    rows = list(
        (
            await tools.db.execute(
                select(GameEvent)
                .where(GameEvent.game_id.in_([game.id for game in games]))
                .order_by(GameEvent.game_id, GameEvent.period, GameEvent.sequence)
            )
        ).scalars()
    )
    grouped: dict[int, list[GameEvent]] = defaultdict(list)
    for event in rows:
        grouped[event.game_id].append(event)
    flows: list[GameFlow] = []
    missing = 0
    for game in games:
        flow = build_flow(game, grouped.get(game.id, []), scope.periods)
        if flow is None:
            missing += 1
            continue
        flows.append(flow)
    return flows, missing


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
) -> ToolResult:
    assert scope is not None
    if scope.relative_game_count:
        games = games[-scope.relative_game_count :]
    flows, missing = await _flow_for_games(tools, scope, games)
    if not flows:
        return ToolResult(
            status="incomplete_coverage",
            message=(
                "No scoring plays are available for the selected games; this is a "
                "coverage gap, not evidence that no run or lead occurred."
            ),
            scope={
                "release": tools.release.version,
                "games": len(games),
                "games_without_events": missing,
            },
        )
    single = len(flows) == 1
    claims, evidence = (
        _single_claims(tools, scope, flows[0]) if single else _set_claims(tools, scope, flows)
    )
    status = "incomplete_coverage" if missing else "ok"
    period_text = f" in periods {scope.periods}" if scope.periods else ""
    message = (
        f"Game flow from {sum(len(flow.plays) for flow in flows)} scoring plays across "
        f"{len(flows)} game(s){period_text}. Every claim cites a game_events receipt with "
        "period, clock and score."
    )
    if missing:
        message += f" {missing} selected game(s) have no play-by-play."
    return ToolResult(
        status=status,
        message=message,
        claims=claims,
        evidence=list({item.evidence_id: item for item in evidence}.values()),
        scope={
            "release": tools.release.version,
            "games": len(flows),
            "games_without_events": missing,
            "periods": scope.periods,
        },
    )
