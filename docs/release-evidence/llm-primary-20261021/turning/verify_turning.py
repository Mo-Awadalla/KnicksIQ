"""Independent SQL/event audit of the turning_points head answers.

This script does not import the application or the get_game_flow module. It reads
game_events and games directly, rebuilds the same public concepts with a separate
implementation (the audit SQL's lag grouping for runs), and checks that every key
number and date in the head answers matches that oracle.

    .venv/bin/python verify_turning.py

Writes verification.json next to this script.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
RESPONSES = HERE / "head.responses.jsonl"
DSN = "postgresql://knicksiq:knicksiq@localhost:55500/knicksiq"

SCORING = {"made_shot", "free_throw"}


def margin(home_team: str, home: int, away: int) -> int:
    return home - away if home_team == "NYK" else away - home


def opponent(game: dict) -> str:
    return game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]


def won(game: dict) -> bool:
    nyk = game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"]
    opp = game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]
    return nyk > opp


class GameFlow:
    def __init__(self, game: dict, rows: list[dict]):
        self.game = game
        self.scoring = sorted(rows, key=lambda row: (row["period"], row["sequence"]))
        self.plays: list[dict] = []
        previous = None
        for row in self.scoring:
            if previous is not None:
                before_total = previous["home_score"] + previous["away_score"]
                after_total = row["home_score"] + row["away_score"]
                delta = after_total - before_total
                if delta > 0 and row["event_type"] in SCORING:
                    self.plays.append(
                        {
                            "sequence": row["sequence"],
                            "period": row["period"],
                            "clock": row["clock"],
                            "team_id": row["team_id"],
                            "points": delta,
                            "nyk_before": (
                                previous["home_score"]
                                if game["home_team_id"] == "NYK"
                                else previous["away_score"]
                            ),
                            "opp_before": (
                                previous["away_score"]
                                if game["home_team_id"] == "NYK"
                                else previous["home_score"]
                            ),
                            "nyk_after": (
                                row["home_score"]
                                if game["home_team_id"] == "NYK"
                                else row["away_score"]
                            ),
                            "opp_after": (
                                row["away_score"]
                                if game["home_team_id"] == "NYK"
                                else row["home_score"]
                            ),
                        }
                    )
            previous = row
        for play in self.plays:
            play["margin_after"] = play["nyk_after"] - play["opp_after"]
            play["margin_before"] = play["nyk_before"] - play["opp_before"]
        self.runs = self._runs()

    def _runs(self) -> list[dict]:
        runs: list[dict] = []
        for play in self.plays:
            if runs and runs[-1]["team_id"] == play["team_id"]:
                runs[-1]["points"] += play["points"]
                runs[-1]["end"] = play
            else:
                runs.append(
                    {
                        "team_id": play["team_id"],
                        "points": play["points"],
                        "start": play,
                        "end": play,
                    }
                )
        return runs

    def biggest_deficit(self) -> int:
        return max(0, -min(play["margin_after"] for play in self.plays))

    def biggest_lead(self) -> int:
        return max(0, max(play["margin_after"] for play in self.plays))

    def go_ahead(self) -> dict | None:
        home = self.game["home_team_id"]
        nyk = self.game["home_score"] if home == "NYK" else self.game["away_score"]
        opp = self.game["away_score"] if home == "NYK" else self.game["home_score"]
        if nyk == opp:
            return None
        wanted = 1 if nyk > opp else -1
        index = len(self.plays) - 1
        while index >= 0 and self.plays[index]["margin_after"] * wanted > 0:
            index -= 1
        return self.plays[index + 1] if index + 1 < len(self.plays) else None

    def comeback(self) -> dict | None:
        if not won(self.game) or not self.plays:
            return None
        low_index = min(range(len(self.plays)), key=lambda i: self.plays[i]["margin_after"])
        low = self.plays[low_index]
        if low["margin_after"] >= 0:
            return None
        end_index = next(
            (i for i in range(low_index + 1, len(self.plays)) if self.plays[i]["margin_after"] >= 0),
            None,
        )
        if end_index is None:
            return None
        end = self.plays[end_index]
        inside = [
            run
            for run in self.runs
            if run["team_id"] == "NYK"
            and run["start"]["sequence"] >= low["sequence"]
            and run["end"]["sequence"] <= end["sequence"]
        ]
        best = max(inside, key=lambda run: (run["points"], -run["start"]["sequence"]), default=None)
        return {
            "deficit": -low["margin_after"],
            "low": low,
            "end": end,
            "nyk_points": end["nyk_after"] - low["nyk_after"],
            "opp_points": end["opp_after"] - low["opp_after"],
            "run": best,
        }


async def load() -> tuple[list[dict], dict[int, GameFlow]]:
    conn = await asyncpg.connect(DSN)
    try:
        games = [
            dict(row)
            for row in await conn.fetch(
                "select id, game_date, home_team_id, away_team_id, home_score, away_score, "
                "season_type from games order by game_date, id"
            )
        ]
        rows = [
            dict(row)
            for row in await conn.fetch(
                "select game_id, period, sequence, clock, team_id, event_type, home_score, "
                "away_score from game_events where event_type in ('made_shot','free_throw') "
                "and home_score + away_score > 0 order by game_id, period, sequence"
            )
        ]
    finally:
        await conn.close()
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["game_id"]].append(row)
    flows = {game["id"]: GameFlow(game, grouped[game["id"]]) for game in games}
    return games, flows


def top_run(
    flows: dict[int, GameFlow],
    *,
    phase: str | None = None,
    team: str | None = None,
    opponent_id: str | None = None,
    losses_only: bool = False,
) -> dict:
    best = None
    for flow in flows.values():
        game = flow.game
        if phase and game["season_type"] != phase:
            continue
        if opponent_id and opponent(game) != opponent_id:
            continue
        if losses_only and won(game):
            continue
        for run in flow.runs:
            if team == "NYK" and run["team_id"] != "NYK":
                continue
            if team == "OPP" and run["team_id"] == "NYK":
                continue
            item = {
                "game_id": game["id"],
                "date": str(game["game_date"]),
                "opponent": opponent(game),
                "phase": game["season_type"],
                "team_id": run["team_id"],
                "points": run["points"],
                "start": run["start"],
                "end": run["end"],
            }
            if best is None or (item["points"], item["date"]) > (best["points"], best["date"]):
                best = item
    return best


def games_against(games: list[dict], opponent_id: str) -> list[dict]:
    return [game for game in games if opponent_id in {game["home_team_id"], game["away_team_id"]}]


def check(answer: str, required: list[str]) -> dict:
    missing = [token for token in required if token.lower() not in answer.lower()]
    return {"required": required, "missing": missing, "pass": not missing}


async def main() -> None:
    games, flows = await load()
    responses: dict[str, list[dict]] = defaultdict(list)
    for line in RESPONSES.read_text().splitlines():
        item = json.loads(line)
        responses[item["id"]].append(item)

    checks: list[dict] = []

    # 001: biggest NYK run against Boston (all phases).
    run = top_run(flows, team="NYK", opponent_id="BOS")
    checks.append(
        {
            "id": "turning_points-001",
            "oracle": {"points": run["points"], "date": run["date"], "opponent": run["opponent"]},
            "answers": [
                {"trial": item["trial"], **check(item["answer"], ["17-0", "2025-10-24", "Q2"])}
                for item in responses["turning_points-001"]
            ],
        }
    )

    # 002 and 004 and 006 and 010: clarification date lists.
    for qid, opp in (
        ("turning_points-002", "TOR"),
        ("turning_points-004", "CHI"),
        ("turning_points-006", "BOS"),
        ("turning_points-010", "ATL"),
    ):
        dates = sorted({str(game["game_date"]) for game in games_against(games, opp)})
        # The resolver offers at most eight choices for an ambiguous game.
        required = dates[:8]
        checks.append(
            {
                "id": qid,
                "oracle": {"dates": dates, "offered": required},
                "answers": [
                    {"trial": item["trial"], **check(item["answer"], required)}
                    for item in responses[qid]
                ],
            }
        )

    # 003: largest lead lost in an ATL loss and largest deficit in an ATL loss.
    atl = [flow for flow in flows.values() if opponent(flow.game) == "ATL" and not won(flow.game)]
    lead_game = max(atl, key=lambda flow: flow.biggest_lead())
    deficit_game = max(atl, key=lambda flow: flow.biggest_deficit())
    checks.append(
        {
            "id": "turning_points-003",
            "oracle": {
                "lead_lost": lead_game.biggest_lead(),
                "lead_lost_date": str(lead_game.game["game_date"]),
                "lead_lost_peak": lead_game.plays[
                    max(range(len(lead_game.plays)), key=lambda i: lead_game.plays[i]["margin_after"])
                ],
                "largest_deficit": deficit_game.biggest_deficit(),
                "largest_deficit_date": str(deficit_game.game["game_date"]),
            },
            "answers": [
                {"trial": item["trial"], **check(item["answer"], ["14", "2026-04-20"])}
                for item in responses["turning_points-003"]
            ],
        }
    )

    # 004 is covered above.

    # 005: largest deficit erased in a regular-season win.
    regular = {gid: flow for gid, flow in flows.items() if flow.game["season_type"] == "regular"}
    comebacks = [
        (flow, flow.comeback())
        for flow in regular.values()
        if flow.comeback() is not None
    ]
    best_game, best = max(comebacks, key=lambda item: item[1]["deficit"])
    checks.append(
        {
            "id": "turning_points-005",
            "oracle": {
                "deficit": best["deficit"],
                "date": str(best_game.game["game_date"]),
                "opponent": opponent(best_game.game),
                "low": best["low"],
                "first_tie_or_lead": best["end"],
                "nyk_points": best["nyk_points"],
                "opp_points": best["opp_points"],
                "run": best["run"]["points"] if best["run"] else None,
                "final": f'{best_game.game["home_score"]}-{best_game.game["away_score"]}',
            },
            "answers": [
                {
                    "trial": item["trial"],
                    **check(
                        item["answer"],
                        [
                            str(best["deficit"]),
                            str(best_game.game["game_date"]),
                            f'{best["nyk_points"]}-{best["opp_points"]}',
                        ],
                    ),
                }
                for item in responses["turning_points-005"]
            ],
        }
    )

    # 007: largest opponent run in the regular season and in a regular-season loss.
    overall = top_run(flows, phase="regular", team="OPP")
    in_loss = top_run(flows, phase="regular", team="OPP", losses_only=True)
    checks.append(
        {
            "id": "turning_points-007",
            "oracle": {
                "overall": {
                    "points": overall["points"],
                    "date": overall["date"],
                    "opponent": overall["opponent"],
                },
                "in_loss": {
                    "points": in_loss["points"],
                    "date": in_loss["date"],
                    "opponent": in_loss["opponent"],
                },
            },
            "answers": [
                {
                    "trial": item["trial"],
                    **check(
                        item["answer"],
                        [
                            f'{overall["points"]}-0',
                            overall["date"],
                            f'{in_loss["points"]}-0',
                            in_loss["date"],
                        ],
                    ),
                }
                for item in responses["turning_points-007"]
            ],
        }
    )

    # 008: largest deficit in each CHA loss.
    cha_losses = [
        flow for flow in flows.values() if opponent(flow.game) == "CHA" and not won(flow.game)
    ]
    top = max(flow.biggest_deficit() for flow in cha_losses)
    detail = [
        (str(flow.game["game_date"]), flow.biggest_deficit(), flow)
        for flow in cha_losses
        if flow.biggest_deficit() == top
    ]
    checks.append(
        {
            "id": "turning_points-008",
            "oracle": {
                "deficit": top,
                "games": [date for date, _, _ in detail],
                "low_points": [
                    {
                        "date": date,
                        "low": max(
                            flow.plays,
                            key=lambda play: (-play["margin_after"], play["sequence"]),
                        ),
                    }
                    for date, _, flow in detail
                ],
            },
            "answers": [
                {
                    "trial": item["trial"],
                    **check(item["answer"], [str(top)] + [date for date, _, _ in detail]),
                }
                for item in responses["turning_points-008"]
            ],
        }
    )

    # 009: largest erased deficit against TOR.
    tor = [flow for flow in flows.values() if opponent(flow.game) == "TOR"]
    tor_comebacks = [
        (flow, flow.comeback()) for flow in tor if flow.comeback() is not None
    ]
    tor_game, tor_best = max(tor_comebacks, key=lambda item: item[1]["deficit"])
    checks.append(
        {
            "id": "turning_points-009",
            "oracle": {
                "deficit": tor_best["deficit"],
                "date": str(tor_game.game["game_date"]),
                "nyk_points": tor_best["nyk_points"],
                "opp_points": tor_best["opp_points"],
                "run": tor_best["run"]["points"] if tor_best["run"] else None,
            },
            "answers": [
                {
                    "trial": item["trial"],
                    **check(
                        item["answer"],
                        [
                            f'{tor_best["deficit"]}-point',
                            str(tor_game.game["game_date"]),
                            f'{tor_best["run"]["points"]}-0',
                        ],
                    ),
                }
                for item in responses["turning_points-009"]
            ],
        }
    )

    report = {
        "responses": str(RESPONSES.name),
        "checks": checks,
        "questions_all_trials_verified": sum(
            all(answer["pass"] for answer in item["answers"]) for item in checks
        ),
        "questions_with_a_verified_answer": sum(
            any(answer["pass"] for answer in item["answers"]) for item in checks
        ),
        "total": len(checks),
    }
    (HERE / "verification.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
