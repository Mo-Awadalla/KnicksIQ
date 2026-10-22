"""Minimal deterministic reproductions of the follow-up scope defects found by the benchmark.

No provider and no model: each case prepares the prior turn, commits its scope and intent the
way the session store does, then prepares the follow-up and prints what the backend resolved.
Fallback cases also run the backend prefetch and the deterministic fallback claim selector.
Each case states the condition that makes it a reproduction, so a fixed defect prints
NOT REPRODUCED instead of a stale transcript. The script exits 0 while every case reproduces.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/6 \
      uv run --package knicksiq-api python tools/release/followup_scope_repros.py

The lease case uses ANALYST_SESSION_LEASE_SECONDS (default 35) so the wait stays short.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_sessions import SessionTurn
from app.services.evidence_contracts import ClaimUse, ProposedAnswer, ToolCall
from app.services.runtime_store import _redis
from followup_repro_support import claim_state, fallback_result, next_state, prepare, show
from pydantic import ValidationError
from sqlalchemy import select


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
        state["declined"] = True
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

        # 13. A refusal that cites facts becomes the topic and scope of the next turn.
        prior = await prepare(
            db, release, "How many points did Brunson average in December?", {}
        )
        state = await claim_state(prior)
        refusal = await prepare(db, release, "Is Brunson's hamstring healthy?", state)
        cited = next(iter(refusal.claims.values()))
        loop = AnalystLoop(refusal, [])
        rendered = loop.render(
            ProposedAnswer(
                text=f"Brunson averaged {cited.value:.1f} points in December.",
                claims=[ClaimUse(claim_id=cited.claim_id, displayed_value=cited.value)],
            ),
            llm=True,
            refused=True,
        )
        followup = await prepare(db, release, "And his assists?", rendered["state"])
        scope = followup.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "refusal that cites facts overwrites the prior topic and month",
                "declined=True, date_start=2025-12-02, 14 games",
                f"declined={rendered['state'].get('declined')}, "
                f"date_start={scope['date_start']}, "
                f"games={len(followup.selected_games(followup.scope))}",
                rendered["state"].get("declined") is not True
                or str(scope["date_start"]) != "2025-12-02"
                or len(followup.selected_games(followup.scope)) != 14,
            )
        )

        # 14. "And per game?" after a committed total: the carried total suppresses the
        #     backend average lookup, so the model only ever sees the total claim.
        prior = await prepare(
            db, release, "How many total points did the Knicks score in December?", {}
        )
        tools = await prepare(db, release, "And per game?", await claim_state(prior))
        loop = AnalystLoop(tools, [])
        await loop.prefetch()
        metrics = [claim.metric_id for result in loop.results for claim in result.claims]
        scope = tools.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "per game after a total never runs the average lookup",
                "prefetched points_per_game, date_start=2025-12-02, 14 games",
                f"prefetch={metrics}, date_start={scope['date_start']}, "
                f"games={len(tools.selected_games(tools.scope))}",
                "points_per_game" not in metrics
                or str(scope["date_start"]) != "2025-12-02",
            )
        )

        # 15. A malformed repair call is reported to the user as a budget problem.
        tools = await prepare(db, release, "What was the Knicks' record?", {})
        loop = AnalystLoop(tools, [])

        async def malformed_repair() -> dict:
            raise ValidationError.from_exception_data(
                "Action", [{"type": "missing", "loc": ("action",), "input": {}}]
            )

        async def reserved(_calls: int) -> bool:
            return True

        loop.investigate = malformed_repair  # type: ignore[method-assign]
        loop.reserve = reserved  # type: ignore[method-assign]
        rendered = await loop.run()
        warning = (rendered.get("warnings") or [""])[0]
        outcomes.append(
            show(
                "a failed repair call claims the model or budget was unavailable",
                "a warning that names neither model nor budget",
                f"warning={warning!r}",
                "budget" in warning.lower() or "model" in warning.lower(),
            )
        )

        # 16. A turn that outlives its lease loses an answer it already produced.
        turn = await SessionTurn.begin(None, uuid.uuid4().hex, 0, {"question": "lease probe"})
        redis = await _redis()
        assert redis is not None
        await redis.delete(turn.key + ":lease")
        await redis.aclose()
        committed = (await turn.commit({"answer": "probe"}, {"answer": "probe"})).committed
        repeated = (await turn.commit({"answer": "probe"}, {"answer": "probe"})).committed
        outcomes.append(
            show(
                "an expired lease discards a completed turn and misreports a replay",
                "commit=True after lease expiry, repeat commit=True",
                f"commit={committed}, repeat={repeated}",
                not committed or not repeated,
            )
        )

        # 17. A refused answer that fails validation is delivered as a factual fallback;
        #     the fallback must not turn the refusal into the accepted topic either.
        prior = await prepare(
            db, release, "How many points did Brunson average in December?", {}
        )
        refusal = await prepare(
            db, release, "Is Brunson's hamstring healthy?", await claim_state(prior)
        )
        loop = AnalystLoop(refusal, [])
        loop.model_refused = True
        loop.results = [
            await refusal.execute(
                ToolCall(
                    name="get_player_stats",
                    question=refusal.question,
                    metric="points",
                    aggregation="average",
                )
            )
        ]
        rendered = loop.render_fallback("Proposed wording did not pass evidence review.")
        followup = await prepare(db, release, "And his assists?", rendered["state"])
        scope = followup.scope.model_dump(mode="json")
        outcomes.append(
            show(
                "refused turn's factual fallback overwrites the prior month",
                "declined=True, date_start=2025-12-02, 14 games",
                f"declined={rendered['state'].get('declined')}, "
                f"answer={rendered['answer'][:60]!r}, date_start={scope['date_start']}, "
                f"games={len(followup.selected_games(followup.scope))}",
                rendered["state"].get("declined") is not True
                or str(scope["date_start"]) != "2025-12-02"
                or len(followup.selected_games(followup.scope)) != 14,
            )
        )
    print("REPRODUCED", sum(outcomes), "of", len(outcomes))
    raise SystemExit(0 if all(outcomes) else 1)


if __name__ == "__main__":
    asyncio.run(main())
