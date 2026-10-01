"""Complete descriptive game stories and canonical unanswered scoring runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from app.models.box_score import PeriodScore
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.evidence_contracts import Evidence, ToolResult, VerifiedClaim
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import scores
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class NarrativeSelection:
    kind: Literal["game_stories", "boston_unanswered_runs"]
    games: list[Game]
    definition: str


def select_narrative(question: str, games: list[Game]) -> NarrativeSelection | None:
    """Select defined extremes from the user's already release-filtered population."""
    q = re.sub(r"[-–—]", " ", question.lower())
    final = [g for g in games if g.status == "final"]
    if not final:
        return None
    if "BOS" in team_ids_in_text(question) and re.search(
        r"\b(?:key sequence|drought|unanswered|cost)\b", q
    ):
        losses = [g for g in final if scores(g)[0] < scores(g)[1]]
        if len(losses) == 1:
            return NarrativeSelection(
                "boston_unanswered_runs",
                losses,
                "Consecutive Boston scoring events without intervening Knicks points; "
                "any Knicks point ends a run; quarter breaks and zero-point events do not.",
            )
        return None
    if "closest" in q or re.search(r"\b(?:smallest|narrowest) (?:final )?margin\b", q):
        value = min(abs(scores(g)[0] - scores(g)[1]) for g in final)
        selected = [g for g in final if abs(scores(g)[0] - scores(g)[1]) == value]
        definition = "Smallest absolute final scoring margin; all tied games."
    elif re.search(r"\b(?:biggest|best|largest) (?:knicks'? )?win\b|\blargest winning margin\b", q):
        wins = [g for g in final if scores(g)[0] > scores(g)[1]]
        if not wins:
            return None
        value = max(scores(g)[0] - scores(g)[1] for g in wins)
        selected = [g for g in wins if scores(g)[0] - scores(g)[1] == value]
        definition = "Largest positive Knicks final scoring margin; all tied games."
    elif "best defensive game" in q:
        value = min(scores(g)[1] for g in final)
        selected = [g for g in final if scores(g)[1] == value]
        definition = "Fewest opponent points in a final archived game; all tied games."
    elif "highest scoring game" in q:
        value = max(scores(g)[0] for g in final)
        selected = [g for g in final if scores(g)[0] == value]
        definition = "Most Knicks points in a final archived game; all tied games."
    elif "lowest scoring game" in q:
        value = min(scores(g)[0] for g in final)
        selected = [g for g in final if scores(g)[0] == value]
        definition = "Fewest Knicks points in a final archived game; all tied games."
    elif re.search(r"\b(?:worst|biggest|largest) loss\b", q) and "margin" in q:
        losses = [g for g in final if scores(g)[0] < scores(g)[1]]
        if not losses:
            return None
        value = min(scores(g)[0] - scores(g)[1] for g in losses)
        selected = [g for g in losses if scores(g)[0] - scores(g)[1] == value]
        definition = "Most negative Knicks final scoring margin; all tied games."
    else:
        return None
    return NarrativeSelection("game_stories", selected, definition)


def measure_clarification(question: str) -> str | None:
    """Ask the approved inputs without question-ID matching or new defaults."""
    q = question.lower()
    if "worst" in q and re.search(r"\b(?:third|3rd) quarter\b", q):
        return (
            "Should worst third quarter mean fewest Knicks points or worst quarter margin? "
            "Which game or date/season scope should I compare?"
        )
    if "largest deficit" in q and "eras" in q:
        return (
            "Which game or season scope should I use? Should largest deficit include all "
            "observed deficits or only erased deficits? Does erased mean tied, regained "
            "the lead, or an eventual win?"
        )
    if "most damaging" in q and "opponent run" in q:
        return (
            "For this season, what boundaries define an opponent run, and should damage mean "
            "unanswered points, net scoring change, or another stated measure?"
        )
    if "biggest run" in q and "BOS" not in team_ids_in_text(question):
        return (
            "Should biggest run mean unanswered Knicks points or net gain over a defined "
            "window? Which game or season scope and window should I use?"
        )
    if "worst" in q and re.search(r"\b(?:collapse|collpase)\b", q):
        return (
            "Should worst collapse mean a lead surrendered or a scoring-margin decline? "
            "Which interval and game/season scope should I use, and must the game end in a loss?"
        )
    return None


def _event_row(game: Game, event: GameEvent) -> dict:
    return {
        "canonical_id": f"event:{game.nba_game_id}:{event.sequence}",
        "sequence": event.sequence,
        "period": event.period,
        "clock": event.clock,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "team_id": event.team_id,
        "event_type": event.event_type,
    }


def _maximum_runs(game: Game, events: list[GameEvent]) -> list[dict]:
    if not events or len({e.sequence for e in events}) != len(events):
        raise ValueError("Missing or duplicate canonical event order")
    previous = (0, 0)
    runs, scoring = [], []
    points, before = 0, previous
    boston = 0 if game.home_team_id == "BOS" else 1
    for event in events:
        current = (event.home_score, event.away_score)
        # Normalized non-scoring events may carry a zero sentinel.
        current = previous if current == (0, 0) else current
        change = tuple(a - b for a, b in zip(current, previous, strict=True))
        if min(change) < 0 or all(value > 0 for value in change):
            raise ValueError("Ambiguous or corrected canonical scoreboard")
        if change[1 - boston] > 0:
            if scoring:
                runs.append((points, before, previous, scoring))
            points, scoring = 0, []
        elif change[boston] > 0:
            if not scoring:
                before = previous
            scoring.append(event)
            points += change[boston]
        previous = current
    if scoring:
        runs.append((points, before, previous, scoring))
    if previous != (game.home_score, game.away_score) or not runs:
        raise ValueError("Canonical event coverage does not match final score")
    maximum = max(run[0] for run in runs)
    return [
        {
            "points": points,
            "knicks_points": 0,
            "start_sequence": scoring[0].sequence,
            "end_sequence": scoring[-1].sequence,
            "start_period": scoring[0].period,
            "end_period": scoring[-1].period,
            "start_clock": scoring[0].clock,
            "end_clock": scoring[-1].clock,
            "score_before": {"home": before[0], "away": before[1]},
            "score_after": {"home": after[0], "away": after[1]},
            "scoring_events": [_event_row(game, e) for e in scoring],
        }
        for points, before, after, scoring in runs
        if points == maximum
    ]


async def build_narrative(
    db: AsyncSession,
    release: DatasetRelease,
    selection: NarrativeSelection,
) -> ToolResult:
    """Read every selected row. An aggregate carries every source it claims to cover."""
    games = selection.games
    if any(g.release_id != release.id or g.season != release.season for g in games):
        return ToolResult(status="unsupported_metric_or_scope", message="Foreign narrative scope.")
    periods = list(
        (
            await db.execute(
                select(PeriodScore)
                .where(
                    PeriodScore.release_id == release.id,
                    PeriodScore.game_id.in_([g.id for g in games]),
                )
                .order_by(PeriodScore.game_id, PeriodScore.period, PeriodScore.team_id)
            )
        ).scalars()
    )
    stories, sources, statements = [], [], []
    for game in games:
        own, opponent = scores(game)
        opponent_id = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        observed = [p for p in periods if p.game_id == game.id]
        if observed and (
            sum(p.points for p in observed if p.team_id == "NYK") != own
            or sum(p.points for p in observed if p.team_id == opponent_id) != opponent
        ):
            return ToolResult(
                status="incomplete_coverage",
                message="I cannot verify period scores against the archived final score.",
            )
        period_values = [
            {
                "period": number,
                "NYK": next(
                    (p.points for p in observed if p.period == number and p.team_id == "NYK"), None
                ),
                opponent_id: next(
                    (p.points for p in observed if p.period == number and p.team_id == opponent_id),
                    None,
                ),
            }
            for number in sorted({p.period for p in observed})
        ]
        story = {
            "nba_game_id": game.nba_game_id,
            "date": str(game.game_date),
            "opponent": opponent_id,
            "knicks_points": own,
            "opponent_points": opponent,
            "season_type": game.season_type,
            "periods": period_values,
        }
        stories.append(story)
        sources.append(f"game:{game.nba_game_id}")
        sources.extend(f"period:{game.nba_game_id}:{p.team_id}:{p.period}" for p in observed)
        outcome = "won" if own > opponent else "lost" if own < opponent else "tied"
        period_text = "; ".join(
            f"{'Q' if p['period'] <= 4 else 'OT'}"
            f"{p['period'] if p['period'] <= 4 else p['period'] - 4}: "
            f"NYK {p['NYK']}, {opponent_id} {p[opponent_id]}"
            for p in period_values
        )
        statements.append(
            f"{game.game_date}: the Knicks {outcome} against {opponent_id}, {own}–{opponent}. "
            + (f"Period scores: {period_text}." if observed else "Period scoring is unavailable.")
        )
    runs, ordered_events = [], []
    if selection.kind == "boston_unanswered_runs":
        game = games[0]
        events = list(
            (
                await db.execute(
                    select(GameEvent)
                    .where(GameEvent.game_id == game.id)
                    .order_by(GameEvent.sequence)
                )
            ).scalars()
        )
        try:
            runs = _maximum_runs(game, events)
        except ValueError:
            return ToolResult(
                status="incomplete_coverage",
                message="I cannot verify the unanswered runs from this game's "
                "canonical scoring sequence.",
            )
        ordered_events = [_event_row(game, event) for event in events]
        sources.extend(e["canonical_id"] for e in ordered_events)
        statements.extend(
            f"Boston scored {r['points']} unanswered points from "
            f"Q{r['start_period']} {r['start_clock']} to "
            f"Q{r['end_period']} {r['end_clock']} "
            f"(events {r['start_sequence']}–{r['end_sequence']})."
            for r in runs
        )
    value = {"games": stories, "runs": runs, "definition": selection.definition}
    statement = selection.definition + "\n\n" + "\n\n".join(statements)
    payload = {**value, "ordered_events": ordered_events}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    identity = f"{release.version}:narrative:" + hashlib.sha256(text.encode()).hexdigest()
    evidence = Evidence(
        evidence_id=identity,
        release_id=release.version,
        text=text,
        metadata={
            "unit_type": "canonical_narrative",
            "game_ids": [g.id for g in games],
            "canonical_sources": sources,
            "definition": selection.definition,
        },
    )
    claim = VerifiedClaim.create(
        subject_id="team:NYK",
        metric_id="canonical_game_narrative",
        metric_definition_version="canonical-game-narrative-v1",
        value=value,
        unit="descriptive game scores and scoring sequences",
        population="every selected final game in the active archive",
        filters={"selection_definition": selection.definition},
        season=release.season,
        season_type=games[0].season_type if len({g.season_type for g in games}) == 1 else None,
        game_ids=[g.id for g in games],
        window=None,
        sample_size=len(games),
        denominator=None,
        baseline_claim_ids=[],
        calculation_version="canonical-game-narrative-v1",
        release_id=release.version,
        supporting_evidence_ids=[identity],
        coverage_limitations=["Descriptive observations only; no inferred causes or tactics."],
        eligibility={"game": "final release-scoped game", "ties": "all"},
        statement=statement,
    )
    return ToolResult(
        status="ok",
        message="Describe every selected game and every tied maximum; do not infer causes.",
        claims=[claim],
        evidence=[evidence],
    )


def complete_narrative_text(text: str, claims: list[VerifiedClaim]) -> bool:
    """The full value alone cannot excuse omission of a tied game/run from prose."""
    narratives = [c for c in claims if c.metric_id == "canonical_game_narrative"]
    if not narratives:
        return False
    for claim in narratives:
        value = claim.value
        if not isinstance(value, dict):
            return False
        for game in value["games"]:
            if game["date"] not in text and game["nba_game_id"] not in text:
                return False
        for run in value["runs"]:
            if run["start_clock"] not in text or run["end_clock"] not in text:
                return False
    return True
