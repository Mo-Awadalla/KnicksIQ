"""Minimal deterministic reproductions of the follow-up scope defects found by the benchmark.

No provider and no model: each case prepares the prior turn, commits its scope and intent the
way the session store does, then prepares the follow-up and prints what the backend resolved.
Fallback cases also run the backend prefetch and the deterministic fallback claim selector.
Each case states the condition that makes it a reproduction, so a fixed defect prints
NOT REPRODUCED instead of a stale transcript. The script exits 0 while every case reproduces.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
      uv run --package knicksiq-api python tools/release/followup_scope_repros.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_fallback import decline_text, fallback_claims, re_search_discovery
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_tool_registry import recovery_tool
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from sqlalchemy import select


class FakeLoop:
    def __init__(self, tools: AnalystTools, results: list) -> None:
        self.tools = tools
        self.results = results
        self.recovery_ran = True
        self.remaining = lambda: 0.0


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


async def prepare(db, release, question: str, state: dict) -> AnalystTools:
    tools = AnalystTools(db, release, question, release.season, clone(state))
    await tools.prepare()
    return tools


def next_state(tools: AnalystTools, claims: list | None = None) -> dict:
    return {
        "scope": tools.scope.model_dump(mode="json") if tools.scope else {},
        "intent": tools.topic,
        "claims": [claim.model_dump(mode="json") for claim in (claims or [])],
        "evidence": [],
        "release": tools.release.version,
    }


async def fallback_result(db, release, question: str, state: dict) -> dict:
    tools = await prepare(db, release, question, state)
    calls = prefetch_calls(tools)
    results = [await tools.execute(call) for call in calls]
    if not any(result.claims for result in results):
        spec = recovery_tool(
            "discovery"
            if re_search_discovery(tools.question)
            else "player"
            if tools.scope.player_ids
            else "team"
        )
        results.append(
            await tools.execute(
                ToolCall(
                    name=spec.name,
                    question=tools.question,
                    aggregation=spec.recovery_aggregation,
                )
            )
        )
    loop = FakeLoop(tools, results)
    claims = fallback_claims(loop)
    return {
        "scope": tools.scope.model_dump(mode="json"),
        "topic": tools.topic,
        "games": len(tools.selected_games(tools.scope)),
        "prefetch": [
            (call.name, call.aggregation, result.status)
            for call, result in zip(calls, results, strict=False)
        ],
        "claims": [claim.metric_id for claim in claims],
        "text": " ".join(claim.statement for claim in claims) or decline_text(loop),
    }


def show(name: str, expected: str, actual: str, reproduced: bool) -> bool:
    print(f"{'REPRODUCED' if reproduced else 'NOT REPRODUCED'} {name}")
    print(f"  want {expected}")
    print(f"  got  {actual}")
    return reproduced


async def main() -> None:
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        outcomes: list[bool] = []

        # 1. A player switch drops the prior last-5 window and the metric.
        prior = await prepare(
            db, release, "How many points did Brunson average over the last 5 games?", {}
        )
        tools = await prepare(db, release, "What about Towns?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        games = len(tools.selected_games(tools.scope))
        outcomes.append(
            show(
                "player switch loses window and metric",
                "relative_game_count=5, metric=points, 5 games",
                f"relative_game_count={scope['relative_game_count']}, "
                f"metric={scope['metric']}, games={games}",
                scope["relative_game_count"] != 5 or scope["metric"] != "points" or games != 5,
            )
        )

        # 2. A pronoun metric change drops the month window.
        prior = await prepare(db, release, "How many assists did Brunson average in December?", {})
        tools = await prepare(db, release, "And his points?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        games = len(tools.selected_games(tools.scope))
        outcomes.append(
            show(
                "pronoun metric change loses month",
                "date_start=2025-12-02, date_end=2025-12-31, 14 games",
                f"date_start={scope['date_start']}, date_end={scope['date_end']}, games={games}",
                str(scope["date_start"]) != "2025-12-02" or games != 14,
            )
        )

        # 3. An elliptical phase change drops the player metric.
        prior = await prepare(
            db, release, "How many points did Brunson average in the regular season?", {}
        )
        tools = await prepare(db, release, "And in the playoffs?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "elliptical playoff follow-up loses metric",
                "player_ids=[134], metric=points, season_type=playoffs",
                f"player_ids={scope['player_ids']}, metric={scope['metric']}, "
                f"season_type={scope['season_type']}",
                scope["metric"] != "points",
            )
        )

        # 4. The elliptical check runs on the merged scope, so the prior intent is not kept.
        prior = await prepare(
            db, release, "How many points did Brunson average over the last 5 games?", {}
        )
        tools = await prepare(db, release, "And overall?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "And overall? after a player window loses topic and metric",
                "topic=How many points did Brunson average over the last 5 games?, metric=points",
                f"topic={tools.topic!r}, metric={scope['metric']}",
                tools.topic == "And overall?" or scope["metric"] != "points",
            )
        )

        # 5. A game reference is not carried into the next turn.
        prior = await prepare(
            db, release, "How many points did the Knicks score in their last game?", {}
        )
        tools = await prepare(
            db, release, "How many points did Brunson score in that game?", next_state(prior)
        )
        scope = tools.scope.model_dump(mode="json")
        games = len(tools.selected_games(tools.scope))
        outcomes.append(
            show(
                "that game loses game_ids and phase",
                "game_ids=[101], season_type=None, 1 game",
                f"game_ids={scope['game_ids']}, season_type={scope['season_type']}, games={games}",
                scope["game_ids"] != [101] or scope["season_type"] is not None or games != 1,
            )
        )

        # 6. A matchup turn has no phase, and the follow-up silently becomes regular season.
        prior = await prepare(db, release, "What was their record against Cleveland?", {})
        tools = await prepare(db, release, "And at home?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        games = len(tools.selected_games(tools.scope))
        outcomes.append(
            show(
                "matchup follow-up drops any-phase scope",
                "season_type=None, 4 games",
                f"season_type={scope['season_type']}, games={games}",
                scope["season_type"] == "regular" or games != 4,
            )
        )

        # 7. what about <team> is treated as an unknown player subject.
        prior = await prepare(db, release, "What was their record against Boston?", {})
        tools = await prepare(db, release, "What about Cleveland?", next_state(prior))
        scope = tools.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "what about an opponent asks for a player",
                "requires_clarification=False, opponent_id=CLE",
                f"requires_clarification={scope['requires_clarification']}, "
                f"opponent_id={scope['opponent_id']}, "
                f"choices={scope['clarification_options'][:3]}",
                bool(scope["requires_clarification"]),
            )
        )

        # 8. per game + opponent is read as one ambiguous game.
        tools = await prepare(
            db, release, "How many points per game did the Knicks score against Boston?", {}
        )
        scope = tools.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "per game against an opponent asks which game",
                "requires_clarification=False, opponent_id=BOS, 4 games",
                f"requires_clarification={scope['requires_clarification']}, "
                f"choices={scope['clarification_options'][:2]}, "
                f"games={len(tools.selected_games(tools.scope))}",
                bool(scope["requires_clarification"]),
            )
        )

        # 9. The deterministic fallback reads how many ... game(s) as a record request.
        result = await fallback_result(
            db, release, "How many points per game did the Knicks score at home?", {}
        )
        outcomes.append(
            show(
                "fallback answers a points-per-game question with wins and losses",
                "claims include points_per_game",
                f"claims={result['claims']}, text={result['text'][:100]!r}",
                "points_per_game" not in result["claims"],
            )
        )

        # 10. A declined turn overwrites intent; the elliptical follow-up has no topic.
        regular = await prepare(db, release, "What was the Knicks' record?", {})
        state = next_state(regular)
        state["intent"] = "Should I put money on the Knicks winning the championship?"
        result = await fallback_result(db, release, "And overall?", state)
        outcomes.append(
            show(
                "overall after a decline loses the record topic",
                "claims include wins and losses",
                f"claims={result['claims']}, text={result['text'][:100]!r}",
                not result["claims"],
            )
        )

        # 11. A total-to-average follow-up keeps the topic's aggregation and drops the month.
        prior = await prepare(
            db, release, "How many total points did the Knicks score in December?", {}
        )
        result = await fallback_result(db, release, "And per game?", next_state(prior))
        scope = result["scope"]
        aggregation = result["prefetch"][0][1] if result["prefetch"] else None
        outcomes.append(
            show(
                "per game after a total keeps total aggregation and loses the month",
                "date_start=2025-12-02, 14 games, average request",
                f"date_start={scope['date_start']}, games={result['games']}, "
                f"prefetch={result['prefetch']}, text={result['text'][:80]!r}",
                str(scope["date_start"]) != "2025-12-02" or aggregation != "average",
            )
        )

        # 12. An explanation follow-up loses the game under discussion and its opponent.
        prior = await prepare(
            db, release, "How many points did the Knicks score in the game on 2026-06-08?", {}
        )
        result = await fallback_result(
            db, release, "Why did they lose that game?", next_state(prior)
        )
        scope = result["scope"]
        games = result["games"]
        outcomes.append(
            show(
                "why follow-up loses the game and answers with a season record",
                "game_ids=[99], 1 game, answer mentions Spurs",
                f"game_ids={scope['game_ids']}, games={games}, text={result['text'][:90]!r}",
                scope["game_ids"] != [99] or "Spurs" not in result["text"],
            )
        )
    print("REPRODUCED", sum(outcomes), "of", len(outcomes))
    raise SystemExit(0 if all(outcomes) else 1)


if __name__ == "__main__":
    asyncio.run(main())
