"""Audit complete canonical measure populations without repairing or approving sources.

Exit 0 means the supplied source populations passed this integrity audit only.
Exit 2 retains a blocked coverage report; exit 1 rejects invalid inputs.
No runtime, credentials, network, retrieval, evaluation labels or approval path.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

APPROVED_SHA = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def integer(value: Any, *, positive: bool = False) -> bool:
    return type(value) is int and value >= (1 if positive else 0)


def load_archive(path: Path, expected_sha: str) -> tuple[dict, dict]:
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_sha, "Bundle digest changed")
    bundle = json.loads(gzip.decompress(raw))
    data, manifest = bundle["data"], bundle["manifest"]
    require(digest(data) == manifest["content_sha256"], "Content manifest changed")
    games = data["games"]
    ids = [g["nba_game_id"] for g in games]
    expected = manifest["expected_game_ids"]
    require(
        bool(games)
        and len(ids) == len(set(ids)) == manifest["expected_games"]
        and len(expected) == len(set(expected)) == len(ids)
        and set(ids) == set(expected),
        "Missing or duplicate scheduled games",
    )
    game_map = {g["nba_game_id"]: g for g in games}
    for game in games:
        require(
            game["status"] == "final"
            and game["season"] == manifest["season"]
            and game["home_team_id"] != game["away_team_id"]
            and "NYK" in {game["home_team_id"], game["away_team_id"]}
            and game["season_type"] in {"regular", "play_in", "playoffs"}
            and integer(game["home_score"])
            and integer(game["away_score"])
            and game["home_score"] != game["away_score"],
            "Invalid final Knicks game population",
        )
    for collection in ("events", "period_scores"):
        for row in data[collection]:
            require(row["nba_game_id"] in game_map, "Foreign canonical source row")
            require(integer(row["period"], positive=True), "Invalid canonical period")
            if collection == "events":
                require(
                    integer(row["sequence"], positive=True)
                    and integer(row["home_score"])
                    and integer(row["away_score"]),
                    "Invalid canonical sequence or scoreboard",
                )
            else:
                game = game_map[row["nba_game_id"]]
                require(
                    row["team_id"] in {game["home_team_id"], game["away_team_id"]}
                    and integer(row["points"]),
                    "Invalid canonical period score",
                )
    return data, manifest


def sequence_issues(game: dict, events: list[dict]) -> list[dict]:
    issues = []
    sequences = [e["sequence"] for e in events]
    if not events:
        return [{"kind": "missing_events", "sequence": None}]
    if len(set(sequences)) != len(sequences):
        issues.append({"kind": "duplicate_sequence", "sequence": None})
    if sequences != list(range(1, len(events) + 1)):
        issues.append({"kind": "noncontiguous_sequence", "sequence": None})
    previous = (0, 0)
    for event in events:
        current = (event["home_score"], event["away_score"])
        current = previous if current == (0, 0) else current
        change = tuple(a - b for a, b in zip(current, previous, strict=True))
        kinds = []
        if min(change) < 0:
            kinds.append("score_decrease")
        if min(change) > 0:
            kinds.append("simultaneous_scoring")
        positive = [side for side, points in enumerate(change) if points > 0]
        if len(positive) == 1 and min(change) >= 0:
            side = positive[0]
            if event["team_id"] != (game["home_team_id"], game["away_team_id"])[side]:
                kinds.append("wrong_team_scoring")
            allowed = (
                {1}
                if event["event_type"] == "free_throw"
                else ({2, 3} if event["event_type"] == "made_shot" else set())
            )
            if change[side] not in allowed:
                kinds.append("invalid_scoring_increment")
        for kind in kinds:
            issues.append(
                {
                    "kind": kind,
                    "sequence": event["sequence"],
                    "canonical_id": f"event:{game['nba_game_id']}:{event['sequence']}",
                    "row_sha256": digest(event),
                    "row": event,
                    "score_before": {"home": previous[0], "away": previous[1]},
                    "score_after": {"home": current[0], "away": current[1]},
                    "score_change": {"home": change[0], "away": change[1]},
                }
            )
        previous = current
    if previous != (game["home_score"], game["away_score"]):
        issues.append({"kind": "event_final_mismatch", "sequence": events[-1]["sequence"]})
    return issues


def quarter_issues(game: dict, rows: list[dict], events: list[dict]) -> list[dict]:
    issues = []
    identities = [(r["team_id"], r["period"]) for r in rows]
    if len(identities) != len(set(identities)):
        issues.append({"kind": "duplicate_period"})
    last_period = max([4, *(r["period"] for r in rows), *(e["period"] for e in events)])
    expected = {
        (team, period)
        for team in (game["home_team_id"], game["away_team_id"])
        for period in range(1, last_period + 1)
    }
    if set(identities) != expected:
        issues.append({"kind": "missing_period"})
    for side in ("home", "away"):
        total = sum(r["points"] for r in rows if r["team_id"] == game[f"{side}_team_id"])
        if total != game[f"{side}_score"]:
            issues.append({"kind": "period_final_mismatch", "team_id": game[f"{side}_team_id"]})
    return issues


def third_quarter_candidates(games: list[dict]) -> dict | None:
    if not games or any(g["quarter_issues"] for g in games):
        return None
    points = min(g["third_quarter"]["knicks_points"] for g in games)
    margin = min(g["third_quarter"]["knicks_margin"] for g in games)
    return {
        "fewest_knicks_points": {
            "value": points,
            "game_ids": sorted(
                g["nba_game_id"] for g in games if g["third_quarter"]["knicks_points"] == points
            ),
        },
        "worst_knicks_margin": {
            "value": margin,
            "game_ids": sorted(
                g["nba_game_id"] for g in games if g["third_quarter"]["knicks_margin"] == margin
            ),
        },
    }


def corroborate(path: Path, games: list[dict]) -> dict:
    raw = path.read_bytes()
    capture = json.loads(raw)
    upstream = capture["play_by_play"]
    game = next((g for g in games if g["nba_game_id"] == upstream["gameId"]), None)
    if game is None:
        raise ValueError("Upstream capture game is outside this archive")
    require(
        capture["source_url"].startswith("https://www.nba.com/game/")
        and upstream["gameId"] in capture["source_url"],
        "Invalid supplied upstream source URL",
    )
    actions = defaultdict(list)
    for action in upstream["actions"]:
        clock = re.fullmatch(r"PT(\d+)M(\d+(?:\.\d+)?)S", action["clock"])
        if clock:
            key = (
                action["period"],
                f"{int(clock[1]):02d}:{int(float(clock[2])):02d}",
                action["description"],
                action["teamTricode"] or None,
            )
            actions[key].append(action)
    rows = []
    seen = set()
    for issue in game["sequence_issues"]:
        row = issue.get("row")
        if row is None or row["sequence"] in seen:
            continue
        seen.add(row["sequence"])
        matches = actions[(row["period"], row["clock"], row["description"], row["team_id"])]
        require(len(matches) == 1, "Missing or ambiguous upstream action for bad canonical row")
        action = matches[0]
        require(
            int(action["scoreHome"] or 0) == row["home_score"]
            and int(action["scoreAway"] or 0) == row["away_score"],
            "Upstream capture differs from bad canonical scoreboard",
        )
        rows.append(
            {
                "sequence": row["sequence"],
                "canonical_row_sha256": digest(row),
                "action_number": action["actionNumber"],
                "action_id": action["actionId"],
                "upstream_action_sha256": digest(action),
                "upstream_action": action,
            }
        )
    return {
        "scope": "Supplied NBA page capture corroborates rows; no correction or approval",
        "source_url": capture["source_url"],
        "capture_sha256": hashlib.sha256(raw).hexdigest(),
        "game_id": upstream["gameId"],
        "rows": rows,
    }


def audit(data: dict, manifest: dict, bundle_sha: str, official: Path | None) -> dict:
    events_by_game, periods_by_game = defaultdict(list), defaultdict(list)
    for row in data["events"]:
        events_by_game[row["nba_game_id"]].append(row)
    for row in data["period_scores"]:
        periods_by_game[row["nba_game_id"]].append(row)
    games = []
    for game in sorted(data["games"], key=lambda g: (g["game_date"], g["nba_game_id"])):
        identity = game["nba_game_id"]
        events = sorted(events_by_game[identity], key=lambda e: e["sequence"])
        periods = sorted(periods_by_game[identity], key=lambda r: (r["period"], r["team_id"]))
        sequence_errors = sequence_issues(game, events)
        quarter_errors = quarter_issues(game, periods, events)
        q3 = None
        if not quarter_errors:
            own = next(r for r in periods if r["period"] == 3 and r["team_id"] == "NYK")
            opponent = next(r for r in periods if r["period"] == 3 and r["team_id"] != "NYK")
            q3 = {
                "knicks_points": own["points"],
                "opponent_points": opponent["points"],
                "knicks_margin": own["points"] - opponent["points"],
                "sources": [
                    {
                        "canonical_id": f"period:{identity}:{r['team_id']}:3",
                        "row_sha256": digest(r),
                        "row": r,
                    }
                    for r in (own, opponent)
                ],
            }
        games.append(
            {
                "nba_game_id": identity,
                "game_date": game["game_date"],
                "season_type": game["season_type"],
                "game_row_sha256": digest(game),
                "event_count": len(events),
                "ordered_events_sha256": digest(events),
                "period_scores_sha256": digest(periods),
                "sequence_issues": sequence_errors,
                "quarter_issues": quarter_errors,
                "third_quarter": q3,
            }
        )
    blocked = any(g["sequence_issues"] or g["quarter_issues"] for g in games)
    return {
        "schema_version": 1,
        "status": "BLOCKED_SOURCE_COVERAGE" if blocked else "SOURCE_COVERAGE_VERIFIED",
        "scope": "Source integrity and alternative Q3 candidates only; not retrieval or gold",
        "bundle_sha256": bundle_sha,
        "data_version": manifest["version"],
        "content_sha256": manifest["content_sha256"],
        "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "game_count": len(games),
        "event_count": len(data["events"]),
        "sequence_complete_games": sum(not g["sequence_issues"] for g in games),
        "quarter_complete_games": sum(not g["quarter_issues"] for g in games),
        "third_quarter_candidates": {
            "archive": third_quarter_candidates(games),
            **{
                phase: third_quarter_candidates([g for g in games if g["season_type"] == phase])
                for phase in sorted({g["season_type"] for g in games})
            },
        },
        "games": games,
        "upstream_corroboration": corroborate(official, games) if official else None,
        "measure_default_selected": False,
        "evaluation_contexts_modified": False,
        "gold_approved": False,
        "frozen": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", default=APPROVED_SHA)
    parser.add_argument("--official-actions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        data, manifest = load_archive(args.bundle, args.expected_bundle_sha256)
        report = audit(data, manifest, args.expected_bundle_sha256, args.official_actions)
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
    artifact = args.output / "measure-source-audit.json"
    artifact.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (args.output / "SHA256SUMS").write_text(
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "game_count",
                    "sequence_complete_games",
                    "quarter_complete_games",
                )
            }
        )
    )
    raise SystemExit(2 if report["status"] == "BLOCKED_SOURCE_COVERAGE" else 0)


if __name__ == "__main__":
    main()
