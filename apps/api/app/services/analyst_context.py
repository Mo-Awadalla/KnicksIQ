"""What a turn may know before it speaks: capability manifest and admitted prior state."""

from __future__ import annotations

from typing import Any

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from app.services.analyst_player_stats import METRICS
from app.services.evidence_contracts import Evidence, VerifiedClaim
from app.services.query_resolution import ResolvedQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def load_archive(
    db: AsyncSession, release: DatasetRelease
) -> tuple[list[Game], list[tuple[PlayerGameStat, Player]], dict[str, str]]:
    """The release's Knicks games, their Knicks box-score rows, and team conferences."""
    games = list(
        (
            await db.execute(
                select(Game)
                .where(
                    Game.release_id == release.id,
                    Game.season == release.season,
                    (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
                )
                .order_by(Game.game_date, Game.id)
            )
        ).scalars()
    )
    rows = list(
        (
            await db.execute(
                select(PlayerGameStat, Player)
                .join(Player)
                .where(
                    PlayerGameStat.release_id == release.id,
                    PlayerGameStat.game_id.in_([g.id for g in games]),
                    PlayerGameStat.team_id == "NYK",
                )
            )
        ).all()
    )
    conferences = {
        team_id: conference
        for team_id, conference in (
            await db.execute(select(Team.id, Team.conference).where(Team.conference.is_not(None)))
        ).all()
    }
    return games, [(stat, player) for stat, player in rows], conferences


def capability_manifest(
    release: DatasetRelease,
    games: list[Game],
    rows: list[tuple[PlayerGameStat, Player]],
    scope: ResolvedQuery | None,
) -> dict[str, Any]:
    return {
        "release_id": release.version,
        "seasons": [release.season],
        "season_types": sorted({g.season_type for g in games}),
        "data_types": ["game_scores", "player_box_scores", "archive_evidence"],
        "metrics": list(METRICS),
        "team_metrics": ["wins", "losses", "points", "margin"],
        "games": len(games),
        "box_score_rows": len(rows),
        "known_gaps": [
            "No live injuries, trades or current updates.",
            "Archive coverage is not necessarily the complete NBA season.",
            "Box scores do not establish causation or overall playing quality.",
            "Ranked retrieval is a sample, not proof that reports or play-by-play are absent.",
        ],
        # The model sees only the filters this request actually sets. The committed scope
        # keeps every field for the server-side calculations, but sending its nulls and
        # empty lists would spend the provider's input budget on nothing.
        "scope": (
            scope.model_dump(mode="json", exclude_none=True, exclude_defaults=True) if scope else {}
        ),
        "operation": scope.operation if scope else None,
    }


def admitted(
    state: dict[str, Any],
    *,
    version: str,
    permitted_games: set[int],
    subjects: set[str],
    different: bool,
    another: bool,
) -> tuple[dict[str, VerifiedClaim], dict[str, Evidence]]:
    """Committed claims and evidence that this release still authorizes, by identity.

    A stored claim is reusable only when it was computed on the active release, inside the
    games this turn permits, about the subject this turn asks for, and the turn is not
    asking for a different player or another instance.
    """
    claims: dict[str, VerifiedClaim] = {}
    evidence: dict[str, Evidence] = {}
    for raw in state.get("claims", []):
        claim = VerifiedClaim.model_validate(raw)
        if (
            claim.release_id == version
            and set(claim.game_ids or []) <= permitted_games
            and (not subjects or claim.subject_id in subjects)
            and not different
            and not another
        ):
            claims[claim.claim_id] = claim
    for raw in state.get("evidence", []):
        item = Evidence.model_validate(raw)
        if item.release_id == version:
            evidence[item.evidence_id] = item
    return claims, evidence
