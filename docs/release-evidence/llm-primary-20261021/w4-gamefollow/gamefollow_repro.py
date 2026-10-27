"""Deterministic reproduction: a one-game turn followed by an elliptical stat question.

No provider and no model. Each session prepares turn 1 (a game named by opponent and date),
commits the scope the session store would commit, prepares turn 2, and compares the resolved
scope with the scope the session file declares. A window is lost when turn 2 no longer
selects the games turn 1 selected. Two extra probes cover the game-id-only window and the
degraded turn between a game question and its follow-up, and every turn-2 tool claim is
checked against the turn's own game window (dispatch may not widen it).

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
      uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-gamefollow/gamefollow_repro.py

Exit 0 when every turn-2 scope matches its expectation (the defect is gone).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

from followup_oracle import (  # noqa: E402
    compare_scope,
    expectation_for,
    load_sessions,
    oracle,
    selected_games,
)
from followup_repro_support import next_state, prepare  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.models.dataset_release import DatasetRelease  # noqa: E402
from app.services.analyst_loop import AnalystLoop  # noqa: E402
from app.services.analyst_prefetch import prefetch_calls  # noqa: E402
from sqlalchemy import select  # noqa: E402

SESSIONS = Path(__file__).with_name("gamefollow_sessions.jsonl")


def brief(scope: dict, actual: int | None = None) -> str:
    return (
        f"games={'?' if actual is None else actual} "
        f"ids={len(scope.get('game_ids') or [])} "
        f"date={scope.get('date_start')}..{scope.get('date_end')} "
        f"opp={scope.get('opponent_id')} phase={scope.get('season_type')} "
        f"metric={scope.get('metric')}"
    )


def claims_outside(tools, results) -> list[int]:
    """Game ids a tool claimed outside the turn's own window."""
    allowed = {game.id for game in tools.selected_games(tools.scope)} if tools.scope else set()
    outside: set[int] = set()
    for result in results:
        for claim in result.claims:
            outside.update(set(claim.game_ids or []) - allowed)
    return sorted(outside)


async def run_tools(tools) -> list[int]:
    """Execute the backend plan for a prepared turn and report claims outside its window."""
    results = [await tools.execute(call) for call in prefetch_calls(tools)]
    return claims_outside(tools, results)


async def main() -> None:
    sessions = load_sessions(SESSIONS)
    values, ids, teams = await oracle()
    lost = 0
    dispatch_widened = 0
    print(f"{'session':40} {'turn 2 question':44} {'game':>6} {'want':>5}  scope")
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        for session in sessions:
            first, second = session["turns"]
            prior = await prepare(db, release, first["question"], {})
            assert prior.scope is not None
            prior_scope = prior.scope.model_dump(mode="json")
            turn1_games = len(prior.selected_games(prior.scope))
            tools = await prepare(db, release, second["question"], next_state(prior))
            assert tools.scope is not None
            actual_scope = tools.scope.model_dump(mode="json")
            actual_games = len(tools.selected_games(tools.scope))
            expectation = expectation_for(second, values.archive, ids, teams)
            issues = compare_scope(actual_scope, expectation.scope, values.archive)
            outside = await run_tools(tools)
            lost += bool(issues)
            dispatch_widened += bool(outside)
            print(
                f"{session['id']:40} {second['question'][:44]:44} {actual_games:6} "
                f"{expectation.games:5}  {'LOST' if issues else 'ok'}"
            )
            print(f"    topic frame: turn1={brief(prior_scope, turn1_games)}")
            print(
                f"    turn2: followup={tools.followup} topic={tools.topic[:60]!r} "
                f"{brief(actual_scope, actual_games)}"
            )
            for issue in issues:
                print(f"    - {issue}")
            if outside:
                print(f"    - claims outside the turn window: {outside}")

        # A game id without a date window must still bound the follow-up.
        prior = await prepare(
            db, release, "How did the Knicks do against the Hawks in their most recent game?", {}
        )
        assert prior.scope is not None
        turn1_ids = list(prior.scope.game_ids)
        tools = await prepare(db, release, "What was the margin?", next_state(prior))
        assert tools.scope is not None
        turn2_ids = list(tools.scope.game_ids)
        game_id_ok = len(prior.selected_games(prior.scope)) == 1 and turn2_ids == turn1_ids
        lost += not game_id_ok
        print(
            f"{'probe_game_id_window':40} {'What was the margin?':44} "
            f"{len(tools.selected_games(tools.scope)):6} {1:5}  "
            f"{'ok' if game_id_ok else 'LOST'}"
        )
        print(f"    turn1: {brief(prior.scope.model_dump(mode='json'), 1)} ids={turn1_ids}")
        print(f"    turn2: ids={turn2_ids}")

        # A degraded (claim-less, non-refusal) game turn must leave its scope for the follow-up.
        record = await prepare(db, release, "What was the Knicks' record?", {})
        game = await prepare(
            db,
            release,
            "How many points did the Knicks score against the Hawks on January 2?",
            next_state(record),
        )
        degraded = AnalystLoop(game, []).render_fallback(
            "Proposed wording did not pass evidence review."
        )
        follow = await prepare(db, release, "What was the margin?", degraded["state"])
        assert follow.scope is not None
        degraded_ok = len(follow.selected_games(follow.scope)) == 1
        lost += not degraded_ok
        print(
            f"{'probe_degraded_turn':40} {'What was the margin?':44} "
            f"{len(follow.selected_games(follow.scope)):6} {1:5}  "
            f"{'ok' if degraded_ok else 'LOST'}"
        )
        print(
            f"    degraded declined={degraded['state'].get('declined')} "
            f"last={brief(degraded['state'].get('last_scope') or {})}"
        )
    print(f"WINDOW LOST {lost} of {len(sessions) + 2} checks")
    print(f"DISPATCH WIDENED {dispatch_widened} of {len(sessions)} sessions")
    raise SystemExit(0 if lost == 0 and dispatch_widened == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
