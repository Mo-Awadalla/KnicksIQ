"""Replace unprovable detector prose with independently selected factual intervals.

No basketball data or approvals are changed. The output is an unreviewed report-only
proposal plus audit evidence; --candidate optionally writes an assembled offline input.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path

from audit import audit, digest, report_hash

SELECTION_POLICY = {
    "id": "canonical-score-intervals-v2",
    "selection": (
        "Enumerate same-period intervals lasting at most 180 seconds. Include all events "
        "at each endpoint clock, including every same-clock free throw. A candidate begins "
        "at a clock with positive scoring and contains no backward scoreboard correction. "
        "Select the greatest NYK margin gain for best_stretch and the greatest opponent "
        "margin gain for worst_stretch; tie-break by own points, shortest duration, earliest "
        "sequence. turning_point displays the larger of those two margin gains, with NYK "
        "winning a tie. These are selected scoring intervals, without a claim of causality "
        "or an unrestricted game-wide best/worst interval."
    ),
    "corrections": (
        "Cached 0-0 rows are missing-score sentinels and carry the prior observed score. "
        "A backward nonzero score is retained as the new canonical baseline. No selected "
        "interval crosses that correction; all excluded corrections are listed for review."
    ),
    "approval": "All repaired reports are unreviewed. This utility cannot grant owner approval.",
}


def clock_seconds(clock):
    minutes, seconds = clock.split(":")
    return 60 * int(minutes) + float(seconds)


def select_intervals(game, events):
    """Compute candidate scoreboard differences from clock groups, not detector deltas."""
    score = (0, 0)
    groups = []
    corrections = []
    for event in sorted(events, key=lambda e: e["sequence"]):
        key = (event["period"], event["clock"])
        if not groups or groups[-1]["key"] != key:
            groups.append(
                {
                    "key": key,
                    "start": event,
                    "end": event,
                    "before": score,
                    "after": score,
                    "correction": False,
                }
            )
        group = groups[-1]
        observed = (event["home_score"], event["away_score"])
        if observed != (0, 0):
            if observed[0] < score[0] or observed[1] < score[1]:
                group["correction"] = True
                corrections.append(
                    {
                        "sequence": event["sequence"],
                        "period": event["period"],
                        "clock": event["clock"],
                        "before": score,
                        "after": observed,
                    }
                )
            score = observed
        group["after"] = score
        group["end"] = event
    choices = {game["home_team_id"]: [], game["away_team_id"]: []}
    for i, first in enumerate(groups):
        if first["before"] == first["after"]:
            continue
        for last in groups[i:]:
            if last["key"][0] != first["key"][0] or last["correction"]:
                break
            duration = clock_seconds(first["key"][1]) - clock_seconds(last["key"][1])
            if not 0 <= duration <= 180:
                break
            points = tuple(a - b for a, b in zip(last["after"], first["before"], strict=True))
            for own, team in enumerate((game["home_team_id"], game["away_team_id"])):
                pf, pa = points[own], points[1 - own]
                if pf <= 0:
                    continue
                choices[team].append(
                    {
                        "team_id": team,
                        "points_for": pf,
                        "points_against": pa,
                        "start_period": first["key"][0],
                        "end_period": last["key"][0],
                        "start_clock": first["key"][1],
                        "end_clock": last["key"][1],
                        "start_sequence": first["start"]["sequence"],
                        "end_sequence": last["end"]["sequence"],
                        "duration": duration,
                    }
                )

    def choose(team):
        if not choices[team]:
            raise ValueError(f"{game['nba_game_id']}: no verified scoring interval for {team}")
        return max(
            choices[team],
            key=lambda c: (
                c["points_for"] - c["points_against"],
                c["points_for"],
                -c["duration"],
                -c["start_sequence"],
                -c["end_sequence"],
            ),
        )

    opponent = game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]
    best, worst = choose("NYK"), choose(opponent)
    turning = max((best, worst), key=lambda c: c["points_for"] - c["points_against"])
    return {"turning_point": turning, "best_stretch": best, "worst_stretch": worst}, corrections


def describe(e):
    return (
        f"Selected scoring interval: {e['team_id']} scored {e['points_for']} points and "
        f"allowed {e['points_against']} points from Q{e['start_period']} {e['start_clock']} "
        f"to Q{e['end_period']} {e['end_clock']} "
        f"(events {e['start_sequence']}-{e['end_sequence']}, inclusive)."
    )


def repair(payload):
    candidate = copy.deepcopy(payload)
    games = {g["nba_game_id"]: g for g in payload["data"]["games"]}
    events = defaultdict(list)
    for event in payload["data"]["events"]:
        events[event["nba_game_id"]].append(event)
    replacements, exceptions = [], []
    for report in candidate["data"]["reports"]:
        game_id = report["nba_game_id"]
        selected, corrections = select_intervals(games[game_id], events[game_id])
        original_hash = report_hash(report)
        for field, interval in selected.items():
            replacements.append(
                {
                    "nba_game_id": game_id,
                    "field": field,
                    "original": report[field],
                    "corrected": describe(interval),
                    "original_report_sha256": original_hash,
                }
            )
            report[field] = describe(interval)
        report["reviewed"] = False
        report.pop("review_hash", None)
        report["tool_trace_json"] = json.dumps(
            [{"selection_policy": SELECTION_POLICY}], separators=(",", ":")
        )
        if corrections:
            exceptions.append({"nba_game_id": game_id, "excluded_score_corrections": corrections})
    candidate["review_manifest"] = {
        "approvals": {},
        "instructions": SELECTION_POLICY["approval"],
        "candidates": {r["nba_game_id"]: report_hash(r) for r in candidate["data"]["reports"]},
    }
    result, verified_proposal = audit(candidate)
    if result["summary"]["unresolved"] or not result["coverage_complete"]:
        raise ValueError(f"Independent audit rejected repairs: {result['summary']}")
    # Use the auditor's independently reconstructed sources, retaining the selection policy.
    candidate["data"]["reports"] = verified_proposal["reports"]
    for report in candidate["data"]["reports"]:
        trace = json.loads(report["tool_trace_json"])
        trace.append({"selection_policy": SELECTION_POLICY})
        report["tool_trace_json"] = json.dumps(trace, separators=(",", ":"))
    candidate["review_manifest"]["candidates"] = {
        r["nba_game_id"]: report_hash(r) for r in candidate["data"]["reports"]
    }
    result, _ = audit(candidate)
    original_canonical = digest({k: v for k, v in payload["data"].items() if k != "reports"})
    assert original_canonical == result["canonical_data_sha256"]
    proposal = {
        "schema_version": 1,
        "kind": "report_only_repair_proposal_not_release",
        "baseline_version": payload["manifest"]["version"],
        "canonical_data_sha256": original_canonical,
        "selection_policy": SELECTION_POLICY,
        "selection_policy_sha256": digest(SELECTION_POLICY),
        "reports": candidate["data"]["reports"],
        "review_manifest": candidate["review_manifest"],
        "approvals": {},
    }
    result["selection_policy"] = SELECTION_POLICY
    result["selection_policy_sha256"] = digest(SELECTION_POLICY)
    result["proposal_sha256"] = digest(proposal)
    result["replaced_claims"] = replacements
    result["canonical_exceptions"] = exceptions
    return candidate, proposal, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    candidate, proposal, result = repair(json.loads(raw))
    import hashlib

    result["input_file_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("report-repairs.json", proposal), ("audit.json", result)):
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    lines = [
        "# Corrected report verification",
        "",
        json.dumps(result["summary"], sort_keys=True),
        "",
        f"Canonical basketball data SHA-256: `{result['canonical_data_sha256']}`",
        "",
        "Canonical basketball rows are unchanged. All 101 report drafts remain unreviewed.",
        "",
        SELECTION_POLICY["selection"],
        "",
        SELECTION_POLICY["corrections"],
        "",
        f"Games with excluded scoreboard corrections: {len(result['canonical_exceptions'])}.",
        "",
        "Every replaced claim and exact sequence-level evidence is in audit.json. "
        "The proposal is not an approved production release.",
        "",
        "Owner review requires the corrected template, correction exceptions and "
        "hash-bound final audit summary. Active archive identity remains a separate release check.",
    ]
    (args.output / "audit.md").write_text("\n".join(lines) + "\n")
    if args.candidate:
        args.candidate.parent.mkdir(parents=True, exist_ok=True)
        args.candidate.write_text(json.dumps(candidate, separators=(",", ":")) + "\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
