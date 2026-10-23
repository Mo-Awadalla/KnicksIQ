"""Question-shape predicates shared by the analytical tool surface."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.services.query_parsing import is_record_request
from app.services.team_scope import comparison_groups

if TYPE_CHECKING:
    from app.models.dataset_release import DatasetRelease
    from app.models.game import Game
    from app.services.canonical_narrative import NarrativeSelection
    from app.services.query_resolution import ResolvedQuery


class ToolFactsMixin:
    # Declarations only: AnalystTools supplies the runtime attributes and methods.
    if TYPE_CHECKING:
        release: DatasetRelease
        question: str
        narrative: NarrativeSelection | None
        scope: ResolvedQuery | None

        def selected_games(self, scope: ResolvedQuery) -> list[Game]: ...

    def scope_label(self, scope: ResolvedQuery, games: list[Game]) -> str:
        label = f"the {self.release.season} {scope.season_type or 'all-phase'} Knicks archive"
        if scope.opponent_id:
            label += f" against {scope.opponent_id}"
        if scope.home_away:
            label += f" ({scope.home_away} games)"
        if scope.game_result:
            label += f" ({'wins' if scope.game_result == 'W' else 'losses'} only)"
        if scope.relative_game_count:
            label += f", {scope.relative_game_order} {scope.relative_game_count} observed games"
        if games:
            label += f", {games[0].game_date} through {games[-1].game_date}"
        return label

    def supports_period_average(self, scope: ResolvedQuery) -> bool:
        return bool(
            scope.periods
            and not scope.player_ids
            and scope.metric == "points"
            and not re.search(r"\b(?:total|sum)\b", self.question, re.I)
            and re.search(r"\b(?:compare|average|per game)\b", self.question, re.I)
        )

    def statistical_extreme_requested(self) -> bool:
        question = re.sub(r"[-–—]", " ", self.question.lower())
        return bool(
            self.narrative
            and self.scope is not None
            and not self.scope.player_ids
            and not re.search(r"\b(?:story|describe|tell|walk|what happened)\b", question)
            and re.search(
                r"\b(?:highest|lowest) scoring game\b"
                r"|\b(?:biggest|best|largest) win\b.*\bmargin\b"
                r"|\b(?:worst|biggest|largest) loss\b.*\bmargin\b"
                r"|\bbest defensive game\b",
                question,
            )
        )

    def player_profile_requested(self) -> bool:
        scope = self.scope
        return bool(
            scope
            and scope.player_ids
            and scope.game_ids
            and not (scope.metric or scope.requested_metrics)
            and (
                len(scope.game_ids) == 1
                or re.search(r"\b(?:biggest|best|largest) win\b", self.question, re.I)
            )
        )

    def season_window_comparison_requested(self) -> bool:
        return bool(
            self.scope
            and self.scope.player_ids
            and self.scope.relative_game_count
            and re.search(r"\b(?:compare|versus|vs|with)\b", self.question, re.I)
            and re.search(r"\bseason average\b", self.question, re.I)
        )

    def season_comparison_baseline_scope(self, scope: ResolvedQuery) -> ResolvedQuery:
        return scope.model_copy(
            update={
                "game_ids": [],
                "date_start": None,
                "date_end": None,
                "calendar_boundary": None,
                "relative_game_count": None,
                "relative_game_order": "last",
            }
        )

    def team_comparison_metrics(self, scope: ResolvedQuery) -> tuple[str, ...]:
        question = self.question.lower()
        if "bench" in question:
            return ("bench_points_per_team_game",)
        if "turnover" in question:
            return ("turnovers_per_game",)
        if "shoot" in question:
            return ("field_goal_percentage",)
        if not is_record_request(self.question):
            if re.search(r"\b(?:allow(?:ed)?|opponents?)\b", question):
                return ("points_allowed_per_game",)
            if "offense" in question or scope.metric == "points":
                return ("points_per_game",)
        record = ("games", "wins", "losses")
        return (
            record + ("average_margin",) if re.search(r"\b(?:better|fare)\b", question) else record
        )

    def requested_team_groups(self) -> list[tuple[str, list[Game]]]:
        if self.scope is None or self.scope.player_ids:
            return []
        return comparison_groups(self.question, self.selected_games(self.scope))
