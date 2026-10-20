"""Knicks-view analytics over the reviewed release bundle, shared by `compute_launch_set.py`.

Every number in the evaluation drafts and the launch set comes from these functions. Scoreboard
state follows `app.services.event_scores.cumulative_score`: a 0-0 pair on an event carries the
previous score.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

BUNDLE = Path(
    "/Users/mohamedawadalla/Projects/KnicksIQ/release-artifacts/2025-26/"
    "reliability-approved-20260928.json.gz"
)
BUNDLE_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
TEAM = "NYK"


@dataclass
class Game:
    row: dict
    opponent: str
    nyk: int
    opp: int
    states: list[tuple[int, int]] = field(default_factory=list)  # (sequence, NYK margin)
    runs: list[tuple[str, int, int, int]] = field(default_factory=list)  # team, pts, start, end
    # False when the source scoreboard decreases or both sides move at once. The app's run and
    # narrative tools refuse such games ("incomplete_coverage"), so the drafts exclude them too.
    scoreboard_ok: bool = True

    @property
    def id(self) -> str:
        return self.row["nba_game_id"]

    @property
    def ref(self) -> str:
        return f"game:{self.id}"

    @property
    def date(self) -> str:
        return self.row["game_date"]

    @property
    def won(self) -> bool:
        return self.nyk > self.opp

    @property
    def label(self) -> str:
        venue = "vs" if self.row["home_team_id"] == TEAM else "at"
        kind = " (playoffs)" if self.row["season_type"] == "playoffs" else ""
        result = "W" if self.won else "L"
        return f"{self.date} {venue} {self.opponent}{kind}, {result} {self.nyk}-{self.opp}"

    def max_lead_lost(self) -> int:
        """Largest NYK lead after which the opponent later led (a lead change against NYK)."""
        best = 0
        for index, (_, margin) in enumerate(self.states):
            if margin > best and any(m < 0 for _, m in self.states[index + 1 :]):
                best = margin
        return best

    def max_deficit_erased(self) -> int:
        """Largest NYK deficit after which the game was later tied or NYK led."""
        best = 0
        for index, (_, margin) in enumerate(self.states):
            if -margin > best and any(m >= 0 for _, m in self.states[index + 1 :]):
                best = -margin
        return best

    def ever_led(self) -> bool:
        return any(m > 0 for _, m in self.states)

    def came_back(self) -> bool:
        """NYK trailed and later led."""
        return self.max_deficit_led() > 0

    def max_deficit_led(self) -> int:
        best = 0
        for index, (_, margin) in enumerate(self.states):
            if -margin > best and any(m > 0 for _, m in self.states[index + 1 :]):
                best = -margin
        return best

    def max_run(self, team: str) -> tuple[int, int, int]:
        """Largest unanswered run for `team` ("NYK" or "OPP"): points, start and end sequence."""
        return max(((p, s, e) for t, p, s, e in self.runs if t == team), default=(0, 0, 0))


class Bundle:
    def __init__(self, path: Path = BUNDLE) -> None:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != BUNDLE_SHA256:
            raise SystemExit(f"bundle sha256 {digest} != {BUNDLE_SHA256}")
        self.data = json.loads(gzip.decompress(raw))["data"]
        self.players = {p["nba_player_id"]: p["full_name"] for p in self.data["players"]}
        self.box: dict[str, list[dict]] = defaultdict(list)
        for row in self.data["player_game_stats"]:
            self.box[row["nba_game_id"]].append(row)
        self.periods = {
            (r["nba_game_id"], r["team_id"], r["period"]): r["points"]
            for r in self.data["period_scores"]
        }
        events: dict[str, list[dict]] = defaultdict(list)
        for event in self.data["events"]:
            events[event["nba_game_id"]].append(event)
        self.games: list[Game] = []
        for row in sorted(self.data["games"], key=lambda g: (g["game_date"], g["nba_game_id"])):
            home = row["home_team_id"] == TEAM
            game = Game(
                row=row,
                opponent=row["away_team_id"] if home else row["home_team_id"],
                nyk=row["home_score"] if home else row["away_score"],
                opp=row["away_score"] if home else row["home_score"],
            )
            self._scoreboard(game, sorted(events[game.id], key=lambda e: e["sequence"]), home)
            self.games.append(game)
        self.by_id = {g.id: g for g in self.games}

    @staticmethod
    def _scoreboard(game: Game, events: list[dict], home: bool) -> None:
        previous = (0, 0)
        run: list = []
        for event in events:
            current = (event["home_score"], event["away_score"])
            if current == (0, 0):
                current = previous
            change = (current[0] - previous[0], current[1] - previous[1])
            if min(change) < 0 or min(change) > 0:
                game.scoreboard_ok = False
                break
            if change != (0, 0):
                team = "NYK" if (change[0] > 0) == home else "OPP"
                points = max(change)
                if run and run[0] == team:
                    run[1] += points
                    run[3] = event["sequence"]
                else:
                    if run:
                        game.runs.append(tuple(run))
                    run = [team, points, event["sequence"], event["sequence"]]
                margin = current[0] - current[1]
                game.states.append((event["sequence"], margin if home else -margin))
            previous = current
        if run:
            game.runs.append(tuple(run))
        if previous != (game.row["home_score"], game.row["away_score"]):
            game.scoreboard_ok = False
        if not game.scoreboard_ok:
            game.states.clear()
            game.runs.clear()

    def verified(self) -> list[Game]:
        return [g for g in self.games if g.scoreboard_ok]

    def vs(self, opponent: str) -> list[Game]:
        return [g for g in self.games if g.opponent == opponent]

    def player_id(self, name: str) -> int:
        return next(i for i, n in self.players.items() if n == name)

    def player_rows(self, player: int, games: list[Game] | None = None) -> list[dict]:
        """Box rows where the player appeared (minutes > 0), in game order."""
        pool = games if games is not None else self.games
        return [
            r
            for g in pool
            for r in self.box[g.id]
            if r["nba_player_id"] == player and (r["minutes"] or 0) > 0
        ]

    def nyk_rows(self, game: Game) -> list[dict]:
        return [r for r in self.box[game.id] if r["team_id"] == TEAM]


def box_ref(row: dict) -> str:
    return f"box:{row['nba_game_id']}:{row['nba_player_id']}"


def event_ref(game: Game, sequence: int) -> str:
    return f"event:{game.id}:{sequence}"
