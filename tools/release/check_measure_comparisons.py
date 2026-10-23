"""Network-denied subprocess E2E for independently pinned comparison evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).with_name("build_measure_comparisons.py")


def fixture(identity: str, phase: str, scoring: list[tuple[str, int, int]]) -> dict:
    game = {
        "recipe": "nba-action-scoring-trajectory-v1",
        "nba_game_id": identity,
        "data_version": "fixture.1",
        "season": "2025-26",
        "season_type": phase,
        "primary_capture_sha256": hashlib.sha256(identity.encode()).hexdigest(),
        "game_date": "2026-01-01",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "events": [],
        "period_receipts": [],
    }
    score = {"home": 0, "away": 0}
    periods = {(t, p): 0 for t in ("NYK", "BOS") for p in range(1, 5)}
    for seq, (team, points, period) in enumerate(scoring, 1):
        before = dict(score)
        if points:
            score["home" if team == "NYK" else "away"] += points
            periods[(team, period)] += points
        game["events"].append(
            {
                "canonical_id": f"event:{identity}:{seq}",
                "sequence": seq,
                "period": period,
                "clock": "01:00",
                "team_id": team or None,
                "points": points,
                "score_before": before,
                "score_after": dict(score),
                "raw_score": {"home": 99, "away": 99},
            }
        )
    game["period_receipts"] = [
        {"canonical_id": f"period:{identity}:{team}:{period}", "points": points}
        for (team, period), points in periods.items()
    ]
    body = json.dumps(game, sort_keys=True, separators=(",", ":")).encode()
    game["source_document_id"] = "derived-score-trajectory:" + hashlib.sha256(body).hexdigest()
    return game


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    status = "failed"
    guard = """import runpy,socket,sys
class Denied(socket.socket):
 def __init__(self,*a,**k): raise AssertionError('Network is forbidden')
socket.socket=Denied
sys.path.insert(0,str(__import__('pathlib').Path(sys.argv[1]).parent))
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
"""

    def run(
        name: str, path: Path, output: Path, expected: str | None = None, review: Path | None = None
    ) -> int:
        sha = expected or hashlib.sha256(path.read_bytes()).hexdigest()
        review = review or (
            path.with_suffix(".review.json")
            if path.parent == args.output
            else path.with_name("derived-source-review.json")
        )
        review_sha = hashlib.sha256(review.read_bytes()).hexdigest()
        command = [
            sys.executable,
            "-c",
            guard,
            str(TARGET),
            "--trajectories",
            str(path),
            "--expected-trajectories-sha256",
            sha,
            "--source-review",
            str(review),
            "--expected-source-review-sha256",
            review_sha,
            "--output",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        receipts.append(
            {
                "name": name,
                "argv": command[3:],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        return result.returncode

    def inputs(name: str, records: list[dict]) -> Path:
        path = args.output / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
        path.with_suffix(".review.json").write_text(
            json.dumps(
                {
                    "status": "PER_ACTION_SCORING_SOURCE_VERIFIED",
                    "recipe": "nba-action-scoring-trajectory-v1",
                    "data_version": "fixture.1",
                    "trajectories_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "games_verified": len(records),
                    "canonical_events_verified": sum(len(r["events"]) for r in records),
                    "period_rows_verified": sum(len(r["period_receipts"]) for r in records),
                    "sources": [
                        {
                            k: r[k]
                            for k in ("nba_game_id", "source_document_id", "primary_capture_sha256")
                        }
                        for r in records
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        return path

    try:
        records = [
            fixture(
                "regular",
                "regular",
                [
                    ("BOS", 3, 1),
                    ("NYK", 2, 1),
                    ("BOS", 2, 1),
                    ("", 0, 2),
                    ("NYK", 3, 2),
                    ("NYK", 2, 2),
                    ("BOS", 3, 3),
                    ("", 0, 4),
                ],
            ),
            fixture(
                "postseason",
                "playoffs",
                [
                    ("NYK", 3, 1),
                    ("BOS", 2, 1),
                    ("NYK", 1, 1),
                    ("NYK", 2, 2),
                    ("BOS", 2, 2),
                    ("", 0, 4),
                ],
            ),
        ]
        path = inputs("valid", records)
        first, repeat = args.output / "first", args.output / "repeat"
        assert run("explicit alternatives, boundary ties, no raw-score authority", path, first) == 0
        report = json.loads((first / "measure-comparisons.json").read_text())
        archive = report["populations"]["complete_archive"]
        assert archive["game_count"] == 2
        expected = {
            "q3_fewest_points": 0,
            "q3_worst_margin": -3,
            "largest_observed_deficit": 3,
            "largest_deficit_later_tied": 3,
            "largest_deficit_later_led": 3,
            "largest_deficit_in_eventual_win": None,
            "knicks_largest_unanswered_run": 5,
            "opponent_largest_unanswered_run": 3,
            "knicks_largest_unrestricted_net_gain": 5,
            "largest_unrestricted_margin_decline": 3,
            "largest_positive_lead_surrendered": 2,
            "largest_positive_lead_surrendered_in_final_loss": 2,
        }
        for metric, value in expected.items():
            assert archive["extrema"][metric]["value"] == value, metric
        assert archive["extrema"]["q3_fewest_points"]["game_sources"] == [
            "game:postseason",
            "game:regular",
        ]
        regular = next(r for r in report["games"] if r["nba_game_id"] == "regular")
        assert len(regular["measures"]["largest_observed_deficit"]["boundaries"]) == 2
        run_boundaries = regular["measures"]["knicks_largest_unanswered_run"]["boundaries"]
        assert run_boundaries[0]["scoring_sources"] == ["event:regular:5", "event:regular:6"]
        assert report["gold_approved"] is False and report["ranked_receipts_created"] is False
        assert run("byte-identical repeat", path, repeat) == 0
        for name in ("measure-comparisons.json", "SHA256SUMS"):
            assert (first / name).read_bytes() == (repeat / name).read_bytes()
        before = (first / "measure-comparisons.json").read_bytes()
        assert run("refuse overwrite", path, first) != 0
        partial = inputs("partial", records[:1])
        assert (
            run(
                "reject reduced approved population",
                partial,
                args.output / "partial",
                review=path.with_suffix(".review.json"),
            )
            == 1
        )
        assert (first / "measure-comparisons.json").read_bytes() == before
        assert (
            run("reject changed pinned bytes", path, args.output / "wrong-binding", "0" * 64) == 1
        )

        def change_event(key, value):
            return lambda rows: rows[0]["events"][0].__setitem__(key, value)

        mutations = [
            ("duplicate-game", lambda rows: rows.append(copy.deepcopy(rows[0]))),
            ("unknown-phase", lambda rows: rows[0].__setitem__("season_type", "future")),
            ("mixed-version", lambda rows: rows[0].__setitem__("data_version", "other")),
            ("missing-order", change_event("sequence", 2)),
            ("negative-contribution", change_event("points", -1)),
            ("oversized-contribution", change_event("points", 4)),
            ("boolean-contribution", change_event("points", True)),
            ("foreign-actor", change_event("team_id", "LAL")),
            ("inconsistent-before", change_event("score_before", {"home": 1, "away": 0})),
            ("inconsistent-after", change_event("score_after", {"home": 3, "away": 0})),
            ("missing-period", lambda rows: rows[0]["period_receipts"].pop()),
            (
                "duplicate-period",
                lambda rows: rows[0]["period_receipts"].append(
                    copy.deepcopy(rows[0]["period_receipts"][0])
                ),
            ),
            (
                "wrong-period-total",
                lambda rows: rows[0]["period_receipts"][0].__setitem__(
                    "points", rows[0]["period_receipts"][0]["points"] + 1
                ),
            ),
            ("foreign-event-source", change_event("canonical_id", "event:other:1")),
        ]
        for name, mutate in mutations:
            changed = copy.deepcopy(records)
            mutate(changed)
            # Rebind document hashes so failures exercise invariants, not only byte identities.
            for row in changed:
                body = {k: v for k, v in row.items() if k != "source_document_id"}
                row["source_document_id"] = (
                    "derived-score-trajectory:"
                    + hashlib.sha256(
                        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                )
            assert run(name, inputs(name, changed), args.output / name) == 1, name
            assert (args.output / name / "failure.json").is_file()
            assert not (args.output / name / "measure-comparisons.json").exists()
        single = inputs("single", records[:1])
        assert (
            run("explicit empty postseason population", single, args.output / "empty-postseason")
            == 0
        )
        empty = json.loads((args.output / "empty-postseason/measure-comparisons.json").read_text())
        assert empty["populations"]["postseason"]["game_count"] == 0
        assert all(
            e["value"] is None for e in empty["populations"]["postseason"]["extrema"].values()
        )
        assert (
            run(
                "complete independently verified archive",
                args.trajectories,
                args.output / "approved",
            )
            == 0
        )
        real = json.loads((args.output / "approved/measure-comparisons.json").read_text())
        assert len(real["games"]) == 101
        actual = real["populations"]["complete_archive"]["extrema"]
        assert actual["q3_fewest_points"]["value"] == 11
        assert actual["q3_fewest_points"]["game_sources"] == ["game:0022500835"]
        assert actual["q3_worst_margin"]["value"] == -15
        assert actual["q3_worst_margin"]["game_sources"] == [
            "game:0022500003",
            "game:0022500125",
            "game:0022500816",
        ]
        status = "passed"
    finally:
        (args.output / "e2e-result.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "scope": (
                        "Comparison CLI E2E; no metric defaults, target approval or retrieval proof"
                    ),
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
