"""Live NBA.com data source backed by `swar/nba_api`.

This module is a pure I/O adapter — it does not touch the database.
It satisfies the `NBADataSource` protocol declared in
`worker_app.adapters` and returns dicts in the same shape as
`StaticSeedDataSource` so the rest of the pipeline (jobs, parsers,
DB layer) can be source-agnostic.

# Why an explicit normalization layer?

nba_api's `playbyplayv3` returns actions in the NBA's "v3" format
(camelCase fields like `teamTricode`, `shotResult`, ISO-8601 clocks).
The rest of the worker pipeline expects the seed-shaped event dict
that `StaticSeedDataSource` produces (lowercase event_type strings,
"MM:SS" clocks, nba_player_id ints, etc.).

We translate v3 → seed shape here so `packages/basketball-core`'s
`play_by_play.parse_events()` doesn't have to learn a new format.

# TODO(file-issue): parser refactor

A future refactor of `play_by_play.parse_events()` to accept the
nba_api v3 shape natively would let us delete the normalization
block in `_parse_pbp_v3_action()` below. Until then, the
duplication is intentional.

# Why no DB access here?

The adapter is intentionally a pure I/O module. The job (which
already holds an `AsyncSession`) is responsible for translating
the int IDs returned here into your DB's `teams.id` (trigraph)
and `players.id` (autoincrement) values via one-shot `SELECT`
queries. See `worker_app.jobs.ingest_game_detail`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

import requests
from nba_api.stats.endpoints import (
    boxscoresummaryv3,
    boxscoretraditionalv3,
    commonallplayers,
    commonplayerinfo,
    commonteamroster,
    leaguegamefinder,
    playbyplayv3,
)

from worker_app.core.config import NbaApiSettings

log = logging.getLogger(__name__)

T = TypeVar("T")

# NBA PBP v3 `actionType` strings → our seed event_type strings.
# See: https://github.com/swar/nba_api — PlayByPlayV3
_ACTION_TYPE_MAP: dict[str, str] = {
    "Made Shot": "made_shot",
    "Missed Shot": "missed_shot",
    "Rebound": "rebound",
    "Turnover": "turnover",
    "Foul": "foul",
    "Free Throw": "free_throw",
    "Substitution": "substitution",
    "Timeout": "timeout",
    "Jump Ball": "jump_ball",
    "Period Begin": "period_start",
    "Period End": "period_end",
    "Violation": "violation",
    "Ejection": "ejection",
}

# PBP v3 `clock` is an ISO 8601 duration like "PT12M00.00S".
_ISO_DURATION_RE = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


class NbaApiDataSource:
    """Live data source backed by stats.nba.com via swar/nba_api.

    Satisfies the `NBADataSource` protocol structurally (does not
    inherit from it to avoid a circular import).

    Constructor does not perform any network I/O — it only loads the
    team-id ↔ trigraph mapping from `seed/teams.json`. Network calls
    happen on `list_seasons()`, `list_games(season)`, and
    `get_game(nba_game_id)`.
    """

    def __init__(self, settings: NbaApiSettings, seed_dir: Path) -> None:
        self._settings = settings
        self._seed_dir = seed_dir
        self._nba_id_to_trigraph, self._trigraph_to_nba_id = self._load_team_maps(seed_dir)
        self._knicks_nba_team_id = self._trigraph_to_nba_id.get("NYK")
        if self._knicks_nba_team_id is None:
            raise ValueError(
                f"Knicks ('NYK') not found in {seed_dir / 'teams.json'}; "
                "the live data source requires all 30 NBA teams to be seeded."
            )
        # Sliding-window timestamps (monotonic seconds) for rate limiting.
        self._call_timestamps: deque[float] = deque()

    @staticmethod
    def _load_team_maps(seed_dir: Path) -> tuple[dict[int, str], dict[str, int]]:
        with (seed_dir / "teams.json").open() as f:
            teams = json.load(f)
        id_to_trigraph: dict[int, str] = {}
        trigraph_to_id: dict[str, int] = {}
        for row in teams:
            nba_id = row.get("nba_team_id")
            tri = row.get("id")
            if nba_id is not None and tri:
                id_to_trigraph[int(nba_id)] = tri
                trigraph_to_id[tri] = int(nba_id)
        return id_to_trigraph, trigraph_to_id

    # -- NBADataSource protocol -------------------------------------------------

    def list_seasons(self) -> list[str]:
        return [s.strip() for s in self._settings.seasons.split(",") if s.strip()]

    def list_games(self, season: str, *, include_playoffs: bool = False) -> list[dict[str, Any]]:
        """Return seed-shaped game dicts for Knicks games in `season`.

        Each entry: `nba_game_id`, `season`, `game_date`, `home_team_id`
        (trigraph), `away_team_id` (trigraph), `home_score`, `away_score`,
        `status`.

        Combines the per-team double rows that `LeagueGameFinder`
        returns (one row for the home team, one for the away team) by
        assigning each row's PTS to the slot it represents (home or
        away) and merging per GAME_ID.
        """
        season_types = ["Regular Season"]
        if include_playoffs:
            season_types.extend(["PlayIn", "Playoffs"])

        frames = []
        for season_type in season_types:
            df = self._call_with_retry(
                lambda season_type=season_type: leaguegamefinder.LeagueGameFinder(
                    player_or_team_abbreviation="T",
                    team_id_nullable=str(self._knicks_nba_team_id or ""),
                    season_nullable=season,
                    season_type_nullable=season_type,
                    proxy=self._settings.proxy_url,
                    headers=self._build_headers(),
                    timeout=self._settings.timeout_seconds,
                ).league_game_finder_results.get_data_frame()
            )
            if not df.empty:
                df = df.copy()
                df["KNICKSIQ_SEASON_TYPE"] = season_type
                frames.append(df)

        if not frames:
            return []

        import pandas as pd

        df = pd.concat(frames, ignore_index=True)

        # Each game appears twice (one row per team). Parse the
        # matchup to determine the home/away slot, then assign this
        # row's PTS to the matching score. Merge at the end.
        partials: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            game_id = str(row.get("GAME_ID") or "").strip()
            if not game_id:
                continue
            matchup = str(row.get("MATCHUP") or "")
            team_abbrev = str(row.get("TEAM_ABBREVIATION") or "").strip()
            pts = int(row.get("PTS") or 0)
            try:
                plus_minus = int(row.get("PLUS_MINUS") or 0)
            except (TypeError, ValueError):
                plus_minus = 0
            if " vs. " in matchup:
                home_abbrev, away_abbrev = [s.strip() for s in matchup.split(" vs. ")]
                row_slot = "home" if team_abbrev == home_abbrev else "away"
            elif " @ " in matchup:
                away_abbrev, home_abbrev = [s.strip() for s in matchup.split(" @ ")]
                row_slot = "home" if team_abbrev == home_abbrev else "away"
            else:
                continue  # unknown matchup format; skip

            game_date_str = str(row.get("GAME_DATE") or "").strip()
            try:
                game_date = self._parse_nba_game_date(game_date_str)
            except ValueError:
                log.warning("Could not parse game_date %r for %s; skipping", game_date_str, game_id)
                continue

            entry = partials.setdefault(
                game_id,
                {
                    "nba_game_id": game_id,
                    "season": season,
                    "game_date": game_date,
                    "home_team_id": home_abbrev,
                    "away_team_id": away_abbrev,
                    "home_score": 0,
                    "away_score": 0,
                    "status": "final",
                    "season_type": self._normalize_season_type(
                        str(row.get("KNICKSIQ_SEASON_TYPE") or "")
                    ),
                },
            )
            entry[f"{row_slot}_score"] = pts  # type: ignore[literal-required]
            if plus_minus != 0:
                opponent_slot = "away" if row_slot == "home" else "home"
                entry[f"{opponent_slot}_score"] = pts - plus_minus  # type: ignore[literal-required]

        return list(partials.values())

    def get_game(self, nba_game_id: str) -> dict[str, Any] | None:
        """Return play-by-play, traditional box score, and period summary."""
        try:
            pbp_ds = self._call_with_retry(
                lambda: (
                    playbyplayv3.PlayByPlayV3(
                        game_id=nba_game_id,
                        end_period="14",
                        start_period="1",
                        proxy=self._settings.proxy_url,
                        headers=self._build_headers(),
                        timeout=self._settings.timeout_seconds,
                    ).play_by_play
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("playbyplayv3 fetch failed for %s: %s", nba_game_id, exc)
            return None

        # nba_api flattens the v3 JSON into a tabular (headers, rows) form.
        # Reconstruct each row as a dict keyed by the column name.
        headers: list[str] = list(pbp_ds.data.get("headers") or [])
        rows: list[list[Any]] = list(pbp_ds.data.get("data") or [])
        events: list[dict[str, Any]] = []
        for row in rows:
            action = dict(zip(headers, row, strict=True))
            parsed = self._parse_pbp_v3_action(action)
            if parsed is not None:
                events.append(parsed)

        return {
            "nba_game_id": nba_game_id,
            "events": events,
        }

    def get_game_release(self, nba_game_id: str) -> dict[str, Any] | None:
        """Fetch all immutable release inputs for a game in one offline operation."""
        game = self.get_game(nba_game_id)
        if game is None:
            return None
        return {**game, **self.get_game_box_score(nba_game_id)}

    def get_game_box_score(self, nba_game_id: str) -> dict[str, Any]:
        """Fetch box-score and period data without re-downloading play-by-play."""
        traditional = self._call_with_retry(
            lambda: boxscoretraditionalv3.BoxScoreTraditionalV3(
                game_id=nba_game_id,
                proxy=self._settings.proxy_url,
                headers=self._build_headers(),
                timeout=self._settings.timeout_seconds,
            )
        )
        summary = self._call_with_retry(
            lambda: boxscoresummaryv3.BoxScoreSummaryV3(
                game_id=nba_game_id,
                proxy=self._settings.proxy_url,
                headers=self._build_headers(),
                timeout=self._settings.timeout_seconds,
            )
        )
        if traditional.player_stats is None or traditional.team_stats is None:
            raise ValueError(f"Traditional box score missing for {nba_game_id}")
        if summary.line_score is None:
            raise ValueError(f"Line score missing for {nba_game_id}")
        player_stats = traditional.player_stats.get_data_frame().to_dict(orient="records")
        team_stats = traditional.team_stats.get_data_frame().to_dict(orient="records")
        line_scores = summary.line_score.get_data_frame().to_dict(orient="records")

        return {
            "player_stats": player_stats,
            "team_stats": team_stats,
            "line_scores": line_scores,
        }

    # -- Player ingest helpers (used by seed_players_from_nba_api job) --------

    def list_active_players(self) -> list[dict[str, Any]]:
        """Return current-season players from `commonallplayers`."""
        df = self._call_with_retry(
            lambda: commonallplayers.CommonAllPlayers(
                is_only_current_season=1,
                proxy=self._settings.proxy_url,
                headers=self._build_headers(),
                timeout=self._settings.timeout_seconds,
            ).common_all_players.get_data_frame()
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def list_team_roster(self, team_trigraph: str, season: str) -> list[dict[str, Any]]:
        """Return a season roster for one team from `commonteamroster`."""
        team_id = self._trigraph_to_nba_id.get(team_trigraph)
        if team_id is None:
            raise ValueError(f"Unknown NBA team trigraph: {team_trigraph}")
        df = self._call_with_retry(
            lambda: commonteamroster.CommonTeamRoster(
                team_id=team_id,
                season=season,
                proxy=self._settings.proxy_url,
                headers=self._build_headers(),
                timeout=self._settings.timeout_seconds,
            ).common_team_roster.get_data_frame()
        )
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def get_player_info(self, nba_player_id: int) -> dict[str, Any] | None:
        """Return `commonplayerinfo` row for `nba_player_id`, or None."""
        try:
            df = self._call_with_retry(
                lambda: commonplayerinfo.CommonPlayerInfo(
                    player_id=nba_player_id,
                    proxy=self._settings.proxy_url,
                    headers=self._build_headers(),
                    timeout=self._settings.timeout_seconds,
                ).common_player_info.get_data_frame()
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("commonplayerinfo fetch failed for %d: %s", nba_player_id, exc)
            return None
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    # -- Internals -------------------------------------------------------------

    def _build_headers(self) -> dict[str, str] | None:
        """Return extra headers (e.g. User-Agent) for the nba_api call, or None."""
        user_agent = self._settings.user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Host": "stats.nba.com",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
            "User-Agent": user_agent,
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
        }

    def _call_with_retry(self, fn: Callable[[], T]) -> T:
        """Call `fn` with rate limiting and transient-error retry.

        Transient errors (5xx, 429, network errors) are retried with
        exponential backoff. Other exceptions are also retried because
        nba_api doesn't call `raise_for_status()` — a non-2xx response
        typically surfaces as a `ValueError` on JSON parsing, which we
        can't distinguish from a transient network glitch without
        peeking at the response object. The cost of over-retrying a
        bug is bounded by `retry_attempts` (default 3).
        """
        self._wait_for_rate_budget()

        attempts = max(1, self._settings.retry_attempts)
        backoff = max(0.0, self._settings.retry_backoff_seconds)
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            self._call_timestamps.append(time.monotonic())
            try:
                return fn()
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (429, 500, 502, 503, 504) and attempt < attempts:
                    last_exc = exc
                    self._sleep_backoff(backoff, attempt)
                    continue
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                if attempt < attempts:
                    self._sleep_backoff(backoff, attempt)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                # nba_api doesn't raise on non-2xx; non-JSON 4xx/5xx
                # bodies surface as ValueError. Treat as transient.
                last_exc = exc
                if attempt < attempts:
                    self._sleep_backoff(backoff, attempt)
                    continue
                raise

        # Shouldn't reach here, but be explicit.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("_call_with_retry exited without result or exception")

    def _wait_for_rate_budget(self) -> None:
        """Sleep just enough to keep under the configured per-minute budget."""
        rate = self._settings.rate_remaining_per_minutes
        if rate <= 0:
            return
        now = time.monotonic()
        # Drop entries older than 60s.
        while self._call_timestamps and (now - self._call_timestamps[0]) > 60.0:
            self._call_timestamps.popleft()
        if len(self._call_timestamps) >= rate:
            sleep_for = 60.0 - (now - self._call_timestamps[0]) + 0.05
            if sleep_for > 0:
                log.debug("Rate limit reached; sleeping %.2fs", sleep_for)
                time.sleep(sleep_for)

    @staticmethod
    def _sleep_backoff(base: float, attempt: int) -> None:
        delay = base * (2 ** (attempt - 1))
        log.debug("Retry attempt %d failed; sleeping %.2fs", attempt, delay)
        time.sleep(delay)

    @staticmethod
    def _parse_nba_game_date(value: str) -> date:
        """Parse NBA's `GAME_DATE` strings.

        `LeagueGameFinder` has returned both ISO dates (`2026-04-12`)
        and legacy display dates (`OCT 22, 2024`) depending on endpoint
        version / nba_api release.
        """
        from datetime import datetime

        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.strptime(value, "%b %d, %Y").date()

    @staticmethod
    def _normalize_season_type(value: str) -> str:
        normalized = value.strip().lower().replace(" ", "_")
        if normalized == "playin":
            return "play_in"
        if normalized == "playoffs":
            return "playoffs"
        return "regular"

    @staticmethod
    def _iso_duration_to_clock(value: str) -> str:
        """Convert ISO 8601 duration ('PT12M00.00S') to 'MM:SS'."""
        if not value:
            return "12:00"
        match = _ISO_DURATION_RE.match(value)
        if not match:
            return value  # pass through; parser tolerates non-standard clocks
        minutes = int(match.group(1) or 0)
        seconds = float(match.group(2) or 0)
        return f"{minutes:02d}:{int(seconds):02d}"

    def _parse_pbp_v3_action(self, action: Any) -> dict[str, Any] | None:
        """Translate one nba_api v3 action row into a seed-shaped event dict.

        The dict shape matches the `events` array in `seed/games.json`:
        `period`, `clock`, `event_type`, `description`, `team_id` (trigraph),
        `player_id` (nba_player_id int, remapped by the job), `home_score`,
        `away_score`, optional `shot_distance_ft`.
        """
        if not isinstance(action, dict):
            return None

        action_type = str(action.get("actionType") or "").strip()
        event_type = _ACTION_TYPE_MAP.get(action_type)
        if event_type is None:
            return None  # unknown action type — skip rather than fabricate

        team_tricode = action.get("teamTricode")
        team_id = str(team_tricode).strip().upper() or None
        if team_id and team_id not in self._trigraph_to_nba_id:
            team_id = None  # unknown team trigraph (e.g. from ASG); drop attribution

        person_id = action.get("personId")
        player_id = int(person_id) if person_id else None

        try:
            home_score = int(action.get("scoreHome") or 0)
        except (TypeError, ValueError):
            home_score = 0
        try:
            away_score = int(action.get("scoreAway") or 0)
        except (TypeError, ValueError):
            away_score = 0

        event: dict[str, Any] = {
            "period": int(action.get("period") or 1),
            "clock": self._iso_duration_to_clock(str(action.get("clock") or "")),
            "event_type": event_type,
            "description": str(action.get("description") or ""),
            "team_id": team_id,
            "player_id": player_id,
            "player_name": str(action.get("playerName") or "").strip() or None,
            "home_score": home_score,
            "away_score": away_score,
        }

        # Optional: shot_distance_ft (only meaningful for shot events).
        shot_distance = action.get("shotDistance")
        if event_type in ("made_shot", "missed_shot", "free_throw") and shot_distance:
            try:
                event["shot_distance_ft"] = int(shot_distance)
            except (TypeError, ValueError):
                pass

        return event
