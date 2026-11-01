"""Controlled, release-pinned analytics. Retrieval never supplies a denominator."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_context import admitted, capability_manifest, load_archive
from app.services.analyst_dispatch import execute_call
from app.services.analyst_player_stats import METRICS
from app.services.analyst_provenance import (
    ProvenanceCapture,
    game_projection,
    player_stat_projection,
)
from app.services.analyst_scope import (
    apply_inherited_scope,
    clarification,
    prior_scope,
    reclassify_with_subject,
)
from app.services.archive_clock import moment_from_question
from app.services.archive_retrieval import (
    RetrievalTrace,
    fuse_archive_evidence,
    ranked_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
from app.services.evidence_contracts import Candidate, Evidence, ToolCall, ToolResult, VerifiedClaim
from app.services.query_comparisons import group_games
from app.services.query_operations import (
    RANKING_OPERATIONS,
    REFERENTIAL_ASK,
    STREAK_OPERATIONS,
    is_record_request,
)
from app.services.query_resolution import ResolvedQuery, resolve_query
from sqlalchemy.ext.asyncio import AsyncSession


class AnalystTools:
    def __init__(
        self,
        db: AsyncSession,
        release: DatasetRelease,
        question: str,
        season: str,
        state: dict[str, Any],
    ):
        self.db, self.release, self.question, self.season = db, release, question, season
        self.state = state
        self.claims: dict[str, VerifiedClaim] = {}
        self.evidence: dict[str, Evidence] = {}
        self.candidates: dict[str, Candidate] = {}
        self.issued_evidence_ids: set[str] = set()
        self.provenance = ProvenanceCapture.from_settings(get_settings())
        self.retrieval_traces: list[dict[str, Any]] = []
        # Bound by the loop from the route's request id; a retrieval trace is never
        # recorded against a synthetic or empty id.
        self.request_id: str | None = None
        self.games: list[Game] = []
        self.rows: list[tuple[PlayerGameStat, Player]] = []
        self.scope: ResolvedQuery | None = None
        self.conferences: dict[str, str] = {}
        self.referential = bool(REFERENTIAL_ASK.search(question))
        self.different = bool(re.search(r"\bdifferent player\b", question, re.I))

    async def prepare(self) -> None:
        self.games, self.rows, self.conferences = await load_archive(self.db, self.release)
        self.scope = await resolve_query(
            self.db, self.question, intent="analyst", data_version=self.release.version
        )
        named_player = bool(self.scope.player_ids)
        prior = prior_scope(self.state, version=self.release.version, rows=self.rows)
        followup = bool(
            re.search(
                r"\b(he|him|his|that|another|different player)\b|^\s*(why|now|and|what about)",
                self.question,
                re.I,
            )
        )
        self.scope = apply_inherited_scope(
            self.scope,
            prior,
            question=self.question,
            followup=followup,
            different_player=self.different,
            referential=self.referential,
            games=self.games,
        )
        if not named_player and self.scope.player_ids:
            # This turn named no player, so the operation was decided without a subject.
            # The inherited player is verified state, so the decision is taken again with
            # it instead of keeping the statless premise it produced.
            self.scope = reclassify_with_subject(self.scope, self.question)
        self.scope = clarification(
            self.question,
            self.scope,
            sorted({p.full_name for _, p in self.rows}),
            different_player=self.different,
        )
        self.state["scope"] = self.scope.model_dump(mode="json")
        self.state["scope_origin"] = "user" if not followup else "verified_followup"
        # The raw question is not conversation authority; drop a legacy stored copy.
        self.state.pop("intent", None)
        # Immutable release references are revalidated for identity and integrity at admission.
        if self.state.get("release") == self.release.version:
            claims, evidence = admitted(
                self.state,
                version=self.release.version,
                permitted_games={g.id for g in self.selected_games(self.scope)},
                subjects={f"player:{pid}" for pid in self.scope.player_ids},
                different=self.different,
                another=bool(re.search(r"\b(another|one more)\b", self.question, re.I)),
            )
            self.claims.update(claims)
            self.evidence.update(evidence)
            self.issued_evidence_ids.update(evidence.keys())
        else:
            self.state["delivered_fact_ids"] = []
        self.state["release"] = self.release.version

    def manifest(self) -> dict[str, Any]:
        manifest = capability_manifest(self.release, self.games, self.rows, self.scope)
        collections = {item.metadata.get("document_collection") for item in self.evidence.values()}
        if "possessions" in collections:
            manifest["data_types"].append("play_by_play")
        if "reports" in collections:
            manifest["data_types"].append("reviewed_game_reports")
        return manifest

    def comparison_populations(self, scope: ResolvedQuery) -> dict[str, list[Game]]:
        """The games each typed comparison group selects, keyed by group identity."""
        spec = scope.comparison
        assert spec is not None
        return {
            group.key: group_games(spec, group, self.games, self.conferences)
            for group in spec.groups
        }

    def selected_games(self, scope: ResolvedQuery) -> list[Game]:
        if scope.comparison is not None:
            # The union of the groups is the complete considered population; it is never
            # used to answer a group, only to bound retrieval and prior-claim validation.
            union = {
                game.id: game
                for games in self.comparison_populations(scope).values()
                for game in games
            }
            return sorted(union.values(), key=lambda game: (game.game_date, game.id))
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
        return self._windowed(games, scope)

    @staticmethod
    def _windowed(games: list[Game], scope: ResolvedQuery) -> list[Game]:
        """Apply the requested first/last window once, over the filtered population."""
        if not scope.relative_game_count:
            return games
        count = scope.relative_game_count
        return games[:count] if scope.relative_game_position == "first" else games[-count:]

    def considered_games(self, scope: ResolvedQuery) -> list[Game]:
        """The population an operation ranks or counts.

        Counting wins must not first discard the losses that define the denominator, streaks
        scan wins and losses together because a win breaks a losing streak, and a both-outcome
        split needs every loss it is asked to compare. An operation that selects an extreme or
        counts across outcomes owns its population, so a game ID derived from its own wording
        is provisional; every other operation keeps an enclosing anchor the user asked for
        ("in their best win") as its population.
        """
        owns_population = (
            RANKING_OPERATIONS
            | STREAK_OPERATIONS
            | {
                "team_record",
                "win_count",
                "loss_count",
                "result_split",
            }
        )
        population_scope = scope
        if scope.operation in owns_population:
            population_scope = population_scope.model_copy(
                update={"game_ids": [], "game_result": None}
            )
        games = self.selected_games(population_scope)
        if scope.operation == "team_record" or (
            scope.operation is None and is_record_request(self.question)
        ):
            games = [g for g in games if g.status == "final" and g.home_score != g.away_score]
        return games

    @staticmethod
    def score(game: Game) -> tuple[int, int]:
        return (
            (game.home_score, game.away_score)
            if game.home_team_id == "NYK"
            else (game.away_score, game.home_score)
        )

    def receipt(
        self, game: Game, stat: PlayerGameStat | None = None, player: Player | None = None
    ) -> Evidence:
        identity = f"{self.release.version}:game:{game.id}"
        if stat is not None and player is not None:
            identity += f":player:{player.id}"
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
        if stat is not None and player is not None:
            data.update(
                subject_id=f"player:{player.id}",
                player=player.full_name,
                **{m: getattr(stat, m) for m in METRICS},
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
        if self.provenance.enabled:
            if stat is not None and player is not None:
                self.provenance.capture_row(
                    identity,
                    collection="player_game_stats",
                    canonical_id=f"box:{game.nba_game_id}:{player.nba_player_id}",
                    row=player_stat_projection(game, stat, player),
                    source_row_id=stat.id,
                )
            else:
                self.provenance.capture_row(
                    identity,
                    collection="games",
                    canonical_id=f"game:{game.nba_game_id}",
                    row=game_projection(game),
                    source_row_id=game.id,
                )
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
        operation: str | None = None,
        considered_game_ids: list[int] | None = None,
        filters: dict[str, Any] | None = None,
        population: str = "available release archive",
        numerator: float | int | None = None,
        decimals: int | None = None,
    ) -> VerifiedClaim:
        if operation is not None or considered_game_ids is not None:
            # Selection is not the complete population considered by the operation.
            eligibility = dict(
                eligibility
                or (
                    {"appearance": "minutes > 0"}
                    if subject.startswith("player:")
                    else {"game": "final archived Knicks game"}
                )
            )
            if operation is not None:
                eligibility["operation"] = operation
            if considered_game_ids is not None:
                eligibility["considered_game_ids"] = list(considered_game_ids)
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
                    # Preserve the measured total, not value * denominator.
                    "numerator": numerator if denominator is not None else None,
                    # Rounding bounds the verifier's arithmetic tolerance.
                    "value_decimals": decimals if denominator is not None else None,
                    # Preserve measured percentage ingredients.
                    "ingredients": {
                        key: value
                        for key, value in (eligibility or {}).items()
                        if key in {"made", "attempted"} and isinstance(value, int | float)
                    },
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
            }
            | (filters or {}),
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
            result = await execute_call(self, call)
            for item in result.evidence:
                self.evidence[item.evidence_id] = item
                self.issued_evidence_ids.add(item.evidence_id)
                self.issued_evidence_ids.update(item.metadata.get("source_evidence_ids", []))
            self.issued_evidence_ids.update(
                ref for c in result.claims for ref in c.supporting_evidence_ids
            )
            return result
        except Exception as exc:
            # Do not disclose provider/database errors or turn failure into absence.
            return ToolResult(
                status="dependency_failure",
                message=f"{call.name} unavailable",
                scope={"error_type": type(exc).__name__},
            )

    async def search(self, call: ToolCall, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        filters: dict[str, Any] = dict(scope.planner_filters())
        filters["game_ids"] = [g.id for g in games]
        moment = moment_from_question(call.question, scope.periods)
        if moment is not None:
            filters["event_clock"] = moment.as_filter()
        lexical = await search_archive_lexical(
            self.db,
            query=call.question,
            collections=["games", "box_scores", "reports", "possessions"],
            filters=filters,
            data_version=self.release.version,
            limit=20,
        )
        dense = []
        dense_status = "disabled"
        errors: tuple[str, ...] = ()
        traces: list[RetrievalTrace] = []
        if get_settings().rag_qdrant_enabled:
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
                dense_status = "ok"
            except Exception as exc:
                dense_status = "failed"
                errors = (f"dense_search_failed:{type(exc).__name__}",)
        else:
            errors = ("dense_disabled",)
        found = fuse_archive_evidence(
            lexical,
            dense,
            limit=20,
            trace=traces,
            data_version=self.release.version,
            request_id=self.request_id,
            errors=errors,
            dense_status=dense_status,
            lexical_limit=20,
            dense_limit=20,
        )
        allowed_games = {game.id for game in games}
        emitted = [
            item
            for item in found
            if item.metadata.get("data_version") == self.release.version
            and item.metadata.get("game_id") in allowed_games
        ]
        if traces:
            observed = replace(traces[-1], selected=ranked_evidence(emitted))
            self.retrieval_traces.append(observed.as_trace())
        evidence = [
            Evidence(
                evidence_id=f"{self.release.version}:{e.evidence_id}",
                release_id=self.release.version,
                text=e.text,
                game_id=e.metadata.get("game_id"),
                source_name=e.metadata.get("source_name"),
                source_url=e.metadata.get("source_url"),
                metadata=e.metadata,
            )
            for e in emitted
        ]
        failure = dense_status == "failed"
        return ToolResult(
            status=("incomplete_coverage" if failure else "ok")
            if evidence
            else ("dependency_failure" if failure else "no_matching_results"),
            message="Retrieved examples only, never a season denominator. "
            + ("Vector retrieval unavailable." if failure else ""),
            evidence=evidence,
            scope={"release": self.release.version, **filters},
        )
