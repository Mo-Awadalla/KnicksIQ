"Canonical archive row selection and stable evidence identities for label review."

from __future__ import annotations

import hashlib
import json

ALL_STAR_END = "2026-02-15"


ALL_STAR_SOURCE = "https://www.nba.com/allstar/2026/"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Canonical:
    def __init__(self, payload):
        self.data = payload["data"]
        self.games = sorted(self.data["games"], key=lambda g: (g["game_date"], g["nba_game_id"]))
        self.by_id = {g["nba_game_id"]: g for g in self.games}
        self.names = {p["nba_player_id"]: p["full_name"] for p in self.data["players"]}
        self.conferences = {t["id"]: t["conference"] for t in self.data["teams"]}

    def own(self, game):
        return game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"]

    def allowed(self, game):
        return game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]

    def opponent(self, game):
        return game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]

    def games_against(self, team):
        return [g for g in self.games if self.opponent(g) == team]

    def month(self, number):
        return [g for g in self.games if int(g["game_date"][5:7]) == number]

    def margin(self, game):
        return self.own(game) - self.allowed(game)

    def record(self, games):
        wins = sum(self.margin(g) > 0 for g in games)
        return {"games": len(games), "wins": wins, "losses": len(games) - wins}

    def player(self, name, games=None, last=None):
        ids = {g["nba_game_id"] for g in (self.games if games is None else games)}
        rows = [
            r
            for r in self.data["player_game_stats"]
            if r["nba_game_id"] in ids
            and r["team_id"] == "NYK"
            and name.lower() in self.names[r["nba_player_id"]].lower()
            and float(r.get("minutes") or 0) > 0
        ]
        rows.sort(key=lambda r: (self.by_id[r["nba_game_id"]]["game_date"], r["nba_game_id"]))
        return rows[-last:] if last else rows

    def evidence(self, rows, collection):
        keys = {
            "games": "game",
            "player_game_stats": "box",
            "team_game_stats": "team_box",
            "period_scores": "period",
        }
        out = []
        for r in rows:
            suffix = ""
            if collection == "player_game_stats":
                suffix = f":{r['nba_player_id']}"
            elif collection == "team_game_stats":
                suffix = f":{r['team_id']}"
            elif collection == "period_scores":
                suffix = f":{r['team_id']}:{r['period']}"
            out.append(
                {
                    "canonical_id": f"{keys[collection]}:{r['nba_game_id']}{suffix}",
                    "collection": collection,
                    "row_sha256": digest(r),
                }
            )
        return out

    def extreme(self, key, maximum=True):
        value = (max if maximum else min)(key(g) for g in self.games)
        return [g for g in self.games if key(g) == value]
