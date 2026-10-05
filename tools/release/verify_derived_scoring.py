"""Verify derived scoring from complete, independently captured NBA action lists.

Canonical rows and raw scoreboards remain immutable. NBA attempt fields establish
individual contributions; separate period and player box rows reconcile them.
This creates proposed source receipts, not indexed retrieval or approved gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

from audit_measure_sources import (
    APPROVED_SHA,
    digest,
    integer,
    load_archive,
    quarter_issues,
    require,
)

RECIPE = "nba-action-scoring-trajectory-v1"
SHOT_FIELDS = (
    "points",
    "field_goals_made",
    "field_goals_attempted",
    "three_pointers_made",
    "three_pointers_attempted",
    "free_throws_made",
    "free_throws_attempted",
)
ATTEMPT_KINDS = {"Made Shot", "Missed Shot", "Free Throw"}
NEUTRAL_KINDS = {
    "Rebound",
    "Turnover",
    "Foul",
    "Substitution",
    "Timeout",
    "Jump Ball",
    "Period Begin",
    "Period End",
    "Violation",
    "Ejection",
    "period",
    "Instant Replay",
    "Heave",
}


def clock(value: str) -> str:
    match = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    require(match is not None and bool(match[1] or match[2]), "Invalid primary action clock")
    if match is None:
        raise ValueError("Invalid primary action clock")
    return f"{int(match[1] or 0):02d}:{int(float(match[2] or 0)):02d}"


def contribution(action: dict) -> tuple[int, dict[str, int]]:
    """Interpret only explicit NBA attempt fields, never raw cumulative scores."""
    kind, description = action["actionType"], action["description"]
    require(isinstance(description, str) and bool(description), "Missing primary description")
    stats = {key: 0 for key in SHOT_FIELDS}
    if kind in {"Made Shot", "Missed Shot"}:
        value, result = action["shotValue"], action["shotResult"]
        require(
            type(value) is int
            and value in {2, 3}
            and action["isFieldGoal"] == 1
            and result == ("Made" if kind == "Made Shot" else "Missed"),
            "Conflicting or unsupported primary field-goal fields",
        )
        require(("3PT" in description) == (value == 3), "Primary shot value/description conflict")
        require(
            description.startswith("MISS ") == (kind == "Missed Shot"),
            "Primary field-goal result/description conflict",
        )
        made = int(kind == "Made Shot")
        stats.update(
            points=value * made,
            field_goals_made=made,
            field_goals_attempted=1,
            three_pointers_made=made * int(value == 3),
            three_pointers_attempted=int(value == 3),
        )
    elif kind == "Free Throw":
        require(
            action["isFieldGoal"] == 0 and "Free Throw" in description,
            "Ambiguous primary free-throw attempt",
        )
        missed = description.startswith("MISS ")
        require(
            action["shotResult"] in {"", "Missed" if missed else "Made"},
            "Primary free-throw result/description conflict",
        )
        require(
            type(action["shotValue"]) is int and action["shotValue"] in {0, 1},
            "Unsupported primary free-throw value",
        )
        stats.update(
            points=int(not missed), free_throws_made=int(not missed), free_throws_attempted=1
        )
    else:
        explicit_neutral = kind in NEUTRAL_KINDS or (
            kind == "" and re.search(r"\b(?:STEAL|BLOCK)\b", description) is not None
        )
        require(
            explicit_neutral and action["isFieldGoal"] == 0 and action["shotResult"] == "",
            "Unknown or conflicting primary scoring kind",
        )
    return stats["points"], stats


def verify_game(
    game: dict,
    events: list[dict],
    periods: list[dict],
    boxes: list[dict],
    capture_path: Path,
    version: str,
) -> dict:
    identity = game["nba_game_id"]
    require(
        [e["sequence"] for e in events] == list(range(1, len(events) + 1)) and bool(events),
        f"{identity}: missing, duplicate or noncontiguous canonical order",
    )
    require(not quarter_issues(game, periods, events), f"{identity}: incomplete canonical periods")
    raw = capture_path.read_bytes()
    capture = json.loads(raw)
    primary = capture["play_by_play"]
    require(primary["gameId"] == identity, f"{identity}: foreign primary game")
    require(
        capture["source_url"].startswith("https://www.nba.com/game/")
        and identity in capture["source_url"],
        f"{identity}: invalid supplied source URL",
    )
    actions = primary["actions"]
    require(
        bool(actions)
        and len({a["actionId"] for a in actions}) == len(actions)
        and all(
            integer(a["actionId"], positive=True) and integer(a["actionNumber"]) for a in actions
        ),
        f"{identity}: duplicate or invalid primary action identities",
    )
    slots = defaultdict(deque)
    action_stats = []
    for index, action in enumerate(actions):
        require(integer(action["period"], positive=True), "Invalid primary period")
        points, stats = contribution(action)
        action_stats.append((points, stats))
        key = (
            action["period"],
            clock(action["clock"]),
            action["description"],
            action["teamTricode"] or None,
            action["personId"] or None,
        )
        slots[key].append(index)
    score = {"home": 0, "away": 0}
    period_points, player_stats, player_points = Counter(), defaultdict(Counter), Counter()
    selected, derived, caption_issues = set(), [], []
    last_index = -1
    for event in events:
        key = (
            event["period"],
            event["clock"],
            event["description"],
            event["team_id"],
            event.get("nba_player_id"),
        )
        require(
            bool(slots[key]), f"{identity}:{event['sequence']}: missing matching primary action"
        )
        index = slots[key].popleft()
        require(index > last_index, f"{identity}:{event['sequence']}: primary action order differs")
        last_index = index
        selected.add(index)
        action = actions[index]
        points, stats = action_stats[index]
        before = dict(score)
        if action["actionType"] in ATTEMPT_KINDS:
            team, player = event["team_id"], event.get("nba_player_id")
            require(
                team in {game["home_team_id"], game["away_team_id"]}
                and integer(player, positive=True),
                f"{identity}: unsupported scoring actor",
            )
            side = "home" if team == game["home_team_id"] else "away"
            score[side] += points
            period_points[(team, event["period"])] += points
            player_stats[(team, player)].update(stats)
            player_points[(team, player)] += points
            caption = re.search(r"\((\d+) PTS\)", event["description"])
            if points and caption and int(caption[1]) != player_points[(team, player)]:
                caption_issues.append(
                    {
                        "sequence": event["sequence"],
                        "caption": int(caption[1]),
                        "derived_player_points": player_points[(team, player)],
                    }
                )
        derived.append(
            {
                "canonical_id": f"event:{identity}:{event['sequence']}",
                "canonical_row_sha256": digest(event),
                "sequence": event["sequence"],
                "period": event["period"],
                "clock": event["clock"],
                "team_id": event["team_id"],
                "nba_player_id": event.get("nba_player_id"),
                "points": points,
                "primary_action_index": index,
                "primary_action_id": action["actionId"],
                "primary_action_number": action["actionNumber"],
                "primary_action_sha256": digest(action),
                "primary_action_type": action["actionType"],
                "canonical_event_type": event["event_type"],
                "score_before": before,
                "score_after": dict(score),
                "raw_score": {"home": event["home_score"], "away": event["away_score"]},
            }
        )
    require(
        all(
            index in selected for index, a in enumerate(actions) if a["actionType"] in ATTEMPT_KINDS
        ),
        f"{identity}: unmatched primary scoring attempt",
    )
    require(
        score == {"home": game["home_score"], "away": game["away_score"]},
        f"{identity}: derived final disagrees with canonical final",
    )
    period_receipts = []
    for row in periods:
        require(
            period_points[(row["team_id"], row["period"])] == row["points"],
            f"{identity}: per-action period total differs",
        )
        period_receipts.append(
            {
                "canonical_id": f"period:{identity}:{row['team_id']}:{row['period']}",
                "row_sha256": digest(row),
                "points": row["points"],
            }
        )
    known_players = set()
    box_receipts = []
    for row in boxes:
        key = (row["team_id"], row["nba_player_id"])
        require(
            key not in known_players
            and key[0] in {game["home_team_id"], game["away_team_id"]}
            and integer(key[1], positive=True),
            f"{identity}: duplicate or foreign player box",
        )
        known_players.add(key)
        for field in SHOT_FIELDS:
            require(
                integer(row[field]) and row[field] == player_stats[key][field],
                f"{identity}:{key[1]}: primary {field} differs from player box",
            )
        box_receipts.append(
            {
                "canonical_id": f"box:{identity}:{key[1]}",
                "row_sha256": digest(row),
                "team_id": key[0],
                "stats": {k: row[k] for k in SHOT_FIELDS},
            }
        )
    require(
        bool(boxes) and set(player_stats) <= known_players, f"{identity}: missing player box rows"
    )
    # Known parser kind/result errors stay visible; they never become point authority.
    kind_map = {
        "Made Shot": "made_shot",
        "Missed Shot": "missed_shot",
        "Free Throw": "free_throw",
        "Rebound": "rebound",
        "Turnover": "turnover",
        "Foul": "foul",
        "Substitution": "substitution",
        "Timeout": "timeout",
        "Jump Ball": "jump_ball",
        "Period Begin": "period_start",
        "Period End": "period_end",
        "Violation": "violation",
        "Ejection": "ejection",
    }
    result = {
        "recipe": RECIPE,
        "data_version": version,
        "nba_game_id": identity,
        "season": game["season"],
        "season_type": game["season_type"],
        "game_date": game["game_date"],
        "home_team_id": game["home_team_id"],
        "away_team_id": game["away_team_id"],
        "game_row_sha256": digest(game),
        "source_url": capture["source_url"],
        "primary_capture_sha256": hashlib.sha256(raw).hexdigest(),
        "primary_action_count": len(actions),
        "events": derived,
        "period_receipts": period_receipts,
        "player_box_receipts": box_receipts,
        "raw_score_discrepancies": [
            e["sequence"]
            for e in derived
            if e["raw_score"] != {"home": 0, "away": 0} and e["raw_score"] != e["score_after"]
        ],
        "canonical_kind_discrepancies": [
            e["sequence"]
            for e in derived
            if kind_map.get(e["primary_action_type"]) != e["canonical_event_type"]
        ],
        "running_caption_discrepancies": caption_issues,
        "verified_fields": [
            "canonical order against primary action list",
            "period",
            "clock",
            "description",
            "team_id",
            "nba_player_id",
            "primary attempt fields",
        ],
        "untrusted_authorities": [
            "raw cumulative scoreboards",
            "running PTS captions",
            "canonical event/shot result classifications",
        ],
    }
    result["source_document_id"] = "derived-score-trajectory:" + digest(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", default=APPROVED_SHA)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        data, manifest = load_archive(args.bundle, args.expected_bundle_sha256)
        grouped = {
            collection: defaultdict(list)
            for collection in ("events", "period_scores", "player_game_stats")
        }
        known = {g["nba_game_id"] for g in data["games"]}
        require(
            {p.name for p in args.official_dir.glob("*.json")} == {f"{i}.json" for i in known},
            "Missing or foreign official capture population",
        )
        for collection, groups in grouped.items():
            for row in data[collection]:
                require(row["nba_game_id"] in known, "Foreign canonical source row")
                groups[row["nba_game_id"]].append(row)
        records = []
        for game in sorted(data["games"], key=lambda g: (g["game_date"], g["nba_game_id"])):
            identity = game["nba_game_id"]
            records.append(
                verify_game(
                    game,
                    sorted(grouped["events"][identity], key=lambda e: e["sequence"]),
                    sorted(
                        grouped["period_scores"][identity],
                        key=lambda r: (r["period"], r["team_id"]),
                    ),
                    sorted(
                        grouped["player_game_stats"][identity], key=lambda r: r["nba_player_id"]
                    ),
                    args.official_dir / f"{identity}.json",
                    manifest["version"],
                )
            )
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        (args.output / "failure.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
            )
            + "\n"
        )
        raise SystemExit(1) from exc
    trajectories = args.output / "derived-scoring-events.jsonl"
    with trajectories.open("x") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    report = {
        "status": "PER_ACTION_SCORING_SOURCE_VERIFIED",
        "recipe": RECIPE,
        "scope": (
            "Proposed derived source integrity; not indexed retrieval, target approval or gold"
        ),
        "bundle_sha256": args.expected_bundle_sha256,
        "content_sha256": manifest["content_sha256"],
        "data_version": manifest["version"],
        "games_verified": len(records),
        "canonical_events_verified": sum(len(r["events"]) for r in records),
        "period_rows_verified": sum(len(r["period_receipts"]) for r in records),
        "player_box_rows_verified": sum(len(r["player_box_receipts"]) for r in records),
        "trajectories_sha256": hashlib.sha256(trajectories.read_bytes()).hexdigest(),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), Path(__file__).with_name("audit_measure_sources.py"))
        },
        "sources": [
            {
                "nba_game_id": r["nba_game_id"],
                "source_document_id": r["source_document_id"],
                "primary_capture_sha256": r["primary_capture_sha256"],
                "raw_score_discrepancies": r["raw_score_discrepancies"],
                "canonical_kind_discrepancies": r["canonical_kind_discrepancies"],
                "running_caption_discrepancies": r["running_caption_discrepancies"],
            }
            for r in records
        ],
        "gold_approved": False,
        "frozen": False,
        "archive_rewritten": False,
    }
    artifact = args.output / "derived-source-review.json"
    artifact.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (args.output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
            for p in (artifact, trajectories)
        )
    )
    print(
        json.dumps(
            {key: report[key] for key in ("status", "games_verified", "canonical_events_verified")}
        )
    )


if __name__ == "__main__":
    main()
