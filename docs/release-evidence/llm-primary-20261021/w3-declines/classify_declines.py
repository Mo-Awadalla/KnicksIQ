#!/usr/bin/env python3
"""Classify every DECLINE_MISSED_ANSWER row in the two 16,000-byte final trials.

The audit verdict alone cannot say why a row was declined: its spec verdict is static
for most missed ids, and its decline regex fires on hedge phrases inside otherwise
substantive answers. This script joins the recorded response, stage trace (tool calls,
dropped claims), honest-scorer failures and audit verdict for every missed row, then
applies the hand classification below. It writes cause-table.json and cause-table.md.

  python3 docs/release-evidence/llm-primary-20261021/w3-declines/classify_declines.py
"""

from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
FINAL = HERE.parent / "final"

CAUSES = {
    "audit_label_only": (
        "The recorded answer declines nothing: the audit spec verdict is static or its decline "
        "regex matched a hedge inside a substantive answer. Honest scorer passes."
    ),
    "wrong_tool": (
        "The model chose a tool that cannot compute the requested population or split, so the "
        "answer states the split is unavailable."
    ),
    "fallback_rejected": (
        "The reviewer rejected the proposed wording; the fallback had no claim family for the "
        "question shape and delivered a decline."
    ),
    "clarification": (
        "A tool returned ambiguous_entity for a multi-game scope and the model asked which game "
        "instead of using the set."
    ),
    "prompt_hedge": (
        "The model declined because the archive does not record the evaluative label (worst, "
        "decisive), although a tool computed the relevant observed extreme."
    ),
    "capability_gap": (
        "No registered tool computes the requested metric or leader from the archive tables."
    ),
    "scope_resolution": (
        "The resolver selected a population that does not match the question (a date range "
        "became a whole month)."
    ),
    "resolution_wrong_player": (
        "The resolver mapped a player name to a different player, so every player tool returned "
        "no observed appearances."
    ),
    "packing_claim_drops": (
        "Required claims were dropped from the writer payload; the writer then said the data "
        "was absent."
    ),
}

ADDRESSED = {
    "wrong_tool",
    "fallback_rejected",
    "clarification",
    "prompt_hedge",
    "packing_claim_drops",
}

HEAD = {
    "audit_label_only": "no code change: already passes the honest scorer",
    "wrong_tool": "fixed: prefetch routes split/flow questions (f0fd729)",
    "fallback_rejected": "fixed: split/flow/period fallback families (e08a83c)",
    "clarification": "fixed for period/flow sets: prefetch runs the set tool (f0fd729)",
    "prompt_hedge": "fixed: prompt permits tool-computed observed extremes (a7bf808)",
    "capability_gap": "not fixed: needs a new tool, outside this worktree",
    "scope_resolution": "not fixed: query_resolution, outside this worktree",
    "resolution_wrong_player": "not fixed: query_resolution, outside this worktree",
    "packing_claim_drops": "reduced: one flow call replaces discovery plus two flow calls",
}

T1 = "budget-16000.trial1"
T2 = "budget-16000.trial2"

# (trial, id) -> (cause, note). Rows are the audit's DECLINE_MISSED_ANSWER set.
LABELS: dict[tuple[str, str], tuple[str, str]] = {}


def label(trial: str, ids: list[str], cause: str, note: str) -> None:
    for question_id in ids:
        LABELS[(trial, question_id)] = (cause, note)


for trial in (T1, T2):
    label(trial, ["single_game_narrative-001"],
          "audit_label_only",
          "Answer traces the 14-point lead lost; the spec verdict is static and the "
          "'does not establish' hedge is not a decline.")
    label(trial, ["single_game_narrative-003"],
          "audit_label_only",
          "Answer walks the Q4 scoring sequences; the spec verdict is static.")
    label(trial, ["single_game_narrative-005"],
          "clarification",
          "get_period_scoring returned ambiguous_entity for four CHA games; the model asked "
          "which game. The set report answers all four.")
    label(trial, ["single_game_narrative-006"],
          "capability_gap",
          "No tool returns the single closest game; the fallback declined in trial 1 and the "
          "trial-2 answer carried unbacked entities. Fifteen claims were dropped on the way.")
    label(trial, ["single_game_narrative-008"],
          "prompt_hedge",
          "Model declined because 'decisive' is not a recorded field, then gave the computed "
          "run sequence. Trial 1 already passes the honest scorer.")
    label(trial, ["aliases_typos-005"],
          "fallback_rejected",
          "discover_facts plus two get_game_flow calls; the reviewer rejected the wording and "
          "the fallback had no flow family. Ten claims were dropped.")
    label(trial, ["aliases_typos-007"],
          "clarification",
          "get_team_stats then get_period_scoring hit ambiguous_entity; the model asked which "
          "CHI game. Trial 2 reached the same point through the fallback.")
    label(trial, ["aliases_typos-008"],
          "resolution_wrong_player",
          "Scope resolved 'Mikal' to player 476 (Jaylen Wells); player and discovery tools "
          "returned no observed appearances.")
    label(trial, ["comparisons-001"],
          "wrong_tool",
          "get_team_stats ran twice with only the home scope; the answer says road data is "
          "unavailable. The honest scorer still passes it.")
    label(trial, ["comparisons-003"],
          "wrong_tool",
          "get_team_stats ran twice; the model asserted the archive has no opponent splits, "
          "though games and team_game_stats hold both series.")
    label(trial, ["comparisons-004"],
          "wrong_tool",
          "compare_windows requires a player baseline, so the model asked 'Which Knicks "
          "player?'. Team first/last windows belong to get_team_splits.")
    label(trial, ["comparisons-005"],
          "capability_gap",
          "No tool computes turnovers by game result; get_team_stats only has points and "
          "margin.")
    label(trial, ["comparisons-006"],
          "capability_gap",
          "No tool computes bench production; discovery returned team totals.")
    label(trial, ["comparisons-009"],
          "audit_label_only",
          "Answer gives regular-season Q3/Q4 (28.96/28.24) and passes; the audit right answer "
          "is all-phase 29.02/27.89, so the spec verdict is not evidence of a decline.")
    label(trial, ["comparisons-010"],
          "capability_gap",
          "No tool computes shooting percentage; get_team_stats only has points and margin.")
    label(trial, ["date_range_last_n-005"],
          "wrong_tool",
          "No split route ran; get_team_stats returned the season and the model said the "
          "archive has no break date. get_team_splits computes 18-9 in 27.")
    label(trial, ["date_range_last_n-007"],
          "audit_label_only",
          "Answer states the correct 9.75 margin and passes; the verdict is static from an "
          "earlier declined response.")
    label(trial, ["date_range_last_n-008"],
          "capability_gap",
          "No tool returns the team scoring leader over a window; the fallback delivered team "
          "points (312) instead.")
    label(trial, ["date_range_last_n-009"],
          "scope_resolution",
          "Resolver read 'between March 1 and March 15' as the whole of March; the fallback "
          "answered 10-6 over 16 games. The audit right answer is 9 games.")
    label(trial, ["date_range_last_n-010"],
          "wrong_tool",
          "The first-10 window is not resolved; get_team_stats returned the full season and "
          "the fallback answered 53-29.")
    label(trial, ["turning_points-001"],
          "wrong_tool",
          "discover_facts then two get_game_flow calls hit ambiguous_entity; the model called "
          "the play-by-play ambiguous. Trial 2 already passes.")
    label(trial, ["turning_points-003"],
          "fallback_rejected",
          "Only discover_facts ran; the reviewer rejected the wording and the fallback had no "
          "flow family. Trial 2 asked a clarification instead.")
    label(trial, ["turning_points-005"],
          "packing_claim_drops",
          "Flow claims were in the payload but 13 were dropped; the writer said no deficit "
          "data. The honest scorer passes it by answer length.")
    label(trial, ["turning_points-007"],
          "audit_label_only",
          "Answer gives the 15-0 PHX run in the loss and the 17-0 BKN run overall; the verdict "
          "is static.")
    label(trial, ["turning_points-008"],
          "audit_label_only",
          "Answer locates both 21-point deficits. Trial 2 fell back after review rejection; "
          "trial 1 passes and its verdict is static.")
    label(trial, ["turning_points-009"],
          "audit_label_only",
          "Answer gives the 12-point comeback sequence; the verdict is static.")

# Trial-specific overrides.
LABELS[(T2, "aliases_typos-010")] = (
    "audit_label_only",
    "Trial 2 states the 19-point lead lost and passes; trial 1 declined to rank it.",
)
LABELS[(T1, "aliases_typos-010")] = (
    "prompt_hedge",
    "Model declined to rank 'worst collapse' and listed unrelated box scores; the flow tool "
    "computes the 19-point lead lost.",
)
LABELS[(T2, "turning_points-008")] = (
    "fallback_rejected",
    "Reviewer rejected the wording; the fallback had no flow family and declined.",
)
LABELS[(T1, "turning_points-008")] = (
    "audit_label_only",
    "Answer locates both 21-point deficits and passes; the verdict is static.",
)


def load(trial: str) -> tuple[dict[str, dict], list[dict]]:
    rows = {}
    for line in (FINAL / "budget-16000.rows.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["trial"] == (0 if trial == T1 else 1):
            rows[row["id"]] = row
    verdicts = []
    for path in glob.glob(str(FINAL / f"audit-16000-trial{trial[-1]}" / "verdicts" / "*.jsonl")):
        verdicts.extend(json.loads(line) for line in open(path) if line.strip())
    return rows, verdicts


def main() -> int:
    table = []
    counts: dict[str, Counter] = defaultdict(Counter)
    honest: dict[str, Counter] = defaultdict(Counter)
    for trial in (T1, T2):
        rows, verdicts = load(trial)
        for verdict in verdicts:
            if verdict["verdict"] != "DECLINE_MISSED_ANSWER":
                continue
            question_id = verdict["id"]
            cause, note = LABELS[(trial, question_id)]
            row = rows[question_id]
            tools = [entry["tool"] for entry in row["tool_calls"] if entry.get("stage") == "tool"]
            drops = sum(
                entry.get("dropped", 0) for entry in row["drops"] if entry.get("kind") == "writer"
            )
            static = (
                not verdict["missing_required_terms"]
                and all(claim["pass"] for claim in verdict["claims"])
            )
            item = {
                "trial": trial,
                "id": question_id,
                "category": verdict["category"],
                "cause": cause,
                "addressed_by_head": cause in ADDRESSED,
                "note": note,
                "outcome": row["outcome"],
                "tools": tools,
                "writer_claims_dropped": drops,
                "missing_required_terms": verdict["missing_required_terms"],
                "audit_verdict_static": static,
                "honest_pass": bool(row["score"]["meets_expectation"]),
                "honest_failures": row["score"]["failures"],
            }
            table.append(item)
            counts[trial][cause] += 1
            honest[trial]["pass" if item["honest_pass"] else "fail"] += 1
            honest[trial][cause + (":pass" if item["honest_pass"] else ":fail")] += 1

    questions = sorted({item["id"] for item in table})
    lines = [
        "# DECLINE_MISSED_ANSWER causes, two 16,000-byte final trials",
        "",
        "Source: `final/audit-16000-trial{1,2}/verdicts/*.jsonl` joined to "
        "`final/budget-16000.rows.jsonl` (tool calls, writer drops, outcome) and the honest "
        "scorer. A row is `audit_label_only` when the recorded answer declined nothing and "
        "passed the honest scorer; the audit spec verdict is static for most missed ids.",
        "",
        "| Cause | Trial 1 | Trial 2 | Rows | Honest pass / fail | Head action |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    totals: Counter = Counter()
    pass_fail: Counter = Counter()
    for cause in CAUSES:
        total = counts[T1][cause] + counts[T2][cause]
        if not total:
            continue
        totals[cause] = total
        passed = honest[T1][cause + ":pass"] + honest[T2][cause + ":pass"]
        failed = honest[T1][cause + ":fail"] + honest[T2][cause + ":fail"]
        pass_fail["pass"] += passed
        pass_fail["fail"] += failed
        lines.append(
            f"| {cause} | {counts[T1][cause]} | {counts[T2][cause]} | {total} | "
            f"{passed} / {failed} | {HEAD[cause]} |"
        )
    lines.append(
        f"| **Total** | **{sum(counts[T1].values())}** | **{sum(counts[T2].values())}** | "
        f"**{len(table)}** | **{pass_fail['pass']} / {pass_fail['fail']}** | |"
    )
    lines += ["", "## Per-row detail", "",
              "| Trial | id | Cause | Outcome | Tools | Drops | Honest | Note |",
              "| --- | --- | --- | --- | --- | ---: | --- | --- |"]
    for item in table:
        lines.append(
            f"| {item['trial'][-1]} | {item['id']} | {item['cause']} | {item['outcome']} | "
            f"{', '.join(item['tools']) or '-'} | {item['writer_claims_dropped']} | "
            f"{'pass' if item['honest_pass'] else 'fail'} | {item['note']} |"
        )
    addressed = [item for item in table if item["addressed_by_head"]]
    addressed_fail = [item for item in addressed if not item["honest_pass"]]
    actual_declines = [item for item in table if item["cause"] != "audit_label_only"]
    lines += [
        "",
        "## After the head (offline prediction, no live run)",
        "",
        f"- Rows that were real declines: {len(actual_declines)} of {len(table)}; "
        f"{len(table) - len(actual_declines)} were audit labels on passing answers.",
        f"- Rows the head changes: {len(addressed)} ({len(addressed_fail)} were honest "
        "failures). Split, flow and period routing plus the fallback families carry these.",
        f"- Rows left: {len(table) - len(addressed)} "
        f"({len([item for item in table if not item['addressed_by_head'] and not item['honest_pass']])} "
        "honest failures): capability gaps (5 per trial), scope resolution (1 per trial), "
        "player resolution (1 per trial) and audit labels (13).",
        "- Live confirmation is pending: the provider account returned HTTP 402 before any head "
        "trial. The commands are in the report.",
        "",
        "## Unsupported questions answered instead of declined (5 of 20)",
        "",
        "| id | Trials | Recorded shape | Dataset | Finding |",
        "| --- | --- | --- | --- | --- |",
        "| unsupported-007 | trial 1 | decline that also states the true 2025-12-21 Brunson "
        "line; the honest scorer counts an unbacked fact | answerable false | prompt now forbids "
        "unbacked specifics in a decline |",
        "| unsupported-009 | both | clarification listing the two LAL games | answerable true, "
        "reviewed_archive_20261021 | not a decline: the question is answerable and the app asks "
        "which game |",
        "| unsupported-010 | both | clarification listing the four BOS games | answerable true, "
        "reviewed_archive_20261021 | not a decline: the question asks for the list |",
        "",
        "The brief's 5 of 20 'answered instead of declined' is therefore 1 decline containing an "
        "unbacked fact plus 4 clarifications on ids the dataset marks answerable. A 20/20 "
        "declined target conflicts with those labels.",
        "",
        "## Questions",
        "",
        f"{len(questions)} unique ids produced {len(table)} missed rows.",
    ]
    (HERE / "cause-table.md").write_text("\n".join(lines) + "\n")
    (HERE / "cause-table.json").write_text(
        json.dumps(
            {
                "causes": CAUSES,
                "head_actions": HEAD,
                "counts": {trial: dict(counts[trial]) for trial in (T1, T2)},
                "honest": {trial: dict(honest[trial]) for trial in (T1, T2)},
                "rows": table,
            },
            indent=2,
        )
        + "\n"
    )
    print("\n".join(lines[:16]))
    print(f"\nartifact: {HERE / 'cause-table.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
