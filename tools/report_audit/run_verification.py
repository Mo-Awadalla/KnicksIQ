"""Independent event endpoint arithmetic for legacy and explicit scoring intervals."""

from __future__ import annotations

import re

RUN = re.compile(r"([A-Z]{3}) produced a (\d+)-(\d+) run in Q(\d+) from ([\d:]+) to ([\d:]+)\.")


EXACT_RUN = re.compile(
    r"Selected scoring interval: ([A-Z]{3}) scored (\d+) points and allowed (\d+) points "
    r"from Q(\d+) ([\d:]+) to Q(\d+) ([\d:]+) "
    r"\(events (\d+)-(\d+), inclusive\)\."
)


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
