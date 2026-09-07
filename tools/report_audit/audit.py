"""Independent, offline claim audit. Never imports the report/run generator.

Usage: python tools/report_audit/audit.py INPUT --output DIRECTORY
Outputs an audit plus report-only proposal; never mutates or approves the input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

RUN = re.compile(r"([A-Z]{3}) produced a (\d+)-(\d+) run in Q(\d+) from ([\d:]+) to ([\d:]+)\.")
EXACT_RUN = re.compile(
    r"Selected scoring interval: ([A-Z]{3}) scored (\d+) points and allowed (\d+) points "
    r"from Q(\d+) ([\d:]+) to Q(\d+) ([\d:]+) "
    r"\(events (\d+)-(\d+), inclusive\)\."
)
POLICY = {
    "id": "agent-report-verification-owner-template-exceptions-summary-v2",
    "review": (
        "Agents verify every report; unresolved checks block approval. Owner "
        "approves the corrected template, all exceptions and final hash-bound audit "
        "summary. reviewed=true alone is not approval."
    ),
    "selection": (
        "Retain the existing selected interval only when canonical cumulative event "
        "scores independently prove its points. Identify both periods explicitly. "
        "These are selected scoring intervals, not causal turning points or "
        "necessarily the best/worst interval. Replacement selection is recorded "
        "separately in the repair proposal; the verifier does not use its selector."
    ),
    "boundary": (
        "Start is inclusive: baseline is the score immediately before the first "
        "scoring event at the stated start clock. End is inclusive: last event at "
        "the end clock. Resolve the end period by chronology and the claimed score "
        "difference; require a unique interval. Repaired descriptions carry explicit "
        "inclusive start/end event sequences. Check those boundaries, both clocks, "
        "the preceding observed score and every intervening scoreboard transition. "
        "Reject a backward scoreboard correction inside a selected interval; a "
        "correction outside it does not invalidate its endpoint arithmetic."
    ),
    "template": (
        "Selected scoring interval: TEAM scored FOR points and allowed AGAINST "
        "points from QSTART CLOCK to QEND CLOCK (inclusive)."
    ),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def report_hash(report):
    return digest({k: v for k, v in report.items() if k not in {"reviewed", "review_hash"}})


def verify_exact_run(text, game, events):
    """Independently verify explicit event endpoints; never call interval selection."""
    match = EXACT_RUN.fullmatch(text)
    if not match:
        return None, "unsupported_exact_format"
    team, pf, pa, sp, sc, ep, ec, start, end = match.groups()
    if team not in (game["home_team_id"], game["away_team_id"]):
        return None, "unknown_run_team"
    if int(start) > int(end):
        return None, "reversed_sequence_bounds"
    selected = [e for e in events if int(start) <= e["sequence"] <= int(end)]
    if (
        not selected
        or selected[0]["sequence"] != int(start)
        or selected[-1]["sequence"] != int(end)
    ):
        return None, "missing_exact_boundary"
    first, last = selected[0], selected[-1]
    if (first["period"], first["clock"], last["period"], last["clock"]) != (
        int(sp),
        sc,
        int(ep),
        ec,
    ):
        return None, "exact_clock_mismatch"
    # Resolve only the baseline from prior rows; 0-0 is the cached absent-score sentinel.
    prior = [e for e in events if e["sequence"] < int(start)]
    previous = {"home_score": 0, "away_score": 0}
    for event in prior:
        if event["home_score"] or event["away_score"]:
            previous = event
    baseline = previous
    for event in selected:
        if not (event["home_score"] or event["away_score"]):
            continue
        if (
            event["home_score"] < previous["home_score"]
            or event["away_score"] < previous["away_score"]
        ):
            return None, "nonmonotonic_selected_score"
        previous = event
    own = "home_score" if team == game["home_team_id"] else "away_score"
    other = "away_score" if own == "home_score" else "home_score"
    if (previous[own] - baseline[own], previous[other] - baseline[other]) != (int(pf), int(pa)):
        return None, "exact_points_mismatch"
    return {
        "team_id": team,
        "points_for": int(pf),
        "points_against": int(pa),
        "start_period": int(sp),
        "end_period": int(ep),
        "start_clock": sc,
        "end_clock": ec,
        "start_sequence": int(start),
        "end_sequence": int(end),
        "baseline_sequence": prior[-1]["sequence"] if prior else None,
        "baseline_score": {"home": baseline["home_score"], "away": baseline["away_score"]},
        "end_score": {"home": previous["home_score"], "away": previous["away_score"]},
    }, None


def resolve_run(text, game, events):
    """Check stated totals by endpoint subtraction, independently of run detection."""
    match = RUN.fullmatch(text)
    if not match:
        return None, "unsupported_run_format"
    team, points_for, points_against, period, start_clock, end_clock = match.groups()
    if team not in (game["home_team_id"], game["away_team_id"]):
        return None, "unknown_run_team"
    own = "home_score" if team == game["home_team_id"] else "away_score"
    other = "away_score" if own == "home_score" else "home_score"
    # Non-scoring cached rows use 0-0 as an absent-score sentinel.
    # Carry the last observed cumulative score, without using generator deltas.
    normalized = []
    score = {"home_score": 0, "away_score": 0}
    for event in events:
        if event["home_score"] or event["away_score"]:
            if any(event[k] < score[k] for k in score):
                return None, "nonmonotonic_canonical_score"
            score = {k: event[k] for k in score}
        normalized.append({**event, **score})
    events = normalized
    starts = []
    for index, event in enumerate(events):
        previous = events[index - 1] if index else {"home_score": 0, "away_score": 0}
        if (
            event["period"] == int(period)
            and event["clock"] == start_clock
            and (event["home_score"], event["away_score"])
            != (previous["home_score"], previous["away_score"])
        ):
            starts.append((index, event, previous))
    # A clock can contain multiple free throws; do not select whichever makes totals fit.
    if not starts:
        return None, "missing_scoring_start"
    index, first, previous = starts[0]
    ends = {}
    for end in events[index:]:
        if end["clock"] == end_clock:
            ends[end["period"]] = end
    candidates = []
    observed = []
    for end in ends.values():
        observed.append(
            {
                "start_sequence": first["sequence"],
                "end_sequence": end["sequence"],
                "start_period": first["period"],
                "end_period": end["period"],
                "points_for": end[own] - previous[own],
                "points_against": end[other] - previous[other],
            }
        )
        if end[own] - previous[own] == int(points_for) and end[other] - previous[other] == int(
            points_against
        ):
            candidates.append(
                {
                    "team_id": team,
                    "points_for": int(points_for),
                    "points_against": int(points_against),
                    "start_period": first["period"],
                    "end_period": end["period"],
                    "start_clock": start_clock,
                    "end_clock": end_clock,
                    "start_sequence": first["sequence"],
                    "end_sequence": end["sequence"],
                    "baseline_sequence": previous.get("sequence"),
                    "baseline_score": {
                        "home": previous["home_score"],
                        "away": previous["away_score"],
                    },
                    "end_score": {"home": end["home_score"], "away": end["away_score"]},
                }
            )
    if len(candidates) != 1:
        return {
            "observed_intervals": observed
        }, "ambiguous_run_boundary" if candidates else "run_points_or_boundary_mismatch"
    return candidates[0], None


def factual_run(evidence):
    e = evidence
    return (
        f"Selected scoring interval: {e['team_id']} scored {e['points_for']} points and "
        f"allowed {e['points_against']} points from Q{e['start_period']} {e['start_clock']} "
        f"to Q{e['end_period']} {e['end_clock']} (inclusive)."
    )


def audit(payload):
    data = payload["data"]
    games = {g["nba_game_id"]: g for g in data["games"]}
    events_by_game = defaultdict(list)
    stats_by_game = defaultdict(list)
    for event in data["events"]:
        events_by_game[event["nba_game_id"]].append(event)
    for stat in data["player_game_stats"]:
        stats_by_game[stat["nba_game_id"]].append(stat)
    players = {p["nba_player_id"]: p["full_name"] for p in data["players"]}
    canonical_hash = digest({k: v for k, v in data.items() if k != "reports"})
    results, proposals = [], []
    for report in data["reports"]:
        game_id = report["nba_game_id"]
        game = games[game_id]
        events = sorted(events_by_game[game_id], key=lambda e: e["sequence"])
        issues, evidence = [], []
        h = report_hash(report)
        if payload.get("review_manifest", {}).get("candidates", {}).get(game_id) != h:
            issues.append("content_hash_mismatch")
        winner = "home" if game["home_score"] > game["away_score"] else "away"
        loser = "away" if winner == "home" else "home"
        win, loss = game[winner + "_team_id"], game[loser + "_team_id"]
        ws, ls = game[winner + "_score"], game[loser + "_score"]
        if (
            report["title"] != f"{win} {ws}, {loss} {ls}"
            or report["summary"] != f"{win} defeated {loss} {ws}-{ls} on {game['game_date']}."
        ):
            issues.append("score_summary_mismatch")
        evidence.append(
            {
                "claims": ["title", "summary"],
                "type": "game",
                "nba_game_id": game_id,
                "fields": ["home_score", "away_score", "home_team_id", "away_team_id", "game_date"],
            }
        )
        leaders = sorted(stats_by_game[game_id], key=lambda s: (-s["points"], s["nba_player_id"]))[
            :3
        ]
        expected_notes = [
            f"{players[s['nba_player_id']]}: {s['points']} points, "
            f"{s['rebounds']} rebounds, {s['assists']} assists."
            for s in leaders
        ]
        if json.loads(report["player_notes"]) != expected_notes:
            issues.append("player_lines_mismatch")
        for index, stat in enumerate(leaders):
            evidence.append(
                {
                    "claims": [f"player_notes[{index}]"],
                    "type": "traditional_box_score",
                    "nba_game_id": game_id,
                    "nba_player_id": stat["nba_player_id"],
                    "fields": ["points", "rebounds", "assists"],
                    "row_sha256": digest(stat),
                }
            )
        repaired = dict(report, reviewed=False)
        # A later countdown clock proves the single-quarter description is impossible.
        cross_period = any(
            (m := RUN.fullmatch(report[field])) and m.group(6) > m.group(5)
            for field in ("turning_point", "best_stretch")
        )
        for field in ("turning_point", "best_stretch"):
            exact = EXACT_RUN.fullmatch(report[field])
            run, error = (verify_exact_run if exact else resolve_run)(report[field], game, events)
            if error:
                issues.append(f"{field}:{error}")
                if run:
                    evidence.append(
                        {
                            "claims": [field],
                            "type": "play_by_play",
                            "nba_game_id": game_id,
                            "status": "contradicted_or_ambiguous",
                            **run,
                        }
                    )
            else:
                cross_period |= run["start_period"] != run["end_period"]
                evidence.append(
                    {"claims": [field], "type": "play_by_play", "nba_game_id": game_id, **run}
                )
                repaired[field] = report[field] if exact else factual_run(run)
        # Existing worst_stretch embeds detector narrative, with explicit period boundaries.
        worst = re.search(
            r"Knicks were outscored (\d+)-(\d+) from Q(\d+) ([\d:]+) to Q(\d+) ([\d:]+)\.",
            report["worst_stretch"],
        )
        if EXACT_RUN.fullmatch(report["worst_stretch"]):
            run, error = verify_exact_run(report["worst_stretch"], game, events)
            if error:
                issues.append("worst_stretch:" + error)
            else:
                cross_period |= run["start_period"] != run["end_period"]
                evidence.append(
                    {
                        "claims": ["worst_stretch"],
                        "type": "play_by_play",
                        "nba_game_id": game_id,
                        **run,
                    }
                )
        elif worst:
            pf, pa, sp, sc, ep, ec = worst.groups()
            opponent = (
                game["away_team_id"] if game["home_team_id"] == "NYK" else game["home_team_id"]
            )
            run, error = resolve_run(
                f"{opponent} produced a {pf}-{pa} run in Q{sp} from {sc} to {ec}.", game, events
            )
            if error or str(run["end_period"]) != ep:
                issues.append("worst_stretch:" + (error or "end_period_mismatch"))
                if run:
                    evidence.append(
                        {
                            "claims": ["worst_stretch"],
                            "type": "play_by_play",
                            "nba_game_id": game_id,
                            "status": "contradicted_or_ambiguous",
                            **run,
                        }
                    )
            else:
                cross_period |= run["start_period"] != run["end_period"]
                evidence.append(
                    {
                        "claims": ["worst_stretch"],
                        "type": "play_by_play",
                        "nba_game_id": game_id,
                        **run,
                    }
                )
                repaired["worst_stretch"] = factual_run(run)
        else:
            issues.append("worst_stretch:unsupported_format")
        repaired["sources_json"] = json.dumps(evidence, separators=(",", ":"))
        repaired["tool_trace_json"] = json.dumps(
            [{"audit_policy": POLICY["id"], "canonical_data_sha256": canonical_hash}],
            separators=(",", ":"),
        )
        results.append(
            {
                "nba_game_id": game_id,
                "original_report_sha256": h,
                "status": "pass" if not issues else "unresolved",
                "issues": issues,
                "cross_period": bool(cross_period),
                "player_line_count": len(leaders),
                "claim_evidence": evidence,
                "checks": {
                    "content_hash": "content_hash_mismatch" not in issues,
                    "score_summary": "score_summary_mismatch" not in issues,
                    "player_lines": "player_lines_mismatch" not in issues,
                },
                "proposed_report_sha256": report_hash(repaired) if not issues else None,
            }
        )
        if not issues:
            proposals.append(repaired)
    coverage = (
        sorted(games) == sorted(r["nba_game_id"] for r in results)
        and sorted(games) == sorted(payload["manifest"]["expected_game_ids"])
        and len(games) == payload["manifest"]["expected_games"]
    )
    result = {
        "schema_version": 1,
        "baseline_version": payload["manifest"]["version"],
        "baseline_identity": "local_candidate_only_active_archive_unverified",
        "canonical_data_sha256": canonical_hash,
        "policy": POLICY,
        "policy_sha256": digest(POLICY),
        "owner_approval": None,
        "release_approved": False,
        "coverage_complete": coverage,
        "reports": results,
        "summary": {
            "reports": len(results),
            "content_hashes_passed": sum(r["checks"]["content_hash"] for r in results),
            "score_summaries_passed": sum(r["checks"]["score_summary"] for r in results),
            "player_lines_passed": sum(
                r["player_line_count"] for r in results if r["checks"]["player_lines"]
            ),
            "passed": sum(r["status"] == "pass" for r in results),
            "unresolved": sum(r["status"] != "pass" for r in results),
            "cross_period_reports": sum(r["cross_period"] for r in results),
        },
        "blockers": [
            "Active archive identity requires verification",
            "Owner template, exceptions and audit approval required",
        ],
    }
    if not coverage or any(r["issues"] for r in results):
        result["blockers"].append("Unresolved report checks or incomplete coverage")
    proposal = {
        "schema_version": 1,
        "kind": "report_only_repair_proposal_not_release",
        "baseline_version": result["baseline_version"],
        "canonical_data_sha256": canonical_hash,
        "policy_sha256": digest(POLICY),
        "reports": proposals,
        "approvals": {},
    }
    return result, proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    result, proposal = audit(json.loads(raw))
    result["input_file_sha256"] = hashlib.sha256(raw).hexdigest()
    result["proposal_sha256"] = digest(proposal)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("audit.json", result), ("report-repairs.json", proposal)):
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    lines = [
        "# Report integrity audit",
        "",
        f"Audit SHA-256 (canonical JSON): `{digest(result)}`",
        "",
        "Local candidate only; active archive identity and owner approval remain unverified.",
        "",
        json.dumps(result["summary"], sort_keys=True),
        "",
        POLICY["review"],
        "",
        POLICY["selection"],
        "",
        POLICY["boundary"],
        "",
        "| Game | Result | Cross-period | Exceptions |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r['nba_game_id']} | {r['status']} | {r['cross_period']} | {', '.join(r['issues'])} |"
        for r in result["reports"]
    ]
    (args.output / "audit.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result["summary"]))
    return 1 if result["summary"]["unresolved"] or not result["coverage_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
