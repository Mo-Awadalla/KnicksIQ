"""Recompute and assert the DRAFT launch set and the DRAFT evaluation adjudications from the bundle.

    python3 tools/release/compute_launch_set.py          # recompute, assert files match, print summary
    python3 tools/release/compute_launch_set.py --write  # regenerate the four draft files

Every expected fact is computed here from
`release-artifacts/2025-26/reliability-approved-20260928.json.gz`; the files are this script's output,
so no number exists only as hand-typed text. No model or network calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_drafts import CONTRACT, DRAFT_HEADER, render  # noqa: E402
from launch_set_data import Bundle, Game, box_ref  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "docs/release-evidence/launch-set-20261020"
QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
STATS = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes": "three_pointers_made",
}


def _game_fact(g: Game, player_value: int | None = None) -> dict:
    value = {"game_date": g.date, "opponent": g.opponent, "nyk": g.nyk, "opp": g.opp, "won": g.won}
    if player_value is not None:
        value["player_value"] = player_value
    return value


def threshold(b: Bundle, name: str, stat: str, op: str, n: int) -> tuple[list[dict], str]:
    pid = b.player_id(name)
    test: Callable[[int], bool] = (lambda v: v > n) if op == ">" else (lambda v: v >= n)
    rows = [r for r in b.player_rows(pid) if test(r[STATS[stat]])]
    facts = [
        {
            "metric": f"{name}: {stat}",
            "canonical_evidence_ids": [box_ref(r), f"game:{r['nba_game_id']}"],
            "value": _game_fact(b.by_id[r["nba_game_id"]], r[STATS[stat]]),
        }
        for r in rows
    ]
    facts.append(
        {
            "metric": "games",
            "canonical_evidence_ids": [box_ref(r) for r in rows],
            "value": len(rows),
        }
    )
    return facts, (
        f"player_game_stats rows for {name} (nba_player_id {pid}) with minutes > 0, all 101 games "
        f"incl. playoffs, where {STATS[stat]} {op} {n}."
    )


def team_threshold(b: Bundle, op: str, n: int) -> tuple[list[dict], str]:
    games = [g for g in b.games if (g.nyk > n if op == ">" else g.nyk >= n)]
    facts = [
        {"metric": "game_score", "canonical_evidence_ids": [g.ref], "value": _game_fact(g)}
        for g in games
    ]
    facts.append(
        {"metric": "games", "canonical_evidence_ids": [g.ref for g in games], "value": len(games)}
    )
    return facts, f"games rows, NYK final score {op} {n}, all 101 games incl. playoffs."


def leader(b: Bundle, stat: str, date: str) -> tuple[list[dict], str]:
    g = next(g for g in b.games if g.date == date)
    rows = b.nyk_rows(g)
    best = max(r[STATS[stat]] for r in rows)
    top = [r for r in rows if r[STATS[stat]] == best]
    facts = [
        {
            "metric": f"leader: {stat}",
            "canonical_evidence_ids": [box_ref(r), g.ref],
            "value": {"player": b.players[r["nba_player_id"]], stat: best, "game": g.label},
        }
        for r in top
    ]
    return (
        facts,
        f"max {STATS[stat]} over NYK player_game_stats rows of {g.ref} ({g.label}); ties all listed.",
    )


def season_high(b: Bundle, stat: str) -> tuple[list[dict], str]:
    rows = [r for g in b.games for r in b.nyk_rows(g)]
    best = max(r[STATS[stat]] for r in rows)
    facts = [
        {
            "metric": f"single-game high: {stat}",
            "canonical_evidence_ids": [box_ref(r), f"game:{r['nba_game_id']}"],
            "value": {
                "player": b.players[r["nba_player_id"]],
                stat: best,
                "game": b.by_id[r["nba_game_id"]].label,
            },
        }
        for r in rows
        if r[STATS[stat]] == best
    ]
    return (
        facts,
        f"max {STATS[stat]} over all NYK player_game_stats rows, 101 games; ties all listed.",
    )


def record(b: Bundle, opponent: str, season_type: str | None = None) -> tuple[list[dict], str]:
    games = [g for g in b.vs(opponent) if season_type in (None, g.row["season_type"])]
    refs = [g.ref for g in games]
    wins = sum(g.won for g in games)
    facts = [
        {"metric": "games", "canonical_evidence_ids": refs, "value": len(games)},
        {"metric": "wins", "canonical_evidence_ids": refs, "value": wins},
        {"metric": "losses", "canonical_evidence_ids": refs, "value": len(games) - wins},
    ] + [
        {"metric": "game_score", "canonical_evidence_ids": [g.ref], "value": _game_fact(g)}
        for g in games
    ]
    scope = season_type or "regular season and playoffs"
    return (
        facts,
        f"games rows with opponent {opponent} ({scope}); win = NYK final score > opponent's.",
    )


def average_vs(
    b: Bundle, name: str, stat: str, opponent: str, season_type: str | None = None
) -> tuple[list[dict], str]:
    pid = b.player_id(name)
    games = [g for g in b.vs(opponent) if season_type in (None, g.row["season_type"])]
    rows = b.player_rows(pid, games)
    total = sum(r[STATS[stat]] for r in rows)
    facts = [
        {
            "metric": f"{name}: average {stat} vs {opponent}",
            "canonical_evidence_ids": [box_ref(r) for r in rows],
            "numerator": total,
            "denominator": len(rows),
            "value": round(total / len(rows), 1),
        }
    ]
    scope = season_type or "regular season and playoffs"
    return facts, (
        f"sum of {STATS[stat]} / appearances (minutes > 0) for {name} in games vs {opponent} ({scope}), "
        "rounded to 1 decimal."
    )


def results_of(b: Bundle, game_ids: list[str]) -> tuple[list[dict], str]:
    games = [b.by_id[i] for i in game_ids]
    facts = [
        {"metric": "game_score", "canonical_evidence_ids": [g.ref], "value": _game_fact(g)}
        for g in games
    ]
    facts.append(
        {
            "metric": "wins",
            "canonical_evidence_ids": [g.ref for g in games],
            "value": sum(g.won for g in games),
        }
    )
    return facts, "final scores of the games named in the prior assistant turn."


def _turn(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def launch_cases(b: Bundle) -> list[dict]:
    specs: list[tuple[str, str, tuple[list[dict], str], list[dict]]] = [
        (
            "threshold",
            "Which games did Jalen Brunson score more than 40 points?",
            threshold(b, "Jalen Brunson", "points", ">", 40),
            [],
        ),
        (
            "threshold",
            "How many games did Brunson score at least 40?",
            threshold(b, "Jalen Brunson", "points", ">=", 40),
            [],
        ),
        (
            "threshold",
            "In which games did Karl-Anthony Towns grab 15 or more rebounds?",
            threshold(b, "Karl-Anthony Towns", "rebounds", ">=", 15),
            [],
        ),
        (
            "threshold",
            "When did Mikal Bridges make at least 5 threes in a game?",
            threshold(b, "Mikal Bridges", "threes", ">=", 5),
            [],
        ),
        (
            "threshold",
            "Which games did OG Anunoby score 30 or more?",
            threshold(b, "OG Anunoby", "points", ">=", 30),
            [],
        ),
        (
            "threshold",
            "How many times did the Knicks score more than 130 points?",
            team_threshold(b, ">", 130),
            [],
        ),
        (
            "single_game_leader",
            "Who led the Knicks in scoring on Christmas Day?",
            leader(b, "points", "2025-12-25"),
            [],
        ),
        (
            "single_game_leader",
            "Who had the most rebounds for the Knicks against Miami on December 21?",
            leader(b, "rebounds", "2025-12-21"),
            [],
        ),
        (
            "single_game_leader",
            "Who led the Knicks in assists in the April 30 playoff game at Atlanta?",
            leader(b, "assists", "2026-04-30"),
            [],
        ),
        (
            "single_game_leader",
            "What was the most points a Knick scored in one game this season?",
            season_high(b, "points"),
            [],
        ),
        (
            "single_game_leader",
            "What was the most rebounds a Knick had in a single game?",
            season_high(b, "rebounds"),
            [],
        ),
        ("head_to_head", "What was the Knicks record against Miami?", record(b, "MIA"), []),
        (
            "head_to_head",
            "How did the Knicks do against the Spurs in the playoffs?",
            record(b, "SAS", "playoffs"),
            [],
        ),
        (
            "head_to_head",
            "What was the Knicks playoff record against Cleveland?",
            record(b, "CLE", "playoffs"),
            [],
        ),
        ("head_to_head", "What was the Knicks record against Detroit?", record(b, "DET"), []),
        (
            "player_vs_opponent",
            "How many points did Brunson average against Atlanta?",
            average_vs(b, "Jalen Brunson", "points", "ATL"),
            [],
        ),
        (
            "player_vs_opponent",
            "What did Towns average in rebounds against Boston?",
            average_vs(b, "Karl-Anthony Towns", "rebounds", "BOS"),
            [],
        ),
        (
            "player_vs_opponent",
            "How many points per game did Mikal Bridges score against the Spurs in the playoffs?",
            average_vs(b, "Mikal Bridges", "points", "SAS", "playoffs"),
            [],
        ),
    ]
    over40 = threshold(b, "Jalen Brunson", "points", ">", 40)[0]
    games40 = [f["value"] for f in over40 if f["metric"] != "games"]
    listed = "; ".join(
        f"{v['game_date']} vs {v['opponent']}, {v['player_value']} points" for v in games40
    )
    ids40 = [f["canonical_evidence_ids"][1].split(":")[1] for f in over40 if f["metric"] != "games"]
    specs.append(
        (
            "follow_up",
            "Did the Knicks win all of those games?",
            results_of(b, ids40),
            [
                _turn("user", "Which games did Jalen Brunson score more than 40 points?"),
                _turn(
                    "assistant", f"Brunson scored more than 40 in {len(games40)} games: {listed}."
                ),
            ],
        )
    )
    den = next(g for g in b.games if g.date == "2026-02-04")
    specs.append(
        (
            "follow_up",
            "Who led the Knicks in rebounds that night?",
            leader(b, "rebounds", den.date),
            [
                _turn("user", "Tell me about the Knicks game against Denver on February 4."),
                _turn(
                    "assistant",
                    f"The Knicks beat Denver {den.nyk}-{den.opp} at home on {den.date}.",
                ),
            ],
        )
    )
    return [
        {
            "id": f"launch-{index:03d}",
            "category": category,
            "question": question,
            "context": context,
            "disposition": "answer",
            "facts": facts,
            "computation": computation,
            "status": "draft_pending_owner_approval",
        }
        for index, (category, question, (facts, computation), context) in enumerate(specs, 1)
    ]


def readme(cases: list[dict]) -> str:
    lines = [
        "# Launch set, 2026-10-20",
        "",
        f"> **DRAFT pending owner approval.** {len(cases)} fan questions not in `questions.jsonl` "
        "(owner decision 4).",
        "",
        "`launch-set.jsonl` is generated by `tools/release/compute_launch_set.py --write` from the "
        "reviewed bundle (SHA-256 `549af2ed...`). Run `python3 tools/release/compute_launch_set.py` to "
        "recompute every expected fact and assert the files match. Each line has the question, any "
        "prior conversation `context`, the expected `disposition`, `facts` with canonical source ids "
        "(`game:`, `box:<game>:<player>`) and the exact `computation`. Player rows count only when "
        "minutes > 0; season scope is all 101 games including playoffs unless the question says otherwise.",
        "",
        "| Id | Category | Question | Expected | Computation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in cases:
        expected = []
        for fact in case["facts"]:
            value = fact["value"]
            if isinstance(value, dict):
                value = ", ".join(f"{k} {v}" for k, v in value.items())
            expected.append(f"{fact['metric']}: {value}")
        question = case["question"]
        if case["context"]:
            question += " _(follow-up; context: " + case["context"][0]["content"] + ")_"
        lines.append(
            f"| `{case['id']}` | {case['category']} | {question} | {'<br>'.join(expected)} | "
            f"{case['computation']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    b = Bundle()
    cases = launch_cases(b)
    asked = {
        json.loads(line)["question"].strip().lower()
        for line in QUESTIONS.read_text().splitlines()
        if line
    }
    overlap = [c["id"] for c in cases if c["question"].strip().lower() in asked]
    assert not overlap, f"launch questions already in questions.jsonl: {overlap}"
    over40 = [f for f in cases[0]["facts"] if f["metric"] != "games"]
    assert [(f["value"]["game_date"], f["value"]["player_value"]) for f in over40] == [
        ("2025-12-21", 47),
        ("2026-02-04", 42),
        ("2026-06-13", 45),
    ], over40
    assert cases[1]["facts"][-1]["value"] == 5
    contract = json.loads((CONTRACT / "expectations.json").read_text())["cases"]
    markdown, adjudications = render(b, contract)
    assert DRAFT_HEADER in markdown
    outputs = {
        LAUNCH / "launch-set.jsonl": "".join(json.dumps(c, sort_keys=True) + "\n" for c in cases),
        LAUNCH / "README.md": readme(cases),
        CONTRACT / "adjudication-drafts.md": markdown,
        CONTRACT / "adjudications-draft.json": adjudications,
    }
    for path, text in outputs.items():
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        elif not path.exists() or path.read_text() != text:
            raise SystemExit(f"MISMATCH: {path.relative_to(ROOT)} differs from recomputation")
    facts = sum(len(c["facts"]) for c in cases)
    print(f"bundle sha256 ok; {len(b.games)} games, {len(b.verified())} with a verified scoreboard")
    print(
        f"launch set: {len(cases)} cases, {facts} facts recomputed; no overlap with questions.jsonl"
    )
    for case in cases:
        tail = case["facts"][-1]
        head = tail if tail["metric"] in ("games", "wins") else case["facts"][0]
        print(f"  {case['id']} {case['question']} -> {head['metric']}: {head['value']}")
    for cid, entry in json.loads(adjudications).items():
        print(f"  {cid}: {len(entry['semantic_targets'])} targets")
    print("all files " + ("written" if args.write else "match recomputation"))


if __name__ == "__main__":
    main()
