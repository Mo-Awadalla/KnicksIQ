"""Typed registry of the tools the analyst model may call.

Adding a tool means one module implementing ``async def run(tools, call, scope, games)`` and one
``ToolSpec`` entry below. The tool name Literal, the provider prompt and dispatch all read this
tuple, so a tool cannot exist in one place but not another.

Handlers are referenced by import path rather than imported here: ``evidence_contracts`` imports
this module for the name Literal, while the handler modules import ``evidence_contracts``. Direct
imports would create a cycle at process start. Resolution is lazy and importlib caches modules.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall, ToolResult
    from app.services.query_resolution import ResolvedQuery

    ToolHandler = Callable[
        ["AnalystTools", "ToolCall", "ResolvedQuery | None", list["Game"]],
        Awaitable["ToolResult"],
    ]

Aggregation = Literal["average", "total"]
RecoveryRole = Literal["discovery", "player", "team"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    handler: str
    # Scope-driven pre-checks and resolution. get_evidence only expands prior references.
    needs_scope: bool = True
    needs_games: bool = True
    supports_periods: bool = False
    needs_player: bool = False
    reads_metric: bool = False
    # Which spec the failed-validation recovery path calls, and with which aggregation.
    recovery_role: RecoveryRole | None = None
    recovery_aggregation: Aggregation = "average"
    # The single tool named in the prompt's opening sentence rather than in the semicolon list.
    prompt_lead: bool = False

    def resolve_handler(self) -> ToolHandler:
        module_name, _, attribute = self.handler.partition(":")
        return getattr(importlib.import_module(module_name), attribute)


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_player_stats",
        description="calculates player metrics",
        handler="app.services.analyst_tool_player:run",
        needs_player=True,
        reads_metric=True,
        recovery_role="player",
    ),
    ToolSpec(
        name="get_team_stats",
        description=(
            "gives team wins and losses plus points and margin, as totals (aggregation total) "
            "or per-game averages (aggregation average), so choose the aggregation the user "
            "asked for"
        ),
        handler="app.services.analyst_tool_team:run",
        recovery_role="team",
        recovery_aggregation="total",
    ),
    ToolSpec(
        name="compare_windows",
        description="compares populations",
        handler="app.services.analyst_tool_compare:run",
        needs_player=True,
        reads_metric=True,
    ),
    ToolSpec(
        name="discover_facts",
        description="FIRST with the user's question unchanged",
        handler="app.services.analyst_tool_discovery:run",
        recovery_role="discovery",
        prompt_lead=True,
    ),
    ToolSpec(
        name="search_archive",
        description="finds narrative examples",
        handler="app.services.analyst_tool_archive:run",
        supports_periods=True,
    ),
    ToolSpec(
        name="get_evidence",
        description="expands returned references",
        handler="app.services.analyst_tool_evidence:run",
        needs_scope=False,
        needs_games=False,
    ),
    ToolSpec(
        name="get_game_flow",
        description="play-by-play flow",
        handler="app.services.analyst_tool_runs:run",
        supports_periods=True,
    ),
)

TOOLS_BY_NAME = {spec.name: spec for spec in TOOLS}
TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOLS)

if len(TOOLS_BY_NAME) != len(TOOLS):
    raise RuntimeError("Duplicate analyst tool name")
if sum(spec.prompt_lead for spec in TOOLS) != 1:
    raise RuntimeError("Exactly one analyst tool must lead the prompt")


def recovery_tool(role: RecoveryRole) -> ToolSpec:
    return next(spec for spec in TOOLS if spec.recovery_role == role)


def tools_hint() -> str:
    """The provider prompt segment that names every tool, in registry order."""
    lead = next(spec for spec in TOOLS if spec.prompt_lead)
    flow = TOOLS_BY_NAME.get("get_game_flow")
    flow_hint = f"Game-flow questions: call {flow.name} alone first. " if flow is not None else ""
    listed = "; ".join(f"{spec.name} {spec.description}" for spec in TOOLS if not spec.prompt_lead)
    return (
        flow_hint
        + f"For interesting stats or another player, call {lead.name} {lead.description}. "
        "Empty claims means call a tool before stating stats. "
        f"{listed}. Answer once evidence is sufficient. "
    )
