"""One LLM orchestrator, bounded investigation and independent whole-answer review."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Literal

from app.core.config import get_settings
from app.services.analyst_budget import BudgetReservation
from app.services.analyst_delivery import (
    fallback,
    render,
    render_fallback,
)
from app.services.analyst_fallback import (
    fallback_claims as pr_fallback_claims,
)
from app.services.analyst_fallback import future_requested, re_search_discovery, re_search_live
from app.services.analyst_native import (
    native_statistic_tool,
    paired_record_claims,
    required_claim_groups,
)
from app.services.analyst_payload import build_payload
from app.services.analyst_prefetch import (
    covers_planned_shape,
    flow_requested,
    prefetch_calls,
    split_requested,
)
from app.services.analyst_provider import Schema, request_model
from app.services.analyst_tools import AnalystTools
from app.services.analyst_validation import validate_answer
from app.services.analyst_wire import (
    compact_schema,
    decode_model_response,
    encode_model_response,
    encoded,
    parse_model_response,
    payload_claim_uses,
    payload_claims,
    payload_evidence,
    payload_proposed_answer,
    scoped_response_schema,
    token_upper_bound,
)
from app.services.conversation_memory import bounded_history
from app.services.evidence_contracts import (
    Action,
    AnswerReview,
    Candidate,
    Evidence,
    ProposedAnswer,
    ToolCall,
    ToolResult,
    VerifiedClaim,
)
from app.services.player_threshold_games import (
    is_player_threshold_question,
    parse_stat_threshold,
    wants_game_listing,
)
from app.services.population_facts import is_player_leader_request
from app.services.query_parsing import is_game_score_request, is_record_request
from app.services.report_llm import get_llm_adapter
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# Main's payload wire helpers are the test-facing seam; keep them importable from here.
__all__ = [
    "AnalystLoop",
    "REFUSAL_ACTIONS",
    "compact_schema",
    "decode_model_response",
    "encode_model_response",
    "encoded",
    "fallback_warning",
    "parse_model_response",
    "payload_claim_uses",
    "payload_claims",
    "payload_evidence",
    "payload_proposed_answer",
    "scoped_response_schema",
    "token_upper_bound",
]

# The model declares why it is not answering from archive facts. These actions are
# refusals for API consumers even when related archive facts are included.
REFUSAL_ACTIONS = frozenset({"decline", "explain_coverage"})


def fallback_warning(failure: Exception) -> str:
    """The user-facing reason a validated answer was not delivered.

    The fallback text is still a verified archive answer; the warning only says what the
    turn could not do. It never attributes a malformed model response to the budget.
    """
    if isinstance(failure, ValidationError):
        return "Proposed wording did not pass evidence review."
    if isinstance(failure, TimeoutError):
        return "The answer could not be verified within this turn's time limit."
    return "The answer could not be verified on this turn."


class AnalystLoop:
    def __init__(
        self, tools: AnalystTools, context: list[dict[str, str]], *, started: float | None = None
    ):
        self.tools, self.context = tools, bounded_history(context)
        self.settings = get_settings()
        self.started = started or time.monotonic()
        # Random per-turn id for host routing and prompt caching; never the session token.
        self.session_id = uuid.uuid4().hex
        self.calls = 0
        self.rounds = 0
        self.tool_count = 0
        self.trace: list[dict[str, Any]] = []
        self.results: list[ToolResult] = []
        self.sent_claims: dict[str, VerifiedClaim] = {}
        self.sent_evidence: dict[str, Evidence] = {}
        self.sent_candidates: dict[str, Candidate] = {}
        self.reservations: list[tuple[BudgetReservation, int]] = []
        self.costs: list[float | None] = []
        self.last_answer: ProposedAnswer | None = None
        self.accepted_suggestions: list[str] = []
        self.recovery_ran = False
        self.request_id = ""
        self.preplanned: list[str] = []
        # The writer chose decline/explain_coverage this turn; a fallback delivery must
        # still not turn that refusal into the next turn's accepted topic.
        self.model_refused = False

    def payload(
        self,
        schema: type,
        *,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
        review: bool = False,
        instruction_bytes: int = 1700,
    ) -> dict[str, Any]:
        return build_payload(
            self,
            schema,
            answer=answer,
            repair=repair,
            review=review,
            instruction_bytes=instruction_bytes,
        )

    async def model(
        self,
        schema: type[Schema],
        *,
        review: bool = False,
        answer: ProposedAnswer | None = None,
        repair: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Schema:
        return await request_model(
            self,
            schema,
            review=review,
            answer=answer,
            repair=repair,
            timeout_seconds=timeout_seconds,
            adapter_factory=get_llm_adapter,
        )

    def remaining(self) -> float:
        return self.settings.analyst_deadline_seconds - (time.monotonic() - self.started)

    async def reserve(self, calls: int) -> bool:
        reservation = await BudgetReservation.reserve(
            self.settings.analyst_call_reservation_usd * calls
        )
        if reservation is None:
            return False
        self.reservations.append((reservation, calls))
        return True

    async def settle(self) -> None:
        offset = 0
        for reservation, slots in self.reservations:
            costs = self.costs[offset : offset + slots]
            amount = sum(
                c if c is not None else self.settings.analyst_call_reservation_usd for c in costs
            )
            await reservation.settle(amount)
            offset += slots

    async def run(self, *, allow_model: bool = True) -> dict[str, Any]:
        failure = None
        try:
            if self.tools.narrative:
                self.results.append(
                    await self.tools.execute(
                        ToolCall(name="get_game_narrative", question=self.tools.question)
                    )
                )
            # Leave recovery and response finalization inside the overall request budget.
            investigation_budget = max(0.001, self.remaining() - 2.5)
            try:
                async with asyncio.timeout(investigation_budget):
                    if allow_model and await self.reserve(3):
                        return await self.investigate()
            except Exception as exc:
                failure = exc
            result = await self.fallback(
                "Model or budget unavailable." if failure is None else fallback_warning(failure)
            )
            if failure is not None:
                logger.warning(
                    "analyst_execution_failed request_id=%s error_type=%s stage=%s "
                    "recovery_ran=%s recovered_facts=%s",
                    self.request_id,
                    type(failure).__name__,
                    self.trace[-1]["stage"] if self.trace else "admission",
                    self.recovery_ran,
                    bool(result["citations"]),
                    extra={
                        "request_id": self.request_id,
                        "error_type": type(failure).__name__,
                        "stage": self.trace[-1]["stage"] if self.trace else "admission",
                        "model_calls": self.calls,
                        "tool_rounds": self.rounds,
                        "recovery_ran": self.recovery_ran,
                        "recovered_facts": bool(result["citations"]),
                    },
                )
            return result
        finally:
            await self.settle()

    async def next_action(self) -> Action:
        """Return a well-formed action, retrying the model once when it is not.

        The model intermittently returns an off-schema or self-contradictory action and the
        same request usually succeeds. Two calls stay free for the answer and its review.
        """
        retried = False
        while True:
            try:
                action = await self.model(Action)
                if action.action == "call_tools":
                    well_formed = action.answer is None and bool(action.tools)
                else:
                    well_formed = action.answer is not None and not action.tools
                if well_formed:
                    if self.trace:
                        self.trace[-1].update(
                            {
                                "action": action.action,
                                "tools_requested": [tool.name for tool in action.tools],
                            }
                        )
                    return action
                error: Exception = ValueError("Malformed action")
            except ValidationError as exc:
                error = exc
            exhausted = self.calls > self.settings.analyst_max_model_calls - 3
            if retried or exhausted or self.remaining() < 8:
                raise error
            retried = True

    async def run_tool(self, call: ToolCall) -> ToolResult:
        tool_started = time.monotonic()
        result = await self.tools.execute(call)
        self.results.append(result)
        self.trace.append(
            {
                "stage": "tool",
                "tool": call.name,
                "latency_ms": round((time.monotonic() - tool_started) * 1000),
                "status": result.status,
                "claims": len(result.claims),
                "evidence": len(result.evidence),
                "candidates": len(result.candidates),
            }
        )
        return result

    async def prefetch(self) -> None:
        """Run backend-chosen tools before the first model call.

        The orchestrator spends one whole provider round trip choosing a tool that the
        question and the resolved scope already determine. Prefetch removes that call for
        clear questions; the model keeps both tool rounds when the prefetched evidence is
        not enough.
        """
        if not self.settings.analyst_prefetch_enabled:
            return
        # Prefetch exists to replace the planning call on a turn that starts without the
        # evidence the question needs. A prefetched lookup would only duplicate claims
        # already committed for this exact shape and population.
        if self.results:
            return
        calls = prefetch_calls(self.tools)
        if not calls:
            return
        # Committed claims are prior-turn facts. They replace the planning call only when
        # they already answer this turn's aggregation and population; "And per game?"
        # after a committed total must fetch the average instead of reusing the total.
        if covers_planned_shape(self.tools, calls):
            return
        self.preplanned = [call.name for call in calls]
        for call in calls:
            if time.monotonic() - self.started >= self.settings.analyst_investigation_seconds:
                break
            # Prefetched lookups count against the same six-tool limit as model-chosen ones.
            self.tool_count += 1
            await self.run_tool(call)

    async def repair(
        self, answer: ProposedAnswer, reason: str, *, timeout_seconds: float
    ) -> ProposedAnswer | None:
        """Retry an off-schema repair once when two calls stay free, then fail closed.

        The writer intermittently adds a host-format key or a malformed tail; the same
        request usually succeeds, and a schema failure must not discard a backed answer.
        """
        for attempt in range(2):
            try:
                return await self.model(
                    ProposedAnswer,
                    answer=answer,
                    repair=reason,
                    timeout_seconds=timeout_seconds,
                )
            except ValidationError:
                available = sum(slots for _, slots in self.reservations) - self.calls
                if (
                    attempt
                    or self.calls + 2 > self.settings.analyst_max_model_calls
                    or self.remaining() < 2
                    or (available < 2 and not await self.reserve(2 - available))
                ):
                    return None
        return None

    async def investigate(self) -> dict[str, Any]:
        native_tool = self._native_statistic_tool()
        if native_tool is not None and not self.fallback_claims():
            if (
                self.rounds >= self.settings.analyst_max_tool_rounds
                or self.tool_count >= 6
                or time.monotonic() - self.started >= self.settings.analyst_investigation_seconds
            ):
                raise TimeoutError("Investigation limit")
            # Resolve native quantitative facts before the model can mistake
            # uninvestigated data for an unavailable or ambiguous scope.
            self.rounds += 1
            self.tool_count += 1
            await self.run_tool(ToolCall(name=native_tool, question=self.tools.question))
        await self.prefetch()
        while True:
            complete_native = self.fallback_claims()
            if (
                self._paired_record_claims()
                or self.tools.narrative
                or (native_tool is not None and complete_native)
            ):
                # Only native, scope-complete claims bypass tool planning. A true but
                # unrelated fallback fact must not short-circuit unsupported selectors.
                answer = await self.model(ProposedAnswer)
                refused = False
                self.model_refused = False
            else:
                action = await self.next_action()
                if action.action == "call_tools":
                    if action.answer is not None or not action.tools:
                        raise ValueError("Malformed tool action")
                    if self.rounds >= self.settings.analyst_max_tool_rounds or (
                        time.monotonic() - self.started
                        >= self.settings.analyst_investigation_seconds
                    ):
                        raise TimeoutError("Investigation limit")
                    if self.tool_count + len(action.tools) > 6:
                        raise ValueError("Tool-call limit")
                    remaining_slots = sum(slots for _, slots in self.reservations) - self.calls
                    if remaining_slots < 2 and not await self.reserve(2 - remaining_slots):
                        return await self.fallback(
                            "Budget unavailable for investigation and review."
                        )
                    self.rounds += 1
                    # One AsyncSession cannot run concurrent database operations.
                    for call in action.tools:
                        if (
                            time.monotonic() - self.started
                            >= self.settings.analyst_investigation_seconds
                        ):
                            break
                        self.tool_count += 1
                        await self.run_tool(call)
                    continue
                answer = action.answer
                refused = action.action in REFUSAL_ACTIONS
                self.model_refused = refused
            if answer is None:  # next_action guarantees this; narrows the type
                raise ValueError("Malformed answer action")
            self.last_answer = answer
            supported, reason = await self.validate(answer)
            if supported:
                return self.render(answer, llm=True, refused=refused)
            # Split the remaining time between revision and review.
            repair_timeout = min(
                self.settings.ai_request_timeout_seconds, (self.remaining() - 0.5) / 2
            )
            observed_call_seconds = max(
                (item["latency_ms"] / 1000 for item in self.trace), default=1.0
            )
            if self.calls + 2 <= self.settings.analyst_max_model_calls and (
                repair_timeout >= max(1.0, observed_call_seconds)
            ):
                available = sum(slots for _, slots in self.reservations) - self.calls
                if available >= 2 or await self.reserve(2 - available):
                    repaired = await self.repair(answer, reason, timeout_seconds=repair_timeout)
                    if repaired is not None:
                        supported, _ = await self.validate(repaired, timeout_seconds=repair_timeout)
                        if supported:
                            return self.render(repaired, llm=True, refused=refused)
                    else:
                        # Both repair replies were off-schema; this is not a review verdict.
                        return await self.fallback("Repair output did not pass schema validation.")
            return await self.fallback("Proposed wording did not pass evidence review.")

    def _has_explicit_archive_scope(self) -> bool:
        scope = self.tools.scope
        return bool(scope and (scope.game_ids or scope.date_start or scope.date_end))

    def _paired_record_claims(self) -> list[VerifiedClaim]:
        return paired_record_claims(self)

    def _native_statistic_tool(
        self,
    ) -> Literal["get_player_stats", "get_team_stats", "find_player_games"] | None:
        return native_statistic_tool(self)

    def _required_claim_groups(self) -> dict[str, list[set[str]]]:
        return required_claim_groups(self)

    async def validate(
        self, answer: ProposedAnswer, *, timeout_seconds: float | None = None
    ) -> tuple[bool, str]:
        return await validate_answer(self, answer, timeout_seconds=timeout_seconds)

    async def review(
        self, answer: ProposedAnswer, *, timeout_seconds: float | None = None
    ) -> AnswerReview | None:
        """Review with one retry when the provider returns non-JSON, then fail closed."""
        for attempt in range(2):
            try:
                return await self.model(
                    AnswerReview, review=True, answer=answer, timeout_seconds=timeout_seconds
                )
            except ValidationError:
                capacity = (
                    self.calls < self.settings.analyst_max_model_calls - 2 and self.remaining() > 5
                )
                if attempt or not capacity:
                    return None
            except (ValueError, RuntimeError):
                return None
        return None

    def fallback_claims(self) -> list[VerifiedClaim]:
        """Complete native facts, with PR-only split/flow families as a last resort."""
        live_or_future = (
            re_search_live(self.tools.question)
            or future_requested(self.tools.question)
            or future_requested(self.tools.topic)
        )
        if (
            live_or_future
            and self._native_statistic_tool() is None
            and not self.tools.narrative
            and not self._has_explicit_archive_scope()
        ):
            return []
        claims = self._native_fallback_claims()
        if claims:
            return claims
        scope = self.tools.scope
        if scope is not None and (
            flow_requested(self.tools.question) or split_requested(self.tools.question, scope)
        ):
            return pr_fallback_claims(self)
        return []

    def _native_fallback_claims(self) -> list[VerifiedClaim]:
        """Only release/scope-matched facts can answer a failed turn.

        Prior claims may be valid historical facts without answering this question.
        Reuse current tool work only when its complete population and metric match.
        """
        scope = self.tools.scope
        if (
            scope is None
            or scope.requires_clarification
            or (scope.periods and not self.tools.supports_period_average(scope))
            or self.tools.season != self.tools.release.season
            or any(
                season != self.tools.release.season
                for season in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", self.tools.question)
            )
        ):
            return []
        games = self.tools.selected_games(scope)
        if is_record_request(self.tools.question) and not scope.player_ids:
            games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
        if scope.relative_game_count and not scope.player_ids:
            games = (
                games[: scope.relative_game_count]
                if scope.relative_game_order == "first"
                else games[-scope.relative_game_count :]
            )
        expected_games = {g.id for g in games}
        discovery = re_search_discovery(self.tools.question)
        threshold_request = is_player_threshold_question(self.tools.question) and bool(
            scope.player_ids
        )
        threshold = parse_stat_threshold(self.tools.question) if threshold_request else None
        threshold_listing = threshold_request and wants_game_listing(self.tools.question)
        team_groups = {
            label: {game.id for game in population}
            for label, population in self.tools.requested_team_groups()
        }
        profile = self.tools.player_profile_requested()
        season_comparison = self.tools.season_window_comparison_requested()
        statistical_extreme = self.tools.statistical_extreme_requested()
        leader_request = is_player_leader_request(self.tools.question)
        player_populations = {}
        if scope.player_ids:
            game_map = {game.id: game for game in self.tools.games}
            baseline_games = (
                {
                    game.id
                    for game in self.tools.selected_games(
                        self.tools.season_comparison_baseline_scope(scope)
                    )
                }
                if season_comparison
                else set()
            )
            for pid in scope.player_ids:
                appearances = {
                    stat.game_id
                    for stat, _ in self.tools.rows
                    if stat.player_id == pid and stat.minutes > 0
                }
                current = sorted(
                    appearances & expected_games,
                    key=lambda identity: (
                        game_map[identity].game_date,
                        game_map[identity].nba_game_id,
                    ),
                )
                if scope.relative_game_count:
                    current = (
                        current[: scope.relative_game_count]
                        if scope.relative_game_order == "first"
                        else current[-scope.relative_game_count :]
                    )
                player_populations[f"player:{pid}"] = [set(current)]
                if season_comparison:
                    player_populations[f"player:{pid}"].append(appearances & baseline_games)
        claims = []
        results = list(self.results)
        if is_record_request(self.tools.question) and not scope.player_ids:
            # Revalidated prior record totals are reusable only for the exact population.
            results.append(
                ToolResult(status="ok", message="", claims=list(self.tools.claims.values()))
            )
        for result in results:
            for claim in result.claims:
                if claim.release_id != self.tools.release.version:
                    continue
                if not claim.supporting_evidence_ids or any(
                    ref not in self.tools.evidence
                    or self.tools.evidence[ref].release_id != self.tools.release.version
                    for ref in claim.supporting_evidence_ids
                ):
                    continue
                if threshold_request and threshold is not None:
                    player_id = int(claim.subject_id.split(":", 1)[1]) if claim.subject_id else -1
                    population = set(player_populations.get(claim.subject_id or "", [[]])[0])
                    matched_ids = {
                        stat.game_id
                        for stat, _ in self.tools.rows
                        if stat.player_id == player_id
                        and stat.game_id in population
                        and stat.minutes > 0
                        and threshold.meets(stat)
                    }
                    relevant = (
                        claim.metric_id == "games:count"
                        and set(claim.game_ids or []) == matched_ids
                        and claim.sample_size == len(population)
                        and claim.eligibility.get("stat_predicate")
                        == {
                            "metric_id": threshold.stat,
                            "operator": threshold.symbol,
                            "cutoff": threshold.value,
                        }
                        or threshold_listing
                        and claim.metric_id == f"{threshold.stat}:total"
                        and len(claim.game_ids or []) == 1
                        and set(claim.game_ids or []) <= matched_ids
                    )
                elif discovery:
                    relevant = (
                        bool(result.candidates) and set(claim.game_ids or []) <= expected_games
                    )
                elif team_groups:
                    label = (claim.window or {}).get("comparison_group")
                    relevant = (
                        self._native_statistic_tool() == "get_team_stats"
                        and claim.subject_id == "team:NYK"
                        and claim.metric_id == "team_comparison"
                        and label in team_groups
                        and set(claim.game_ids or []) == team_groups[label]
                        and isinstance(claim.value, dict)
                        and set(claim.value) == set(self.tools.team_comparison_metrics(scope))
                    )
                elif scope.periods:
                    relevant = (
                        claim.subject_id == "team:NYK"
                        and claim.metric_id == "period_points:average"
                        and claim.filters.get("periods") in [[p] for p in scope.periods]
                        and set(claim.game_ids or []) == expected_games
                    )
                elif leader_request:
                    relevant = (
                        claim.subject_id == "team:NYK"
                        and (
                            claim.metric_id.endswith(":leaders")
                            or claim.metric_id.endswith(":single_game_high")
                        )
                        and set(claim.game_ids or []) <= expected_games
                    )
                elif statistical_extreme:
                    relevant = (
                        claim.subject_id == "team:NYK"
                        and len(claim.game_ids or []) == 1
                        and set(claim.game_ids or []) <= expected_games
                        and claim.metric_id in {"game_score", "margin"}
                    )
                elif self.tools.narrative:
                    relevant = (
                        claim.metric_id == "canonical_game_narrative"
                        and set(claim.game_ids or []) == expected_games
                    )
                elif profile:
                    relevant = (
                        len(claim.game_ids or []) == 1
                        and set(claim.game_ids or []) <= expected_games
                        and (
                            (
                                claim.subject_id in {f"player:{pid}" for pid in scope.player_ids}
                                and claim.metric_id
                                in {"points:total", "rebounds:total", "assists:total"}
                            )
                            or (claim.subject_id == "team:NYK" and claim.metric_id == "game_score")
                        )
                    )
                else:
                    subject = (
                        claim.subject_id in {f"player:{pid}" for pid in scope.player_ids}
                        if scope.player_ids
                        else claim.subject_id == "team:NYK"
                    )
                    populations = [expected_games]
                    if scope.player_ids:
                        populations = player_populations.get(claim.subject_id, [])
                    relevant = subject and set(claim.game_ids or []) in populations
                    if not scope.player_ids:
                        relevant = relevant and claim.sample_size == len(expected_games)
                    if scope.player_ids:
                        expected_metric = (
                            "three_point_percentage"
                            if re.search(
                                r"\bthree[ -]point percentage\b", self.tools.question, re.I
                            )
                            else "starts"
                            if re.search(
                                r"\b(?:games?|times)\b.*\bstart(?:ed)?\b", self.tools.question, re.I
                            )
                            else scope.metric or "points"
                        )
                        allowed_metrics = set(scope.requested_metrics) or {expected_metric}
                        relevant = relevant and claim.metric_id.split(":")[0] in allowed_metrics
                if relevant:
                    claims.append(claim)
        if threshold_request:
            counts = [claim for claim in claims if claim.metric_id == "games:count"]
            if len(counts) != len(scope.player_ids):
                return []
            if threshold_listing:
                matching = {
                    (claim.subject_id, game_id)
                    for claim in claims
                    if claim.metric_id.endswith(":total") and len(claim.game_ids or []) == 1
                    for game_id in claim.game_ids or []
                }
                expected_matches = {
                    (claim.subject_id, game_id)
                    for claim in counts
                    for game_id in claim.eligibility.get("matching_game_ids", [])
                }
                if matching != expected_matches:
                    return []
            return list({claim.claim_id: claim for claim in claims}.values())
        if team_groups:
            if {c.window["comparison_group"] for c in claims if c.window} != set(team_groups):
                return []
            return list({c.claim_id: c for c in claims}.values())
        if scope.periods:
            if {c.filters["periods"][0] for c in claims} != set(scope.periods):
                return []
        if profile:
            required = {
                (f"player:{pid}", metric, game.id)
                for pid in scope.player_ids
                for metric in ("points:total", "rebounds:total", "assists:total")
                for game in games
            } | {("team:NYK", "game_score", game.id) for game in games}
            supplied = {(c.subject_id, c.metric_id, (c.game_ids or [None])[0]) for c in claims}
            if supplied != required:
                return []
        if statistical_extreme:
            metrics = {"game_score"}
            if "margin" in self.tools.question.lower():
                metrics.add("margin")
            selected_extremes = (
                self.tools.narrative.games if self.tools.narrative is not None else games
            )
            required = {(metric, g.id) for metric in metrics for g in selected_extremes}
            supplied = {(c.metric_id, (c.game_ids or [None])[0]) for c in claims}
            if supplied != required:
                return []
            # Each slot may have alternative native claim IDs (for example a corrected
            # margin receipt). Deliver one deterministic representative, not every alias.
            selected: dict[tuple[str, int | None], VerifiedClaim] = {}
            for claim in claims:
                slot = (claim.metric_id, (claim.game_ids or [None])[0])
                selected.setdefault(slot, claim)
            claims = list(selected.values())
        if season_comparison:
            for pid in scope.player_ids:
                required = {
                    frozenset(population) for population in player_populations[f"player:{pid}"]
                }
                supplied = {
                    frozenset(c.game_ids or [])
                    for c in claims
                    if c.subject_id == f"player:{pid}"
                    and c.metric_id == f"{scope.metric or 'points'}:average"
                }
                if supplied != required:
                    return []
        if is_game_score_request(self.tools.question) and not scope.player_ids:
            claims = [c for c in claims if c.metric_id == "game_score"]
        if is_record_request(self.tools.question) and not scope.player_ids:
            claims = [c for c in claims if c.metric_id in {"wins", "losses"}]
            if {c.metric_id for c in claims} != {"wins", "losses"}:
                return []
        return list({c.claim_id: c for c in claims}.values())

    async def fallback(self, reason: str) -> dict[str, Any]:
        return await fallback(self, reason)

    def render_fallback(self, reason: str) -> dict[str, Any]:
        return render_fallback(self, reason)

    def render(
        self,
        answer: ProposedAnswer,
        *,
        llm: bool,
        warning: str = "",
        refused: bool = False,
        backend_claims: list[VerifiedClaim] | None = None,
    ) -> dict[str, Any]:
        return render(
            self,
            answer,
            llm=llm,
            warning=warning,
            refused=refused,
            backend_claims=backend_claims,
        )
