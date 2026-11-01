"""Private provenance for delivered receipts: actual rows, computed digests, identity.

A receipt's citation proves an identity. This module adds the content that identity
refers to: the exact SQL row projection the receipt was built from, the digest
computed from those values, and the row's own database id. The snapshots travel
only in the non-production private response registry, never in the model-facing
evidence metadata, and a production process skips every hash and copy because the
response schema excludes the registry there.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

GAME_FIELDS = (
    "away_score",
    "away_team_id",
    "data_status",
    "game_date",
    "game_label",
    "home_score",
    "home_team_id",
    "nba_game_id",
    "season",
    "season_type",
    "series_game_number",
    "series_name",
    "source_fetched_at",
    "source_game_id",
    "source_name",
    "source_payload_hash",
    "source_url",
    "status",
)

PLAYER_GAME_STAT_FIELDS = (
    "assists",
    "blocks",
    "defensive_rebounds",
    "field_goals_attempted",
    "field_goals_made",
    "free_throws_attempted",
    "free_throws_made",
    "minutes",
    "nba_game_id",
    "nba_player_id",
    "offensive_rebounds",
    "personal_fouls",
    "plus_minus",
    "points",
    "position",
    "rebounds",
    "starter",
    "steals",
    "team_id",
    "three_pointers_attempted",
    "three_pointers_made",
    "turnovers",
)

PERIOD_SCORE_FIELDS = ("nba_game_id", "period", "points", "team_id")

TEAM_GAME_STAT_FIELDS = (
    "assists",
    "blocks",
    "defensive_rebounds",
    "field_goals_attempted",
    "field_goals_made",
    "free_throws_attempted",
    "free_throws_made",
    "nba_game_id",
    "offensive_rebounds",
    "personal_fouls",
    "plus_minus",
    "points",
    "rebounds",
    "steals",
    "team_id",
    "three_pointers_attempted",
    "three_pointers_made",
    "turnovers",
)


def canonical_digest(value: Any) -> str:
    """The release's canonical row digest; the same recipe the mapping records."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def row_receipt(release: str, collection: str, game_id: int, runtime_id: int) -> str:
    """The receipt id the analyst emits for one canonical SQL row."""
    if collection == "games":
        return f"{release}:game:{int(game_id)}"
    if collection == "player_game_stats":
        return f"{release}:game:{int(game_id)}:player:{int(runtime_id)}"
    segment, marker = {
        "team_game_stats": ("team_box", "team"),
        "period_scores": ("period", "period"),
    }[collection]
    return f"{release}:{segment}:{int(game_id)}:{marker}:{int(runtime_id)}"


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def game_projection(game: Any) -> dict[str, Any]:
    """The canonical row a game receipt stands for, read from the loaded ORM row."""
    return {field: _json_value(getattr(game, field)) for field in GAME_FIELDS}


def player_stat_projection(game: Any, stat: Any, player: Any) -> dict[str, Any]:
    """A box-score row plus the NBA identities its relations carry."""
    projection = {
        field: _json_value(getattr(stat, field))
        for field in PLAYER_GAME_STAT_FIELDS
        if field not in {"nba_game_id", "nba_player_id"}
    }
    projection["nba_game_id"] = game.nba_game_id
    projection["nba_player_id"] = player.nba_player_id
    return projection


def period_projection(game: Any, row: Any) -> dict[str, Any]:
    """A period-score row plus the NBA game identity it belongs to."""
    return {
        "nba_game_id": game.nba_game_id,
        "period": _json_value(row.period),
        "points": _json_value(row.points),
        "team_id": _json_value(row.team_id),
    }


def team_stat_projection(game: Any, row: Any) -> dict[str, Any]:
    """A team box-score row plus the NBA game identity it belongs to."""
    projection = {
        field: _json_value(getattr(row, field))
        for field in TEAM_GAME_STAT_FIELDS
        if field != "nba_game_id"
    }
    projection["nba_game_id"] = game.nba_game_id
    return projection


class ProvenanceCapture:
    """Per-turn private captures, keyed by the receipt they belong to."""

    def __init__(self, *, enabled: bool):
        self.enabled = enabled
        self.rows: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_settings(cls, settings: Any) -> ProvenanceCapture:
        return cls(enabled=not settings.is_production)

    def capture_row(
        self,
        evidence_id: str,
        *,
        collection: str,
        canonical_id: str,
        row: dict[str, Any],
        source_row_id: int,
        sequence_id: int | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        self.rows[evidence_id] = {
            "source_collection": collection,
            "canonical_id": canonical_id,
            "source_row_id": source_row_id,
            "sequence_id": sequence_id,
            "source_row": row,
            "row_sha256": canonical_digest(row),
        }
        return True

    def registry(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The response registry: the committed evidence plus its captured content."""
        if not self.enabled:
            return list(items)
        entries = []
        for item in items:
            captured = self.rows.get(str(item.get("evidence_id") or ""))
            entries.append({**item, **captured} if captured else dict(item))
        return entries
