"""Compare explicitly named measures over a complete hash-pinned scoring source.

No metric default, causal claim, target selection, retrieval or gold approval.
The source-review digest must come from independently verified source evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from audit_measure_sources import digest, integer, require

DEFINITIONS = {
    "q3_fewest_points": "Fewest NYK points in the complete third quarter.",
    "q3_worst_margin": "Lowest NYK-minus-opponent third-quarter points.",
    "largest_observed_deficit": "Largest negative NYK margin at an observed scoring boundary.",
    "largest_deficit_later_tied": "Largest deficit followed by a later nonnegative NYK margin.",
    "largest_deficit_later_led": "Largest deficit followed by a later positive NYK margin.",
    "largest_deficit_in_eventual_win": "Largest observed deficit in a game NYK eventually won.",
    "knicks_largest_unanswered_run": "Most successive NYK points before an opponent point.",
    "opponent_largest_unanswered_run": "Most successive opponent points before a NYK point.",
    "knicks_largest_unrestricted_net_gain": (
        "Largest NYK margin increase over any later scoring boundary within one game; "
        "no clock/period window limit."
    ),
    "largest_unrestricted_margin_decline": (
        "Largest NYK margin decrease over any later scoring boundary within one game, "
        "whether previously leading or trailing; no clock/period window limit."
    ),
    "largest_positive_lead_surrendered": (
        "Largest positive NYK margin followed by a later nonpositive margin; "
        "first such later boundary identifies surrender."
    ),
    "largest_positive_lead_surrendered_in_final_loss": (
        "Same positive-lead surrender, restricted to games NYK ultimately lost."
    ),
}
MINIMUMS = {"q3_fewest_points", "q3_worst_margin"}


def empty() -> dict[str, Any]:
    return {"value": None, "boundaries": []}


def offer(result: dict[str, Any], value: int, boundary: dict) -> None:
    if result["value"] is None or value > result["value"]:
        result.update(value=value, boundaries=[boundary])
    elif value == result["value"]:
        result["boundaries"].append(boundary)


def window(start: dict, end: dict) -> dict:
    return {
        "start_source": start["source"],
        "start_source_state": start["source_state"],
        "end_source": end["source"],
        "end_source_state": end["source_state"],
        "start_margin": start["margin"],
        "end_margin": end["margin"],
    }


def changes(states: list[dict], direction: int) -> dict:
    """Retain all tied unrestricted scoring-boundary intervals in one pass."""
    result = empty()
    prefix = [states[0]]
    for state in states[1:]:
        gain = direction * (state["margin"] - prefix[0]["margin"])
        if gain > 0:
            for start in prefix:
                offer(result, gain, window(start, state))
        compared = direction * (state["margin"] - prefix[0]["margin"])
        if compared < 0:
            prefix = [state]
        elif compared == 0:
            prefix.append(state)
    return result


def compare_game(record: dict) -> dict:
    identity = record["nba_game_id"]
    home, away = record["home_team_id"], record["away_team_id"]
    require(home != away and "NYK" in {home, away}, "Foreign game teams")
    opponent = away if home == "NYK" else home
    side = "home" if home == "NYK" else "away"
    other = "away" if side == "home" else "home"
    score = {"home": 0, "away": 0}
    periods = Counter()
    measures = {key: empty() for key in DEFINITIONS}
    previous_period = 1
    events = record["events"]
    require(bool(events), "Missing canonical event population")
    states = [{"source": events[0]["canonical_id"], "source_state": "before", "margin": 0}]
    current_team = None
    run_points, run_sources, run_start = 0, [], states[0]
    for sequence, event in enumerate(events, 1):
        require(
            integer(event["sequence"], positive=True)
            and event["sequence"] == sequence
            and event["canonical_id"] == f"event:{identity}:{sequence}",
            "Missing, duplicate or foreign canonical event order",
        )
        points, team, period = event["points"], event["team_id"], event["period"]
        require(
            integer(points)
            and points <= 3
            and team in {home, away, None}
            and (not points or team in {home, away}),
            "Invalid contribution or scoring actor",
        )
        require(
            integer(period, positive=True) and period >= previous_period,
            "Nonchronological or invalid period",
        )
        require(re.fullmatch(r"\d{2}:\d{2}", event["clock"]) is not None, "Invalid canonical clock")
        previous_period = period
        require(event["score_before"] == score, "Inconsistent before state")
        if points:
            score["home" if team == home else "away"] += points
            periods[(team, period)] += points
        require(event["score_after"] == score, "Inconsistent after state")
        if not points:
            continue
        state = {
            "source": event["canonical_id"],
            "source_state": "after",
            "margin": score[side] - score[other],
        }
        if team != current_team:
            current_team, run_points, run_sources, run_start = team, 0, [], states[-1]
        run_points += points
        run_sources.append(event["canonical_id"])
        run_key = (
            "knicks_largest_unanswered_run" if team == "NYK" else "opponent_largest_unanswered_run"
        )
        # Keep only completed/maximal run endpoints; extending a run supersedes its prefix.
        run = measures[run_key]
        if run["value"] is None or run_points >= run["value"]:
            offer(
                run, run_points, {**window(run_start, state), "scoring_sources": list(run_sources)}
            )
        states.append(state)
    require(score["home"] != score["away"], "Non-final tied game")
    receipts = record["period_receipts"]
    period_rows = {}
    for row in receipts:
        prefix = f"period:{identity}:"
        require(row["canonical_id"].startswith(prefix), "Foreign period source")
        team, number = row["canonical_id"][len(prefix) :].split(":")
        period = int(number)
        key = (team, period)
        require(
            team in {home, away}
            and period >= 1
            and key not in period_rows
            and integer(row["points"]),
            "Duplicate or invalid period source",
        )
        require(row["points"] == periods[key], "Per-action period total differs")
        period_rows[key] = row
    last = max((p for _, p in period_rows), default=0)
    require(
        last >= 4
        and previous_period <= last
        and set(period_rows) == {(team, p) for team in (home, away) for p in range(1, last + 1)},
        "Incomplete period pair population",
    )
    q3_points, q3_against = period_rows[("NYK", 3)]["points"], period_rows[(opponent, 3)]["points"]
    quarter_boundary = {
        "period_sources": sorted(
            [period_rows[("NYK", 3)]["canonical_id"], period_rows[(opponent, 3)]["canonical_id"]]
        )
    }
    measures["q3_fewest_points"] = {"value": q3_points, "boundaries": [quarter_boundary]}
    measures["q3_worst_margin"] = {
        "value": q3_points - q3_against,
        "boundaries": [quarter_boundary],
    }
    next_tie, next_lead, next_surrender = None, None, None
    for state in reversed(states):
        margin = state["margin"]
        if margin < 0:
            boundary = {"source": state["source"], "margin": margin}
            offer(measures["largest_observed_deficit"], -margin, boundary)
            if next_tie is not None:
                offer(measures["largest_deficit_later_tied"], -margin, window(state, next_tie))
            if next_lead is not None:
                offer(measures["largest_deficit_later_led"], -margin, window(state, next_lead))
            if states[-1]["margin"] > 0:
                offer(
                    measures["largest_deficit_in_eventual_win"], -margin, window(state, states[-1])
                )
        elif margin > 0 and next_surrender is not None:
            offer(
                measures["largest_positive_lead_surrendered"], margin, window(state, next_surrender)
            )
            if states[-1]["margin"] < 0:
                offer(
                    measures["largest_positive_lead_surrendered_in_final_loss"],
                    margin,
                    window(state, next_surrender),
                )
        if margin >= 0:
            next_tie = state
        if margin > 0:
            next_lead = state
        if margin <= 0:
            next_surrender = state
    measures["knicks_largest_unrestricted_net_gain"] = changes(states, 1)
    measures["largest_unrestricted_margin_decline"] = changes(states, -1)
    for measure in measures.values():
        measure["boundaries"].sort(key=lambda b: json.dumps(b, sort_keys=True))
    return {
        "nba_game_id": identity,
        "game_source": f"game:{identity}",
        "source_document_id": record["source_document_id"],
        "season": record["season"],
        "season_type": record["season_type"],
        "game_date": record["game_date"],
        "final_nyk_margin": states[-1]["margin"],
        "measures": measures,
    }


def population(games: list[dict]) -> dict:
    extrema = {}
    for key in DEFINITIONS:
        present = [g for g in games if g["measures"][key]["value"] is not None]
        best = (min if key in MINIMUMS else max)(
            (g["measures"][key]["value"] for g in present), default=None
        )
        tied = [g for g in present if g["measures"][key]["value"] == best]
        extrema[key] = {
            "value": best,
            "game_sources": sorted(g["game_source"] for g in tied),
            "boundaries": [
                {
                    "game_source": g["game_source"],
                    "source_document_id": g["source_document_id"],
                    **boundary,
                }
                for g in tied
                for boundary in g["measures"][key]["boundaries"]
            ],
        }
    return {
        "game_count": len(games),
        "game_sources": sorted(g["game_source"] for g in games),
        "extrema": extrema,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--expected-trajectories-sha256", required=True)
    parser.add_argument("--source-review", type=Path, required=True)
    parser.add_argument("--expected-source-review-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        raw, review_raw = args.trajectories.read_bytes(), args.source_review.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == args.expected_trajectories_sha256,
            "Pinned trajectory bytes changed",
        )
        require(
            hashlib.sha256(review_raw).hexdigest() == args.expected_source_review_sha256,
            "Pinned source-review bytes changed",
        )
        review = json.loads(review_raw)
        require(
            review["status"] == "PER_ACTION_SCORING_SOURCE_VERIFIED"
            and review["recipe"] == "nba-action-scoring-trajectory-v1"
            and review["trajectories_sha256"] == args.expected_trajectories_sha256,
            "Unverified or mismatching source review",
        )
        records = [json.loads(line) for line in raw.splitlines()]
        sources = review["sources"]
        require(
            bool(records)
            and len(records) == review["games_verified"] == len(sources)
            and len({r["nba_game_id"] for r in records}) == len(records)
            and len({r["nba_game_id"] for r in sources}) == len(sources),
            "Missing or duplicate approved game population",
        )
        source_map = {s["nba_game_id"]: s for s in sources}
        require(
            sum(len(r["events"]) for r in records) == review["canonical_events_verified"]
            and sum(len(r["period_receipts"]) for r in records) == review["period_rows_verified"],
            "Incomplete approved event/period population",
        )
        require(len({r["season"] for r in records}) == 1, "Mixed season population")
        games = []
        for record in records:
            require(
                record["recipe"] == review["recipe"]
                and record["data_version"] == review["data_version"]
                and record["season_type"] in {"regular", "play_in", "playoffs"},
                "Foreign recipe, release or season phase",
            )
            source = source_map[record["nba_game_id"]]
            body = {k: v for k, v in record.items() if k != "source_document_id"}
            require(
                record["source_document_id"] == "derived-score-trajectory:" + digest(body)
                and record["source_document_id"] == source["source_document_id"]
                and record["primary_capture_sha256"] == source["primary_capture_sha256"],
                "Foreign or changed verified trajectory identity",
            )
            games.append(compare_game(record))
        games.sort(key=lambda g: (g["game_date"], g["nba_game_id"]))
        report = {
            "status": "COMPLETE_PINNED_MEASURE_COMPARISONS",
            "data_version": review["data_version"],
            "source_review_sha256": args.expected_source_review_sha256,
            "trajectories_sha256": args.expected_trajectories_sha256,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "definitions": DEFINITIONS,
            "games": games,
            "populations": {
                "complete_archive": population(games),
                "regular_season": population([g for g in games if g["season_type"] == "regular"]),
                "postseason": population(
                    [g for g in games if g["season_type"] in {"play_in", "playoffs"}]
                ),
            },
            "scope": (
                "Explicit comparison proposals; not default measures or indexed/ranked retrieval"
            ),
            "requires_clarification": [
                "metric",
                "run/window boundaries where applicable",
                "season scope",
            ],
            "metric_defaults": None,
            "gold_approved": False,
            "frozen": False,
            "ranked_receipts_created": False,
        }
    except (ValueError, KeyError, TypeError, OSError) as exc:
        (args.output / "failure.json").write_text(
            json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, indent=2)
            + "\n"
        )
        raise SystemExit(1) from exc
    artifact = args.output / "measure-comparisons.json"
    artifact.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (args.output / "SHA256SUMS").write_text(
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
    )
    print(json.dumps({"status": report["status"], "games": len(games)}))


if __name__ == "__main__":
    main()
