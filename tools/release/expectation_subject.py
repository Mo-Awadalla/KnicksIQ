"""Canonical subject identity for proposed evaluation facts.

Each resolution is grounded in the approved archive rows: a team fact takes
``team:NYK`` only when its typed value reproduces as a Knicks-side aggregate, a
declared player name is confirmed against the roster row by row, and a leader
takes its name only from a unique canonical winner. No value, scope or evidence
id is ever rewritten.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from statistics import mean

TEAM_SUBJECT = "team:NYK"
GAME_PREFIXES = frozenset({"game", "box", "team_box", "period"})
QUARTER = re.compile(r"quarter (\d)")


class EnrichmentError(RuntimeError):
    """An input failed an identity, ownership or preservation check."""


class RecipeError(ValueError):
    """A fact's value has no independent Knicks-side reconstruction."""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def decimal_places(want):
    text = repr(want)
    return len(text.split(".", 1)[1]) if "." in text else 0


def matches(got, want):
    """An integer is exact; a decimal equals the canonical value at its precision."""
    if isinstance(want, bool):
        return got is want
    if isinstance(want, int):
        return got == want
    return abs(round(got, decimal_places(want)) - want) <= 1e-9


class Archive:
    """The approved bundle rows, indexed for independent NYK-side recomputation."""

    def __init__(self, payload):
        data = payload["data"]
        self.manifest = payload["manifest"]
        self.data_sha256 = digest(data)
        self.games = {row["nba_game_id"]: row for row in data["games"]}
        self.box = {
            (row["nba_game_id"], row["nba_player_id"]): row for row in data["player_game_stats"]
        }
        self.team_box = {
            (row["nba_game_id"], row["team_id"]): row for row in data["team_game_stats"]
        }
        self.periods = {
            (row["nba_game_id"], row["team_id"], row["period"]): row["points"]
            for row in data["period_scores"]
        }
        self.rosters = {}
        for row in data["players"]:
            name = str(row["full_name"]).casefold()
            self.rosters.setdefault(name, []).append(row["nba_player_id"])
        self.days = {row["game_date"] for row in data["games"]}

    def own(self, game_id):
        game = self.games[game_id]
        return game["home_score"] if game["home_team_id"] == "NYK" else game["away_score"]

    def allowed(self, game_id):
        game = self.games[game_id]
        return game["away_score"] if game["home_team_id"] == "NYK" else game["home_score"]

    def won(self, game_id):
        return self.own(game_id) > self.allowed(game_id)

    def previous_day_game(self, game_id):
        day = date.fromisoformat(self.games[game_id]["game_date"]).toordinal() - 1
        return date.fromordinal(day).isoformat() in self.days

    def consecutive(self, first, second):
        left = date.fromisoformat(self.games[first]["game_date"])
        right = date.fromisoformat(self.games[second]["game_date"])
        return (right - left).days == 1

    def roster_ids(self, name):
        return self.rosters.get(name.casefold(), [])

    def knicks_box(self, game_id):
        return [
            row
            for row in self.box.values()
            if row["nba_game_id"] == game_id and row["team_id"] == "NYK"
        ]


def evidence(fact):
    refs = []
    for reference in fact["canonical_evidence_ids"]:
        parts = reference.split(":")
        if len(parts) < 2 or parts[0] not in GAME_PREFIXES or not parts[1]:
            raise EnrichmentError(f"unexpressible evidence reference {reference}")
        refs.append(parts)
    return refs


def game_ids(fact):
    ids = []
    for parts in evidence(fact):
        if parts[1] not in ids:
            ids.append(parts[1])
    if not ids:
        raise EnrichmentError(f"fact {fact['metric']} names no canonical game")
    return ids


def box_rows(archive, fact, field):
    rows = []
    for parts in evidence(fact):
        if parts[0] != "box" or len(parts) != 3:
            continue
        row = archive.box.get((parts[1], int(parts[2])))
        if row is None:
            raise RecipeError(f"box row {':'.join(parts)} is absent from the bundle")
        rows.append(row)
    if not rows:
        raise RecipeError("no box rows named by the fact's evidence")
    return rows


def team_box_rows(archive, fact):
    rows = []
    for parts in evidence(fact):
        if parts[0] != "team_box" or len(parts) != 3 or parts[2] != "NYK":
            raise RecipeError(f"team box reference {':'.join(parts)} is not a NYK row")
        row = archive.team_box.get((parts[1], parts[2]))
        if row is None:
            raise RecipeError(f"team box row {':'.join(parts)} is absent from the bundle")
        rows.append(row)
    return rows


def period_rows(archive, fact):
    points, teams = [], set()
    for parts in evidence(fact):
        if parts[0] != "period" or len(parts) != 4:
            continue
        teams.add(parts[2])
        point = archive.periods.get((parts[1], parts[2], int(parts[3])))
        if point is None:
            raise RecipeError(f"period row {':'.join(parts)} is absent from the bundle")
        points.append(point)
    if teams != {"NYK"}:
        raise RecipeError(f"period evidence names teams {sorted(teams)}")
    return points


def metric_key(metric):
    """The evaluator's label metric key: a leading ``Player:`` prefix is dropped."""
    remainder = metric.split(": ", 1)[1] if ": " in metric else metric
    return re.sub(r"\s+", "_", remainder.strip().casefold())


def counted(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _games(archive, fact, ids):
    return len(ids)


def _wins(archive, fact, ids):
    return sum(1 for game in ids if archive.won(game))


def _losses(archive, fact, ids):
    return sum(1 for game in ids if not archive.won(game))


def _points(archive, fact, ids):
    return sum(archive.own(game) for game in ids)


def _points_per_game(archive, fact, ids):
    return _points(archive, fact, ids) / len(ids)


def _allowed_per_game(archive, fact, ids):
    return sum(archive.allowed(game) for game in ids) / len(ids)


def _single_margin(archive, fact, ids):
    if len(ids) != 1:
        raise RecipeError("a single-game margin needs exactly one canonical game")
    return archive.own(ids[0]) - archive.allowed(ids[0])


def _mean_margin(archive, fact, ids):
    return mean(archive.own(game) - archive.allowed(game) for game in ids)


def _team_mean(field):
    def value(archive, fact, ids):
        return mean(row[field] for row in team_box_rows(archive, fact))

    return value


def _team_percentage(made, attempted):
    def value(archive, fact, ids):
        rows = team_box_rows(archive, fact)
        attempts = sum(row[attempted] for row in rows)
        if not attempts:
            raise RecipeError(f"no {attempted} in the named NYK team rows")
        return 100 * sum(row[made] for row in rows) / attempts

    return value


def _bench_points(archive, fact, ids):
    rows = [row for row in box_rows(archive, fact, "points") if not row["starter"]]
    if not rows:
        raise RecipeError("no bench row is named by the fact")
    return sum(row["points"] for row in rows) / len(ids)


def _quarter_points(archive, fact, ids):
    match = QUARTER.search(fact["scope"])
    if match is None:
        raise RecipeError(f"scope {fact['scope']!r} names no quarter")
    quarter = int(match.group(1))
    refs = evidence(fact)
    if any(parts[0] != "period" or int(parts[3]) != quarter for parts in refs):
        raise RecipeError(f"evidence is not restricted to quarter {quarter}")
    return mean(period_rows(archive, fact))


def _month(archive, ids):
    months = {archive.games[game]["game_date"][:7] for game in ids}
    if len(months) != 1:
        raise RecipeError(f"named games span months {sorted(months)}")
    return months.pop()


def _second_nights(archive, fact, ids):
    month = _month(archive, ids)
    expected = {
        game
        for game, row in archive.games.items()
        if row["game_date"][:7] == month and archive.previous_day_game(game)
    }
    if set(ids) != expected:
        raise RecipeError(f"evidence is not the complete {month} second-night set")
    return sum(1 for game in ids if archive.won(game))


def _swept_pairs(archive, fact, ids):
    month = _month(archive, ids)
    by_day = {
        row["game_date"]: game
        for game, row in archive.games.items()
        if row["game_date"][:7] == month
    }
    days = sorted(by_day)
    pairs = [
        (by_day[first], by_day[second])
        for first, second in zip(days, days[1:], strict=False)
        if archive.consecutive(by_day[first], by_day[second])
    ]
    if set(ids) != {game for pair in pairs for game in pair}:
        raise RecipeError(f"evidence is not the complete {month} back-to-back set")
    return sum(1 for first, second in pairs if archive.won(first) and archive.won(second))


def _fewest_third_quarter(archive, fact, ids):
    scored = {
        game: points
        for (game, team, period), points in archive.periods.items()
        if team == "NYK" and period == 3
    }
    lowest = min(scored.values())
    worst = {game for game, points in scored.items() if points == lowest}
    if set(ids) != worst:
        raise RecipeError(f"named games are not the lowest third quarter {sorted(worst)}")
    return lowest


TEAM_RECIPES = {
    "games": (_games, "distinct canonical Knicks games named by the fact"),
    "game_count": (_games, "distinct canonical Knicks games named by the fact"),
    "wins": (_wins, "Knicks wins among the named games"),
    "losses": (_losses, "Knicks losses among the named games"),
    "points": (_points, "sum of Knicks points in the named games"),
    "points_per_game": (_points_per_game, "Knicks points divided by the named games"),
    "points_allowed_per_game": (_allowed_per_game, "opponent points divided by the named games"),
    "margin": (_single_margin, "Knicks points minus opponent points in the named game"),
    "average_margin": (_mean_margin, "mean Knicks margin over the named games"),
    "turnovers_per_game": (_team_mean("turnovers"), "mean Knicks team_box turnovers"),
    "field_goal_percentage": (
        _team_percentage("field_goals_made", "field_goals_attempted"),
        "Knicks made over attempted field goals",
    ),
    "three_point_percentage": (
        _team_percentage("three_pointers_made", "three_pointers_attempted"),
        "Knicks made over attempted three-pointers",
    ),
    "free_throw_percentage": (
        _team_percentage("free_throws_made", "free_throws_attempted"),
        "Knicks made over attempted free throws",
    ),
    "bench_points_per_team_game": (
        _bench_points,
        "non-starter points divided by the named games",
    ),
    "period_points_per_game": (_quarter_points, "mean Knicks points in the named quarter"),
    "second_night_wins": (_second_nights, "Knicks wins on the second night of a back-to-back"),
    "both_games_won": (_swept_pairs, "Knicks back-to-back pairs won outright"),
    "fewest_third_quarter_points": (
        _fewest_third_quarter,
        "lowest Knicks third-quarter points in the schedule",
    ),
}

PLAYER_RECIPES = {
    "average points": lambda rows: mean(row["points"] for row in rows),
    "total points": lambda rows: sum(row["points"] for row in rows),
    "average rebounds": lambda rows: mean(row["rebounds"] for row in rows),
    "total rebounds": lambda rows: sum(row["rebounds"] for row in rows),
    "total assists": lambda rows: sum(row["assists"] for row in rows),
    "starts starter": lambda rows: sum(1 for row in rows if row["starter"]),
    "percentage three_pointers_made": lambda rows: (
        100
        * sum(row["three_pointers_made"] for row in rows)
        / sum(row["three_pointers_attempted"] for row in rows)
    ),
    "double_doubles points": lambda rows: sum(
        1
        for row in rows
        if sum(value >= 10 for value in (row["points"], row["rebounds"], row["assists"])) >= 2
    ),
}

LEADER_STATS = ("points", "rebounds", "assists", "steals")


def resolve_team(archive, fact):
    """A Knicks team fact needs a value that reproduces as a NYK-side aggregate."""
    key = metric_key(fact["metric"])
    recipe = TEAM_RECIPES.get(key)
    if recipe is None:
        raise RecipeError(f"no independent Knicks-side reconstruction for metric {key}")
    compute, method = recipe
    ids = game_ids(fact)
    foreign = [
        game
        for game in ids
        if "NYK" not in (archive.games[game]["home_team_id"], archive.games[game]["away_team_id"])
    ]
    if foreign:
        raise RecipeError(f"evidence names non-Knicks games {foreign[:3]}")
    recomputed = compute(archive, fact, ids)
    if not matches(recomputed, fact["value"]):
        raise RecipeError(
            f"value {fact['value']!r} is not the Knicks aggregate "
            f"{round(recomputed, 4)!r} ({method})"
        )
    return {"subject": TEAM_SUBJECT}, {
        "kind": "knicks_recomputation",
        "method": method,
        "recomputed": round(recomputed, 4),
    }


def resolve_player(archive, fact):
    """A declared player_name is the subject once the roster and rows confirm it."""
    name = fact["player_name"]
    ids = archive.roster_ids(name)
    if len(ids) != 1:
        raise RecipeError(f"the roster holds {len(ids)} canonical players named {name!r}")
    if not fact["metric"].startswith(f"{name}: "):
        raise RecipeError(f"metric {fact['metric']!r} does not declare {name!r}")
    rows = box_rows(archive, fact, "points")
    foreign = {row["nba_player_id"] for row in rows} - set(ids)
    if foreign:
        raise RecipeError(f"evidence rows belong to canonical players {sorted(foreign)}")
    if fact.get("appearances") is not None and fact["appearances"] != len(rows):
        raise RecipeError(f"{len(rows)} evidence rows against {fact['appearances']} appearances")
    recipe = PLAYER_RECIPES.get(fact["metric"].split(": ", 1)[1])
    if recipe is None:
        value_check = "no_recipe"
    elif matches(recipe(rows), fact["value"]):
        value_check = "matched"
    else:
        value_check = f"mismatch:{round(recipe(rows), 4)}"
    return {}, {"kind": "player_evidence", "rows": len(rows), "value_check": value_check}


def resolve_leader(archive, fact):
    """A leader names its player only when one canonical player wins outright."""
    value = fact["value"]
    if not isinstance(value, dict) or "name" not in value:
        raise RecipeError("leader value names no player")
    name = str(value["name"])
    ids = archive.roster_ids(name)
    if len(ids) != 1:
        raise RecipeError(f"the roster holds {len(ids)} canonical players named {name!r}")
    stat = fact["metric"].split(" ", 1)[0]
    if stat not in LEADER_STATS:
        raise RecipeError(f"metric {fact['metric']!r} ranks no countable stat")
    totals = {}
    for game in game_ids(fact):
        for row in archive.knicks_box(game):
            if float(row.get("minutes") or 0) <= 0:
                continue
            totals[row["nba_player_id"]] = totals.get(row["nba_player_id"], 0) + row[stat]
    if not totals:
        raise RecipeError("no Knicks appearance in the named games")
    best = max(totals.values())
    leaders = sorted(player for player, total in totals.items() if total == best)
    if leaders != ids:
        raise RecipeError(f"the {stat} leader is {leaders}, not {ids}")
    field = next(key for key in ("total", "average") if key in value)
    if not matches(best, value[field]):
        raise RecipeError(f"{stat} total {best!r} against the value {value[field]!r}")
    return {"player_name": name}, {
        "kind": "leader_rank",
        "stat": stat,
        "recomputed_total": best,
        "unique_leader": True,
    }


def resolve_game(archive, fact):
    """A scoreline asserts the game it names; the runtime claim subject is the team."""
    refs = evidence(fact)
    if len(refs) != 1 or refs[0][0] != "game":
        raise RecipeError("a scoreline names exactly one canonical game")
    row = archive.games.get(refs[0][1])
    if row is None:
        raise RecipeError(f"game {refs[0][1]} is absent from the bundle")
    if "NYK" not in (row["home_team_id"], row["away_team_id"]):
        raise RecipeError(f"game {refs[0][1]} is not a Knicks game")
    fields = {
        "nba_game_id": row["nba_game_id"],
        "game_date": row["game_date"],
        "home_team_id": row["home_team_id"],
        "away_team_id": row["away_team_id"],
        "home_score": row["home_score"],
        "away_score": row["away_score"],
    }
    if fact["value"] != fields:
        raise RecipeError(f"scoreline value differs from bundle row {row['nba_game_id']}")
    return {"subject": TEAM_SUBJECT}, {
        "kind": "game_row",
        "row_sha256": digest(row),
        "subject_contract": "game_score claims carry subject team:NYK",
    }


def classify(fact):
    key = metric_key(fact["metric"])
    if key == "game_score":
        return "game_score"
    if key.endswith("_leader"):
        return "leader"
    if fact.get("player_name"):
        return "player"
    return "team"


RESOLVERS = {
    "game_score": resolve_game,
    "leader": resolve_leader,
    "player": resolve_player,
    "team": resolve_team,
}
