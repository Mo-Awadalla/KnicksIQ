"""Shared prepare/commit/fallback helpers for the follow-up reproduction scripts.

The case list lives in followup_scope_repros.py; this module only holds the mechanics so
that file stays under the 20,000-byte authored-file limit.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.analyst_fallback import decline_text, fallback_claims, re_search_discovery
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_tool_registry import recovery_tool
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall


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


def next_state(
    tools: AnalystTools, claims: list | None = None, evidence: list | None = None
) -> dict:
    # The session store commits the whole state dict prepare produced, not only the
    # fields it names; keep last_topic/last_scope so a later decline can fall back.
    state = clone(tools.state)
    state.update(
        {
            "scope": tools.scope.model_dump(mode="json") if tools.scope else {},
            "intent": tools.topic,
            "claims": [claim.model_dump(mode="json") for claim in (claims or [])],
            "evidence": [item.model_dump(mode="json") for item in (evidence or [])],
            "release": tools.release.version,
        }
    )
    return state


async def claim_state(tools: AnalystTools) -> dict:
    """State after a turn that ran the backend plan and committed its claims."""
    calls = prefetch_calls(tools)
    results = [await tools.execute(call) for call in calls]
    claims = [claim for result in results for claim in result.claims]
    # Delivery commits every receipt a used claim references, including a calculation
    # receipt's source evidence; the follow-up revalidates the same set.
    return next_state(tools, claims, list(tools.evidence.values()))


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
