"""Data source adapters.

The `NBADataSource` protocol defines a stable interface for fetching
game data. Two implementations are provided:

- `StaticSeedDataSource` — reads from the API's seed JSON files
  (default; used in dev and tests).
- `NbaApiDataSource` — live data source backed by `swar/nba_api`.

`get_data_source()` is the single factory used by jobs; the active
implementation is selected at runtime via the `NBA_DATA_SOURCE`
env var (see `worker_app.core.config`).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from worker_app.adapters.nba_api_source import NbaApiDataSource
from worker_app.core.config import Settings


class NBADataSource(Protocol):
    """Protocol for NBA data sources. Implementations may be remote or local."""

    def list_seasons(self) -> list[str]: ...
    def list_games(
        self, season: str, *, include_playoffs: bool = False
    ) -> list[dict[str, Any]]: ...
    def get_game(self, nba_game_id: str) -> dict[str, Any] | None: ...


class StaticSeedDataSource:
    """Reads game data from the API's seed JSON files.

    This is the default source. It plays the role of a real upstream
    API in dev/test environments: it returns data in the same shape
    we would parse from `stats.nba.com`.
    """

    def __init__(self, seed_dir: Path) -> None:
        self._seed_dir = seed_dir

    def _read(self, name: str) -> list[dict[str, Any]]:
        with (self._seed_dir / name).open() as f:
            return json.load(f)

    def list_seasons(self) -> list[str]:
        games = self._read("games.json")
        return sorted({g["season"] for g in games})

    def list_games(self, season: str, *, include_playoffs: bool = False) -> list[dict[str, Any]]:
        games = self._read("games.json")
        rows = [g for g in games if g.get("season") == season]
        if include_playoffs:
            return rows
        return [g for g in rows if g.get("season_type", "regular") == "regular"]

    def get_game(self, nba_game_id: str) -> dict[str, Any] | None:
        games = self._read("games.json")
        for g in games:
            if g.get("nba_game_id") == nba_game_id:
                return g
        return None

    def list_teams(self) -> list[dict[str, Any]]:
        return self._read("teams.json")

    def list_players(self) -> list[dict[str, Any]]:
        return self._read("players.json")


def get_data_source(settings: Settings, seed_dir: Path) -> NBADataSource:
    """Construct the data source selected by `settings.data_source`.

    Args:
        settings: The worker's settings (see `worker_app.core.config`).
            `settings.data_source` selects the implementation.
        seed_dir: Path to the API's seed directory. The static source
            reads JSON files from here; the live source loads the
            team-id mapping from `teams.json` here.

    Returns:
        A `StaticSeedDataSource` (default) or `NbaApiDataSource`.
    """
    if settings.data_source == "nba_api":
        return NbaApiDataSource(settings.nba_api, seed_dir)
    return StaticSeedDataSource(seed_dir)


def parse_game_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
