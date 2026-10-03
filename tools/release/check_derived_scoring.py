"""Network-denied per-action derived-source CLI E2E, specified before implementation."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPROVED_SHA = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fixture():
    kinds = [
        (1, "11:00", "NYK", 11, "made_shot", "Made Shot", "Player 3PT (3 PTS)", 3, "Made", 3, 0),
        (
            1,
            "10:00",
            "BOS",
            22,
            "made_shot",
            "Made Shot",
            "Opponent layup (2 PTS)",
            2,
            "Made",
            3,
            2,
        ),
        (
            1,
            "09:00",
            "NYK",
            11,
            "free_throw",
            "Free Throw",
            "MISS Player Free Throw 1 of 2",
            0,
            "",
            0,
            0,
        ),
        (
            1,
            "09:00",
            "NYK",
            11,
            "free_throw",
            "Free Throw",
            "Player Free Throw 2 of 2 (4 PTS)",
            0,
            "",
            3,
            3,
        ),
        (2, "10:00", "NYK", 11, "made_shot", "Made Shot", "Player layup (6 PTS)", 2, "Made", 6, 2),
        (
            2,
            "09:00",
            "BOS",
            22,
            "made_shot",
            "Made Shot",
            "Opponent layup (4 PTS)",
            2,
            "Made",
            6,
            4,
        ),
        (2, "08:00", "NYK", 11, "missed_shot", "Missed Shot", "MISS Player 3PT", 3, "Missed", 0, 0),
        (
            2,
            "07:00",
            "NYK",
            11,
            "missed_shot",
            "Violation",
            "Player Violation:Kicked Ball",
            0,
            "",
            6,
            4,
        ),
        (4, "00:00", None, None, "period_end", "Period End", "End of period", 0, "", 6, 4),
    ]
    game = {
        "nba_game_id": "fixture",
        "season": "2025-26",
        "season_type": "regular",
        "game_date": "2026-01-01",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "home_score": 6,
        "away_score": 4,
        "status": "final",
    }
    data = {"games": [game], "events": [], "period_scores": [], "player_game_stats": []}
    actions = []
    numbers = [10, 12, 14, 9, 18, 20, 22, 24, 24]
    for seq, row in enumerate(kinds, 1):
        period, clock, team, player, kind, action_kind, description, value, result, home, away = row
        data["events"].append(
            {
                "nba_game_id": "fixture",
                "sequence": seq,
                "period": period,
                "clock": clock,
                "team_id": team,
                "nba_player_id": player,
                "event_type": kind,
                "description": description,
                "home_score": home,
                "away_score": away,
                "shot_result": "made" if kind == "free_throw" else result.lower() or None,
            }
        )
        minutes, seconds = clock.split(":")
        actions.append(
            {
                "actionNumber": numbers[seq - 1],
                "actionId": seq,
                "period": period,
                "clock": f"PT{minutes}M{seconds}.00S",
                "teamTricode": team or "",
                "personId": player or 0,
                "actionType": action_kind,
                "description": description,
                "isFieldGoal": int(action_kind in {"Made Shot", "Missed Shot"}),
                "shotValue": value,
                "shotResult": result,
                "scoreHome": str(home),
                "scoreAway": str(away),
                "pointsTotal": home + away,
            }
        )
    for period, pair in enumerate(((4, 2), (2, 2), (0, 0), (0, 0)), 1):
        for team, points in zip(("NYK", "BOS"), pair, strict=True):
            data["period_scores"].append(
                {"nba_game_id": "fixture", "period": period, "team_id": team, "points": points}
            )
    for player, team, stats in (
        (11, "NYK", [6, 2, 3, 1, 2, 1, 2]),
        (22, "BOS", [4, 2, 2, 0, 0, 0, 0]),
    ):
        fields = (
            "points",
            "field_goals_made",
            "field_goals_attempted",
            "three_pointers_made",
            "three_pointers_attempted",
            "free_throws_made",
            "free_throws_attempted",
        )
        data["player_game_stats"].append(
            {
                "nba_game_id": "fixture",
                "nba_player_id": player,
                "team_id": team,
                **dict(zip(fields, stats, strict=True)),
            }
        )
    bundle = {
        "manifest": {
            "version": "fixture",
            "season": "2025-26",
            "expected_games": 1,
            "expected_game_ids": ["fixture"],
            "content_sha256": digest(data),
        },
        "data": data,
    }
    capture = {
        "source_url": "https://www.nba.com/game/bos-vs-nyk-fixture/play-by-play",
        "method": "NBA page __NEXT_DATA__.props.pageProps.playByPlay",
        "play_by_play": {"gameId": "fixture", "actions": actions},
    }
    return bundle, capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    command = ROOT / "tools/release/verify_derived_scoring.py"
    bootstrap = (
        "import socket,runpy,sys; "
        "socket.socket=lambda *a,**k: "
        "(_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.path.insert(0,str(__import__('pathlib').Path(sys.argv[1]).parent)); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    environment = {**os.environ, "AI_API_KEY": "", "OPENROUTER_API_KEY": "", "REDIS_URL": ""}
    receipts = []

    def run(name, bundle, official, sha, destination):
        argv = [
            sys.executable,
            "-c",
            bootstrap,
            str(command),
            "--bundle",
            str(bundle),
            "--official-dir",
            str(official),
            "--expected-bundle-sha256",
            sha,
            "--output",
            str(destination),
        ]
        result = subprocess.run(argv, env=environment, text=True, capture_output=True, timeout=90)
        receipts.append(
            {
                "name": name,
                "argv": argv,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        return result.returncode

    def inputs(name, bundle, capture):
        directory = args.output / f"{name}-inputs"
        directory.mkdir()
        raw = gzip.compress(json.dumps(bundle, sort_keys=True).encode(), mtime=0)
        path = directory / "bundle.json.gz"
        path.write_bytes(raw)
        official = directory / "official"
        official.mkdir()
        (official / "fixture.json").write_text(json.dumps(capture, sort_keys=True))
        return path, official, hashlib.sha256(raw).hexdigest()

    status = "failed"
    try:
        bundle, capture = fixture()
        path, official, sha = inputs("valid", bundle, capture)
        first, repeat = args.output / "first", args.output / "repeat"
        assert (
            run(
                "explicit contributions, missed FT, nonmonotonic action numbers",
                path,
                official,
                sha,
                first,
            )
            == 0
        )
        report = json.loads((first / "derived-source-review.json").read_text())
        assert report["games_verified"] == 1 and report["canonical_events_verified"] == 9
        trajectory = json.loads((first / "derived-scoring-events.jsonl").read_text())
        assert [r["points"] for r in trajectory["events"]] == [3, 2, 0, 1, 2, 2, 0, 0, 0]
        assert trajectory["events"][3]["score_after"] == {"home": 4, "away": 2}
        assert trajectory["events"][3]["raw_score"] == {"home": 3, "away": 3}
        assert report["gold_approved"] is False and report["archive_rewritten"] is False
        assert run("repeat identical bytes", path, official, sha, repeat) == 0
        for name in ("derived-source-review.json", "derived-scoring-events.jsonl", "SHA256SUMS"):
            assert (first / name).read_bytes() == (repeat / name).read_bytes()
        before = (first / "derived-source-review.json").read_bytes()
        assert run("reject overwrite", path, official, sha, first) != 0
        assert (first / "derived-source-review.json").read_bytes() == before
        assert (
            run("reject bundle binding", path, official, "0" * 64, args.output / "wrong-binding")
            == 1
        )

        for name, mutate in (
            (
                "duplicate-action-id",
                lambda b, c: c["play_by_play"]["actions"][1].update(actionId=1),
            ),
            ("foreign-source-game", lambda b, c: c["play_by_play"].update(gameId="foreign")),
            ("changed-actor", lambda b, c: c["play_by_play"]["actions"][0].update(personId=22)),
            (
                "changed-clock",
                lambda b, c: c["play_by_play"]["actions"][0].update(clock="PT10M59.00S"),
            ),
            (
                "changed-description",
                lambda b, c: c["play_by_play"]["actions"][0].update(description="Other shot"),
            ),
            (
                "changed-team",
                lambda b, c: c["play_by_play"]["actions"][0].update(teamTricode="BOS"),
            ),
            (
                "changed-kind",
                lambda b, c: c["play_by_play"]["actions"][0].update(actionType="Free Throw"),
            ),
            (
                "invalid-shot-value",
                lambda b, c: c["play_by_play"]["actions"][0].update(shotValue=4),
            ),
            (
                "changed-shot-value",
                lambda b, c: c["play_by_play"]["actions"][0].update(shotValue=2),
            ),
            (
                "conflicting-shot-result",
                lambda b, c: c["play_by_play"]["actions"][0].update(shotResult="Missed"),
            ),
            (
                "unknown-scoring-kind",
                lambda b, c: c["play_by_play"]["actions"][0].update(actionType="Bonus Points"),
            ),
            ("missing-canonical-attempt", lambda b, c: b["data"]["events"].pop(2)),
            ("missing-primary-attempt", lambda b, c: c["play_by_play"]["actions"].pop(2)),
            (
                "duplicate-canonical-sequence",
                lambda b, c: b["data"]["events"][1].update(sequence=1),
            ),
            ("reordered-primary-scoring", lambda b, c: c["play_by_play"]["actions"].reverse()),
            ("wrong-period-total", lambda b, c: b["data"]["period_scores"][0].update(points=3)),
            ("wrong-player-total", lambda b, c: b["data"]["player_game_stats"][0].update(points=7)),
            (
                "wrong-player-fga",
                lambda b, c: b["data"]["player_game_stats"][0].update(field_goals_attempted=2),
            ),
            (
                "wrong-player-3pa",
                lambda b, c: b["data"]["player_game_stats"][0].update(three_pointers_attempted=1),
            ),
            (
                "wrong-player-fta",
                lambda b, c: b["data"]["player_game_stats"][0].update(free_throws_attempted=1),
            ),
            ("missing-player", lambda b, c: b["data"]["player_game_stats"].pop()),
            (
                "duplicate-player",
                lambda b, c: b["data"]["player_game_stats"].append(
                    copy.deepcopy(b["data"]["player_game_stats"][0])
                ),
            ),
        ):
            bad_bundle, bad_capture = copy.deepcopy(bundle), copy.deepcopy(capture)
            mutate(bad_bundle, bad_capture)
            for seq, row in enumerate(bad_bundle["data"]["events"], 1):
                if name != "duplicate-canonical-sequence":
                    row["sequence"] = seq
            bad_bundle["manifest"]["content_sha256"] = digest(bad_bundle["data"])
            path, official, sha = inputs(name, bad_bundle, bad_capture)
            destination = args.output / name
            assert run(name, path, official, sha, destination) == 1, name
            assert (destination / "failure.json").exists(), name
            assert not (destination / "derived-source-review.json").exists(), name

        actual = args.output / "approved"
        assert (
            run(
                "full approved archive with independent NBA actions",
                args.bundle,
                args.official_dir,
                APPROVED_SHA,
                actual,
            )
            == 0
        )
        verified = json.loads((actual / "derived-source-review.json").read_text())
        assert verified["games_verified"] == 101
        assert verified["canonical_events_verified"] == 46500
        assert verified["period_rows_verified"] == 816
        assert verified["player_box_rows_verified"] == 2748
        records = [
            json.loads(line)
            for line in (actual / "derived-scoring-events.jsonl").read_text().splitlines()
        ]
        mil = next(r for r in records if r["nba_game_id"] == "0022500125")
        e197, e198 = (mil["events"][n - 1] for n in (197, 198))
        assert e197["points"] == 1 and e197["score_after"] == {"home": 52, "away": 66}
        assert e198["points"] == 3 and e198["score_after"] == {"home": 55, "away": 66}
        assert e197["raw_score"] == {"home": 55, "away": 66}
        assert e198["raw_score"] == {"home": 55, "away": 65}
        status = "passed"
    finally:
        (args.output / "e2e-result.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "scope": "Per-action source CLI E2E; not indexed retrieval or gold",
                    "socket_creation_denied": True,
                    "receipts": receipts,
                    "artifacts": {
                        str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(args.output.rglob("*"))
                        if p.is_file()
                    },
                },
                indent=2,
            )
            + "\n"
        )
    print(status)


if __name__ == "__main__":
    main()
