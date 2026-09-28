"""Prepare a read-only, hash-bound correction review; never approve or publish."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path

from audit import audit, digest, report_hash, resolve_run
from repair import SELECTION_POLICY, repair


def prepare(baseline, replacement):
    before_audit, _ = audit(baseline)
    after_audit, _ = audit(replacement)
    if after_audit["summary"]["unresolved"] or not after_audit["coverage_complete"]:
        raise ValueError("Replacement failed independent audit")
    generated, _, _ = repair(baseline)
    if generated["data"]["reports"] != replacement["data"]["reports"]:
        raise ValueError("Replacement does not reproduce the existing correction policy")
    if before_audit["canonical_data_sha256"] != after_audit["canonical_data_sha256"]:
        raise ValueError("Canonical basketball rows changed")
    before = {r["nba_game_id"]: r for r in baseline["data"]["reports"]}
    after = {r["nba_game_id"]: r for r in replacement["data"]["reports"]}
    changes = [
        {
            "nba_game_id": key,
            "before_sha256": report_hash(before[key]),
            "after_sha256": report_hash(after[key]),
            "before": before[key],
            "after": after[key],
        }
        for key in sorted(before)
        if before[key] != after[key]
    ]
    game_id = "0022501168"
    game = next(g for g in baseline["data"]["games"] if g["nba_game_id"] == game_id)
    events = sorted(
        (e for e in baseline["data"]["events"] if e["nba_game_id"] == game_id),
        key=lambda e: e["sequence"],
    )
    diagnosis = []
    for text in (
        "BOS produced a 16-4 run in Q3 from 06:11 to 02:22.",
        "NYK produced a 12-4 run in Q3 from 11:41 to 09:33.",
    ):
        evidence, error = resolve_run(text, game, events)
        if error:
            raise ValueError(f"Report 80 diagnosis did not reproduce: {error}")
        diagnosis.append({"claim": text, "evidence": evidence})
    return {
        "status": "prepared_unapproved_not_activated",
        "baseline_version": baseline["manifest"]["version"],
        "baseline_identity": "local_candidate; production must be pinned again before publication",
        "canonical_data_sha256": before_audit["canonical_data_sha256"],
        "replacement_content_sha256": digest(replacement["data"]["reports"]),
        "rollback_content_sha256": digest(baseline["data"]["reports"]),
        "selection_policy": SELECTION_POLICY,
        "selection_policy_sha256": digest(SELECTION_POLICY),
        "read_only_baseline_audit": before_audit,
        "replacement_audit": after_audit,
        "report80_diagnosis": diagnosis,
        "report80_game_events_sha256": digest(events),
        "changes": changes,
        "approval": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("replacement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw_before, raw_after = args.baseline.read_bytes(), args.replacement.read_bytes()
    baseline, replacement = json.loads(raw_before), json.loads(raw_after)
    review = prepare(baseline, replacement)
    review["source_files"] = {
        str(args.baseline): hashlib.sha256(raw_before).hexdigest(),
        str(args.replacement): hashlib.sha256(raw_after).hexdigest(),
    }
    args.output.mkdir(parents=True, exist_ok=True)

    def serialize(value):
        return json.dumps(value, indent=2, sort_keys=True) + "\n"

    before_text = serialize(baseline["data"]["reports"])
    after_text = serialize(replacement["data"]["reports"])
    artifacts = {
        "review.json": serialize(review),
        "rollback-reports.json": before_text,
        "replacement-reports.json": after_text,
        "reports.diff": "".join(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile="stored-baseline-reports",
                tofile="unreviewed-replacement-reports",
            )
        ),
    }
    for name, text in artifacts.items():
        (args.output / name).write_text(text)
    (args.output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(text.encode()).hexdigest()}  {name}\n"
            for name, text in artifacts.items()
        )
    )
    print(
        json.dumps(
            {
                "baseline": review["read_only_baseline_audit"]["summary"],
                "replacement": review["replacement_audit"]["summary"],
                "status": review["status"],
            }
        )
    )


if __name__ == "__main__":
    main()
