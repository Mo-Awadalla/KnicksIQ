"""Controlled, release-pinned analytics. Retrieval never supplies a denominator."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.core.config import get_settings
from app.evaluation.trace_capture import record_search, record_tool
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.archive_retrieval import (
    fuse_archive_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
from app.services.archive_units import accepts_unit, build_archive_units
from app.services.canonical_narrative import NarrativeSelection, build_narrative, select_narrative
from app.services.evidence_contracts import (
    PLAYER_METRICS,
    TEAM_METRICS,
    Candidate,
    Evidence,
    ToolCall,
    ToolResult,
    VerifiedClaim,
)
from app.services.game_reference import resolve_game_reference
from app.services.query_resolution import (
    ResolvedQuery,
    all_star_end,
    is_game_score_request,
    is_record_request,
    resolve_query,
)
from app.services.team_aliases import team_ids_in_text
from app.services.team_scope import comparison_groups
from basketball_core.analytics.catalog import _windows, build_fact_catalog
from basketball_core.analytics.registry import STAT_REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

METRICS = (
    "points",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "three_pointers_made",
    "plus_minus",
    "minutes",
)


class AnalystTools:
    def __init__(
        self,
        db: AsyncSession,
        release: DatasetRelease,
        question: str,
        season: str,
        state: dict[str, Any],
        context: list[dict[str, str]] | None = None,
    ):
        self.db, self.release, self.question, self.season = db, release, question, season
        self.state = state
        self.context = context or []
        self.claims: dict[str, VerifiedClaim] = {}
        self.evidence: dict[str, Evidence] = {}
        self.candidates: dict[str, Candidate] = {}
        self.issued_evidence_ids: set[str] = set()
        self.games: list[Game] = []
        self.rows: list[tuple[PlayerGameStat, Player]] = []
        self.scope: ResolvedQuery | None = None
        self.narrative: NarrativeSelection | None = None
        self.discovery: ToolResult | None = None
        self.different = bool(re.search(r"\bdifferent player\b", question, re.I))

    async def prepare(self) -> None:
        self.games = list(
            (
                await self.db.execute(
                    select(Game)
                    .where(
                        Game.release_id == self.release.id,
                        Game.season == self.release.season,
                        (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
                    )
                    .order_by(Game.game_date, Game.id)
                )
            ).scalars()
        )
        loaded_rows = list(
            (
                await self.db.execute(
                    select(PlayerGameStat, Player)
                    .join(Player)
                    .where(
                        PlayerGameStat.release_id == self.release.id,
                        PlayerGameStat.game_id.in_([g.id for g in self.games]),
                        PlayerGameStat.team_id == "NYK",
                    )
                )
            ).all()
        )
        self.rows = [(stat, player) for stat, player in loaded_rows]
        self.scope = await resolve_query(
            self.db, self.question, intent="analyst", data_version=self.release.version
        )
        self.scope = resolve_game_reference(self.question, self.scope, self.context, self.games)
        if (
            self.scope.date_start
            and self.scope.date_end
            and (self.scope.date_start != self.scope.date_end)
            and re.search(r"\b(between|from|through|until)\b", self.question, re.I)
        ):
            self.scope = self.scope.model_copy(update={"game_ids": []})
        prior = self.state.get("scope", {})
        followup = bool(
            re.search(
                r"\b(he|him|his|that|another|different player)\b|^\s*(why|now|and|what about)",
                self.question,
                re.I,
            )
        )
        if followup:
            updates = {}
            for key in ("player_ids", "season_type", "opponent_id", "home_away", "game_result"):
                if key == "game_result" and is_record_request(self.question):
                    continue
                if not getattr(self.scope, key) and prior.get(key):
                    updates[key] = prior[key]
            if self.different:
                updates["player_ids"] = []
            self.scope = self.scope.model_copy(update=updates)
        if not self.scope.player_ids and (
            not self.scope.requires_clarification
            or self.scope.clarification_reason == "ambiguous_game"
        ):
            self.narrative = select_narrative(self.question, self.selected_games(self.scope))
            if self.narrative:
                self.scope = self.scope.model_copy(
                    update={
                        "game_ids": [g.id for g in self.narrative.games],
                        "requires_clarification": False,
                        "clarification_reason": None,
                        "clarification_options": [],
                    }
                )
        unknown_subject = re.search(r"\babout\s+(.+?)[?.!]*$", self.question, re.I)
        if (
            unknown_subject
            and not self.scope.player_ids
            and not self.different
            and not re.search(
                r"\b(knicks|nyk|season|archive|team|playoff|game)\b", unknown_subject[1], re.I
            )
        ):
            self.scope = self.scope.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_options": sorted({p.full_name for _, p in self.rows}),
                }
            )
        if re.search(r"\b(he|him|his)\b", self.question, re.I) and not self.scope.player_ids:
            self.scope = self.scope.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_options": sorted({p.full_name for _, p in self.rows}),
                }
            )
        self.state["scope"] = self.scope.model_dump(mode="json")
        self.state["scope_origin"] = "user" if not followup else "verified_followup"
        self.state["intent"] = self.question[:1200]
        # Immutable release references are revalidated for identity and integrity at admission.
        if self.state.get("release") == self.release.version:
            permitted_games = {g.id for g in self.selected_games(self.scope)}
            for raw in self.state.get("claims", []):
                claim = VerifiedClaim.model_validate(raw)
                if (
                    claim.release_id == self.release.version
                    and set(claim.game_ids or []) <= permitted_games
                    and (
                        not self.scope.player_ids
                        or claim.subject_id in {f"player:{pid}" for pid in self.scope.player_ids}
                    )
                    and not self.different
                    and not re.search(r"\b(another|one more)\b", self.question, re.I)
                ):
                    self.claims[claim.claim_id] = claim
            for raw in self.state.get("evidence", []):
                item = Evidence.model_validate(raw)
                if item.release_id == self.release.version:
                    self.evidence[item.evidence_id] = item
                    self.issued_evidence_ids.add(item.evidence_id)
        else:
            self.state["delivered_fact_ids"] = []
        self.state["release"] = self.release.version

    def manifest(self) -> dict[str, Any]:
        return {
            "release_id": self.release.version,
            "seasons": [self.release.season],
            "season_types": sorted({g.season_type for g in self.games}),
            "data_types": [
                "game_scores",
                "player_box_scores",
                "team_box_scores",
                "period_scores",
                "archive_evidence",
            ],
            "metrics": list(PLAYER_METRICS),
            "team_metrics": list(TEAM_METRICS),
            "games": len(self.games),
            "box_score_rows": len(self.rows),
            "known_gaps": [
                "No live injuries, trades or current updates.",
                "Archive coverage is not necessarily the complete NBA season.",
                "Box scores do not establish causation or overall playing quality.",
            ],
            "scope": self.scope.model_dump(mode="json") if self.scope else {},
        }

    def selected_games(self, scope: ResolvedQuery) -> list[Game]:
        games = [
            g
            for g in self.games
            if (not scope.game_ids or g.id in scope.game_ids)
            and (not scope.season_type or g.season_type == scope.season_type)
            and (not scope.date_start or g.game_date >= scope.date_start)
            and (not scope.date_end or g.game_date <= scope.date_end)
            and (not scope.opponent_id or scope.opponent_id in (g.home_team_id, g.away_team_id))
            and (not scope.home_away or (g.home_team_id == "NYK") == (scope.home_away == "home"))
        ]
        if scope.game_result:
            games = [
                g
                for g in games
                if (self.score(g)[0] > self.score(g)[1]) == (scope.game_result == "W")
            ]
        return games

    @staticmethod
    def score(game: Game) -> tuple[int, int]:
        return (
            (game.home_score, game.away_score)
            if game.home_team_id == "NYK"
            else (game.away_score, game.home_score)
        )

    def receipt(
        self,
        game: Game,
        stat: PlayerGameStat | TeamGameStat | PeriodScore | None = None,
        player: Player | None = None,
    ) -> Evidence:
        identity = f"{self.release.version}:game:{game.id}"
        if isinstance(stat, PlayerGameStat) and player is not None:
            identity += f":player:{player.id}"
        elif isinstance(stat, TeamGameStat):
            identity += f":team_box:{stat.team_id}"
        elif isinstance(stat, PeriodScore):
            identity += f":period:{stat.team_id}:{stat.period}"
        if identity in self.evidence:
            return self.evidence[identity]
        data: dict[str, Any] = {
            "date": str(game.game_date),
            "season_type": game.season_type,
            "home": game.home_team_id,
            "away": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
        }
        if isinstance(stat, PlayerGameStat) and player is not None:
            data.update(
                subject_id=f"player:{player.id}",
                player=player.full_name,
                **{m: getattr(stat, m) for m in METRICS},
            )
            data.update(
                three_pointers_attempted=stat.three_pointers_attempted, starter=stat.starter
            )
        elif isinstance(stat, TeamGameStat):
            data.update(
                canonical_source_id=f"team_box:{game.nba_game_id}:{stat.team_id}",
                **{
                    key: getattr(stat, key)
                    for key in ("turnovers", "field_goals_made", "field_goals_attempted")
                },
            )
        elif isinstance(stat, PeriodScore):
            data.update(
                canonical_source_id=f"period:{game.nba_game_id}:{stat.team_id}:{stat.period}",
                period=stat.period,
                points=stat.points,
            )
        evidence = Evidence(
            evidence_id=identity,
            release_id=self.release.version,
            game_id=game.id,
            text=json.dumps(data, sort_keys=True),
            source_name=game.source_name,
            source_url=game.source_url,
            metadata=data,
        )
        self.evidence[identity] = evidence
        return evidence

    def claim(
        self,
        *,
        subject: str,
        metric: str,
        value: Any,
        unit: str,
        games: list[Game],
        evidence: list[Evidence],
        statement: str,
        scope: ResolvedQuery,
        sample: int,
        denominator: float | int | None,
        baseline: list[str] | None = None,
        limitations: list[str] | None = None,
        eligibility: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
        population: str = "available release archive",
    ) -> VerifiedClaim:
        if len(evidence) > 3:
            import hashlib

            source_ids = list(dict.fromkeys(e.evidence_id for e in evidence))
            identity = (
                "calculation:"
                + hashlib.sha256(
                    json.dumps(
                        [self.release.version, subject, metric, source_ids, value], sort_keys=True
                    ).encode()
                ).hexdigest()
            )
            receipt = Evidence(
                evidence_id=identity,
                release_id=self.release.version,
                text=statement,
                metadata={
                    "source_evidence_ids": source_ids,
                    "calculation_version": "analyst-v1",
                    "sample_size": sample,
                    "denominator": denominator,
                },
            )
            self.evidence[identity] = receipt
            evidence = [receipt]
        claim = VerifiedClaim.create(
            subject_id=subject,
            metric_id=metric,
            value=value,
            unit=unit,
            metric_definition_version="box-score-v1",
            population=population,
            filters={
                key: value
                for key, value in scope.model_dump(mode="json").items()
                if key in ("opponent_id", "home_away", "game_result", "periods")
            },
            season=self.release.season,
            season_type=next(iter({g.season_type for g in games}))
            if len({g.season_type for g in games}) == 1
            else None,
            game_ids=[g.id for g in games],
            window=window,
            sample_size=sample,
            denominator=denominator,
            baseline_claim_ids=baseline or [],
            calculation_version="analyst-v1",
            release_id=self.release.version,
            supporting_evidence_ids=[e.evidence_id for e in evidence],
            coverage_limitations=limitations or ["Available archive only; no causal inference."],
            eligibility=eligibility or {"appearance": "minutes > 0"},
            statement=statement,
        )
        self.claims[claim.claim_id] = claim
        return claim

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            result = await self._execute(call)
            self.claims.update({c.claim_id: c for c in result.claims})
            for item in result.evidence:
                self.evidence[item.evidence_id] = item
                self.issued_evidence_ids.add(item.evidence_id)
                self.issued_evidence_ids.update(item.metadata.get("source_evidence_ids", []))
            self.issued_evidence_ids.update(
                ref for c in result.claims for ref in c.supporting_evidence_ids
            )
            record_tool(
                {"call": call.model_dump(mode="json"), "result": result.model_dump(mode="json")}
            )
            return result
        except Exception as exc:
            # Do not disclose provider/database errors or turn failure into absence.
            result = ToolResult(
                status="dependency_failure",
                message=f"{call.name} unavailable",
                scope={"error_type": type(exc).__name__},
            )
            record_tool(
                {"call": call.model_dump(mode="json"), "result": result.model_dump(mode="json")}
            )
            return result

    async def _execute(self, call: ToolCall) -> ToolResult:
        assert self.scope is not None
        if call.name == "get_evidence":
            if not all(ref in self.issued_evidence_ids for ref in call.evidence_ids):
                return ToolResult(
                    status="unsupported_metric_or_scope",
                    message="Only previously returned release references are allowed.",
                )
            return ToolResult(
                status="ok",
                message="Additional receipt detail.",
                evidence=[self.evidence[ref] for ref in call.evidence_ids],
            )
        if self.scope.requires_clarification:
            return ToolResult(
                status="ambiguous_entity",
                message="Which subject did you mean?",
                choices=self.scope.clarification_options,
            )
        if (
            self.season != self.release.season
            or re.search(r"\b20\d{2}-\d{2}(?!-\d{2})\b", self.question)
            and any(
                s != self.release.season
                for s in re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", self.question)
            )
        ):
            return ToolResult(
                status="unsupported_metric_or_scope",
                message=f"Available season: {self.release.season}.",
            )
        if call.name == "get_game_narrative" or (
            self.narrative and call.name in {"get_team_stats", "discover_facts"}
        ):
            if not self.narrative:
                return ToolResult(
                    status="unsupported_metric_or_scope",
                    message="A defined game-story selection is required.",
                )
            if self.statistical_extreme_requested():
                results = []
                for game in self.narrative.games:
                    game_scope = self.scope.model_copy(update={"game_ids": [game.id]})
                    results.append(self.game_score(game_scope, [game]))
                    if "margin" in self.question.lower():
                        own, opponent = self.score(game)
                        claim = self.claim(
                            subject="team:NYK",
                            metric="margin",
                            value=own - opponent,
                            unit="points",
                            games=[game],
                            evidence=[self.receipt(game)],
                            scope=game_scope,
                            sample=1,
                            denominator=None,
                            eligibility={"selection": self.narrative.definition},
                            statement=(
                                f"Knicks final scoring margin on {game.game_date}: "
                                f"{own - opponent} points."
                            ),
                        )
                        results.append(
                            ToolResult(
                                status="ok", message="Selected final margin.", claims=[claim]
                            )
                        )
                return ToolResult(
                    status="ok",
                    message=self.narrative.definition,
                    claims=[c for r in results for c in r.claims],
                    evidence=[e for r in results for e in r.evidence],
                    scope=self.scope.model_dump(mode="json"),
                )
            return await build_narrative(self.db, self.release, self.narrative)
        # Resolve model suggestions locally, but they may only narrow the user's scope.
        scope = await resolve_query(
            self.db, call.question, intent=call.name, data_version=self.release.version
        )
        if scope.requires_clarification:
            return ToolResult(
                status="ambiguous_entity",
                message="Ambiguous entity.",
                choices=scope.clarification_options,
            )
        for key in (
            "player_ids",
            "game_ids",
            "season_type",
            "opponent_id",
            "home_away",
            "game_result",
            "date_start",
            "date_end",
            "periods",
            "relative_game_count",
            "relative_game_order",
        ):
            authoritative = getattr(self.scope, key)
            if authoritative:
                scope = scope.model_copy(update={key: authoritative})
        if (
            scope.periods
            and call.name != "search_archive"
            and not (call.name == "get_team_stats" and self.supports_period_average(scope))
        ):
            return ToolResult(
                status="unsupported_metric_or_scope",
                message=(
                    "Period calculations support team points per game, "
                    "not this requested statistic."
                ),
            )
        games = self.selected_games(scope)
        if not games:
            return ToolResult(
                status="no_matching_results",
                message="No archived games match this scope; this is not evidence "
                "that no such games occurred.",
                scope=scope.model_dump(mode="json"),
            )
        if call.name == "search_archive":
            return await self.search(call, scope, games)
        if call.name == "get_team_stats":
            return await self.team(scope, games)
        if call.name == "discover_facts":
            return self.discover(scope, games)
        if not scope.player_ids:
            return ToolResult(
                status="ambiguous_entity",
                message="Which Knicks player?",
                choices=sorted({p.full_name for _, p in self.rows}),
            )
        metric = call.metric or scope.metric or "points"
        if self.scope.metric:
            if call.metric and call.metric != self.scope.metric:
                return ToolResult(
                    status="unsupported_metric_or_scope",
                    message="The tool metric differs from the user's requested statistic.",
                )
            metric = self.scope.metric
        if call.name == "get_player_stats" and re.search(
            r"\bbefore\s+and\s+after\s+(?:the\s+)?all[ -]star\b", self.question, re.I
        ):
            return self.all_star_comparison(scope, games, metric)
        if call.name == "get_player_stats" and self.player_profile_requested():
            results = []
            for game in games:
                game_scope = scope.model_copy(
                    update={"game_ids": [game.id], "relative_game_count": None}
                )
                results.extend(
                    self.player(game_scope, [game], key, "total")
                    for key in ("points", "rebounds", "assists")
                )
                results.append(self.game_score(game_scope, [game]))
            return ToolResult(
                status="ok" if all(r.status == "ok" for r in results) else "incomplete_coverage",
                message="Complete requested player profile and archived game score.",
                claims=[c for r in results for c in r.claims],
                evidence=[e for r in results for e in r.evidence],
                scope=scope.model_dump(mode="json"),
            )
        if call.name == "get_player_stats" and self.season_window_comparison_requested():
            baseline_scope = self.season_comparison_baseline_scope(scope)
            current = self.player(scope, games, metric, "average")
            baseline = self.player(
                baseline_scope, self.selected_games(baseline_scope), metric, "average"
            )
            return ToolResult(
                status="ok" if current.status == baseline.status == "ok" else "incomplete_coverage",
                message="Requested appearance window and full scoped season baseline.",
                claims=current.claims + baseline.claims,
                evidence=current.evidence + baseline.evidence,
                scope=scope.model_dump(mode="json"),
            )
        if call.name == "compare_windows":
            if not call.baseline_question:
                return ToolResult(
                    status="unsupported_metric_or_scope",
                    message="Comparison requires an explicit baseline window.",
                )
            requested_seasons = re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", call.baseline_question)
            if any(season != self.release.season for season in requested_seasons):
                return ToolResult(
                    status="unsupported_metric_or_scope",
                    message="The baseline season is unavailable in this release.",
                )
            baseline_scope = await resolve_query(
                self.db, call.baseline_question, intent=call.name, data_version=self.release.version
            )
            # A baseline may intentionally use a different phase/window, never another release.
            baseline_scope = baseline_scope.model_copy(update={"player_ids": scope.player_ids})
            baseline_games = self.selected_games(baseline_scope)
            first = self.player(scope, games, metric, call.aggregation)
            second = self.player(baseline_scope, baseline_games, metric, call.aggregation)
            if not first.claims or not second.claims:
                return ToolResult(
                    status="incomplete_coverage",
                    message="One comparison population is unavailable.",
                    claims=first.claims + second.claims,
                    evidence=first.evidence + second.evidence,
                )
            comparisons = []
            for a in first.claims:
                b = next((b for b in second.claims if b.subject_id == a.subject_id), None)
                if (
                    b is None
                    or not isinstance(a.value, (int, float))
                    or not isinstance(b.value, (int, float))
                ):
                    continue
                comparisons.append(
                    self.claim(
                        subject=a.subject_id or "",
                        metric=f"{metric}:delta",
                        value=float(a.value) - float(b.value),
                        unit=a.unit or "",
                        games=list({g.id: g for g in games + baseline_games}.values()),
                        evidence=first.evidence + second.evidence,
                        statement=(f"{a.statement} Baseline: {b.statement}"),
                        scope=scope,
                        sample=a.sample_size or 0,
                        denominator=a.denominator,
                        baseline=[a.claim_id, b.claim_id],
                        window={"current": a.game_ids, "baseline": b.game_ids},
                    )
                )
            return ToolResult(
                status="ok",
                message="Both complete applicable archive populations.",
                claims=first.claims + second.claims + comparisons,
                evidence=first.evidence + second.evidence,
            )
        if re.search(r"\btotal\b", self.question, re.I):
            aggregation = "total"
        else:
            aggregation = call.aggregation
        if re.search(r"\bthree[ -]point percentage\b", self.question, re.I):
            metric = "three_point_percentage"
        elif re.search(r"\b(?:games?|times)\b.*\bstart(?:ed)?\b", self.question, re.I):
            metric = "starts"
        return self.player(scope, games, metric, aggregation)

    def all_star_comparison(
        self, scope: ResolvedQuery, games: list[Game], metric: str
    ) -> ToolResult:
        boundary = all_star_end(self.release.season)
        if boundary is None:
            return ToolResult(
                status="unsupported_metric_or_scope",
                message="An independently supported All-Star boundary is required.",
            )
        populations = {
            "before": [g for g in games if g.game_date <= boundary],
            "after": [g for g in games if g.game_date > boundary],
        }
        results = {
            label: self.player(scope, population, metric, "average")
            for label, population in populations.items()
        }
        claims, evidence = [], []
        for player_id in scope.player_ids:
            subject = f"player:{player_id}"
            baselines = {
                label: next((c for c in result.claims if c.subject_id == subject), None)
                for label, result in results.items()
            }
            before, after = baselines["before"], baselines["after"]
            if (
                before is None
                or after is None
                or not isinstance(before.value, (int, float))
                or not isinstance(after.value, (int, float))
            ):
                return ToolResult(
                    status="incomplete_coverage",
                    message="Both comparison populations require observed player appearances.",
                )
            sources = [
                e
                for result in results.values()
                for e in result.evidence
                if e.metadata.get("subject_id") == subject
            ]
            evidence.extend(sources)
            name = next(p.full_name for _, p in self.rows if p.id == player_id)
            window: dict[str, Any] = {
                label: {
                    "game_ids": claim.game_ids,
                    "sample_size": claim.sample_size,
                    "dates": claim.window,
                }
                for label, claim in (("before", before), ("after", after))
            }
            window.update(
                boundary=boundary.isoformat(), source_url="https://www.nba.com/allstar/2026"
            )
            values = {"before": before.value, "after": after.value}
            values["delta"] = float(after.value) - float(before.value)
            claims.append(
                self.claim(
                    subject=subject,
                    metric=f"{metric}:window_comparison",
                    value=values,
                    unit=f"{metric} per appearance",
                    games=[
                        g
                        for g in games
                        if g.id in set((before.game_ids or []) + (after.game_ids or []))
                    ],
                    evidence=sources,
                    statement=(
                        f"{name}: before the All-Star break, {float(before.value):.1f} {metric} "
                        f"per appearance over {before.sample_size} observed appearances; after, "
                        f"{float(after.value):.1f} over {after.sample_size}. Boundary: {boundary}; "
                        f"{scope.season_type or 'all-phase'} {self.release.season} archive."
                    ),
                    scope=scope,
                    sample=(before.sample_size or 0) + (after.sample_size or 0),
                    denominator=None,
                    baseline=[before.claim_id, after.claim_id],
                    limitations=list(
                        dict.fromkeys(before.coverage_limitations + after.coverage_limitations)
                    ),
                    window=window,
                )
            )
        return ToolResult(
            status="incomplete_coverage"
            if any(r.status != "ok" for r in results.values())
            else "ok",
            message="Complete scoped before/after populations "
            "with observed appearance denominators.",
            claims=claims,
            evidence=evidence,
        )

    def player(
        self, scope: ResolvedQuery, games: list[Game], metric: str, aggregation: str
    ) -> ToolResult:
        game_map = {g.id: g for g in games}
        claims, evidence = [], []
        missing = False
        for player_id in scope.player_ids:
            all_rows = [
                (s, p) for s, p in self.rows if s.player_id == player_id and s.game_id in game_map
            ]
            # Zero minutes means observed DNP, not an appearance; missing rows remain unknown.
            absent = sorted(set(game_map) - {s.game_id for s, _ in all_rows})
            rows = sorted(
                [(s, p) for s, p in all_rows if s.minutes > 0],
                key=lambda row: (
                    game_map[row[0].game_id].game_date,
                    game_map[row[0].game_id].nba_game_id,
                ),
            )
            if scope.relative_game_count:
                rows = (
                    rows[: scope.relative_game_count]
                    if scope.relative_game_order == "first"
                    else rows[-scope.relative_game_count :]
                )
            if not rows:
                continue
            count = len(rows)
            attempts = 0
            if metric == "double_doubles":
                aggregation = "total"
                value = sum(
                    sum(
                        getattr(s, key) >= 10
                        for key in ("points", "rebounds", "assists", "steals", "blocks")
                    )
                    >= 2
                    for s, _ in rows
                )
            elif metric == "three_point_percentage":
                aggregation = "percentage"
                attempts = sum(s.three_pointers_attempted for s, _ in rows)
                if not attempts:
                    continue
                value = sum(s.three_pointers_made for s, _ in rows) / attempts * 100
            elif metric == "starts":
                aggregation = "total"
                value = sum(bool(s.starter) for s, _ in rows)
            else:
                value = sum(getattr(s, metric) for s, _ in rows)
            if aggregation == "average":
                value /= count
            receipts = [self.receipt(game_map[s.game_id], s, p) for s, p in rows]
            evidence.extend(receipts)
            limitations = ["Only observed appearances in the available archive."]
            if absent:
                missing = True
                limitations.append(f"Missing player rows for archived game IDs: {absent}.")
            name = rows[0][1].full_name
            unit = f"{metric} per appearance" if aggregation == "average" else metric
            observed_games = [game_map[s.game_id] for s, _ in rows]
            statement = (
                f"{name}: {value:.1f} {unit} across {count} observed appearances "
                f"in {self.scope_label(scope, observed_games)}."
            )
            if metric == "three_point_percentage":
                statement = (
                    f"{name}: {value:.1f}% from three, "
                    f"{sum(s.three_pointers_made for s, _ in rows)} makes in {attempts} attempts "
                    f"across {count} observed appearances "
                    f"in {self.scope_label(scope, observed_games)}."
                )
            claims.append(
                self.claim(
                    subject=f"player:{player_id}",
                    metric=metric
                    if metric in {"three_point_percentage", "starts"}
                    else f"{metric}:{aggregation}",
                    value=value,
                    unit=unit,
                    games=[game_map[s.game_id] for s, _ in rows],
                    evidence=receipts,
                    statement=statement,
                    scope=scope,
                    sample=count,
                    denominator=attempts
                    if metric == "three_point_percentage"
                    else count
                    if aggregation == "average"
                    else None,
                    limitations=limitations,
                    window={
                        "date_start": str(game_map[rows[0][0].game_id].game_date),
                        "date_end": str(game_map[rows[-1][0].game_id].game_date),
                    },
                )
            )
        return ToolResult(
            status=("incomplete_coverage" if missing else "ok")
            if claims
            else "no_matching_results",
            message="Calculated from all applicable database rows; retrieval is "
            "not the denominator."
            if claims
            else "No observed appearances.",
            claims=claims,
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

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
            and scope.metric is None
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

    def game_score(self, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        if len(games) != 1:
            return ToolResult(
                status="ambiguous_entity",
                message="Which game score?",
                choices=[str(g.game_date) for g in games],
            )
        game = games[0]
        if game.status != "final":
            return ToolResult(
                status="unsupported_metric_or_scope",
                message="A final score is not available for this archived game.",
            )
        evidence = [self.receipt(game)]
        knicks, opponent = self.score(game)
        opponent_id = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        statement = f"Final score on {game.game_date}: NYK {knicks}, {opponent_id} {opponent}."
        if (
            self.narrative
            and self.statistical_extreme_requested()
            and re.search(r"\bexplain\b", self.question, re.I)
        ):
            statement = f"Selection measure: {self.narrative.definition} {statement}"
        claim = self.claim(
            subject="team:NYK",
            metric="game_score",
            value={"NYK": knicks, opponent_id: opponent},
            unit="points by team",
            games=games,
            evidence=evidence,
            scope=scope,
            sample=1,
            denominator=None,
            eligibility={"game": "final archived Knicks game"},
            statement=statement,
        )
        return ToolResult(
            status="ok",
            message="Archived final score.",
            claims=[claim],
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

    async def team(self, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        if is_game_score_request(self.question):
            return self.game_score(scope, games)
        if scope.periods:
            return await self.period_points(scope, games)
        groups = self.requested_team_groups()
        if groups:
            return await self.team_comparison(scope, groups)
        if re.search(r"\b(?:who led|leaders?|which player)\b", self.question, re.I):
            return self.team_leaders(scope, games)
        if is_record_request(self.question):
            games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
        if scope.relative_game_count:
            games = (
                games[: scope.relative_game_count]
                if scope.relative_game_order == "first"
                else games[-scope.relative_game_count :]
            )
        evidence = [self.receipt(g) for g in games]
        wins = sum(self.score(g)[0] > self.score(g)[1] for g in games)
        values = {
            "wins": wins,
            "losses": len(games) - wins,
            "points": sum(self.score(g)[0] for g in games),
            "margin": sum(self.score(g)[0] - self.score(g)[1] for g in games),
        }
        question = self.question.lower()
        denominator = None
        eligibility: dict[str, Any] = {"game": "archived Knicks game"}
        threshold_description = ""
        threshold = re.search(r"\b(at least|under|over|more than|fewer than)\s+(\d+)\b", question)
        if threshold and re.search(r"\bhow many games\b", question):
            cutoff = int(threshold[2])
            opponent_points = bool(re.search(r"\b(opponents?|allow|hold)\b", question))
            operator = (
                ">="
                if threshold[1] == "at least"
                else "<"
                if threshold[1] in {"under", "fewer than"}
                else ">"
            )
            eligibility["score_predicate"] = {
                "subject_id": "opponent" if opponent_points else "team:NYK",
                "metric_id": "points",
                "operator": operator,
                "cutoff": cutoff,
            }
            threshold_description = (
                f" with {'opponent' if opponent_points else 'NYK'} points {operator} {cutoff}"
            )
            observed = [self.score(g)[1 if opponent_points else 0] for g in games]
            count = sum(
                v >= cutoff
                if threshold[1] == "at least"
                else v < cutoff
                if threshold[1] in {"under", "fewer than"}
                else v > cutoff
                for v in observed
            )
            values = {"games:count": count}
        elif is_record_request(self.question):
            values = {"wins": wins, "losses": len(games) - wins}
        elif re.search(r"\bhow many\b.*\b(?:win|wins|won)\b", question):
            values = {"wins": wins}
        elif re.search(r"\bhow many\b.*\b(?:lose|losses|lost)\b", question):
            values = {"losses": len(games) - wins}
        elif re.search(r"\bhow many games\b", question):
            values = {"games:count": len(games)}
        elif not is_record_request(self.question) and re.search(
            r"\b(average|per game|points allowed)\b", question
        ):
            metric = (
                "margin"
                if "margin" in question
                else "points_allowed"
                if re.search(r"\b(allow(?:ed)?|opponents?)\b", question)
                else "points"
            )
            total = (
                sum(self.score(g)[1] for g in games)
                if metric == "points_allowed"
                else values[metric]
            )
            denominator = len(games)
            values = {f"{metric}:average": total / denominator}
        elif scope.metric == "points":
            values = {"points": values["points"]}
        elif "margin" in question:
            values = {"margin": values["margin"]}
        else:
            values = {"wins": wins, "losses": len(games) - wins}
        claims = [
            self.claim(
                subject="team:NYK",
                metric=metric,
                value=value,
                unit=metric,
                games=games,
                evidence=evidence,
                scope=scope,
                sample=len(games),
                denominator=denominator,
                eligibility=eligibility,
                statement=(
                    f"Knicks {metric}{threshold_description}: {value} "
                    f"over {len(games)} archived games "
                    f"in {self.scope_label(scope, games)}."
                ),
            )
            for metric, value in values.items()
        ]
        return ToolResult(
            status="ok",
            message="Archive team totals.",
            claims=claims,
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

    def team_leaders(self, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        metric = scope.metric
        if metric not in METRICS:
            return ToolResult(
                status="unsupported_metric_or_scope",
                message="Specify a supported leader statistic.",
            )
        game_map = {g.id: g for g in games}
        rows = [(s, p) for s, p in self.rows if s.game_id in game_map]
        if {s.game_id for s, _ in rows} != set(game_map):
            return ToolResult(
                status="incomplete_coverage",
                message="Complete scoped player box scores are unavailable.",
            )
        totals: dict[str, int | float] = {}
        for stat, player in rows:
            totals[player.full_name] = totals.get(player.full_name, 0) + getattr(stat, metric)
        maximum = max(totals.values())
        leaders = sorted(name for name, value in totals.items() if value == maximum)
        evidence = [self.receipt(game_map[s.game_id], s, p) for s, p in rows]
        claim = self.claim(
            subject="team:NYK",
            metric=f"{metric}:leaders",
            value={"leaders": leaders, "total": maximum},
            unit=f"total {metric}",
            games=games,
            evidence=evidence,
            scope=scope,
            sample=len(games),
            denominator=None,
            eligibility={"player": "NYK box-score rows", "ties": "all leaders"},
            statement=(
                f"{', '.join(leaders)} led the Knicks with {maximum} total {metric} "
                f"across {len(games)} archived games."
            ),
        )
        return ToolResult(
            status="ok",
            message="Complete scoped leader population.",
            claims=[claim],
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

    async def period_points(self, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        game_map = {g.id: g for g in games}
        rows = list(
            (
                await self.db.execute(
                    select(PeriodScore).where(
                        PeriodScore.release_id == self.release.id,
                        PeriodScore.game_id.in_(game_map),
                        PeriodScore.team_id == "NYK",
                        PeriodScore.period.in_(scope.periods),
                    )
                )
            ).scalars()
        )
        claims, evidence = [], []
        for period in scope.periods:
            population = [r for r in rows if r.period == period]
            if {r.game_id for r in population} != set(game_map):
                return ToolResult(
                    status="incomplete_coverage",
                    message=(
                        f"Complete quarter {period} scores are unavailable for this population."
                    ),
                )
            receipts = [self.receipt(game_map[r.game_id], r) for r in population]
            evidence.extend(receipts)
            total = sum(r.points for r in population)
            average = total / len(games)
            claims.append(
                self.claim(
                    subject="team:NYK",
                    metric="period_points:average",
                    value=average,
                    unit="points per team game",
                    games=games,
                    evidence=receipts,
                    scope=scope.model_copy(update={"periods": [period]}),
                    sample=len(games),
                    denominator=len(games),
                    eligibility={"period": period, "coverage": "one score per team game"},
                    statement=(
                        f"Quarter {period}: Knicks averaged {average:.4f} points per game "
                        f"({total} points across {len(games)} games)."
                    ),
                )
            )
        return ToolResult(
            status="ok",
            message="Complete requested quarter populations.",
            claims=claims,
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

    async def team_comparison(
        self, scope: ResolvedQuery, groups: list[tuple[str, list[Game]]]
    ) -> ToolResult:
        """Use the existing team-scope definitions and box-score denominators."""
        metrics = self.team_comparison_metrics(scope)
        game_map = {g.id: g for _, games in groups for g in games}
        team_rows: dict[int, TeamGameStat] = {}
        if metrics in {("turnovers_per_game",), ("field_goal_percentage",)}:
            team_rows = {
                r.game_id: r
                for r in (
                    await self.db.execute(
                        select(TeamGameStat).where(
                            TeamGameStat.release_id == self.release.id,
                            TeamGameStat.game_id.in_(game_map),
                            TeamGameStat.team_id == "NYK",
                        )
                    )
                ).scalars()
            }
            if set(team_rows) != set(game_map):
                return ToolResult(
                    status="incomplete_coverage",
                    message="Complete scoped team box scores are unavailable.",
                )
        claims, evidence = [], []
        for label, games in groups:
            if not games:
                return ToolResult(
                    status="incomplete_coverage", message=f"{label}: no matching archived games."
                )
            ids = {g.id for g in games}
            receipts = [self.receipt(g) for g in games]
            values: dict[str, int | float]
            if metrics == ("bench_points_per_team_game",):
                rows = [(s, p) for s, p in self.rows if s.game_id in ids]
                if {s.game_id for s, _ in rows} != ids:
                    return ToolResult(
                        status="incomplete_coverage",
                        message=f"{label}: complete player box scores are unavailable.",
                    )
                values = {
                    "bench_points_per_team_game": sum(s.points for s, _ in rows if not s.starter)
                    / len(games)
                }
                receipts = [self.receipt(game_map[s.game_id], s, p) for s, p in rows]
            elif metrics == ("turnovers_per_game",):
                values = {
                    "turnovers_per_game": sum(team_rows[i].turnovers for i in ids) / len(games)
                }
                receipts = [self.receipt(game_map[i], team_rows[i]) for i in ids]
            elif metrics == ("field_goal_percentage",):
                attempts = sum(team_rows[i].field_goals_attempted for i in ids)
                if not attempts:
                    return ToolResult(
                        status="incomplete_coverage", message=f"{label}: no field-goal attempts."
                    )
                values = {
                    "field_goal_percentage": 100
                    * sum(team_rows[i].field_goals_made for i in ids)
                    / attempts
                }
                receipts = [self.receipt(game_map[i], team_rows[i]) for i in ids]
            elif metrics == ("points_allowed_per_game",):
                values = {
                    "points_allowed_per_game": sum(self.score(g)[1] for g in games) / len(games)
                }
            elif metrics == ("points_per_game",):
                values = {"points_per_game": sum(self.score(g)[0] for g in games) / len(games)}
            else:
                wins = sum(self.score(g)[0] > self.score(g)[1] for g in games)
                values = {"games": len(games), "wins": wins, "losses": len(games) - wins}
                if "average_margin" in metrics:
                    values["average_margin"] = sum(
                        self.score(g)[0] - self.score(g)[1] for g in games
                    ) / len(games)
            evidence.extend(receipts)
            description = ", ".join(
                f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}"
                for key, value in values.items()
            )
            claims.append(
                self.claim(
                    subject="team:NYK",
                    metric="team_comparison",
                    value=values,
                    unit="requested team comparison metrics",
                    games=games,
                    evidence=receipts,
                    scope=scope,
                    sample=len(games),
                    denominator=len(games),
                    window={
                        "comparison_group": label,
                        "date_start": str(games[0].game_date),
                        "date_end": str(games[-1].game_date),
                    },
                    eligibility={"game": "complete requested comparison group"},
                    statement=f"{label}: {description} across {len(games)} archived games.",
                )
            )
        return ToolResult(
            status="ok",
            message="All requested team comparison populations.",
            claims=claims,
            evidence=evidence,
            scope=scope.model_dump(mode="json"),
        )

    def discover(self, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        game_map = {g.id: g for g in games}
        seen = set(self.state.get("delivered_fact_ids", []))
        excluded = set(self.state.get("last_subjects", [])) if self.different else set()
        pool: list[tuple[float, Candidate, list[VerifiedClaim], list[Evidence]]] = []
        for stat, player in self.rows:
            subject = f"player:{player.id}"
            if stat.game_id not in game_map or stat.minutes <= 0 or subject in excluded:
                continue
            if scope.player_ids and player.id not in scope.player_ids:
                continue
            game = game_map[stat.game_id]
            opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
            fact_id = f"{self.release.version}:box:{game.id}:{player.id}"
            if fact_id in seen:
                continue
            receipt = self.receipt(game, stat, player)
            metrics = [scope.metric] if scope.metric in METRICS else ["box_score"]
            claims = []
            for metric in metrics:
                values = {
                    key: getattr(stat, key)
                    for key in ("points", "rebounds", "assists", "turnovers")
                }
                value = values if metric == "box_score" else getattr(stat, metric)
                line = (
                    f"{stat.points} points, {stat.rebounds} rebounds, "
                    f"{stat.assists} assists and {stat.turnovers} turnovers"
                    if metric == "box_score"
                    else f"{value} {metric}"
                )
                claims.append(
                    self.claim(
                        subject=subject,
                        metric=metric,
                        value=value,
                        unit="count by box-score metric" if metric == "box_score" else metric,
                        games=[game],
                        evidence=[receipt],
                        scope=scope,
                        sample=1,
                        denominator=None,
                        statement=f"{player.full_name} recorded {line} on {game.game_date} against "
                        f"{opponent}.",
                        limitations=[
                            "Observed appearance; no season or historical ranking.",
                            "Selected for a high box-score value; not proof of improvement.",
                        ],
                        eligibility={
                            "appearance": "minutes > 0",
                            "policy_version": "single-game-v1",
                        },
                    )
                )
            candidate = Candidate(
                fact_id=fact_id,
                fact_family="single_game",
                subject_id=subject,
                metric=",".join(metrics),
                window={"game_ids": [game.id]},
                baseline=[],
                claim_ids=[c.claim_id for c in claims],
                selection_reason=(
                    "High requested metric"
                    if scope.metric
                    else "High points + 1.5*assists + rebounds - turnovers"
                ),
                extreme_selected=True,
            )
            score = (
                getattr(stat, scope.metric)
                if scope.metric in METRICS
                else stat.points + 1.5 * stat.assists + stat.rebounds - stat.turnovers
            )
            pool.append((score, candidate, claims, [receipt]))
        # Recompute the existing catalog from the COMPLETE release population. This retains
        # its eligibility rules and never mistakes retrieved examples for comparison baselines.
        game_all = {g.id: g for g in self.games}
        catalog_rows = []
        players = {}
        for stat, player in self.rows:
            if player.nba_player_id is None:
                continue
            players[player.nba_player_id] = player
            catalog_rows.append(
                {
                    **{c.name: getattr(stat, c.name) for c in PlayerGameStat.__table__.columns},
                    "nba_player_id": player.nba_player_id,
                    "nba_game_id": game_all[stat.game_id].nba_game_id,
                }
            )
        catalog = build_fact_catalog(
            [
                {
                    "nba_game_id": g.nba_game_id,
                    "game_date": str(g.game_date),
                    "season_type": g.season_type,
                }
                for g in self.games
                if g.nba_game_id
            ],
            catalog_rows,
            [{"nba_player_id": key, "full_name": p.full_name} for key, p in players.items()],
        )
        by_source = {g.nba_game_id: g for g in games}
        rows_by_game_player = {(s.game_id, p.id): (s, p) for s, p in self.rows}
        for fact in catalog:
            if fact["fingerprint"] in seen or not set(fact["source_game_ids"]) <= by_source.keys():
                continue
            player = players[fact["player_ids"][0]]
            subject = f"player:{player.id}"
            if subject in excluded or (scope.player_ids and player.id not in scope.player_ids):
                continue
            if scope.metric and scope.metric not in fact["stat_keys"]:
                continue
            selected = [by_source[key] for key in fact["source_game_ids"]]
            receipts = [
                self.receipt(g, s, p)
                for g in selected
                if (g.id, player.id) in rows_by_game_player
                for s, p in [rows_by_game_player[(g.id, player.id)]]
            ]
            eligibility = {
                "policy_version": fact["detector_version"],
                "minimum_appearances": 4,
                "appearance": "minutes > 0",
                "true_shooting_minimum_fga_per_appearance": 5,
                "recent_window": 10,
                "prior_minimum_appearances": 4,
                "population": "Knicks qualifiers in complete release window",
            }
            metric = fact["stat_keys"][0]
            label = STAT_REGISTRY[metric].label.lower()
            unit = "percent" if "percentage" in metric else f"{label} per appearance"
            common: dict[str, Any] = dict(
                subject=subject,
                unit=unit,
                scope=scope,
                eligibility=eligibility,
                limitations=[
                    "Available archive and stated qualifiers only.",
                    "Extreme selection does not establish improvement or causation.",
                ],
            )
            fact_claims = []
            if fact["fact_type"] == "recent_vs_baseline":
                ordered = sorted(selected, key=lambda g: (g.game_date, g.nba_game_id))
                for key, subset in (("recent", ordered[-10:]), ("prior", ordered[:-10])):
                    subset_ids = {g.id for g in subset}
                    subset_receipts = [e for e in receipts if e.game_id in subset_ids]
                    value = fact["result"][key]
                    fact_claims.append(
                        self.claim(
                            **common,
                            metric=metric + ":average",
                            value=value,
                            games=subset,
                            evidence=subset_receipts,
                            sample=len(subset),
                            denominator=len(subset),
                            window={"kind": key},
                            statement=f"{player.full_name}: {value:.1f} {unit} across "
                            f"{len(subset)} {key} observed appearances.",
                        )
                    )
                baseline_ids = [c.claim_id for c in fact_claims]
                claim = self.claim(
                    **common,
                    metric=metric + ":delta",
                    value=fact["result"]["delta"],
                    games=ordered,
                    evidence=receipts,
                    statement=fact["statement"],
                    sample=len(ordered[-10:]),
                    denominator=len(ordered[-10:]),
                    baseline=baseline_ids,
                    window=fact["timeframe"],
                )
                fact_claims.append(claim)
            else:
                # Rank depends on ALL qualifiers, including games the leader did not play.
                population_ids = next(
                    ids
                    for window, ids in _windows(
                        [
                            {
                                "nba_game_id": g.nba_game_id,
                                "game_date": str(g.game_date),
                                "season_type": g.season_type,
                            }
                            for g in self.games
                            if g.nba_game_id
                        ]
                    )
                    if window == fact["timeframe"]
                )
                if not population_ids <= by_source.keys():
                    continue
                population_games = [by_source[key] for key in sorted(population_ids)]
                population_rows = [
                    (row, p)
                    for row, p in self.rows
                    if game_all[row.game_id].nba_game_id in population_ids and row.minutes > 0
                ]
                # The original catalog qualifies players at four appearances, and TS at 5 FGA.
                qualifiers = {}
                for row, p in population_rows:
                    qualifiers.setdefault(p.id, []).append(row)
                qualified = {
                    pid
                    for pid, rows in qualifiers.items()
                    if len(rows) >= 4
                    and (
                        metric != "true_shooting_percentage"
                        or sum(row.field_goals_attempted for row in rows) / len(rows) >= 5
                    )
                }
                all_receipts = [
                    self.receipt(game_all[row.game_id], row, p)
                    for row, p in population_rows
                    if p.id in qualified
                ]
                value = fact["result"]["value"]
                average = self.claim(
                    **common,
                    metric=metric + ":average",
                    value=value,
                    games=selected,
                    evidence=receipts,
                    sample=len(selected),
                    denominator=len(selected),
                    window=fact["timeframe"],
                    statement=f"{player.full_name}: {value:.1f} {unit} across "
                    f"{len(selected)} appearances in {fact['timeframe']['label']}.",
                )
                # Percentage calculations use shot opportunities, not appearances, as denominator.
                if metric == "true_shooting_percentage":
                    subject_rows = [row for row, p in population_rows if p.id == player.id]
                    denominator = 2 * (
                        sum(row.field_goals_attempted for row in subject_rows)
                        + 0.44 * sum(row.free_throws_attempted for row in subject_rows)
                    )
                    values = average.model_dump(exclude={"claim_id"})
                    values["denominator"] = denominator
                    self.claims.pop(average.claim_id)
                    average = VerifiedClaim.create(**values)
                    self.claims[average.claim_id] = average
                rank = self.claim(
                    subject=subject,
                    metric=metric + ":qualifier_rank",
                    value=1,
                    unit="rank",
                    games=population_games,
                    evidence=all_receipts,
                    statement=fact["statement"],
                    scope=scope,
                    sample=len(qualified),
                    denominator=len(qualified),
                    baseline=[average.claim_id],
                    window=fact["timeframe"],
                    eligibility=eligibility,
                    population="all eligible Knicks players in complete catalog window",
                )
                fact_claims = [average, rank]
                claim = rank
            candidate = Candidate(
                fact_id=fact["fingerprint"],
                fact_family=fact["fact_type"],
                subject_id=subject,
                metric=metric,
                window=fact["timeframe"],
                baseline=claim.baseline_claim_ids,
                claim_ids=[c.claim_id for c in fact_claims],
                selection_reason="Existing catalog eligibility and magnitude.",
                extreme_selected=True,
            )
            support = list(
                {
                    e.evidence_id: e
                    for c in fact_claims
                    for ref in c.supporting_evidence_ids
                    for e in [self.evidence[ref]]
                }.values()
            )
            pool.append((40 * fact["total_score"], candidate, fact_claims, support))
        families = set(self.state.get("delivered_families", []))
        pool.sort(key=lambda row: (row[1].fact_family in families, -row[0], row[1].fact_id))
        chosen = pool[:10]
        for _, candidate, _, _ in chosen:
            self.candidates[candidate.fact_id] = candidate
        return ToolResult(
            status="ok" if chosen else "no_matching_results",
            message="Choose a relevant candidate and explain its observed meaning."
            if chosen
            else "No undelivered eligible facts match this scope.",
            claims=[c for _, _, claims, _ in chosen for c in claims],
            evidence=list({e.evidence_id: e for _, _, _, es in chosen for e in es}.values()),
            candidates=[c for _, c, _, _ in chosen],
            scope=scope.model_dump(mode="json"),
        )

    async def canonical_discovery(self) -> ToolResult:
        """Search local records before admission without changing authoritative scope."""
        if self.discovery is not None:
            return self.discovery
        if self.scope is None:
            raise ValueError("Canonical discovery requires prepared request scope")
        scope = self.scope
        games = self.selected_games(scope) if self.season == self.release.season else []
        names = sorted({p.full_name for _, p in self.rows if p.id in scope.player_ids})[:3]
        teams = {scope.opponent_id} if scope.opponent_id else set()
        if scope.clarification_reason == "missing_conversation_game":
            teams.update(
                team_ids_in_text(" ".join(m["content"] for m in self.context[-10:])) - {"NYK"}
            )
        # Context team names are search terms only. They cannot establish the
        # game or make an unverified assistant account authoritative.
        anchors = names + sorted(teams)
        expansion = " OR ".join(json.dumps(value) for value in anchors)
        # Tool questions retain their existing cap. Only ordinary independently
        # resolved identities expand the user's bounded search query.
        query = self.question[: max(0, 1200 - len(expansion) - 4)]
        query += " OR " + expansion if expansion else ""
        try:
            async with asyncio.timeout(2):
                self.discovery = await self.search(
                    ToolCall(name="search_archive", question=query),
                    scope,
                    games,
                    local_only=True,
                    purpose="canonical_discovery",
                )
        except Exception as exc:
            record_search(
                {
                    "purpose": "canonical_discovery",
                    "status": "dependency_failure",
                    "release": self.release.version,
                    "question": self.question,
                    "query": query,
                    "filters": {**scope.planner_filters(), "game_ids": [g.id for g in games]},
                    "candidate_evidence_ids": [],
                    "returned_evidence_ids": [],
                    "lexical_evidence_ids": [],
                    "dense_evidence_ids": [],
                    "evidence": [],
                    "dense_failed": False,
                    "error_type": type(exc).__name__,
                }
            )
            self.discovery = ToolResult(
                status="dependency_failure",
                message="Local archive discovery is unavailable on this turn.",
            )
        for item in self.discovery.evidence:
            self.evidence[item.evidence_id] = item
            self.issued_evidence_ids.add(item.evidence_id)
        return self.discovery

    async def search(
        self,
        call: ToolCall,
        scope: ResolvedQuery,
        games: list[Game],
        *,
        local_only: bool = False,
        purpose: str = "analyst_search",
    ) -> ToolResult:
        filters: dict[str, Any] = scope.planner_filters()
        filters["game_ids"] = [g.id for g in games]
        filters["unanchored_game_reference"] = (
            scope.clarification_reason == "missing_conversation_game"
        )
        # One verified corpus backs both lexical retrieval and receipt admission.
        unit_records = (
            await build_archive_units(self.db, games, self.release.version) if games else []
        )
        lexical = (
            await search_archive_lexical(
                self.db,
                query=call.question,
                collections=["games", "box_scores", "reports", "possessions"],
                filters=filters,
                data_version=self.release.version,
                limit=20,
                unit_records=unit_records,
            )
            if games
            else []
        )
        dense, failure = [], False
        if games and not local_only and get_settings().rag_qdrant_enabled:
            try:
                dense = await asyncio.to_thread(
                    search_archive_vectors,
                    queries=[call.question],
                    collections=["games", "box_scores", "reports", "possessions"],
                    filters=filters,
                    data_version=self.release.version,
                    limit=20,
                    candidate_limit=20,
                )
            except Exception:
                failure = True
        found = fuse_archive_evidence(lexical, dense, limit=20, filters=filters)
        evidence = [
            Evidence(
                evidence_id=f"{self.release.version}:{e.evidence_id}",
                release_id=self.release.version,
                text=e.text,
                game_id=e.metadata.get("game_id"),
                source_name=e.metadata.get("source_name"),
                source_url=e.metadata.get("source_url"),
                metadata={
                    key: value
                    for key, value in e.metadata.items()
                    if key
                    not in {
                        "retrieval_sources",
                        "fusion_components",
                        "component_ranks",
                        "exact_match_fields",
                        "_index_embedding",
                        "chunk_id",
                    }
                },
            )
            for e in found
            if e.metadata.get("data_version") == self.release.version
            and (
                e.metadata.get("game_id") in {g.id for g in games}
                if not e.metadata.get("unit_type")
                else accepts_unit(
                    e.metadata,
                    unit_records=unit_records,
                    selected_game_ids={g.id for g in games},
                    player_ids=scope.player_ids,
                    periods=scope.periods,
                    version=self.release.version,
                )
                and e.text == e.metadata.get("text")
            )
        ]
        record_search(
            {
                "purpose": purpose,
                "status": "ok",
                "release": self.release.version,
                "question": self.question if local_only else call.question,
                "query": call.question,
                "filters": filters,
                "lexical_evidence_ids": [
                    f"{self.release.version}:{e.evidence_id}" for e in lexical
                ],
                "dense_evidence_ids": [f"{self.release.version}:{e.evidence_id}" for e in dense],
                "candidate_evidence_ids": [e.evidence_id for e in evidence],
                "returned_evidence_ids": [e.evidence_id for e in evidence[:5]],
                "evidence": [e.model_dump(mode="json") for e in evidence],
                "ranking": [
                    {
                        "evidence_id": f"{self.release.version}:{e.evidence_id}",
                        "score": e.score,
                        "retrieval_sources": e.metadata.get("retrieval_sources", []),
                        "fusion_components": e.metadata.get("fusion_components", []),
                        "component_ranks": e.metadata.get("component_ranks", {}),
                        "exact_match_fields": e.metadata.get("exact_match_fields", []),
                        "index_embedding": e.metadata.get("_index_embedding"),
                    }
                    for e in found
                    if f"{self.release.version}:{e.evidence_id}"
                    in {r.evidence_id for r in evidence}
                ],
                "dense_failed": failure,
            }
        )
        return ToolResult(
            status=("incomplete_coverage" if failure else "ok")
            if evidence
            else ("dependency_failure" if failure else "no_matching_results"),
            message="Retrieved examples only, never a season denominator. "
            + ("Vector retrieval unavailable." if failure else ""),
            evidence=evidence,
            scope={"release": self.release.version, **filters},
        )
