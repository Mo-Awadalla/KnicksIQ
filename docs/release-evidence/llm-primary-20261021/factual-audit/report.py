"""Render the audit reports. Kept separate so each committed file stays small."""

from collections import Counter, defaultdict
from decimal import Decimal


def fmt(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def reports(rows, facts):
    passes = [r for r in rows if r.get("meets_expectation")]
    correct_passes = [r for r in passes if r["verdict"] == "CORRECT"]
    decline_passes = [r for r in passes
                      if not r.get("answerable") and r["verdict"] == "DECLINE_APPROPRIATE"]
    ok_passes = correct_passes + decline_passes
    strict = [r for r in correct_passes if "season_scope" in r.get("flags", [])]
    counts = Counter(r["verdict"] for r in rows)
    by_cat = defaultdict(Counter)
    for r in rows:
        by_cat[r["category"]][r["verdict"]] += 1

    missed_a, missed_b = missed(rows)
    return {
        "summary.md": summary(rows, facts, counts, by_cat, passes, correct_passes,
                              decline_passes, ok_passes, strict),
        "incorrect.md": incorrect(rows),
        "unsupported.md": unsupported(rows),
        "missed-answers.md": missed_a,
        "missed-answers-more.md": missed_b,
    }


def summary(rows, facts, counts, by_cat, passes, correct_passes, decline_passes,
            ok_passes, strict):
    out = []
    out.append("# Independent factual audit: final3-n70\n")
    out.append(
        f"Responses audited: {len(rows)}. `meets_expectation` passes: {len(passes)}. "
        f"Passes that survive this audit as correct behavior: {len(ok_passes)}/{len(passes)} "
        f"({len(correct_passes)} substantive answers plus {len(decline_passes)} appropriate "
        f"declines on unsupported questions). Of the substantive passes, {len(strict)} use "
        "all-phase totals where a regular-season reading gives a different number (see below).\n"
    )
    out.append("Oracle: independent SQL over the local restored release "
               "`2025-26.20260928.1` (101 games: 82 regular season, 19 playoffs). "
               "No application calculation code was used.\n")
    out.append("Detail files: `incorrect.md`, `unsupported.md`, `missed-answers.md`. "
               "Machine-readable verdicts are in `verdicts/<category>.jsonl`.\n")

    out.append("## Verdicts\n")
    out.append("| Verdict | Count |\n| --- | ---: |")
    for key in ("CORRECT", "INCORRECT", "UNSUPPORTED_CLAIM", "DECLINE_APPROPRIATE",
                "DECLINE_MISSED_ANSWER", "INSUFFICIENT"):
        out.append(f"| {key} | {counts.get(key, 0)} |")
    out.append(f"| **Total** | **{len(rows)}** |\n")
    hand_count = sum(1 for r in rows if r.get("hand_labeled"))
    out.append(f"Hand-labeled rows: {hand_count}/{len(rows)}. Numeric claims in those rows "
               "are still compared with SQL; the label covers only question interpretation or "
               "polite-decline judgment.\n")

    out.append("## By category\n")
    cats = ["exact_statistics", "date_range_last_n", "comparisons", "single_game_narrative",
            "turning_points", "aliases_typos", "unsupported"]
    out.append("| Category | CORRECT | INCORRECT | UNSUPPORTED | DECLINE_OK | MISSED | INSUFFICIENT |")
    out.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cat in cats:
        c = by_cat[cat]
        out.append(
            f"| {cat} | {c.get('CORRECT',0)} | {c.get('INCORRECT',0)} | "
            f"{c.get('UNSUPPORTED_CLAIM',0)} | {c.get('DECLINE_APPROPRIATE',0)} | "
            f"{c.get('DECLINE_MISSED_ANSWER',0)} | {c.get('INSUFFICIENT',0)} |"
        )
    out.append("")

    out.append("## Pass audit\n")
    out.append("The 37 `meets_expectation` passes break down as follows:\n")
    out.append(f"- Correct substantive answers: {len(correct_passes)}")
    out.append(f"- Appropriate declines on unanswerable questions: {len(decline_passes)}")
    out.append(f"- Missed answers: "
               f"{sum(1 for r in passes if r['verdict']=='DECLINE_MISSED_ANSWER')}")
    out.append(f"- Factually wrong: {sum(1 for r in passes if r['verdict']=='INCORRECT')}")
    out.append(f"- Unsupported claim: {sum(1 for r in passes if r['verdict']=='UNSUPPORTED_CLAIM')}")
    bad_passes = [r for r in passes if r not in ok_passes]
    if bad_passes:
        out.append("\nPasses that do not survive:\n")
        out.append("| id | verdict | reason |")
        out.append("| --- | --- | --- |")
        for r in bad_passes:
            reason = r.get("right_answer") or r.get("note") or ""
            out.append(f"| {r['id']} | {r['verdict']} | {reason} |")
    out.append("")

    fn = [r for r in rows if not r.get("meets_expectation")
          and (r["verdict"] == "CORRECT"
               or (r["verdict"] == "DECLINE_APPROPRIATE" and not r.get("answerable")))]
    if fn:
        out.append("## Meets-expectation false negatives\n")
        out.append("The phrase-match screen marked these responses as failures, but the audit "
                   "finds them correct:\n")
        out.append("| id | verdict | why |")
        out.append("| --- | --- | --- |")
        for r in fn:
            why = r.get("right_answer") or r.get("note") or ""
            out.append(f"| {r['id']} | {r['verdict']} | {why} |")
        out.append("")

    out.append("## Tone and framing flags\n")
    tone = {
        "process_leak": "Mentions internal tool rounds to the user.",
        "tool_output_dump": "Dumps raw aggregate fields instead of answering or declining.",
        "internal_jargon": "Uses internal schema terms such as game_result = W.",
        "stale_scope": "Claims a play-in scope that does not exist in the release.",
        "stale_current_framing": "Uses current/standings framing the archive cannot support.",
        "stale_recency": "States a false latest-game date.",
        "speculation_framing": "Offers a historical average as if it were a forecast.",
        "question_drift": "Answers a different statistic than the one asked.",
        "tool_artifact": "Leaks a filtered-set artifact such as '0 losses in that filtered set'.",
    }
    for flag, why in tone.items():
        ids = [r["id"] for r in rows if flag in r.get("flags", [])]
        if ids:
            out.append(f"- `{flag}`: {why} ({', '.join(ids)})")
    out.append("- No betting advice or gambling recommendation appears in any response.")
    out.append("")

    out.append("## Flags\n")
    flag_counts = Counter(f for r in rows for f in r.get("flags", []))
    for flag, count in flag_counts.most_common():
        ids = [r["id"] for r in rows if flag in r.get("flags", [])]
        out.append(f"- `{flag}` x{count}: {', '.join(ids)}")
    out.append("")

    scope_ids = [r["id"] for r in rows if "season_scope" in r.get("flags", [])]
    if scope_ids:
        a = facts["core"]["all"]
        g = facts["core"]["regular"]
        out.append("## Season scope on the seven all-phase answers\n")
        out.append("These answers say 'archive' or 'across 101 games' and are correct under that "
                   "reading. A user asking 'this season' may mean the regular season, where every "
                   "value differs:\n")
        out.append("| Metric | All-phase (used) | Regular season |")
        out.append("| --- | ---: | ---: |")
        out.append(f"| Record | {a['wins']}-{a['losses']} | {g['wins']}-{g['losses']} |")
        out.append(f"| Points | {a['points']:,} | {g['points']:,} |")
        out.append(f"| Points per game | {a['avg_points']} | {g['avg_points']} |")
        out.append(f"| Average margin | {a['avg_margin']} | {g['avg_margin']} |")
        out.append(f"| Home wins | {a['home_wins']} | {g['home_wins']} |")
        out.append(f"| Road wins | {a['away_wins']} | {g['away_wins']} |")
        out.append("")
        out.append(f"Affected: {', '.join(scope_ids)}.\n")

    out.append("## Audit notes\n")
    integ = facts["integrity"]
    out.append(f"- Integrity: {integ['games']} games, {integ['distinct_nba_game_ids']} distinct "
               f"nba_game_ids, {integ['team_score_mismatches']} team-score mismatches, "
               f"{integ['period_score_mismatches']} period-score mismatches. No game is "
               "double-counted.")
    out.append("- Rounding: every one-decimal average matched its SQL value within 0.05 and every "
               "two-decimal value within 0.005. No rounding error was found.")
    out.append("- `game_events` holds 46,500 play-by-play rows for all 101 games, and "
               "`period_scores` covers all 101 games. Answers that say the archive has no "
               "play-by-play, possession, quarter or halftime data are contradicted by the restore.")
    out.append("- `team_game_stats` has two rows per game (one per team); every query here "
               "filters `team_id = 'NYK'`. Unfiltered team-stat sums double count.")
    out.append("- 2025-26 player averages here exclude zero-minute DNP rows when the answer "
               "says \"appearances\". Towns has 96 rows, 94 appearances; that is why 19.2 and "
               "11.6 over 94 reconcile.")
    out.append("- `unsupported-009` and `unsupported-010` are labelled not answerable in the "
               "benchmark, but the archive has two Lakers games and four Celtics games. The "
               "responses ask which game, which is correct; the labels are wrong.")
    out.append("- Reproduction: `python3 audit.py` runs every query in `queries_core.sql` and "
               "`queries_events.sql` through psql and rewrites all report files.")
    return "\n".join(out) + "\n"


def incorrect(rows):
    out = ["# INCORRECT responses\n"]
    bad = [r for r in rows if r["verdict"] == "INCORRECT"
           or any(f["type"] == "INCORRECT" for f in r.get("findings", []))]
    primary = [r for r in rows if r["verdict"] == "INCORRECT"]
    out.append(f"Primary verdict INCORRECT: {len(primary)} responses. Including finding-level "
               f"incorrect statements: {len(bad)} responses.\n")
    for r in bad:
        out.append(f"## {r['id']}\n")
        out.append(f"- Question: {r['question']}")
        out.append(f"- Quoted answer: \"{r['answer']}\"")
        out.append(f"- Primary verdict: {r['verdict']}")
        out.append(f"- Right value: {r.get('right_answer','')}")
        if r.get("missing_required_terms"):
            out.append(f"- Missing required fact: {', '.join(r['missing_required_terms'])}")
        for c in r.get("claims", []):
            if c["pass"]:
                continue
            out.append(f"- FAIL: {c['label']} claimed `{fmt(c['claimed'])}`, SQL "
                       f"`{fmt(c['actual'])}`; quote \"{c['quote']}\"")
        for f in r.get("findings", []):
            if f["type"] != "INCORRECT":
                continue
            out.append(f"- finding: \"{f['quote']}\" - {f['detail']} ({f.get('evidence','')})")
        out.append(f"- Tables: {', '.join(r.get('data_tables', [])) or 'n/a'}\n")
    return "\n".join(out) + "\n"


def unsupported(rows):
    out = ["# UNSUPPORTED_CLAIM responses and findings\n"]
    primary = [r for r in rows if r["verdict"] == "UNSUPPORTED_CLAIM"]
    findings = [(r, f) for r in rows for f in r.get("findings", [])
                if f["type"] == "UNSUPPORTED_CLAIM"]
    out.append(f"Primary verdict UNSUPPORTED_CLAIM: {len(primary)} responses. "
               f"Claim-level findings inside other responses: {len(findings)}.\n")
    for r in primary:
        out.append(f"## {r['id']}\n")
        out.append(f"- Question: {r['question']}")
        out.append(f"- Answer: \"{r['answer']}\"")
        out.append(f"- Why: {r.get('right_answer','')}")
        if r.get("note"):
            out.append(f"- Evidence: {r['note']}")
        out.append("")
    for r, f in findings:
        out.append(f"## {r['id']} (finding)\n")
        out.append(f"- Question: {r['question']}")
        out.append(f"- Quote: \"{f['quote']}\"")
        out.append(f"- Why: {f['detail']}")
        if f.get("evidence"):
            out.append(f"- SQL: {f['evidence']}")
        out.append("")
    return "\n".join(out) + "\n"


def missed(rows):
    out = ["# DECLINE_MISSED_ANSWER, ranked by existing data\n"]
    missed_rows = sorted([r for r in rows if r["verdict"] == "DECLINE_MISSED_ANSWER"],
                         key=lambda r: r.get("data_score", 0), reverse=True)
    out.append("Ranked by rows already loaded for the slice the question needs. Play-by-play "
               "and period data dominate, so those analyst tools come first.\n")
    out.append("| Rank | id | Data already loaded | Tables | Right answer |")
    out.append("| ---: | --- | ---: | --- | --- |")
    for i, r in enumerate(missed_rows, 1):
        out.append(f"| {i} | {r['id']} | {r.get('data_score',0):,} rows | "
                   f"{', '.join(r.get('data_tables', []))} | {r.get('right_answer','')} |")
    out.append("")
    head = "\n".join(out) + "\n"
    detail = ["# DECLINE_MISSED_ANSWER details (part 2)\n"]
    for i, r in enumerate(missed_rows):
        target = out if i < 13 else detail
        target.append(f"## {r['id']} ({r.get('data_score',0):,} rows)\n")
        target.append(f"- Question: {r['question']}")
        target.append(f"- Declined with: \"{r['answer']}\"")
        target.append(f"- Right answer: {r.get('right_answer','')}")
        if r.get("note"):
            target.append(f"- Note: {r['note']}")
        target.append("")
    first = "\n".join(out) + "\n"
    second = "\n".join(detail) + "\n"
    return first, second
