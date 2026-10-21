#!/usr/bin/env python3
"""Independent factual audit for the llm_primary 70-question run.

The oracle is SQL in queries_core.sql / queries_events.sql, executed against the
local restored release. No application calculation code is imported or called.

Usage:
    python3 audit.py [responses.jsonl]

Outputs verdicts.jsonl and summary.md next to this script, and prints a summary.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RESPONSES = os.path.join(
    HERE, "..", "..", "llm-primary-20261018", "final3-n70.responses.jsonl"
)
PSQL = os.environ.get(
    "KIQ_PSQL", "docker exec kiq-integrate-postgres-1 psql -U knicksiq -d knicksiq"
)
CUTOFF = 0.005
DECLINE = re.compile(
    r"\b(i can(?:'|’)t|i cannot|can(?:'|’)t (?:give|provide|answer|confirm|determine|verify)|"
    r"cannot (?:give|provide|answer|confirm|determine|verify)|not able to|unable to|"
    r"do(?:es)? not (?:include|cover|contain|have)|doesn(?:'|’)t (?:include|cover|contain|have)|"
    r"no (?:live|future|current))",
    re.I,
)


def split_blocks(path):
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"^-- name: ", text, flags=re.M)[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1] for p in parts}


def run_sql(sql):
    cmd = PSQL.split() + ["-At", "-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    out = proc.stdout.strip()
    return json.loads(out, parse_float=Decimal) if out else None


def load_facts():
    blocks = {}
    for name in ("queries_core.sql", "queries_events.sql"):
        blocks.update(split_blocks(os.path.join(HERE, name)))
    raw = {name: run_sql(sql) for name, sql in blocks.items()}
    facts = {
        "core": {r["scope"]: r for r in raw["core"]},
        "integrity": raw["integrity"],
        "extremes": raw["extremes"],
        "splits": {r["name"]: r for r in raw["splits"]},
        "players": {r["full_name"]: r for r in raw["players"]},
        "player_windows": raw["player_windows"],
        "matchup_summary": {},
        "matchups": {},
        "team": raw["team_splits"],
        "event_runs": raw["event_runs"],
        "event_deficits": raw["event_deficits"],
        "box": {},
        "player_matchups": raw["player_matchups"],
        "coverage": raw["coverage"],
    }
    for r in raw["matchup_summary"]:
        key = r["opp"] + "|" + (r["season_type"] or "all")
        facts["matchup_summary"][key] = r
    for r in raw["matchups"]:
        facts["matchups"].setdefault(r["opp"], []).append(r)
    for r in raw["box_scores"]:
        facts["box"][f'{r["full_name"]}|{r["game_id"]}'] = r
    return facts


def resolve(facts, path):
    if callable(path):
        return path(facts)
    cur = facts
    for part in path.split("."):
        cur = cur[part]
    return cur


def score_value(facts, score):
    if callable(score):
        return int(score(facts))
    if isinstance(score, str):
        return int(resolve(facts, score))
    return int(score or 0)


def equal(claimed, actual, tol=CUTOFF):
    if isinstance(claimed, bool) or isinstance(actual, bool):
        return bool(claimed) == bool(actual)
    if isinstance(claimed, (int, float, Decimal)) and isinstance(actual, (int, float, Decimal)):
        return abs(Decimal(str(claimed)) - Decimal(str(actual))) <= Decimal(str(tol))
    if isinstance(claimed, list):
        return list(claimed) == list(actual)
    return str(claimed) == str(actual)


def evaluate_claim(facts, claim):
    actual = resolve(facts, claim["fn"])
    passed = equal(claim["claimed"], actual, claim.get("tol", CUTOFF))
    return {
        "label": claim["label"],
        "claimed": claim["claimed"],
        "actual": actual,
        "pass": passed,
        "quote": claim.get("quote", ""),
        "sql": claim.get("sql", ""),
    }


def main():
    responses_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RESPONSES
    responses = [json.loads(line) for line in open(responses_path, encoding="utf-8") if line.strip()]
    facts = load_facts()
    sys.path.insert(0, HERE)
    from checks_numeric import SPECS as NUMERIC
    from checks_policy_20261021 import SPECS as POLICY
    from checks_semantic_a import SPECS as SEM_A
    from checks_semantic_b import SPECS as SEM_B
    specs = {**NUMERIC, **SEM_A, **SEM_B, **POLICY}

    rows = []
    for response in responses:
        rid = response["id"]
        spec = specs.get(rid)
        if spec is None:
            rows.append({**response, "verdict": "INSUFFICIENT", "hand_labeled": True,
                         "note": "No check registered for this id."})
            continue
        answer = response["answer"]
        claims = []
        for spec_claim in spec.get("claims", []):
            claim = dict(spec_claim)
            if "extract" in claim:
                claim["claimed"] = claim["extract"](answer)
                if claim.get("optional") and claim["claimed"] is None:
                    continue
            claims.append(evaluate_claim(facts, claim))
        failed = [c for c in claims if not c["pass"]]
        required = spec.get("required_terms", [])
        missing_terms = [t for t in required if t.lower() not in answer.lower()]
        forbidden = [t for t in spec.get("forbidden_terms", []) if t.lower() in answer.lower()]
        verdict = spec.get("verdict")
        if failed or missing_terms or forbidden:
            declined = bool(DECLINE.search(answer))
            if declined and spec.get("decline_verdict") and not forbidden:
                verdict = spec["decline_verdict"]
            else:
                verdict = "INCORRECT"
        elif verdict is None:
            verdict = "CORRECT"
        row = {
            **response,
            "verdict": verdict,
            "hand_labeled": bool(spec.get("hand", False)),
            "claims": claims,
            "missing_required_terms": missing_terms,
            "findings": spec.get("findings", []),
            "flags": spec.get("flags", []),
            "right_answer": spec.get("right", ""),
            "data_tables": spec.get("tables", []),
            "data_score": score_value(facts, spec.get("data_score", 0)),
            "note": spec.get("note", ""),
            "hand_label_reason": spec.get("hand_reason", ""),
        }
        rows.append(row)

    from report import reports as render

    docs = render(rows, facts)
    for name, content in docs.items():
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    verdict_dir = os.path.join(HERE, "verdicts")
    os.makedirs(verdict_dir, exist_ok=True)
    by_cat = {}
    for row in rows:
        by_cat.setdefault(row["category"], []).append(row)
    for cat, items in by_cat.items():
        with open(os.path.join(verdict_dir, cat + ".jsonl"), "w", encoding="utf-8") as fh:
            for row in items:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    print(docs["summary.md"])


if __name__ == "__main__":
    main()
