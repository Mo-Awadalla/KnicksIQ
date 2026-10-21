"""Claim construction for the get_game_flow analyst tool.

``analyst_flow`` defines every flow concept deterministically. This file turns a
game flow into immutable claims backed by game_events receipts. The model may
reference claim ids and values but never authors a number.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.analyst_flow import (
    CLUTCH_MARGIN,
    CLUTCH_SECONDS,
    GameFlow,
    Play,
    event_type,
    phase,
    prefix,
    run_text,
    score_text,
    time_text,
)
from app.services.evidence_contracts import Evidence
from app.services.query_resolution import ResolvedQuery

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import VerifiedClaim

CLAIM_LIMITATION = "Available release archive only; sequence order is not evidence of cause."


def _points(value: int) -> str:
    return f"{value} point" if value == 1 else f"{value} points"


def _receipt(tools: AnalystTools, game: Game, play: Play) -> Evidence:
    evidence_id = f"{tools.release.version}:event:{game.id}:{play.sequence}"
    existing = tools.evidence.get(evidence_id)
    if existing is not None:
        return existing
    metadata: dict[str, Any] = {
        "date": str(game.game_date),
        "season_type": game.season_type,
        "home": game.home_team_id,
        "away": game.away_team_id,
        "period": play.period,
        "clock": play.clock,
        "sequence": play.sequence,
        "event_type": event_type(play.event),
        "team_id": play.team_id,
        "description": play.event.description,
        "points": play.points,
        "nyk_before": play.nyk_before,
        "opp_before": play.opp_before,
        "nyk_after": play.nyk_after,
        "opp_after": play.opp_after,
        "margin_before": play.margin_before,
        "margin_after": play.margin_after,
        "home_score_before": play.home_before,
        "away_score_before": play.away_before,
        "home_score_after": play.home_after,
        "away_score_after": play.away_after,
    }
    evidence = Evidence(
        evidence_id=evidence_id,
        release_id=tools.release.version,
        game_id=game.id,
        text=(
            f"{game.game_date} {phase(game)}: {time_text(play)} {play.team_id} scored "
            f"{play.points}; score {play.nyk_before}-{play.opp_before} to "
            f"{score_text(play)} ({play.event.description})."
        ),
        source_name=game.source_name,
        source_url=game.source_url,
        metadata=metadata,
    )
    tools.evidence[evidence_id] = evidence
    return evidence


def _claim(
    tools: AnalystTools,
    scope: ResolvedQuery,
    games: list[Game],
    *,
    subject: str,
    metric: str,
    value: float | int | str,
    unit: str,
    statement: str,
    evidence: list[Evidence],
    sample: int,
    limitation: str,
) -> VerifiedClaim:
    return tools.claim(
        subject=subject,
        metric=metric,
        value=value,
        unit=unit,
        games=games,
        evidence=evidence,
        statement=statement,
        scope=scope,
        sample=sample,
        denominator=None,
        baseline=[],
        limitations=[limitation, CLAIM_LIMITATION],
        eligibility={
            "source": "game_events",
            "scoring_play": "made_shot or free_throw with a changed cumulative score",
            "periods": scope.periods,
        },
        window={"game_ids": [game.id for game in games], "periods": scope.periods},
    )


def _single_claims(
    tools: AnalystTools, scope: ResolvedQuery, flow: GameFlow
) -> tuple[list[VerifiedClaim], list[Evidence]]:
    game, opponent = flow.game, flow.opponent
    game_prefix = prefix(game, opponent)
    claims: list[VerifiedClaim] = []
    evidence: list[Evidence] = []
    anchor = flow.plays[-1]

    def emit(
        *,
        subject: str,
        metric: str,
        value: float | int | str,
        unit: str,
        statement: str,
        plays: list[Play],
        limitation: str,
    ) -> None:
        receipts = [_receipt(tools, game, play) for play in plays]
        claims.append(
            _claim(
                tools,
                scope,
                [game],
                subject=subject,
                metric=metric,
                value=value,
                unit=unit,
                statement=statement,
                evidence=receipts,
                sample=len(flow.plays),
                limitation=limitation,
            )
        )
        evidence.extend(receipts)

    final_receipt = _receipt(tools, game, anchor)
    claims.append(
        _claim(
            tools,
            scope,
            [game],
            subject=f"game:{game.id}",
            metric="final_score",
            value=f"{flow.final_nyk}-{flow.final_opp}",
            unit="score",
            statement=(
                f"{game_prefix}: final score {flow.final_nyk}-{flow.final_opp}"
                + (f", {flow.winner} won." if flow.winner else ", tied.")
            ),
            evidence=[final_receipt],
            sample=len(flow.plays),
            limitation="Final score is the release game row, not a reconstructed total.",
        )
    )
    evidence.append(final_receipt)

    if flow.largest_lead_nyk_play is not None:
        largest_nyk = flow.largest_lead_nyk_play
        emit(
            subject="team:NYK",
            metric="largest_lead",
            value=flow.largest_lead_nyk,
            unit="points",
            statement=(
                f"{game_prefix}: NYK's largest lead was {_points(flow.largest_lead_nyk)} at "
                f"{time_text(largest_nyk)} when the score was {score_text(largest_nyk)}."
            ),
            plays=[largest_nyk],
            limitation="Largest lead uses the carried scoreboard at each scoring play.",
        )
    else:
        emit(
            subject="team:NYK",
            metric="largest_lead",
            value=0,
            unit="points",
            statement=f"{game_prefix}: NYK never led.",
            plays=[flow.plays[0]],
            limitation="A zero lead means no NYK score state had a positive margin.",
        )

    if flow.largest_lead_opp_play is not None:
        largest_opp = flow.largest_lead_opp_play
        emit(
            subject=f"team:{opponent}",
            metric="largest_lead",
            value=flow.largest_lead_opp,
            unit="points",
            statement=(
                f"{game_prefix}: {opponent}'s largest lead was "
                f"{_points(flow.largest_lead_opp)} at {time_text(largest_opp)} when the "
                f"score was {score_text(largest_opp)}."
            ),
            plays=[largest_opp],
            limitation="Largest lead uses the carried scoreboard at each scoring play.",
        )
    else:
        emit(
            subject=f"team:{opponent}",
            metric="largest_lead",
            value=0,
            unit="points",
            statement=f"{game_prefix}: {opponent} never led.",
            plays=[flow.plays[0]],
            limitation="A zero lead means no opponent score state had a positive margin.",
        )

    change_tail = list(dict.fromkeys(flow.change_plays[:1] + flow.change_plays[-1:]))
    emit(
        subject=f"game:{game.id}",
        metric="lead_changes",
        value=flow.lead_changes,
        unit="count",
        statement=(
            f"{game_prefix}: the lead changed {flow.lead_changes} times"
            + (
                f"; first at {time_text(flow.change_plays[0])} "
                f"({score_text(flow.change_plays[0])}), last at "
                f"{time_text(flow.change_plays[-1])} ({score_text(flow.change_plays[-1])})."
                if flow.change_plays
                else "."
            )
        ),
        plays=change_tail or [anchor],
        limitation="A tie does not count as a lead change; the next go-ahead score does.",
    )
    tie_tail = list(dict.fromkeys(flow.tie_plays[:1] + flow.tie_plays[-1:]))
    emit(
        subject=f"game:{game.id}",
        metric="ties",
        value=flow.ties,
        unit="count",
        statement=(
            f"{game_prefix}: the score was tied {flow.ties} times after a score"
            + (
                f"; first at {time_text(flow.tie_plays[0])} ({score_text(flow.tie_plays[0])}), "
                f"last at {time_text(flow.tie_plays[-1])} ({score_text(flow.tie_plays[-1])})."
                if flow.tie_plays
                else "."
            )
        ),
        plays=tie_tail or [anchor],
        limitation="The initial 0-0 state is not a tie.",
    )

    if flow.best_run_nyk is not None:
        run = flow.best_run_nyk
        emit(
            subject="team:NYK",
            metric="biggest_run",
            value=run.points,
            unit="points",
            statement=(
                f"{game_prefix}: NYK's biggest run was {run.points}-0 from {run_text(run)}."
            ),
            plays=[run.start, run.end],
            limitation="A run is consecutive scoring plays; non-scoring events do not break it.",
        )
    if flow.best_run_opp is not None:
        run = flow.best_run_opp
        emit(
            subject=f"team:{opponent}",
            metric="biggest_run",
            value=run.points,
            unit="points",
            statement=(
                f"{game_prefix}: {opponent}'s biggest run was {run.points}-0 from {run_text(run)}."
            ),
            plays=[run.start, run.end],
            limitation="A run is consecutive scoring plays; non-scoring events do not break it.",
        )

    if flow.go_ahead is not None:
        go = flow.go_ahead
        team = "NYK" if go.team_id == "NYK" else opponent
        wire_to_wire = go.sequence == flow.plays[0].sequence
        emit(
            subject=f"team:{team}",
            metric="go_ahead_margin",
            value=abs(go.margin_after),
            unit="points (winner's lead after the score)",
            statement=(
                f"{game_prefix}: {team} led from the first basket at {time_text(go)} "
                f"({score_text(go)}) and never trailed or tied again."
                if wire_to_wire
                else f"{game_prefix}: {team} took the lead for good at {time_text(go)} when "
                f"{go.event.description} made it {score_text(go)}."
            ),
            plays=[go],
            limitation="Go-ahead for good means no later tie or deficit for the winner.",
        )
        if flow.go_ahead_run is not None:
            run = flow.go_ahead_run
            emit(
                subject=f"team:{team}",
                metric="decisive_run",
                value=run.points,
                unit="points",
                statement=(
                    f"{game_prefix}: the run containing that go-ahead score was {team} "
                    f"{run.points}-0 from {run_text(run)}."
                ),
                plays=[run.start, run.end],
                limitation="The run is a consecutive scoring sequence, not a causal claim.",
            )

    window = (
        f"last {CLUTCH_SECONDS // 60}:00 of Q4 and any overtime with the margin "
        f"within {CLUTCH_MARGIN}"
    )
    if flow.clutch_plays:
        clutch_nyk = sum(play.points for play in flow.clutch_plays if play.team_id == "NYK")
        clutch_opp = sum(play.points for play in flow.clutch_plays if play.team_id != "NYK")
        clutch_start, clutch_end = flow.clutch_plays[0], flow.clutch_plays[-1]
        emit(
            subject="team:NYK",
            metric="clutch_points",
            value=clutch_nyk,
            unit="points",
            statement=(
                f"{game_prefix}: in the clutch window ({window}), NYK scored {clutch_nyk} "
                f"points and {opponent} scored {clutch_opp}, from "
                f"{score_text(clutch_start)} to {score_text(clutch_end)}."
            ),
            plays=[clutch_start, clutch_end],
            limitation="Clutch points count only scoring plays inside the stated window.",
        )
        emit(
            subject=f"team:{opponent}",
            metric="clutch_points",
            value=clutch_opp,
            unit="points",
            statement=(
                f"{game_prefix}: in the clutch window ({window}), {opponent} scored "
                f"{clutch_opp} points and NYK scored {clutch_nyk}, from "
                f"{score_text(clutch_start)} to {score_text(clutch_end)}."
            ),
            plays=[clutch_start, clutch_end],
            limitation="Clutch points count only scoring plays inside the stated window.",
        )
        if flow.clutch_change_plays:
            last_change = flow.clutch_change_plays[-1]
            emit(
                subject=f"game:{game.id}",
                metric="clutch_lead_changes",
                value=flow.clutch_lead_changes,
                unit="count",
                statement=(
                    f"{game_prefix}: the lead changed {flow.clutch_lead_changes} times in the "
                    f"clutch window; the last change was at {time_text(last_change)} "
                    f"({score_text(last_change)})."
                ),
                plays=[last_change],
                limitation="Clutch window is last 5:00 of Q4 plus overtime, margin within 5.",
            )
    else:
        emit(
            subject="team:NYK",
            metric="clutch_points",
            value=0,
            unit="points",
            statement=(
                f"{game_prefix}: no scoring play met the clutch window ({window}); "
                f"the game was not within {CLUTCH_MARGIN} in the last five minutes."
            ),
            plays=[anchor],
            limitation="An empty clutch window is a scoreboard condition, not missing data.",
        )

    if flow.comeback is not None:
        comeback = flow.comeback
        emit(
            subject="team:NYK",
            metric="deficit_erased",
            value=comeback.deficit,
            unit="points",
            statement=(
                f"{game_prefix}: NYK's largest deficit was {comeback.deficit} points at "
                f"{time_text(comeback.low)} ({score_text(comeback.low)}); they first tied "
                f"or led at {time_text(comeback.first_tie_or_lead)} "
                f"({score_text(comeback.first_tie_or_lead)}) and won "
                f"{flow.final_nyk}-{flow.final_opp}."
            ),
            plays=[comeback.low, comeback.first_tie_or_lead],
            limitation="The comeback window is the low point to the first tie or lead.",
        )
        emit(
            subject="team:NYK",
            metric="comeback_scoring",
            value=comeback.nyk_points,
            unit="points",
            statement=(
                f"{game_prefix}: from the {comeback.deficit}-point deficit at "
                f"{time_text(comeback.low)} ({score_text(comeback.low)}) to the first tie "
                f"or lead at {time_text(comeback.first_tie_or_lead)} "
                f"({score_text(comeback.first_tie_or_lead)}), NYK outscored {opponent} "
                f"{comeback.nyk_points}-{comeback.opp_points}."
            ),
            plays=[comeback.low, comeback.first_tie_or_lead],
            limitation="The stretch can contain runs by both teams.",
        )
        if comeback.run is not None:
            run = comeback.run
            emit(
                subject="team:NYK",
                metric="comeback_run",
                value=run.points,
                unit="points",
                statement=(
                    f"{game_prefix}: within that comeback, NYK's biggest run was "
                    f"{run.points}-0 from {run_text(run)}."
                ),
                plays=[run.start, run.end],
                limitation="The run is a consecutive scoring sequence inside the comeback.",
            )

    if flow.lost_lead is not None:
        lost = flow.lost_lead
        go = lost.winner_go_ahead
        emit(
            subject="team:NYK",
            metric="lead_lost",
            value=lost.lead,
            unit="points",
            statement=(
                f"{game_prefix}: NYK's largest lead was {lost.lead} points at "
                f"{time_text(lost.peak)} ({score_text(lost.peak)}) and they lost "
                f"{flow.final_nyk}-{flow.final_opp}; {opponent} took the lead for good at "
                f"{time_text(go)} ({score_text(go)})."
            ),
            plays=[lost.peak, go],
            limitation="A lead lost is the peak lead; the winner's go-ahead is separate.",
        )

    worst = min(flow.period_nets, key=lambda item: (item.net, item.period), default=None)
    if worst is not None:
        emit(
            subject=f"game:{game.id}",
            metric="worst_period_net",
            value=worst.net,
            unit="net points",
            statement=(
                f"{game_prefix}: NYK's worst period was Q{worst.period}, where they were "
                f"outscored {worst.opp_points}-{worst.nyk_points} (net {worst.net}); the "
                f"margin went from {worst.margin_before:+d} to {worst.margin_after:+d}."
            ),
            plays=[worst.start, worst.end],
            limitation="Period net counts scoring plays in that period only.",
        )

    question = tools.question.lower()
    comeback = bool(re.search(r"\b(erase|comeback|deficit|rally)\b", question))
    collapse = bool(
        re.search(r"\b(collapse|lose control|lost control|blow|blown|lead)\b", question)
    )
    run_question = bool(re.search(r"\b(run|runs|scoring run|surge|spurt)\b", question))
    turn_question = bool(re.search(r"\b(turn|turned|where|when|sequence|control)\b", question))
    clutch_question = bool(re.search(r"\b(clutch|late[- ]game|last \d|final minutes)\b", question))

    def priority(claim: VerifiedClaim) -> tuple[int, int]:
        metric = claim.metric_id
        subject = claim.subject_id or ""
        if metric == "final_score":
            return (1, 0)
        if clutch_question and metric in {"clutch_points", "clutch_lead_changes"}:
            return (2 if subject == "team:NYK" else 3, 0)
        if comeback and metric in {"deficit_erased", "comeback_scoring", "comeback_run"}:
            return (
                {"deficit_erased": 2, "comeback_scoring": 3, "comeback_run": 4}[metric],
                0,
            )
        if collapse and metric == "lead_lost":
            return (2, 0)
        if turn_question and metric == "go_ahead_margin":
            return (2, 0)
        if turn_question and metric == "decisive_run":
            return (3, 0)
        if run_question and metric == "biggest_run":
            return (2 if subject == "team:NYK" else 3, 0)
        if metric == "largest_lead":
            return (4 if subject == "team:NYK" else 5, 0)
        if metric == "go_ahead_margin":
            return (4, 0)
        if metric == "biggest_run":
            return (5 if subject == "team:NYK" else 6, 0)
        if metric == "lead_changes":
            return (7, 0)
        if metric == "ties":
            return (8, 0)
        return (9, 0)

    claims.sort(key=priority)
    return claims, evidence
