"""Complete, deterministic source units; no evaluation inputs or model calls."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.query_resolution import _CURATED_PLAYER_ALIASES, _player_aliases
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

UNIT_RECIPE = "archive-source-units-v1"


def _record(payload: dict[str, Any], text: str) -> dict[str, Any]:
    payload = {"recipe": UNIT_RECIPE, **payload, "text": text, "semantic_summary": text}
    identity = (
        "archive-unit:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {"id": identity, "payload": {**payload, "source_document_id": identity}}


def opponent_unit(games: list[Game], opponent: str, version: str) -> dict[str, Any]:
    games = sorted(games, key=lambda g: (g.game_date, g.nba_game_id))
    rows = [
        {
            "game_id": g.id,
            "nba_game_id": g.nba_game_id,
            "game_date": g.game_date.isoformat(),
            "season": g.season,
            "season_type": g.season_type,
            "home_team_id": g.home_team_id,
            "away_team_id": g.away_team_id,
            "home_score": g.home_score,
            "away_score": g.away_score,
            "status": g.status,
            "source_payload_hash": g.source_payload_hash,
        }
        for g in games
    ]
    results = [
        "W" if (r["home_score"] > r["away_score"]) == (r["home_team_id"] == "NYK") else "L"
        for r in rows
    ]
    text = (
        f"Knicks NYK results against {opponent} in the {games[0].season} archive: "
        f"{results.count('W')} wins, {results.count('L')} losses in {len(rows)} final games. "
        "Complete opponent population, including every available phase.\n"
    ) + "\n".join(
        f"{r['nba_game_id']} | {r['game_date']} | {r['season_type']} | "
        f"{r['away_team_id']} {r['away_score']} at {r['home_team_id']} {r['home_score']} | "
        f"Knicks {result}"
        for r, result in zip(rows, results, strict=True)
    )
    return _record(
        {
            "unit_type": "multigame_aggregate",
            "aggregate_kind": "opponent_results",
            "data_version": version,
            "season": games[0].season,
            "opponent_id": opponent,
            "team_ids": ["NYK", opponent],
            "game_ids": sorted(g.id for g in games),
            "dates": sorted({r["game_date"] for r in rows}),
            "season_types": sorted({g.season_type for g in games}),
            "canonical_sources": sorted(f"game:{g.nba_game_id}" for g in games),
            "canonical_rows": rows,
        },
        text,
    )


def identity_unit(player: Player, version: str) -> dict[str, Any]:
    row = {
        key: getattr(player, key)
        for key in ("nba_player_id", "full_name", "team_id", "position", "jersey_number")
    }
    aliases = sorted(_player_aliases(player))
    curated = {
        alias: name for alias, name in _CURATED_PLAYER_ALIASES.items() if name == player.full_name
    }
    display = [a.upper() if a in curated and len(a) <= 3 else a for a in aliases]
    text = (
        f"Canonical player identity: {player.full_name}; NBA player ID {player.nba_player_id}; "
        f"team {player.team_id}. Name-derived and project-curated aliases: {', '.join(display)}. "
        "Identity only; this does not identify a game or establish game performance."
    )
    return _record(
        {
            "unit_type": "player_identity",
            "data_version": version,
            "player_ids": [player.id],
            "player_names": [player.full_name],
            "team_ids": [player.team_id] if player.team_id else [],
            "canonical_player": row,
            "aliases": aliases,
            "alias_provenance": {"name_derived": True, "project_curated": curated},
            "canonical_sources": [f"player:{player.nba_player_id}"],
        },
        text,
    )


def accepts_unit(
    metadata: dict[str, Any],
    *,
    games: list[Game],
    players: list[Player],
    selected_game_ids: set[int],
    player_ids: list[int],
    periods: list[int],
    version: str,
) -> bool:
    """Verify the full recipe against SQL and the complete requested population."""
    if "game_id" in metadata or metadata.get("data_version") != version:
        return False
    expected = None
    if metadata.get("unit_type") == "multigame_aggregate":
        opponent = metadata.get("opponent_id")
        if not isinstance(opponent, str) or opponent == "NYK":
            return False
        population = [
            g
            for g in games
            if g.status == "final"
            and g.home_score != g.away_score
            and opponent in {g.home_team_id, g.away_team_id}
        ]
        if (
            not population
            or player_ids
            or periods
            or not {g.id for g in population} <= selected_game_ids
        ):
            return False
        expected = opponent_unit(population, opponent, version)
    elif metadata.get("unit_type") == "player_identity":
        identity = metadata.get("canonical_player", {}).get("nba_player_id")
        player = next(
            (p for p in players if p.nba_player_id == identity and p.id in player_ids), None
        )
        if player is None:
            return False
        expected = identity_unit(player, version)
    if expected is None:
        return False
    return all(metadata.get(key) == value for key, value in expected["payload"].items())


async def build_archive_units(
    db: AsyncSession, games: list[Game], version: str
) -> list[dict[str, Any]]:
    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.version == version, DatasetRelease.validation_passed.is_(True)
            )
        )
    ).scalar_one_or_none()
    if release is None or not games:
        return []
    population = list(
        (
            await db.execute(
                select(Game)
                .where(
                    Game.release_id == release.id,
                    Game.season == release.season,
                    Game.status == "final",
                    Game.home_score != Game.away_score,
                    (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
                )
                .order_by(Game.game_date, Game.id)
            )
        ).scalars()
    )
    included = {g.id for g in games}
    groups: dict[str, list[Game]] = defaultdict(list)
    for game in population:
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        groups[opponent].append(game)
    records = [
        opponent_unit(group, opponent, version)
        for opponent, group in sorted(groups.items())
        if len(group) > 1 and {g.id for g in group} <= included
    ]
    players = list(
        (
            await db.execute(
                select(Player)
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(
                    PlayerGameStat.release_id == release.id,
                    PlayerGameStat.game_id.in_(included),
                    PlayerGameStat.team_id == "NYK",
                )
                .distinct()
                .order_by(Player.nba_player_id)
            )
        ).scalars()
    )
    records.extend(identity_unit(player, version) for player in players)
    return sorted(records, key=lambda record: record["id"])
