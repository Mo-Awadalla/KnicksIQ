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
    # Archive tables this tool can actually read, aggregated into the model-facing capabilities.
    data_types: tuple[str, ...] = ()

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
        data_types=("player_box_scores",),
    ),
    ToolSpec(
        name="get_team_stats",
        description=(
            "wins, losses, points and margin for one population (season, window or opponent "
            "scope), total or per game; it does not split a population"
        ),
        handler="app.services.analyst_tool_team:run",
        recovery_role="team",
        recovery_aggregation="total",
        data_types=("team_game_scores",),
    ),
    ToolSpec(
        name="compare_windows",
        description="compares populations",
        handler="app.services.analyst_tool_compare:run",
        needs_player=True,
        reads_metric=True,
        data_types=("player_box_scores",),
    ),
    ToolSpec(
        name="discover_facts",
        description="FIRST with the user's question unchanged",
        handler="app.services.analyst_tool_discovery:run",
        recovery_role="discovery",
        prompt_lead=True,
        data_types=("player_box_scores",),
    ),
    ToolSpec(
        name="search_archive",
        description="finds narrative examples",
        handler="app.services.analyst_tool_archive:run",
        supports_periods=True,
        data_types=("game_scores", "player_box_scores", "archive_reports", "play_by_play_events"),
    ),
    ToolSpec(
        name="get_evidence",
        description="expands returned references",
        handler="app.services.analyst_tool_evidence:run",
        needs_scope=False,
        needs_games=False,
    ),
    ToolSpec(
        name="find_player_games",
        description=(
            "counts a player's games meeting an explicit per-game stat threshold and lists "
            "the matching archived games"
        ),
        handler="app.services.analyst_tool_player:find_player_games",
        needs_player=True,
        reads_metric=True,
        data_types=("player_box_scores",),
    ),
    ToolSpec(
        name="get_game_narrative",
        description=(
            "canonical game narratives, tied game stories, comebacks and lost leads selected "
            "from the archive"
        ),
        handler="app.services.analyst_tool_narrative:run",
        needs_games=False,
        supports_periods=True,
    ),
    ToolSpec(
        name="get_game_flow",
        description=(
            "play-by-play runs, deficits, comebacks and lost leads; ranks the observed "
            "extreme across the selected games"
        ),
        handler="app.services.analyst_tool_runs:run",
        supports_periods=True,
    ),
    ToolSpec(
        name="get_team_splits",
        description=(
            "home/road, wins/losses, opponent, month, first N, All-Star break, phase, close, "
            "overtime and back-to-back splits; each bucket reports its own record, points and "
            "margin"
        ),
        handler="app.services.analyst_tool_splits:run",
        needs_games=False,
    ),
    ToolSpec(
        name="get_period_scoring",
        description=(
            "quarter, half, halftime and overtime scoring, per game and aggregated; use "
            "instead of get_team_stats"
        ),
        handler="app.services.analyst_tool_periods:run",
        supports_periods=True,
    ),
)

TOOLS_BY_NAME = {spec.name: spec for spec in TOOLS}

BASE_DATA_TYPES: tuple[str, ...] = ("game_scores", "player_box_scores", "archive_evidence")


def capability_data_types() -> tuple[str, ...]:
    """Archive data the model may rely on, derived from the registered tools only."""
    types = set(BASE_DATA_TYPES)
    for spec in TOOLS:
        types.update(spec.data_types)
        if spec.supports_periods:
            types.add("period_scores")
    return tuple(sorted(types))


def period_tool_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in TOOLS if spec.supports_periods)


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
    splits = TOOLS_BY_NAME.get("get_team_splits")
    split_hint = (
        f"Split or comparison questions: call {splits.name} alone first. "
        if splits is not None
        else ""
    )
    periods = TOOLS_BY_NAME.get("get_period_scoring")
    period_hint = (
        f"Quarter, half and halftime questions: call {periods.name} alone first. "
        if periods is not None
        else ""
    )

    def short(description: str, limit: int = 36) -> str:
        # The full description is repeated in the capability manifest. The routing prompt
        # keeps one terse clause per tool so the bounded input fits (see prompt budget tests).
        head = description.split(";")[0].split(" (")[0].strip()
        if len(head) <= limit:
            return head
        return head[:limit].rsplit(" ", 1)[0]

    listed = "; ".join(
        f"{spec.name} {short(spec.description)}" for spec in TOOLS if not spec.prompt_lead
    )
    return (
        flow_hint
        + split_hint
        + period_hint
        + f"For interesting stats or another player, call {lead.name} {lead.description}. "
        "Empty claims means call a tool before stating stats. "
        f"{listed}. Answer once evidence is sufficient. "
    )
