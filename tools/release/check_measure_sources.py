"""Network-denied source-audit CLI E2E specification, written before implementation."""

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
    data = {"games": [], "events": [], "period_scores": []}
    for identity, phase, home, away, quarters in (
        ("fixture-a", "regular", "NYK", "BOS", [(2, 2), (2, 2), (3, 7), (3, 1)]),
        ("fixture-b", "playoffs", "MIL", "NYK", [(2, 2), (3, 2), (1, 3), (3, 3)]),
    ):
        game = {
            "nba_game_id": identity,
            "season": "2025-26",
            "season_type": phase,
            "game_date": "2026-01-01",
            "home_team_id": home,
            "away_team_id": away,
            "home_score": sum(q[0] for q in quarters),
            "away_score": sum(q[1] for q in quarters),
            "status": "final",
        }
        data["games"].append(game)
        score = [0, 0]
        sequence = 0
        for period, quarter in enumerate(quarters, 1):
            for team, points in zip((home, away), quarter, strict=True):
                data["period_scores"].append(
                    {
                        "nba_game_id": identity,
                        "team_id": team,
                        "period": period,
                        "points": points,
                    }
                )
            for side, points in enumerate(quarter):
                for _ in range(points):
                    sequence += 1
                    score[side] += 1
                    data["events"].append(
                        {
                            "nba_game_id": identity,
                            "sequence": sequence,
                            "period": period,
                            "clock": f"11:{59 - sequence:02d}",
                            "home_score": score[0],
                            "away_score": score[1],
                            "team_id": (home, away)[side],
                            "event_type": "free_throw",
                            "description": "Made free throw",
                        }
                    )
            sequence += 1
            data["events"].append(
                {
                    "nba_game_id": identity,
                    "sequence": sequence,
                    "period": period,
                    "clock": "00:00",
                    "home_score": 0,
                    "away_score": 0,
                    "team_id": None,
                    "event_type": "period_end",
                    "description": "Period end",
                }
            )
    return {
        "manifest": {
            "version": "fixture",
            "season": "2025-26",
            "expected_games": 2,
            "expected_game_ids": ["fixture-a", "fixture-b"],
            "content_sha256": digest(data),
        },
        "data": data,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--official-actions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    command = ROOT / "tools/release/audit_measure_sources.py"
    bootstrap = (
        "import socket,runpy,sys; "
        "socket.socket=lambda *a,**k: "
        "(_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    environment = {**os.environ, "AI_API_KEY": "", "OPENROUTER_API_KEY": "", "REDIS_URL": ""}
    receipts = []

    def run(name, bundle, sha, destination, official=None):
        argv = [
            sys.executable,
            "-c",
            bootstrap,
            str(command),
            "--bundle",
            str(bundle),
            "--expected-bundle-sha256",
            sha,
            "--output",
            str(destination),
        ]
        if official:
            argv.extend(["--official-actions", str(official)])
        result = subprocess.run(argv, env=environment, text=True, capture_output=True, timeout=60)
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

    def save_bundle(name, value):
        path = args.output / f"{name}.json.gz"
        raw = gzip.compress(json.dumps(value, sort_keys=True).encode(), mtime=0)
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    status = "failed"
    try:
        first, repeat = args.output / "first", args.output / "repeat"
        assert (
            run("approved archive blocked", args.bundle, APPROVED_SHA, first, args.official_actions)
            == 2
        )
        report = json.loads((first / "measure-source-audit.json").read_text())
        assert report["game_count"] == 101 and report["event_count"] == 46500
        assert report["sequence_complete_games"] == 100
        assert report["quarter_complete_games"] == 101
        bad = [g for g in report["games"] if g["sequence_issues"]]
        assert [g["nba_game_id"] for g in bad] == ["0022500125"]
        assert [
            (r["kind"], r["sequence"])
            for r in bad[0]["sequence_issues"]
            if r["kind"] in {"simultaneous_scoring", "score_decrease"}
        ] == [("simultaneous_scoring", 197), ("score_decrease", 198)]
        archive = report["third_quarter_candidates"]["archive"]
        assert archive["fewest_knicks_points"]["value"] == 11
        assert archive["fewest_knicks_points"]["game_ids"] == ["0022500835"]
        assert archive["worst_knicks_margin"]["value"] == -15
        assert archive["worst_knicks_margin"]["game_ids"] == [
            "0022500003",
            "0022500125",
            "0022500816",
        ]
        if args.official_actions:
            corroborated = report["upstream_corroboration"]["rows"]
            assert [(r["sequence"], r["action_number"]) for r in corroborated] == [
                (197, 308),
                (198, 318),
                (199, 309),
            ]
            altered = json.loads(args.official_actions.read_text())
            next(a for a in altered["play_by_play"]["actions"] if a["actionNumber"] == 308)[
                "scoreHome"
            ] = "52"
            altered_path = args.output / "altered-official.json"
            altered_path.write_text(json.dumps(altered))
            assert (
                run(
                    "reject inconsistent upstream capture",
                    args.bundle,
                    APPROVED_SHA,
                    args.output / "altered-official",
                    altered_path,
                )
                == 1
            )
        assert (
            run("repeat approved audit", args.bundle, APPROVED_SHA, repeat, args.official_actions)
            == 2
        )
        for name in ("measure-source-audit.json", "SHA256SUMS"):
            assert (first / name).read_bytes() == (repeat / name).read_bytes()
        before = (first / "measure-source-audit.json").read_bytes()
        assert run("refuse overwrite", args.bundle, APPROVED_SHA, first) != 0
        assert (first / "measure-source-audit.json").read_bytes() == before
        assert (
            run("reject changed binding", args.bundle, "0" * 64, args.output / "wrong-binding") == 1
        )

        original = fixture()
        path, sha = save_bundle("valid-fixture", original)
        destination = args.output / "valid-fixture"
        assert run("complete synthetic population", path, sha, destination) == 0
        synthetic = json.loads((destination / "measure-source-audit.json").read_text())
        assert synthetic["sequence_complete_games"] == 2
        assert synthetic["third_quarter_candidates"]["archive"]["fewest_knicks_points"] == {
            "value": 3,
            "game_ids": ["fixture-a", "fixture-b"],
        }
        assert synthetic["third_quarter_candidates"]["archive"]["worst_knicks_margin"] == {
            "value": -4,
            "game_ids": ["fixture-a"],
        }
        assert synthetic["third_quarter_candidates"]["regular"]["fewest_knicks_points"][
            "game_ids"
        ] == ["fixture-a"]
        assert synthetic["third_quarter_candidates"]["playoffs"]["fewest_knicks_points"][
            "game_ids"
        ] == ["fixture-b"]

        for name, mutation, exit_code, issue in (
            (
                "duplicate-sequence",
                lambda d: d["events"].append(copy.deepcopy(d["events"][0])),
                2,
                "duplicate_sequence",
            ),
            ("missing-sequence", lambda d: d["events"].pop(1), 2, "noncontiguous_sequence"),
            (
                "missing-events",
                lambda d: d.update(
                    events=[r for r in d["events"] if r["nba_game_id"] != "fixture-a"]
                ),
                2,
                "missing_events",
            ),
            ("negative-score", lambda d: d["events"][0].update(home_score=-1), 1, None),
            ("invalid-score-type", lambda d: d["events"][0].update(home_score=True), 1, None),
            ("foreign-event", lambda d: d["events"][0].update(nba_game_id="foreign"), 1, None),
            ("duplicate-game", lambda d: d["games"].append(copy.deepcopy(d["games"][0])), 1, None),
            ("missing-game", lambda d: d["games"].pop(), 1, None),
            ("nonfinal-game", lambda d: d["games"][0].update(status="live"), 1, None),
            ("foreign-team", lambda d: d["games"][0].update(home_team_id="LAL"), 1, None),
            (
                "duplicate-period",
                lambda d: d["period_scores"].append(copy.deepcopy(d["period_scores"][0])),
                2,
                "duplicate_period",
            ),
            ("missing-quarter", lambda d: d["period_scores"].pop(4), 2, "missing_period"),
            (
                "wrong-period-total",
                lambda d: d["period_scores"][0].update(points=9),
                2,
                "period_final_mismatch",
            ),
            (
                "wrong-final",
                lambda d: d["games"][0].update(home_score=11),
                2,
                "event_final_mismatch",
            ),
            (
                "wrong-team-scoring",
                lambda d: d["events"][0].update(team_id="BOS"),
                2,
                "wrong_team_scoring",
            ),
            (
                "score-decrease",
                lambda d: d["events"][1].update(home_score=0, away_score=1),
                2,
                "score_decrease",
            ),
            (
                "simultaneous-scoring",
                lambda d: d["events"][0].update(away_score=1),
                2,
                "simultaneous_scoring",
            ),
            (
                "oversized-scoring",
                lambda d: d["events"][0].update(home_score=4),
                2,
                "invalid_scoring_increment",
            ),
        ):
            value = copy.deepcopy(original)
            mutation(value["data"])
            value["manifest"]["content_sha256"] = digest(value["data"])
            path, sha = save_bundle(name, value)
            destination = args.output / name
            assert run(name, path, sha, destination) == exit_code
            if issue:
                result = json.loads((destination / "measure-source-audit.json").read_text())
                issues = [
                    i["kind"]
                    for g in result["games"]
                    for i in g["sequence_issues"] + g["quarter_issues"]
                ]
                assert issue in issues, (name, issues)
                if name in {"duplicate-period", "missing-quarter", "wrong-period-total"}:
                    assert result["third_quarter_candidates"]["archive"] is None
            else:
                assert (destination / "failure.json").exists()
                assert not (destination / "measure-source-audit.json").exists()
        changed = copy.deepcopy(original)
        changed["data"]["games"][0]["home_score"] = 11
        path, sha = save_bundle("wrong-content-manifest", changed)
        assert run("wrong content manifest", path, sha, args.output / "wrong-content-manifest") == 1
        status = "passed"
    finally:
        result = {
            "status": status,
            "scope": "offline CLI E2E, not approved gold or readiness",
            "socket_creation_denied": True,
            "receipts": receipts,
            "artifacts": {
                str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(args.output.rglob("*"))
                if p.is_file()
            },
        }
        (args.output / "e2e-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(status)


if __name__ == "__main__":
    main()
