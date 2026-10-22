#!/usr/bin/env python3
"""Replacement factual audit: every numeric atom is recomputed from raw tables.

Usage:
    python3 audit.py RESPONSES.jsonl --out OUTDIR [--old OLD_VERDICTS] [--label NAME]

RESPONSES is a JSONL file with id, category, question, answer (trial optional).
OLD_VERDICTS is a directory of old-audit verdicts/*.jsonl, or a JSONL file.
Outputs rows.jsonl, summary.md and diff.md in OUTDIR.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from oracle_db import Oracle  # noqa: E402
from model import Session  # noqa: E402
from scope import base_scope  # noqa: E402
import verify_basic  # noqa: E402
import verify_flow  # noqa: E402
import verify_period  # noqa: E402
import verify_player  # noqa: E402
import verify_scores  # noqa: E402
import verify_team  # noqa: E402

VERIFIERS = [
    verify_basic.verify_seasons,
    verify_basic.verify_dates,
    verify_basic.verify_game_numbers,
    verify_scores.verify_final_scores,
    verify_scores.verify_team_labelled_scores,
    verify_scores.verify_score_lists,
    verify_team.verify_records,
    verify_team.verify_record_lines,
    verify_team.verify_points_lines,
    verify_team.verify_games_counts,
    verify_team.verify_team_rates,
    verify_team.verify_extremes,
    verify_basic.verify_month_years,
    verify_period.verify_periods,
    verify_player.verify_player_aggregates,
    verify_player.verify_player_lines,
    verify_flow.verify_flow,
]


def load_responses(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def load_old(path: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    if not path:
        return rows
    target = Path(path)
    files = sorted(target.glob("*.jsonl")) if target.is_dir() else [target]
    for file in files:
        for line in open(file, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            rid = row.get("id")
            if rid and rid not in rows:
                rows[rid] = row.get("verdict", "")
    return rows


def audit_response(response: dict, oracle: Oracle) -> dict:
    answer = response.get("answer", "")
    session = Session(
        response=response,
        oracle=oracle,
        text=answer,
        defaults={"scope": base_scope(response.get("question", ""), answer, oracle.team_aliases)},
    )
    for verifier in VERIFIERS:
        verifier(session)
    results = []
    for atom in session.atoms:
        result = session.results.get(atom.index)
        if result is None:
            results.append({
                "raw": atom.raw, "kind": atom.kind, "status": "unverified",
                "claimed": atom.raw, "expected": None, "fact": "no verifier matched this number",
                "sql": "", "detail": "", "start": atom.start, "end": atom.end,
            })
        else:
            results.append({
                "raw": atom.raw, "kind": atom.kind, "status": result.status,
                "claimed": _jsonable(result.claimed), "expected": _jsonable(result.expected),
                "fact": result.fact, "sql": result.sql, "detail": result.detail,
                "start": atom.start, "end": atom.end,
            })
    counts = Counter(r["status"] for r in results)
    found = len(results)
    checked = counts["verified"] + counts["wrong"]
    if counts["wrong"]:
        verdict = "INCORRECT"
    elif counts["unverified"]:
        verdict = "UNVERIFIED"
    elif found == 0:
        verdict = "NO_NUMBERS"
    else:
        verdict = "CORRECT"
    return {
        "id": response.get("id"),
        "category": response.get("category"),
        "trial": response.get("trial"),
        "question": response.get("question"),
        "answer": answer,
        "outcome": response.get("outcome"),
        "meets_expectation": response.get("meets_expectation"),
        "found": found,
        "verified": counts["verified"],
        "wrong": counts["wrong"],
        "unverified": counts["unverified"],
        "checked": checked,
        "coverage": round(checked / found, 4) if found else None,
        "verdict": verdict,
        "numbers": results,
    }


def _jsonable(value):
    if isinstance(value, tuple):
        return list(value)
    return value


def render(rows: list[dict], label: str, old: dict[str, str]) -> tuple[str, str]:
    totals = Counter()
    categories: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        for key in ("found", "verified", "wrong", "unverified", "checked"):
            totals[key] += row[key]
        cat = categories[row.get("category") or "unknown"]
        for key in ("found", "verified", "wrong", "unverified", "checked"):
            cat[key] += row[key]
        cat[row["verdict"]] += 1
    coverage = round(totals["checked"] / totals["found"], 4) if totals["found"] else None
    lines = [
        f"# Replacement factual audit: {label}",
        "",
        f"Responses: {len(rows)}. Numeric atoms found: {totals['found']}. "
        f"Checked: {totals['checked']} ({coverage:.2%} coverage). "
        f"Verified: {totals['verified']}. Wrong: {totals['wrong']}. "
        f"Unverified: {totals['unverified']}.",
        "",
        "Every numeric atom is extracted from the answer text, assigned a subject, phase, "
        "window, location, opponent and type from the surrounding sentence, and recomputed "
        "from raw restore tables by this audit's own SQL. An atom that no verifier can bind "
        "is UNVERIFIED and cannot pass.",
        "",
        "## Per-response table",
        "",
        "| id | trial | found | verified | wrong | unverified | coverage | verdict | old |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in sorted(rows, key=lambda r: (str(r.get("category")), str(r.get("id")), r.get("trial") or 0)):
        cov = f"{row['coverage']:.0%}" if row["coverage"] is not None else "n/a"
        old_verdict = old.get(row["id"], "n/a")
        lines.append(
            f"| {row['id']} | {row.get('trial') or ''} | {row['found']} | {row['verified']} | "
            f"{row['wrong']} | {row['unverified']} | {cov} | {row['verdict']} | {old_verdict} |"
        )
    lines += ["", "## By category", "", "| category | responses | found | verified | wrong | unverified | coverage |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for cat, counts in sorted(categories.items()):
        cov = f"{counts['checked'] / counts['found']:.0%}" if counts["found"] else "n/a"
        lines.append(
            f"| {cat} | {sum(counts[v] for v in ('CORRECT','INCORRECT','UNVERIFIED','NO_NUMBERS'))} | "
            f"{counts['found']} | {counts['verified']} | {counts['wrong']} | "
            f"{counts['unverified']} | {cov} |"
        )
    wrong = [r for row in rows for r in row["numbers"] if r["status"] == "wrong"]
    lines += ["", f"## Wrong numbers ({len(wrong)})", ""]
    if not wrong:
        lines.append("None.")
    for row in rows:
        bad = [r for r in row["numbers"] if r["status"] == "wrong"]
        if not bad:
            continue
        lines += [f"### {row['id']} (trial {row.get('trial') or 'n/a'})", ""]
        for item in bad:
            lines += [
                f"- `{item['raw']}` claimed; expected `{item['expected']}` ({item['fact']}).",
                "",
                "  ```sql",
                "  " + (item["sql"] or "no SQL recorded"),
                "  ```",
                "",
            ]
    unverified = [r for row in rows for r in row["numbers"] if r["status"] == "unverified"]
    lines += ["", f"## Unverified numbers ({len(unverified)})", ""]
    if not unverified:
        lines.append("None.")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for item in row["numbers"]:
            if item["status"] == "unverified":
                grouped[row["id"]].append(item)
    for rid, items in sorted(grouped.items()):
        sample = ", ".join(f"`{i['raw']}`" for i in items[:12])
        more = "" if len(items) <= 12 else f" (+{len(items) - 12} more)"
        lines.append(f"- {rid}: {len(items)} unverified: {sample}{more}")
    return "\n".join(lines) + "\n", render_diff(rows, old)


def render_diff(rows: list[dict], old: dict[str, str]) -> str:
    lines = [
        "# Old audit versus replacement audit",
        "",
        "Old verdicts are the claim-list audit at commit 5b585e6. Its numeric check "
        "counted only listed claims, and claims without an extractor compared a stored "
        "constant rather than the answer text.",
        "",
        "| id | trial | old verdict | new verdict | found | wrong | unverified | change |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | --- |",
    ]
    changes = 0
    for row in sorted(rows, key=lambda r: (str(r.get("category")), str(r.get("id")), r.get("trial") or 0)):
        old_verdict = old.get(row["id"], "n/a")
        if old_verdict == "n/a":
            change = "no old verdict"
        elif old_verdict == row["verdict"]:
            change = "same"
        elif old_verdict in {"CORRECT", "DECLINE_APPROPRIATE", "DECLINE_MISSED_ANSWER"} and row["verdict"] in {"UNVERIFIED", "INCORRECT"}:
            change = "old pass downgraded"
            changes += 1
        elif old_verdict == "INCORRECT" and row["verdict"] == "CORRECT":
            change = "old fail cleared"
            changes += 1
        else:
            change = "changed"
        lines.append(
            f"| {row['id']} | {row.get('trial') or ''} | {old_verdict} | {row['verdict']} | "
            f"{row['found']} | {row['wrong']} | {row['unverified']} | {change} |"
        )
    lines += ["", f"Verdict changes: {changes}. A downgrade means the old audit reported a "
              "pass for a response with numbers it did not check, or checked them against a "
              "constant. An old fail cleared means every number now recomputes."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("responses")
    parser.add_argument("--out", required=True)
    parser.add_argument("--old", default="")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    oracle = Oracle()
    responses = load_responses(args.responses)
    old = load_old(args.old)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [audit_response(response, oracle) for response in responses]
    label = args.label or Path(args.responses).stem
    summary, diff = render(rows, label, old)
    (out / "rows.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )
    (out / "summary.md").write_text(summary, encoding="utf-8")
    (out / "diff.md").write_text(diff, encoding="utf-8")
    totals = Counter()
    for row in rows:
        for key in ("found", "verified", "wrong", "unverified"):
            totals[key] += row[key]
    print(f"{label}: responses={len(rows)} found={totals['found']} verified={totals['verified']} "
          f"wrong={totals['wrong']} unverified={totals['unverified']}")


if __name__ == "__main__":
    main()
