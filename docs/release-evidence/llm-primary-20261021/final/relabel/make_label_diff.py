"""Prove the held-out relabel: question stability, per-fact SQL, phase table, verdict changes.

Run from the repository root with the local release:

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
        uv run --package knicksiq-api python \
        docs/release-evidence/llm-primary-20261021/final/relabel/make_label_diff.py

The old labels come from commit 5ddfddc, the new labels from the worktree. The script reads
no response file to build a fact; the response files are read only to list verdict changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "apps/api"))
sys.path.insert(0, str(ROOT / "tools/release"))

from app.evaluation.heldout_phase import phase_policy  # noqa: E402
from app.evaluation.heldout_facts import dsn  # noqa: E402

HERE = Path(__file__).resolve().parent
OLD_LABELS_REF = "5ddfddc:apps/api/app/evaluation/heldout_questions.jsonl"
NEW_LABELS = ROOT / "apps/api/app/evaluation/heldout_questions.jsonl"
RUNS = {
    "final-run": {
        "responses": ROOT
        / "docs/release-evidence/llm-primary-20261021/final/heldout-60.responses.jsonl",
        "old": HERE / "final-run.old-labels.rescored.scored.jsonl",
        "new": HERE / "final-run.new-labels.rescored.scored.jsonl",
    },
    "baseline": {
        "responses": ROOT
        / "docs/release-evidence/llm-primary-20261021/scoring/heldout-60.responses.jsonl",
        "old": HERE / "baseline.old-labels.rescored.scored.jsonl",
        "new": HERE / "baseline.new-labels.rescored.scored.jsonl",
    },
}

TEAM_CTE = """
with g as (
  select season_type,
         case when home_team_id = 'NYK' then home_score else away_score end as nyk,
         case when home_team_id = 'NYK' then away_score else home_score end as opp,
         (home_team_id = 'NYK') as is_home
  from games
  where release_id = 1
)
"""


def team_sql(expression: str, where: str = "") -> str:
    return TEAM_CTE + f"select round({expression}::numeric, 4) as value from g {where}".strip()


def player_sql(
    player: str,
    expression: str,
    *,
    season: str | None = None,
    opponent: str | None = None,
    observed: bool = False,
) -> str:
    clauses = [
        "s.release_id = 1",
        "s.team_id = 'NYK'",
        f"p.full_name = '{player}'",
    ]
    if season:
        clauses.append(f"g.season_type = '{season}'")
    if opponent:
        clauses.append(
            f"(g.home_team_id = '{opponent}' or g.away_team_id = '{opponent}')"
        )
    if observed:
        clauses.append("s.minutes > 0")
    return (
        f"select round({expression}::numeric, 4) as value\n"
        "from player_game_stats s\n"
        "join players p on p.id = s.player_id\n"
        "join games g on g.id = s.game_id\n"
        "where " + "\n  and ".join(clauses)
    )


# id, fact index, change kind, old SQL, new SQL, explanation.
CHANGES: list[tuple[str, int, str, str, str, str]] = [
    (
        "heldout-exact_statistics-002",
        0,
        "phase",
        team_sql("avg(nyk)"),
        team_sql("avg(nyk)", "where season_type = 'regular'"),
        "Season-level question (no opponent, date or relative window): the policy default is "
        "the regular season. Old population was all 101 games; new is the 82 regular-season games.",
    ),
    (
        "heldout-exact_statistics-004",
        0,
        "phase",
        team_sql("count(*)", "where is_home and nyk < opp"),
        team_sql("count(*)", "where is_home and nyk < opp and season_type = 'regular'"),
        "Season-level question: home losses default to the regular season. Old 12 over 49 home "
        "games; new 10 over 40 regular-season home games.",
    ),
    (
        "heldout-exact_statistics-005",
        0,
        "phase",
        player_sql("Mitchell Robinson", "sum(s.rebounds)"),
        player_sql("Mitchell Robinson", "sum(s.rebounds)", season="regular"),
        "Season-level player total: the regular season is the default. Old total included the 19 "
        "playoff games; the new total is regular season only.",
    ),
    (
        "heldout-exact_statistics-006",
        0,
        "phase+appearance",
        player_sql("Miles McBride", "avg(s.assists)"),
        player_sql("Miles McBride", "avg(s.assists)", season="regular", observed=True),
        "Season-level player average: regular season, and the denominator is appearances "
        "(minutes > 0), not every player-game row. Old 129/61 all-phase rows; new 106/41.",
    ),
    (
        "heldout-exact_statistics-007",
        0,
        "phase",
        player_sql("Landry Shamet", "sum(s.three_pointers_made)"),
        player_sql("Landry Shamet", "sum(s.three_pointers_made)", season="regular"),
        "Season-level player total: regular season is the default. Old total included the "
        "playoffs; the new total is regular season only.",
    ),
    (
        "heldout-exact_statistics-008",
        0,
        "phase+appearance",
        player_sql("Jordan Clarkson", "avg(s.points)"),
        player_sql("Jordan Clarkson", "avg(s.points)", season="regular", observed=True),
        "Season-level player average: regular season and appearances only. Old 711/101 all-phase "
        "rows; new 622/72 regular-season appearances.",
    ),
    (
        "heldout-exact_statistics-009",
        0,
        "phase",
        team_sql("count(*)", "where nyk - opp >= 20"),
        team_sql("count(*)", "where nyk - opp >= 20 and season_type = 'regular'"),
        "Season-level team count: regular season is the default. Old 22 over all 101 games; new "
        "17 over the 82 regular-season games.",
    ),
    (
        "heldout-comparisons-001",
        0,
        "phase+appearance",
        player_sql("Miles McBride", "avg(s.points)"),
        player_sql("Miles McBride", "avg(s.points)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 598/61 "
        "all-phase rows; new 491/41 regular-season appearances.",
    ),
    (
        "heldout-comparisons-001",
        1,
        "phase+appearance",
        player_sql("Landry Shamet", "avg(s.points)"),
        player_sql("Landry Shamet", "avg(s.points)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 589/70; new "
        "475/51.",
    ),
    (
        "heldout-comparisons-002",
        0,
        "phase+appearance",
        player_sql("Mitchell Robinson", "avg(s.rebounds)"),
        player_sql("Mitchell Robinson", "avg(s.rebounds)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 624/79; new "
        "525/60.",
    ),
    (
        "heldout-comparisons-002",
        1,
        "phase+appearance",
        player_sql("Ariel Hukporti", "avg(s.rebounds)"),
        player_sql("Ariel Hukporti", "avg(s.rebounds)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 191/99; new "
        "159/54.",
    ),
    (
        "heldout-comparisons-003",
        0,
        "phase",
        team_sql("avg(nyk)", "where is_home"),
        team_sql("avg(nyk)", "where is_home and season_type = 'regular'"),
        "Season-level home/road split: regular season is the default. Old home average over 49 "
        "games; new over 40 regular-season home games.",
    ),
    (
        "heldout-comparisons-003",
        1,
        "phase",
        team_sql("avg(nyk)", "where not is_home"),
        team_sql("avg(nyk)", "where not is_home and season_type = 'regular'"),
        "Season-level home/road split: regular season is the default. Old road average over 52 "
        "games; new over 42 regular-season road games.",
    ),
    (
        "heldout-comparisons-005",
        0,
        "phase+appearance",
        player_sql("Miles McBride", "avg(s.assists)"),
        player_sql("Miles McBride", "avg(s.assists)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 129/61; new "
        "106/41.",
    ),
    (
        "heldout-comparisons-005",
        1,
        "phase+appearance",
        player_sql("Landry Shamet", "avg(s.assists)"),
        player_sql("Landry Shamet", "avg(s.assists)", season="regular", observed=True),
        "Season-level player comparison: regular season and appearances only. Old 86/70; new "
        "72/51.",
    ),
    (
        "heldout-comparisons-006",
        0,
        "appearance",
        player_sql("Jordan Clarkson", "avg(s.points)", season="regular"),
        player_sql("Jordan Clarkson", "avg(s.points)", season="regular", observed=True),
        "The question names both phases, so the phase is unchanged. Only the denominator changed: "
        "old 622/82 regular-season rows; new 622/72 regular-season appearances.",
    ),
    (
        "heldout-comparisons-006",
        1,
        "appearance",
        player_sql("Jordan Clarkson", "avg(s.points)", season="playoffs"),
        player_sql("Jordan Clarkson", "avg(s.points)", season="playoffs", observed=True),
        "The question names both phases, so the phase is unchanged. Only the denominator changed: "
        "old 89/19 playoff rows; new 89/18 playoff appearances.",
    ),
    (
        "heldout-comparisons-007",
        0,
        "phase",
        team_sql("avg(nyk - opp)", "where is_home"),
        team_sql("avg(nyk - opp)", "where is_home and season_type = 'regular'"),
        "Season-level home/road split: regular season is the default. Old home margin over 49 "
        "games; new over 40 regular-season home games.",
    ),
    (
        "heldout-comparisons-007",
        1,
        "phase",
        team_sql("avg(nyk - opp)", "where not is_home"),
        team_sql("avg(nyk - opp)", "where not is_home and season_type = 'regular'"),
        "Season-level home/road split: regular season is the default. Old road margin over 52 "
        "games; new over 42 regular-season road games.",
    ),
    (
        "heldout-aliases_typos-003",
        0,
        "appearance",
        player_sql("Mitchell Robinson", "avg(s.rebounds)", opponent="PHI"),
        player_sql("Mitchell Robinson", "avg(s.rebounds)", opponent="PHI", observed=True),
        "Opponent question, so every phase is correct and the phase did not change. The old "
        "denominator included a zero-minute DNP row: 53/8; the observed-appearance average is "
        "53/7.",
    ),
]

REASONS = {
    "heldout-exact_statistics-002": "Old fact was the all-phase 101-game average (116.34). "
    "The policy default is the regular season; the run states 116.45 over 82 games.",
    "heldout-exact_statistics-004": "Old fact counted all-phase home losses (12 over 49). The "
    "regular-season population is 10 over 40; the run states 10.",
    "heldout-exact_statistics-006": "Old fact was all-phase over every player row (2.1). The "
    "regular-season observed-appearance average is 2.6; the run states 2.6.",
    "heldout-exact_statistics-008": "Old fact was all-phase over every player row (7.0). The "
    "regular-season observed-appearance average is 8.6; the run states 8.6.",
    "heldout-comparisons-001": "Old facts were all-phase over every player row (9.80/8.41). "
    "Regular-season observed averages are 11.98/9.31; the run states 12.0/9.3.",
    "heldout-comparisons-002": "Old facts were all-phase over every player row (7.90/1.93). "
    "Regular-season observed averages are 8.75/2.94; the run states 8.8/2.9.",
    "heldout-comparisons-005": "Old facts were all-phase over every player row (2.11/1.23). "
    "Regular-season observed averages are 2.59/1.41; the run states 2.6/1.4.",
    "heldout-aliases_typos-003": "Phase is every phase under the opponent rule and did not "
    "change. The old label divided by 8 rows including a zero-minute DNP; the observed "
    "average is 7.57 and the run states 7.6.",
    "heldout-exact_statistics-004:lost": "The baseline response says 12 home losses, which was "
    "right under the old all-phase label and is wrong under the policy; the baseline loses "
    "this row.",
}


def load_old_labels() -> list[dict]:
    text = subprocess.run(
        ["git", "show", OLD_LABELS_REF], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_new_labels() -> list[dict]:
    return [json.loads(line) for line in NEW_LABELS.read_text().splitlines() if line.strip()]


def pairs(rows: list[dict]) -> str:
    return "".join(
        json.dumps({"id": row["id"], "question": row["question"]}, separators=(",", ":")) + "\n"
        for row in rows
    )


def fact_number(fact: str) -> float:
    """The fact value is the last number in the label; earlier numbers are qualifiers."""
    import re

    found = re.findall(r"-?\d+(?:\.\d+)?", fact)
    if not found:
        raise ValueError(fact)
    return float(found[-1])


def places(fact: str) -> int:
    import re

    found = re.findall(r"-?\d+(?:\.\d+)?", fact)
    if not found or "." not in found[-1]:
        return 0
    return len(found[-1].split(".")[1])


async def sql_value(connection: asyncpg.Connection, sql: str) -> float:
    row = await connection.fetchrow(sql)
    return float(row["value"])


async def main() -> None:
    old = load_old_labels()
    new = load_new_labels()
    if len(old) != 60 or len(new) != 60:
        raise SystemExit(f"expected 60 rows, got {len(old)} and {len(new)}")
    if [row["id"] for row in old] != [row["id"] for row in new]:
        raise SystemExit("ids changed")
    if [row["question"] for row in old] != [row["question"] for row in new]:
        raise SystemExit("question text changed")
    for before, after in zip(old, new):
        for field in (
            "category",
            "expected_route",
            "answerable",
            "required_entities",
            "required_phrases",
        ):
            if before.get(field) != after.get(field):
                raise SystemExit(f"{before['id']}: {field} changed")
    before_pairs = pairs(old)
    after_pairs = pairs(new)
    if before_pairs != after_pairs:
        raise SystemExit("id/question pairs changed")

    stability = {
        "old_source": OLD_LABELS_REF,
        "old_sha256": hashlib.sha256(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in old).encode()
        ).hexdigest(),
        "new_source": str(NEW_LABELS.relative_to(ROOT)),
        "new_sha256": hashlib.sha256(NEW_LABELS.read_bytes()).hexdigest(),
        "count": len(new),
        "ids_identical": True,
        "questions_identical": True,
        "id_question_pairs_sha256": hashlib.sha256(after_pairs.encode()).hexdigest(),
        "id_question_pairs_diff": "",
        "categories_unchanged": True,
        "expected_routes_unchanged": True,
        "answerable_unchanged": True,
        "required_entities_unchanged": True,
        "required_phrases_unchanged": True,
        "fields_changed": [
            "required_facts on 14 rows (20 facts)",
        ],
    }
    (HERE / "questions-stable.json").write_text(json.dumps(stability, indent=2) + "\n")

    phase_rows = []
    for row in new:
        if row["answerable"]:
            phase, rule = phase_policy(row["question"])
        else:
            phase, rule = None, "unsupported"
        phase_rows.append(
            {
                "id": row["id"],
                "category": row["category"],
                "phase": phase,
                "rule": rule,
                "filters": row["filters"],
                "question": row["question"],
            }
        )
    (HERE / "phase-policy.json").write_text(json.dumps(phase_rows, indent=1) + "\n")

    connection = await asyncpg.connect(dsn())
    try:
        changes = []
        for cid, index, kind, old_sql, new_sql, why in CHANGES:
            old_row = next(row for row in old if row["id"] == cid)
            new_row = next(row for row in new if row["id"] == cid)
            old_fact = old_row["required_facts"][index]
            new_fact = new_row["required_facts"][index]
            old_value = await sql_value(connection, old_sql)
            new_value = await sql_value(connection, new_sql)
            old_places = places(old_fact)
            new_places = places(new_fact)
            if abs(round(old_value, old_places) - fact_number(old_fact)) > 1e-9:
                raise SystemExit(
                    f"{cid}[{index}]: old fact {old_fact!r} != SQL {old_value} "
                    f"rounded to {old_places}"
                )
            if abs(round(new_value, new_places) - fact_number(new_fact)) > 1e-9:
                raise SystemExit(
                    f"{cid}[{index}]: new fact {new_fact!r} != SQL {new_value} "
                    f"rounded to {new_places}"
                )
            changes.append(
                {
                    "id": cid,
                    "fact_index": index,
                    "kind": kind,
                    "old_fact": old_fact,
                    "new_fact": new_fact,
                    "old_sql": old_sql.strip(),
                    "new_sql": new_sql.strip(),
                    "old_value": old_value,
                    "new_value": new_value,
                    "phase": phase_policy(new_row["question"])[0],
                    "why": why,
                }
            )
    finally:
        await connection.close()

    (HERE / "label-diff.json").write_text(
        json.dumps(changes, separators=(",", ":")) + "\n"
    )

    verdicts = []
    for run, paths in RUNS.items():
        old_scored = {
            json.loads(line)["id"]: json.loads(line)
            for line in paths["old"].read_text().splitlines()
            if line.strip()
        }
        new_scored = {
            json.loads(line)["id"]: json.loads(line)
            for line in paths["new"].read_text().splitlines()
            if line.strip()
        }
        responses = {
            json.loads(line)["id"]: json.loads(line)
            for line in paths["responses"].read_text().splitlines()
            if line.strip()
        }
        if len(old_scored) != 60 or len(new_scored) != 60:
            raise SystemExit(f"{run}: rescored row count is not 60")
        for cid in old_scored:
            before = old_scored[cid]
            after = new_scored[cid]
            if before["meets_expectation"] == after["meets_expectation"]:
                continue
            key = cid if after["meets_expectation"] else cid + ":lost"
            verdicts.append(
                {
                    "run": run,
                    "id": cid,
                    "direction": "gained" if after["meets_expectation"] else "lost",
                    "old_failures": before["failures"],
                    "new_failures": after["failures"],
                    "old_required_facts": before["checks"]["required_facts"],
                    "new_required_facts": after["checks"]["required_facts"],
                    "answer": responses[cid].get("answer", ""),
                    "reason": REASONS[key],
                }
            )
    (HERE / "verdict-changes.json").write_text(json.dumps(verdicts, indent=2) + "\n")

    print(f"label changes: {len(changes)} facts on {len({c['id'] for c in changes})} rows")
    print(f"verdict changes: {len(verdicts)}")
    print(f"questions stable: {stability['id_question_pairs_sha256']}")


if __name__ == "__main__":
    asyncio.run(main())
