"""Generate the held-out v2 analyst evaluation set from the active local release.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
        uv run --package knicksiq-api python -m app.evaluation.heldout_v2.build

No provider is called. The committed questions, follow-up sessions, hash and overlap report are
the evidence artifact. Do not hand-edit the generated JSONL.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import asyncpg

from app.evaluation.heldout_phase import Phase, phase_policy

from .cases import COMPARISONS, DATES, EXACT, Case
from .cases_games import ALIASES, NARRATIVE, TURNING, canonical_question
from .facts import Archive, dsn, load_archive
from .follow_ups import FOLLOW_UP_SESSIONS, follow_up_order_digest
from .unsupported import UNSUPPORTED

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.jsonl"
FOLLOW_UPS = HERE / "follow_ups.jsonl"
META = HERE / "meta.json"
OVERLAP = HERE / "overlap_report.json"

MAIN_CASES: list[Case] = EXACT + DATES + COMPARISONS + NARRATIVE + TURNING + ALIASES + UNSUPPORTED
EXPECTED_COUNT = 80
EXPECTED_CATEGORIES = {
    "aliases_typos": 11,
    "comparisons": 11,
    "date_range_last_n": 12,
    "exact_statistics": 12,
    "single_game_narrative": 11,
    "turning_points": 11,
    "unsupported": 12,
}
EXPECTED_QUESTION_ORDER_SHA256 = "897c693f9c978cfe2f68a05136cda75d4d74e37c3640bd352c0196f76d3ed9bd"
EXPECTED_FOLLOW_UP_ORDER_SHA256 = "4d540490faec3944430871bb37024a5ef4f935205fe4f2b214a19df423601448"

POLICY = (
    "Held-out set. Nobody tunes prompts, tools, thresholds, labels or routing against individual "
    "items. The only permitted use is one release run and its aggregate scorer report, including "
    "per-question check output for audit. Do not select examples, prompts or fixes from this set."
)
PHASE_POLICY = (
    "Season-level questions use the regular season. A question naming playoffs, overall or all "
    "phases uses that phase. A question naming an opponent spans every phase unless it also names "
    "a phase. A date window uses the named dates; a relative window spans every phase. A specific "
    "game is that game. Player averages count only appearances with minutes > 0. Follow-up turns "
    "inherit the game established in their session context. Team nicknames are canonicalised "
    "before the shared policy runs, without changing the policy rules."
)


def resolved_phase(question: str) -> Phase:
    return phase_policy(canonical_question(question))[0]


def _json_line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"


def build_main(archive: Archive) -> list[dict]:
    rows: list[dict] = []
    counts: defaultdict[str, int] = defaultdict(int)
    for case in MAIN_CASES:
        counts[case.category] += 1
        phase: Phase | None
        if case.answerable:
            phase = resolved_phase(case.question)
            facts, entities, phrases = case.facts(archive, phase)
            if not facts:
                raise RuntimeError(f"missing required facts: {case.question}")
            if not entities:
                raise RuntimeError(f"missing required entities: {case.question}")
        else:
            phase = None
            facts, entities, phrases = case.facts(archive, "regular")
            if facts or entities:
                raise RuntimeError(f"unsupported case carries facts: {case.question}")
        row: dict[str, object] = {
            "id": f"heldout2-{case.category}-{counts[case.category]:03d}",
            "category": case.category,
            "question": case.question,
            "expected_route": case.route,
            "answerable": case.answerable,
            "required_facts": facts,
            "required_entities": entities,
            "filters": case.filters,
            "label_status": "heldout",
        }
        if phase is not None:
            row["resolved_phase"] = phase
        if phrases:
            row["required_phrases"] = list(dict.fromkeys(phrases))
        if case.allowed is not None and case.answerable:
            assert phase is not None
            allowed = [str(value) for value in case.allowed(archive, phase) if str(value)]
            if allowed:
                row["allowed_numbers"] = list(dict.fromkeys(allowed))
        rows.append(row)
    actual_categories = dict(sorted(counts.items()))
    if len(rows) != EXPECTED_COUNT:
        raise RuntimeError(f"expected {EXPECTED_COUNT} cases, got {len(rows)}")
    if actual_categories != EXPECTED_CATEGORIES:
        raise RuntimeError(f"category counts changed: {actual_categories}")
    return rows


def build_follow_ups(archive: Archive) -> list[dict]:
    rows: list[dict] = []
    for number, session in enumerate(FOLLOW_UP_SESSIONS, start=1):
        game = archive.game(session.game_id)
        answer = (
            f"They {'won' if game.won else 'fell'} {game.knicks_points}-{game.opponent_points}."
        )
        facts, entities, phrases = session.facts(archive, "game")
        if not facts or not entities:
            raise RuntimeError(f"missing follow-up facts: {session.follow_up}")
        allowed = [str(value) for value in (session.allowed or (lambda a, p: []))(archive, "game")]
        allowed.extend([str(game.knicks_points), str(game.opponent_points)])
        row: dict[str, object] = {
            "id": f"heldout2-follow_ups-{number:03d}",
            "category": "follow_ups",
            "session": number,
            "question": session.follow_up,
            "context": [
                {"role": "user", "content": session.first_question},
                {"role": "assistant", "content": answer},
            ],
            "turns": [
                {
                    "turn": 1,
                    "question": session.first_question,
                    "required_facts": [f"final score {game.knicks_points}-{game.opponent_points}"],
                },
                {"turn": 2, "question": session.follow_up, "required_facts": facts},
            ],
            "expected_route": "retrieval_rag",
            "answerable": True,
            "required_facts": facts,
            "required_entities": entities,
            "filters": {"game_id": session.game_id, "turn": 2},
            "resolved_phase": "game",
            "label_status": "heldout",
        }
        if phrases:
            row["required_phrases"] = list(dict.fromkeys(phrases))
        if allowed:
            row["allowed_numbers"] = list(dict.fromkeys(allowed))
        rows.append(row)
    if len(rows) != 10:
        raise RuntimeError(f"expected 10 follow-up sessions, got {len(rows)}")
    return rows


def question_hash(rows: list[dict]) -> str:
    payload = "".join(f"{row['category']}\x1f{row['question']}\n" for row in rows)
    return hashlib.sha256(payload.encode()).hexdigest()


def combined_hash(main_hash: str, follow_hash: str) -> str:
    return hashlib.sha256(f"{main_hash}\x1f{follow_hash}".encode()).hexdigest()


def render_meta(
    archive: Archive,
    main_rows: list[dict],
    follow_rows: list[dict],
    creation_commit: str,
    set_commit: str,
) -> dict:
    counts: defaultdict[str, int] = defaultdict(int)
    for row in main_rows:
        counts[str(row["category"])] += 1
    main_hash = question_hash(main_rows)
    follow_hash = follow_up_order_digest(FOLLOW_UP_SESSIONS)
    return {
        "split": "heldout_v2",
        "version": 1,
        "count": len(main_rows),
        "categories": dict(sorted(counts.items())),
        "follow_up_sessions": len(follow_rows),
        "follow_up_turns": len(follow_rows) * 2,
        "generated_by": "app/evaluation/heldout_v2/build.py",
        "computed_from": archive.release,
        "label_source": "database",
        "answer_contract": "docs/api.md (ANALYSIS_ANSWER_MODE=llm_primary)",
        "tuning_policy": POLICY,
        "phase_policy": PHASE_POLICY,
        "question_order_sha256": main_hash,
        "follow_up_order_sha256": follow_hash,
        "combined_order_sha256": combined_hash(main_hash, follow_hash),
        "creation_commit": creation_commit,
        "set_commit": set_commit,
        "files": {
            "questions": "questions.jsonl",
            "follow_ups": "follow_ups.jsonl",
            "overlap_report": "overlap_report.json",
        },
        "notes": [
            "No model labels. Every fact is computed from the active local release.",
            "No live provider call was made while building or checking this set.",
            "Questions, players, opponents and game ids are disjoint from questions.jsonl "
            "and heldout_questions.jsonl; the overlap report is mechanical and contains no "
            "question text.",
            "creation_commit is the first commit that added the set; set_commit is the commit "
            "whose questions.jsonl and follow_ups.jsonl bytes match this file.",
            "Run once at release. Do not tune on it.",
        ],
    }


def _check(
    archive: Archive,
    main_rows: list[dict],
    follow_rows: list[dict],
    creation_commit: str,
    set_commit: str,
) -> None:
    expected_main = "".join(_json_line(row) for row in main_rows)
    expected_follow = "".join(_json_line(row) for row in follow_rows)
    if QUESTIONS.read_text(encoding="utf-8") != expected_main:
        raise SystemExit(f"{QUESTIONS.name} does not match the generator")
    if FOLLOW_UPS.read_text(encoding="utf-8") != expected_follow:
        raise SystemExit(f"{FOLLOW_UPS.name} does not match the generator")
    meta = json.loads(META.read_text(encoding="utf-8"))
    expected = render_meta(archive, main_rows, follow_rows, creation_commit, set_commit)
    for key in (
        "count",
        "categories",
        "follow_up_sessions",
        "follow_up_turns",
        "question_order_sha256",
        "follow_up_order_sha256",
        "combined_order_sha256",
        "computed_from",
    ):
        if meta.get(key) != expected[key]:
            raise SystemExit(f"meta.{key} does not match the generator")
    print("held-out v2 files match the generator")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creation-commit", default=None)
    parser.add_argument("--set-commit", default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare with the committed files",
    )
    args = parser.parse_args()

    commit = args.creation_commit
    if commit is None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=HERE).strip()
    set_commit = args.set_commit or commit

    async def run() -> Archive:
        connection = await asyncpg.connect(dsn())
        try:
            return await load_archive(connection)
        finally:
            await connection.close()

    archive = asyncio.run(run())
    main_rows = build_main(archive)
    follow_rows = build_follow_ups(archive)
    main_hash = question_hash(main_rows)
    follow_hash = follow_up_order_digest(FOLLOW_UP_SESSIONS)
    if EXPECTED_QUESTION_ORDER_SHA256 and main_hash != EXPECTED_QUESTION_ORDER_SHA256:
        raise SystemExit(
            f"question order changed: {main_hash}; update the expected digest deliberately"
        )
    if EXPECTED_FOLLOW_UP_ORDER_SHA256 and follow_hash != EXPECTED_FOLLOW_UP_ORDER_SHA256:
        raise SystemExit(
            f"follow-up order changed: {follow_hash}; update the expected digest deliberately"
        )
    if args.check:
        _check(archive, main_rows, follow_rows, commit, set_commit)
        return
    QUESTIONS.write_text("".join(_json_line(row) for row in main_rows), encoding="utf-8")
    FOLLOW_UPS.write_text("".join(_json_line(row) for row in follow_rows), encoding="utf-8")
    META.write_text(
        json.dumps(
            render_meta(archive, main_rows, follow_rows, commit, set_commit),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"release {archive.release}")
    print(f"main questions {len(main_rows)} {dict(EXPECTED_CATEGORIES)}")
    print(f"follow-up sessions {len(follow_rows)} ({len(follow_rows) * 2} turns)")
    print(f"question_order_sha256 {main_hash}")
    print(f"follow_up_order_sha256 {follow_hash}")
    print(f"combined_order_sha256 {combined_hash(main_hash, follow_hash)}")
    print(f"creation_commit {commit}")
    print(f"set_commit {set_commit}")


if __name__ == "__main__":
    main()
