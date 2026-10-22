"""Expected values for the multi-turn follow-up benchmark, computed from the local archive.

Every expectation names a question scope in structured form. The value is derived from the
active release by this module; no model writes or labels an expected number. The harness and
the session file stay free of hand-typed answers.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
      uv run --package knicksiq-api python tools/release/followup_oracle.py
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg
from app.evaluation.heldout_facts import dsn, record
from archive_values import ArchiveValues, build, scoped_corpus

PHASES = {"regular", "playoffs", "all", "any"}
METRICS = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "three_pointers_made": "three_pointers_made",
}
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "october": 10,
    "november": 11,
    "december": 12,
}
RECORD_PAIR = re.compile(r"(?<![\w.-])(\d{1,3})\s*-\s*(\d{1,3})(?![\w-]|\.\w)")
WINS = re.compile(r"\b(\d{1,3})\s+wins?\b", re.I)
LOSSES = re.compile(r"\b(\d{1,3})\s+loss(?:es)?\b", re.I)
FALLBACK_WINS = re.compile(r"\bwins:\s*(\d{1,3})\s+over\b", re.I)
FALLBACK_LOSSES = re.compile(r"\blosses:\s*(\d{1,3})\s+over\b", re.I)
NUMBER = re.compile(r"(?<![\w.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)(?![\w])")


@dataclass
class TurnExpectation:
    kind: str
    filters: dict[str, Any]
    question: str
    games: int
    fact: str | None = None
    value: float | None = None
    record: tuple[int, int] | None = None
    player: str | None = None
    metric: str | None = None
    aggregation: str | None = None
    entity: str | None = None
    game_ids: list[int] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)
    answerable: bool = True


def load_sessions(path: Path) -> list[dict[str, Any]]:
    sessions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    seen: set[str] = set()
    for session in sessions:
        if session["id"] in seen:
            raise SystemExit(f"duplicate session id {session['id']}")
        seen.add(session["id"])
        turns = session.get("turns") or []
        if not 2 <= len(turns) <= 4:
            raise SystemExit(f"{session['id']}: expected 2 to 4 turns, got {len(turns)}")
        for index, turn in enumerate(turns):
            if not turn.get("question") or not turn.get("expect"):
                raise SystemExit(f"{session['id']} turn {index + 1}: question and expect required")
            kind = turn["expect"].get("kind")
            if kind not in {
                "record",
                "player_average",
                "player_total",
                "team_average",
                "team_total",
                "narrative",
                "decline",
            }:
                raise SystemExit(f"{session['id']} turn {index + 1}: bad kind {kind}")
    return sessions


def _month_dates(archive, month: int) -> tuple[date, date]:
    dates = [game.game_date for game in archive.games if game.game_date.month == month]
    if not dates:
        raise SystemExit(f"no games in month {month}")
    return min(dates), max(dates)


def filter_games(archive, filters: dict[str, Any]) -> list:
    games = list(archive.games)
    phase = filters.get("phase", "regular")
    if phase not in PHASES:
        raise SystemExit(f"bad phase {phase}")
    if phase in {"regular", "playoffs"}:
        games = [game for game in games if game.season_type == phase]
    opponent = filters.get("opponent")
    if opponent:
        games = [game for game in games if game.opponent == opponent]
    site = filters.get("site")
    if site == "home":
        games = [game for game in games if game.knicks_home]
    elif site == "away":
        games = [game for game in games if not game.knicks_home]
    month = filters.get("month")
    if month:
        start, end = _month_dates(archive, MONTHS[str(month).casefold()])
        games = [game for game in games if start <= game.game_date <= end]
    if filters.get("date"):
        day = date.fromisoformat(filters["date"])
        games = [game for game in games if game.game_date == day]
    count = filters.get("relative_game_count")
    if count:
        games = games[-int(count) :]
    return games


def _expected_scope(spec: dict[str, Any], games: list, player_ids: dict[str, int]) -> dict:
    filters = spec.get("filters") or {}
    phase = filters.get("phase", "regular")
    scope: dict[str, Any] = {
        "season_type": phase if phase in {"regular", "playoffs"} else None,
        "all_phases": phase == "all",
        "game_count": len(games),
        "game_ids": [game.id for game in games] if filters.get("date") else None,
        "player_ids": [],
        "metric": spec.get("metric"),
        "home_away": filters.get("site"),
        "opponent_id": filters.get("opponent"),
        "relative_game_count": filters.get("relative_game_count"),
    }
    player = spec.get("player")
    if player:
        if player not in player_ids:
            raise SystemExit(f"unknown player {player}")
        scope["player_ids"] = [player_ids[player]]
    month = filters.get("month")
    if month:
        start, end = _month_dates_for_scope(games)
        scope["date_start"] = str(start)
        scope["date_end"] = str(end)
    else:
        explicit = date.fromisoformat(filters["date"]) if filters.get("date") else None
        scope["date_start"] = str(explicit) if explicit else None
        scope["date_end"] = scope["date_start"]
    return scope


def _month_dates_for_scope(games: list) -> tuple[date, date]:
    if not games:
        raise SystemExit("month scope has no games")
    return min(game.game_date for game in games), max(game.game_date for game in games)


def expectation_for(
    turn: dict[str, Any], archive, player_ids: dict[str, int], teams: dict[str, str]
) -> TurnExpectation:
    spec = turn["expect"]
    kind = spec["kind"]
    filters = spec.get("filters") or {}
    games = filter_games(archive, filters)
    expectation = TurnExpectation(
        kind=kind,
        filters=filters,
        question=turn["question"],
        games=len(games),
        player=spec.get("player"),
        metric=spec.get("metric"),
        aggregation=spec.get("aggregation"),
        scope=_expected_scope(spec, games, player_ids),
    )
    if kind == "decline":
        expectation.answerable = False
        return expectation
    if not games:
        raise SystemExit(f"{turn.get('id') or turn['question']}: empty scope")
    if kind == "record":
        wins, losses = record(games)
        expectation.record = (wins, losses)
        expectation.fact = f"{wins}-{losses}"
        expectation.entity = "Knicks"
    elif kind in {"player_average", "player_total"}:
        player = spec.get("player")
        metric = METRICS[spec.get("metric") or "points"]
        if not player:
            raise SystemExit(f"{turn['question']}: player required")
        allowed = {game.id for game in games}
        lines = [
            line
            for line in archive.lines
            if line.player.casefold() == player.casefold()
            and line.game_id in allowed
            and line.minutes > 0
        ]
        if not lines:
            raise SystemExit(f"{turn['question']}: no player rows")
        total = sum(getattr(line, metric) for line in lines)
        if kind == "player_average":
            expectation.value = round(total / len(lines), 4)
            expectation.fact = f"{total / len(lines):.1f}"
        else:
            expectation.value = float(total)
            expectation.fact = str(int(total))
        expectation.metric = metric
        expectation.entity = player
    elif kind == "team_average":
        if spec.get("metric", "points") == "margin":
            values = [game.margin for game in games]
        else:
            values = [game.knicks_points for game in games]
        expectation.value = round(sum(values) / len(values), 4)
        expectation.fact = f"{sum(values) / len(values):.2f}"
        expectation.metric = spec.get("metric") or "points"
        expectation.entity = "Knicks"
    elif kind == "team_total":
        values = [game.knicks_points for game in games]
        expectation.value = float(sum(values))
        expectation.fact = str(int(sum(values)))
        expectation.metric = spec.get("metric") or "points"
        expectation.entity = "Knicks"
    elif kind == "narrative":
        game = games[-1]
        expected_fact = spec.get("fact", "points")
        if expected_fact == "score":
            expectation.fact = f"{game.knicks_points}-{game.opponent_points}"
        elif expected_fact == "points":
            expectation.fact = str(int(game.knicks_points))
        else:
            expectation.fact = None
        expectation.game_ids = [game.id]
        if spec.get("entity") == "opponent":
            expectation.entity = teams.get(game.opponent, game.opponent)
        expectation.scope["game_ids"] = [game.id]
    expectation.scope["game_ids"] = expectation.game_ids or expectation.scope["game_ids"]
    return expectation


async def oracle() -> tuple[ArchiveValues, dict[str, int], dict[str, str]]:
    connection = await asyncpg.connect(dsn())
    try:
        values = await build(connection)
        ids = {
            row["full_name"]: row["id"]
            for row in await connection.fetch("select id, full_name from players")
        }
        team_rows = await connection.fetch("select id, name from teams")
        teams = {row["id"]: row["name"] for row in team_rows}
    finally:
        await connection.close()
    return values, ids, teams


def matches_record(answer: str, wins: int, losses: int, games: int) -> bool:
    """A record is stated as W-L, as W wins and L losses, or in the fallback wording.

    The pair must add up to the population size, which rejects game scores that happen to
    match two of the numbers.
    """
    for match in RECORD_PAIR.finditer(answer or ""):
        left, right = int(match.group(1)), int(match.group(2))
        if (left, right) == (wins, losses) and left + right == games:
            return True
    all_wins = [int(value) for value in WINS.findall(answer or "")] + [
        int(value) for value in FALLBACK_WINS.findall(answer or "")
    ]
    all_losses = [int(value) for value in LOSSES.findall(answer or "")] + [
        int(value) for value in FALLBACK_LOSSES.findall(answer or "")
    ]
    return wins in all_wins and losses in all_losses


def matches_value(answer: str, expected: float, *, integer: bool) -> bool:
    tolerance = 0.0 if integer else 0.051
    for raw in NUMBER.finditer(answer or ""):
        value = float(raw.group(1).replace(",", ""))
        if abs(value - expected) <= tolerance:
            return True
    return False


def expectation_checks(answer: str, expectation: TurnExpectation, teams: dict[str, str]) -> dict:
    text = answer or ""
    if expectation.kind == "decline":
        return {"decline": True}
    if expectation.kind == "record":
        wins, losses = expectation.record or (0, 0)
        return {
            "record": f"{wins}-{losses}",
            "records_in_answer": [
                f"{match.group(1)}-{match.group(2)}" for match in RECORD_PAIR.finditer(text)
            ],
            "record_ok": matches_record(text, wins, losses, expectation.games),
        }
    if expectation.kind == "narrative":
        if not expectation.fact:
            return {"fact": None, "fact_ok": True}
        if "-" in expectation.fact:
            nyk, opp = (int(part) for part in expectation.fact.split("-"))
            pairs = [
                (int(match.group(1)), int(match.group(2))) for match in RECORD_PAIR.finditer(text)
            ]
            ok = any(pair in {(nyk, opp), (opp, nyk)} for pair in pairs)
            return {"fact": expectation.fact, "fact_ok": ok}
        return {
            "fact": expectation.fact,
            "fact_ok": matches_value(text, float(expectation.fact), integer=True),
        }
    integer = expectation.kind == "player_total"
    return {
        "fact": expectation.fact,
        "value": expectation.value,
        "value_ok": matches_value(text, expectation.value or 0.0, integer=integer),
    }


def scoped(answer: str, case: dict, values: ArchiveValues):
    return scoped_corpus(values, case.get("question", ""), case, answer)


def expectation_case(expectation: TurnExpectation) -> dict:
    """The honest scoring case for a turn. Values still come from the oracle."""
    case: dict[str, Any] = {
        "id": expectation.question,
        "category": "follow_ups",
        "question": expectation.question,
        "answerable": expectation.answerable,
        "required_facts": [],
        "required_entities": [],
    }
    if not expectation.answerable:
        return case
    if expectation.kind == "record":
        case["required_facts"] = [expectation.fact]
        case["required_entities"] = ["Knicks"]
    elif expectation.kind == "narrative":
        if expectation.fact:
            case["required_facts"] = [expectation.fact]
        if expectation.entity:
            case["required_entities"] = [expectation.entity]
    elif expectation.kind in {
        "player_average",
        "player_total",
        "team_average",
        "team_total",
    }:
        case["required_facts"] = [expectation.fact]
        if expectation.entity:
            case["required_entities"] = [expectation.entity]
    return case


def selected_games(scope: dict, archive) -> list:
    games = [
        game
        for game in archive.games
        if (not scope.get("game_ids") or game.id in set(scope["game_ids"]))
        and (not scope.get("season_type") or game.season_type == scope["season_type"])
        and (not scope.get("date_start") or str(game.game_date) >= str(scope["date_start"]))
        and (not scope.get("date_end") or str(game.game_date) <= str(scope["date_end"]))
        and (
            not scope.get("opponent_id")
            or scope["opponent_id"] in (game.home_team_id, game.away_team_id)
        )
        and (not scope.get("home_away") or game.knicks_home == (scope["home_away"] == "home"))
    ]
    if scope.get("game_result") == "W":
        games = [game for game in games if game.won]
    elif scope.get("game_result") == "L":
        games = [game for game in games if not game.won]
    return games


def compare_scope(actual: dict, expected: dict, archive) -> list[str]:
    """Differences between the committed scope and the scope the follow-up implies."""
    issues: list[str] = []
    if actual.get("season_type") != expected.get("season_type"):
        issues.append(f"season_type={actual.get('season_type')} want {expected.get('season_type')}")
    if bool(actual.get("all_phases")) != bool(expected.get("all_phases")):
        issues.append(f"all_phases={actual.get('all_phases')} want {expected.get('all_phases')}")
    for key in ("home_away", "opponent_id", "relative_game_count", "metric"):
        if actual.get(key) != expected.get(key):
            issues.append(f"{key}={actual.get(key)} want {expected.get(key)}")
    actual_players = sorted(actual.get("player_ids") or [])
    expected_players = sorted(expected.get("player_ids") or [])
    if actual_players != expected_players:
        issues.append(f"player_ids={actual_players} want {expected_players}")
    for key in ("date_start", "date_end"):
        got = str(actual[key]) if actual.get(key) else None
        want = expected.get(key) or None
        if got != want:
            issues.append(f"{key}={got} want {want}")
    count = len(selected_games(actual, archive))
    if count != expected.get("game_count"):
        issues.append(f"game_count={count} want {expected.get('game_count')}")
    if expected.get("game_ids"):
        got_ids = set(actual.get("game_ids") or [])
        want_ids = set(expected["game_ids"])
        if got_ids != want_ids:
            issues.append(f"game_ids differ (got {sorted(got_ids)}, want {sorted(want_ids)})")
    if actual.get("requires_clarification"):
        issues.append("requires_clarification")
    return issues


def _print(sessions: list[dict], archive, ids: dict[str, int], teams: dict[str, str]) -> None:
    total = 0
    for session in sessions:
        print(session["id"], session.get("category", ""))
        for index, turn in enumerate(session["turns"], start=1):
            expectation = expectation_for(turn, archive, ids, teams)
            total += 1
            print(
                f"  {index}. {turn['question']!r} -> {expectation.kind} {expectation.fact} "
                f"games={expectation.games} scope={json.dumps(expectation.scope, sort_keys=True)}"
            )
    print("TURNS", total)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sessions",
        type=Path,
        default=Path("apps/api/app/evaluation/followup_sessions.jsonl"),
    )
    parser.add_argument("--session", action="append", default=[])
    args = parser.parse_args()
    sessions = load_sessions(args.sessions)
    if args.session:
        sessions = [session for session in sessions if session["id"] in set(args.session)]
    values, ids, teams = __import__("asyncio").run(oracle())
    _print(sessions, values.archive, ids, teams)


if __name__ == "__main__":
    main()
