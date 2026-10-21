#!/usr/bin/env python3
"""Independent audit of get_team_splits answers.

The oracle is raw SQL over the local restored release, executed with psql. No
application calculation code is imported. For every cited claim the script rebuilds
the bucket from the raw game rows, compares every number and the game-id set, and
records the verdict. Run from the repo root:

    python3 docs/release-evidence/llm-primary-20261021/splits/audit_splits.py \
        docs/release-evidence/llm-primary-20261021/splits/head2.responses.jsonl
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = os.environ.get(
    "KIQ_PSQL", "docker exec kiq-integrate-postgres-1 psql -U knicksiq -d knicksiq"
)
RELEASE = os.environ.get("KIQ_RELEASE", "2025-26.20260928.1")
TOLERANCE = Decimal("0.011")


def sql_rows(query: str) -> list[dict[str, str]]:
    command = PSQL.split() + ["-At", "-F", "\t", "-c", query]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    rows = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        values = line.split("\t")
        rows.append(dict(zip(HEADER, values, strict=False)))
    return rows


HEADER: list[str] = []


def load_archive() -> tuple[list[dict[str, Any]], dict[str, str]]:
    global HEADER
    HEADER = [
        "id",
        "game_date",
        "season_type",
        "home_team_id",
        "away_team_id",
        "home_score",
        "away_score",
        "status",
    ]
    raw_games = sql_rows(
        "select id, game_date, season_type, home_team_id, away_team_id, home_score, "
        "away_score, status from games where release_id=("
        f"select id from dataset_releases where version='{RELEASE}') "
        "order by game_date, id"
    )
    games = [
        {
            "id": int(row["id"]),
            "game_date": date.fromisoformat(row["game_date"]),
            "season_type": row["season_type"],
            "home": row["home_team_id"],
            "away": row["away_team_id"],
            "home_score": int(row["home_score"]),
            "away_score": int(row["away_score"]),
            "status": row["status"],
        }
        for row in raw_games
    ]
    HEADER = ["id", "conference"]
    raw_teams = sql_rows("select id, conference from teams order by id")
    teams = {row["id"]: row["conference"] for row in raw_teams}
    return games, teams


def nyk_points(game: dict[str, Any]) -> tuple[int, int]:
    if game["home"] == "NYK":
        return game["home_score"], game["away_score"]
    return game["away_score"], game["home_score"]


def opponent(game: dict[str, Any]) -> str:
    return game["away"] if game["home"] == "NYK" else game["home"]


def decided(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        game
        for game in games
        if game["status"] == "final" and game["home_score"] != game["away_score"]
    ]


def stats(games: list[dict[str, Any]]) -> dict[str, Any]:
    games = decided(games)
    count = len(games)
    if count == 0:
        return {"games": 0}
    points_for = sum(nyk_points(game)[0] for game in games)
    points_against = sum(nyk_points(game)[1] for game in games)
    wins = sum(nyk_points(game)[0] > nyk_points(game)[1] for game in games)
    return {
        "games": count,
        "wins": wins,
        "losses": count - wins,
        "points_for_per_game": round(points_for / count, 2),
        "points_against_per_game": round(points_against / count, 2),
        "margin_per_game": round((points_for - points_against) / count, 2),
        "points": points_for,
        "margin": points_for - points_against,
        "game_ids": sorted(game["id"] for game in games),
    }


def regular(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game["season_type"] == "regular"]


def phase(games: list[dict[str, Any]], value: str) -> list[dict[str, Any]]:
    if value == "all":
        return games
    return [game for game in games if game["season_type"] == value]


def home(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game["home"] == "NYK"]


def away(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game["away"] == "NYK"]


def versus(games: list[dict[str, Any]], team: str) -> list[dict[str, Any]]:
    return [game for game in games if opponent(game) == team]


def month(games: list[dict[str, Any]], year: int, number: int) -> list[dict[str, Any]]:
    return [
        game
        for game in games
        if game["game_date"].year == year and game["game_date"].month == number
    ]


def by_margin(games: list[dict[str, Any]], low: int, high: int | None) -> list[dict[str, Any]]:
    result = []
    for game in games:
        margin = abs(game["home_score"] - game["away_score"])
        if margin >= low and (high is None or margin <= high):
            result.append(game)
    return result


def back_to_back_seconds(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dates = {game["game_date"] for game in games}
    return [
        game
        for game in games
        if (game["game_date"].toordinal() - 1) in {day.toordinal() for day in dates}
    ]


def all_star_break(games: list[dict[str, Any]]) -> tuple[date, date] | None:
    regular_dates = sorted({game["game_date"] for game in regular(games)})
    if not regular_dates:
        return None
    year = regular_dates[-1].year
    window = [day for day in regular_dates if day.year == year and 1 <= day.month <= 3]
    gaps = [
        ((after - before).days, before, after)
        for before, after in zip(window, window[1:], strict=False)
    ]
    if not gaps:
        return None
    gap, before, after = max(gaps)
    return (before, after) if gap >= 5 else None


def after_break(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    break_dates = all_star_break(games)
    if break_dates is None:
        return []
    return [game for game in regular(games) if game["game_date"] >= break_dates[1]]


def before_break(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    break_dates = all_star_break(games)
    if break_dates is None:
        return []
    return [game for game in regular(games) if game["game_date"] <= break_dates[0]]


def first_n(games: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return sorted(regular(games), key=lambda game: (game["game_date"], game["id"]))[:count]


def last_n(games: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return sorted(regular(games), key=lambda game: (game["game_date"], game["id"]))[-count:]


def conference(
    games: list[dict[str, Any]], teams: dict[str, str], value: str
) -> list[dict[str, Any]]:
    return [game for game in games if teams.get(opponent(game)) == value]


def overtime(games: list[dict[str, Any]], overtime_ids: set[int]) -> list[dict[str, Any]]:
    return [game for game in games if game["id"] in overtime_ids]


def load_overtime_ids(games: list[dict[str, Any]]) -> set[int]:
    global HEADER
    HEADER = ["game_id"]
    ids = [game["id"] for game in games]
    rows = sql_rows(
        "select distinct game_id from period_scores where release_id=("
        f"select id from dataset_releases where version='{RELEASE}') "
        f"and period > 4 and game_id in ({','.join(str(item) for item in ids)})"
    )
    return {int(row["game_id"]) for row in rows}


EXPECTED: dict[
    str, dict[str, Callable[[list[dict[str, Any]], dict[str, str]], list[dict[str, Any]]]]
] = {
    "comparisons-001": {
        "team_splits:home": lambda games, teams: home(regular(games)),
        "team_splits:away": lambda games, teams: away(regular(games)),
    },
    "comparisons-003": {
        "team_splits:opponent:BOS:all": lambda games, teams: versus(games, "BOS"),
        "team_splits:opponent:BOS:regular": lambda games, teams: versus(regular(games), "BOS"),
        "team_splits:opponent:BOS:playoffs": lambda games, teams: versus(
            phase(games, "playoffs"), "BOS"
        ),
        "team_splits:opponent:TOR:all": lambda games, teams: versus(games, "TOR"),
        "team_splits:opponent:TOR:regular": lambda games, teams: versus(regular(games), "TOR"),
        "team_splits:opponent:TOR:playoffs": lambda games, teams: versus(
            phase(games, "playoffs"), "TOR"
        ),
    },
    "comparisons-004": {
        "team_splits:window:first:10": lambda games, teams: first_n(games, 10),
        "team_splits:window:last:10": lambda games, teams: last_n(games, 10),
    },
    "comparisons-012": {"team_splits:scope": lambda games, teams: regular(games)},
    "comparisons-013": {
        "team_splits:close": lambda games, teams: by_margin(regular(games), 0, 5),
        "team_splits:middle": lambda games, teams: by_margin(regular(games), 6, 9),
        "team_splits:blowout": lambda games, teams: by_margin(regular(games), 10, None),
    },
    "comparisons-014": {
        "team_splits:conference:East": lambda games, teams: conference(
            regular(games), teams, "East"
        ),
        "team_splits:conference:West": lambda games, teams: conference(
            regular(games), teams, "West"
        ),
    },
    "date_range_last_n-004": {
        "team_splits:scope": lambda games, teams: [
            game
            for game in regular(games)
            if date(2026, 1, 1) <= game["game_date"] <= date(2026, 1, 31)
        ]
    },
    "date_range_last_n-005": {
        "team_splits:after_break": lambda games, teams: after_break(games),
    },
    "date_range_last_n-006": {
        "team_splits:scope": lambda games, teams: [
            game
            for game in away(regular(games))
            if game["game_date"].year == 2025 and game["game_date"].month == 12
        ]
    },
    "date_range_last_n-010": {
        "team_splits:window:first:10": lambda games, teams: first_n(games, 10),
    },
    "date_range_last_n-013": {
        "team_splits:window:last:15": lambda games, teams: last_n(games, 15),
    },
    "date_range_last_n-014": {
        "team_splits:back_to_back": lambda games, teams: [
            game
            for game in back_to_back_seconds(regular(games))
            if game["game_date"].year == 2026 and game["game_date"].month == 2
        ],
    },
    "date_range_last_n-015": {
        "team_splits:month:2026-01": lambda games, teams: month(regular(games), 2026, 1),
        "team_splits:month:2026-02": lambda games, teams: month(regular(games), 2026, 2),
    },
}


def compare(claimed: Any, actual: Any) -> bool:
    if isinstance(claimed, dict):
        return isinstance(actual, dict) and all(
            compare(value, actual.get(key)) for key, value in claimed.items()
        )
    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
        return abs(Decimal(str(claimed)) - Decimal(str(actual))) <= TOLERANCE
    return claimed == actual


def claim_value(claim: dict[str, Any]) -> Any:
    return claim.get("value")


def audit_response(
    response: dict[str, Any],
    games: list[dict[str, Any]],
    teams: dict[str, str],
    overtime_ids: set[int],
) -> dict[str, Any]:
    question_id = response["id"]
    expected = EXPECTED.get(question_id, {})
    claims = []
    for citation in response.get("citations") or []:
        claim = (citation.get("metadata") or {}).get("claim")
        if claim:
            claims.append(claim)
    checks = []
    seen: set[str] = set()
    for claim in claims:
        metric_id = claim.get("metric_id", "")
        if not metric_id.startswith("team_splits:"):
            if metric_id in {
                "wins",
                "losses",
                "points",
                "points_per_game",
                "margin",
                "margin_per_game",
            }:
                game_ids = set(claim.get("game_ids") or [])
                population = [game for game in games if game["id"] in game_ids]
                actual = stats(population)
                value = claim_value(claim)
                key = {
                    "points_per_game": "points_for_per_game",
                    "margin_per_game": "margin_per_game",
                }.get(metric_id, metric_id)
                passed = compare(value, actual.get(key))
                checks.append(
                    {
                        "metric_id": metric_id,
                        "claimed": value,
                        "actual": actual.get(key),
                        "game_ids_match": game_ids == set(actual.get("game_ids", [])),
                        "pass": passed and game_ids == set(actual.get("game_ids", [])),
                        "kind": "scalar",
                    }
                )
            continue
        seen.add(metric_id)
        if metric_id.startswith("team_splits:delta:"):
            left_key, _, right_key = metric_id.removeprefix("team_splits:delta:").partition("__")
            left_metric = f"team_splits:{left_key}"
            right_metric = f"team_splits:{right_key}"
            left = stats(expected[left_metric](games, teams)) if left_metric in expected else {}
            right = stats(expected[right_metric](games, teams)) if right_metric in expected else {}
            actual = {
                "margin_per_game_difference": round(
                    left.get("margin_per_game", 0) - right.get("margin_per_game", 0), 2
                ),
                "points_for_per_game_difference": round(
                    left.get("points_for_per_game", 0) - right.get("points_for_per_game", 0), 2
                ),
                "points_against_per_game_difference": round(
                    left.get("points_against_per_game", 0)
                    - right.get("points_against_per_game", 0),
                    2,
                ),
            }
            checks.append(
                {
                    "metric_id": metric_id,
                    "claimed": claim_value(claim),
                    "actual": actual,
                    "pass": compare(claim_value(claim), actual),
                    "kind": "delta",
                }
            )
            continue
        if metric_id not in expected:
            checks.append(
                {
                    "metric_id": metric_id,
                    "claimed": claim_value(claim),
                    "actual": None,
                    "pass": False,
                    "kind": "unmapped",
                }
            )
            continue
        actual = stats(expected[metric_id](games, teams))
        claimed = claim_value(claim) if isinstance(claim_value(claim), dict) else {}
        actual_subset = {
            key: actual.get(key)
            for key in (
                "games",
                "wins",
                "losses",
                "points_for_per_game",
                "points_against_per_game",
                "margin_per_game",
            )
        }
        checks.append(
            {
                "metric_id": metric_id,
                "claimed": claimed,
                "actual": actual_subset,
                "game_ids_match": set(claim.get("game_ids") or []) == set(actual["game_ids"]),
                "pass": compare(claimed, actual_subset)
                and set(claim.get("game_ids") or []) == set(actual["game_ids"]),
                "kind": "bucket",
            }
        )
    missing = sorted(
        key for key in set(expected) - seen if stats(expected[key](games, teams))["games"] > 0
    )
    return {
        "id": question_id,
        "outcome": response.get("outcome"),
        "answer": response.get("answer"),
        "claims_audited": len(checks),
        "checks": checks,
        "missing_expected_claims": missing,
        "pass": bool(checks) and all(check["pass"] for check in checks),
    }


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "head2.responses.jsonl")
    responses = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    games, teams = load_archive()
    overtime_ids = load_overtime_ids(games)
    audited = [audit_response(item, games, teams, overtime_ids) for item in responses]
    summary = {
        "responses": len(audited),
        "pass": sum(item["pass"] for item in audited),
        "fail": [item["id"] for item in audited if not item["pass"]],
        "archive": {
            "games": len(games),
            "regular": len(regular(games)),
            "playoffs": len(phase(games, "playoffs")),
            "overtime": len(overtime_ids),
            "all_star_break": [str(day) for day in all_star_break(games) or ()],
        },
        "results": audited,
    }
    output = os.path.join(HERE, "audit.json")
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
        handle.write("\n")
    lines = [
        "# Independent split audit",
        "",
        f"Responses audited: {summary['responses']}. "
        f"Pass: {summary['pass']}/{summary['responses']}.",
        "",
        f"Archive: {summary['archive']}.",
        "",
        "| id | outcome | claims | pass | failing checks |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for item in audited:
        failing = [check["metric_id"] for check in item["checks"] if not check["pass"]]
        lines.append(
            f"| {item['id']} | {item['outcome']} | {item['claims_audited']} | "
            f"{'yes' if item['pass'] else 'no'} | {', '.join(failing) or '-'} |"
        )
    lines.append("")
    lines.append("Full per-claim values and game-id comparisons are in `audit.json`.")
    with open(os.path.join(HERE, "summary.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(
        json.dumps(
            {key: summary[key] for key in ("responses", "pass", "fail", "archive")}, indent=2
        )
    )


if __name__ == "__main__":
    main()
