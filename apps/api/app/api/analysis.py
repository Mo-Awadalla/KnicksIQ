"""Public analyst chat endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.schemas.analytics import AnalyticsPayload
from app.services.llm_planner import maybe_plan_query
from app.services.player_analytics import answer_player_question
from app.services.possession_chunks import chunk_evidence
from app.services.qdrant_client import is_qdrant_healthy
from app.services.query_classifier import QueryClassifierResult, classify_query
from app.services.rag import SearchResult, search_possession_chunks, search_season_docs
from app.services.releases import restrict_to_active_release
from app.services.report_llm import get_llm_adapter
from app.services.runtime_store import (
    answer_cache_key,
    enforce_redis_limits,
    get_cached_answer,
    reserve_ai_budget,
    set_cached_answer,
)
from app.services.table_rag import answer_table_question
from app.services.team_aliases import team_ids_in_text

router = APIRouter(prefix="/analysis", tags=["analysis"])

_WINDOW_SECONDS = 60
_requests_by_client: dict[str, deque[float]] = defaultdict(deque)
_daily_requests_by_client: dict[str, deque[float]] = defaultdict(deque)


class AnalysisContextMessage(BaseModel):
    role: str
    content: str = Field(..., min_length=1, max_length=2000)


class AnalysisQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1200)
    season: str = "2025-26"
    context: list[AnalysisContextMessage] = Field(default_factory=list, max_length=4)


class AnalysisCitation(BaseModel):
    claim: str
    type: str
    title: str
    game_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisQueryResponse(BaseModel):
    answer: str
    route: str | None = Field(default=None, exclude=get_settings().is_production)
    classifier: dict[str, Any] = Field(default_factory=dict, exclude=get_settings().is_production)
    evidence: list[dict[str, Any]] = Field(
        default_factory=list, exclude=get_settings().is_production
    )
    warnings: list[str] = Field(default_factory=list)
    citations: list[AnalysisCitation]
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list, exclude=get_settings().is_production
    )
    refused: bool = False
    degraded: bool = False
    data_version: str = "unreleased"
    request_id: str = ""
    analytics: AnalyticsPayload | None = None


def _client_id(request: Request) -> str:
    # Uvicorn resolves trusted proxy headers before constructing Request.client.
    # Never consume X-Forwarded-For directly here: a caller-controlled header
    # would let one client manufacture unlimited rate-limit identities.
    ip = request.client.host if request.client else "unknown"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return hmac.new(
        getattr(get_settings(), "ip_hash_secret", "test-secret").encode(),
        f"{day}:{ip}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def _rate_limit(request: Request) -> bool:
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return False
    client = _client_id(request)
    now = time.monotonic()
    bucket = _requests_by_client[client]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= settings.public_chat_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    bucket.append(now)
    day_bucket = _daily_requests_by_client[client]
    while day_bucket and now - day_bucket[0] > 86_400:
        day_bucket.popleft()
    if len(day_bucket) >= getattr(settings, "public_chat_rate_limit_per_day", 100):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily rate limit exceeded",
        )
    day_bucket.append(now)
    try:
        return await enforce_redis_limits(client)
    except ValueError as exc:
        label = "Daily" if str(exc) == "day" else "Minute"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{label} rate limit exceeded",
        ) from exc


def _is_supported_question(question: str) -> bool:
    q = question.lower()
    blocked = (
        "algorithm",
        "coding",
        "compiler",
        "leetcode",
        "programming",
        "python",
        "today",
        "tonight",
        "tomorrow",
        "next game",
        "live",
        "injury",
        "trade",
        "standings",
        "yankees",
        "mets",
        "giants",
        "nets",
        "lakers",
        "warriors",
        "two sum",
    )
    if any(term in q for term in blocked):
        return False
    team_terms = (
        "knick",
        "nyk",
        "brunson",
        "towns",
        "bridges",
        "anunoby",
        "hart",
        "robinson",
        "mcbride",
        "boston",
        "celtics",
        "toronto",
        "raptors",
        "atlanta",
        "hawks",
        "chicago",
        "bulls",
        "charlotte",
        "hornets",
    )
    basketball_terms = (
        "against",
        "assist",
        "average",
        "beat",
        "bench",
        "best",
        "biggest",
        "defense",
        "game",
        "lineup",
        "led",
        "lead",
        "loss",
        "lose",
        "lost",
        "losing",
        "longest",
        "margin",
        "offense",
        "player",
        "playoff",
        "point",
        "possession",
        "receipt",
        "quarter",
        "rebound",
        "record",
        "run",
        "score",
        "season",
        "shot",
        "steal",
        "streak",
        "stretch",
        "swing",
        "turnover",
        "win",
        "worst",
        "data",
    )
    broad_archive_terms = (
        "last game",
        "4th quarter",
        "fourth quarter",
        "their biggest win",
        "their best win",
        "their biggest game",
        "their record",
        "they win",
        "they lose",
        "they lost",
        "they score",
        "who led",
        "most assists",
        "big leads",
        "comeback",
        "bench",
        "clutch",
        "shoot well",
        "from three",
        "wildest swings",
        "not in the data",
    )
    return (
        any(term in q for term in team_terms) and any(term in q for term in basketball_terms)
    ) or any(term in q for term in broad_archive_terms)


def _requires_explicit_refusal(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(r"\b(?:202[7-9]|20[3-9]\d)(?:-\d{2}-\d{2})?\b", q)
        or re.search(r"\b2026-(?:0[7-9]|1[0-2])-\d{2}\b", q)
        or re.search(r"\bwill\b", q)
        or any(
            term in q
            for term in (
                "today",
                "tonight",
                "tomorrow",
                "next game",
                "upcoming",
                "live",
                "injury",
                "current injury",
                "injury status",
                "injured",
                "trade",
                "will he",
                "will they",
                "will the knicks",
                "future",
                "next season",
            )
        )
    )


def _looks_like_follow_up(question: str) -> bool:
    q = question.lower().strip()
    return q.startswith(("what about", "how about", "why", "what happened then")) or q in {
        "that game",
        "those games",
        "that one",
        "tell me more",
        "explain",
        "nice",
    }


def _score_line(game: Game) -> str:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    result = "beat" if knicks_score > opponent_score else "lost to"
    return f"On {game.game_date}, the Knicks {result} {opponent} {knicks_score}-{opponent_score}."


def _llm_enabled() -> bool:
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return False
    if settings.ai_provider.lower() in {"mock", "none", "disabled"} or not settings.ai_api_key:
        return False
    allowed_models = getattr(settings, "openrouter_allowed_models", [])
    return not allowed_models or (settings.ai_chat_model in allowed_models)


def _analysis_context(
    *,
    question: str,
    season: str,
    games: list[Game],
    docs: list[SearchResult],
    evidence: list[dict[str, Any]] | None = None,
    classifier: QueryClassifierResult | None = None,
    chat_context: list[AnalysisContextMessage] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "season": season,
        "classifier": classifier.as_dict() if classifier else {},
        "chat_context": [
            {"role": item.role, "content": item.content}
            for item in (chat_context or [])[-6:]
            if item.role in {"user", "assistant"}
        ],
        "games": [
            {
                "game_id": game.id,
                "date": str(game.game_date),
                "home_team_id": game.home_team_id,
                "away_team_id": game.away_team_id,
                "home_score": game.home_score,
                "away_score": game.away_score,
                "season_type": game.season_type,
                "data_status": game.data_status,
                "summary": _score_line(game),
            }
            for game in games[:5]
        ],
        "documents": [
            {
                "title": doc.title,
                "text": doc.text,
                "metadata": doc.metadata,
            }
            for doc in docs[:3]
        ],
        "evidence": evidence or [],
    }


def _table_evidence_note(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    examples = ", ".join(
        f"{item['date']} vs {item['opponent']} ({item['score']['NYK']}-"
        f"{item['score'][item['opponent']]})"
        for item in evidence[:3]
    )
    suffix = f"; {len(evidence) - 3} more" if len(evidence) > 3 else ""
    return f"\n\nKey evidence\n- {len(evidence)} available Knicks game(s): {examples}{suffix}."


def _possession_evidence_note(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    notes: list[str] = []
    for item in evidence[:3]:
        first_row = next(
            (row for row in item.get("rows", []) if row.get("description")),
            None,
        )
        description = f" - {first_row['description']}" if first_row else ""
        notes.append(
            f"{item['date']} Q{item['period_window'][0]} "
            f"{item['clock_window'][0]}-{item['clock_window'][1]}{description}"
        )
    return "\n\nReceipts\n" + "\n".join(f"- {note}" for note in notes)


def _format_answer(
    *,
    direct_answer: str,
    evidence_note: str = "",
    limitation_note: str | None = None,
) -> str:
    sections = [f"Short answer\n{direct_answer.strip()}"]
    if evidence_note:
        sections.append(evidence_note.strip())
    if limitation_note:
        sections.append(f"Limitation\n{limitation_note.strip()}")
    return "\n\n".join(sections)


def _unknown_data_question(question: str) -> bool:
    q = question.lower()
    return "not in the data" in q or "not in knicksiq" in q


def _retrieval_limitation_note(question: str) -> str | None:
    q = question.lower()
    if _unknown_data_question(question):
        return (
            "I can only speak to the games currently in KnicksIQ. I do not have "
            "enough available season data to answer about a game outside that set."
        )
    if (
        ("who led" in q and any(term in q for term in ("scoring", "points", "assists", "rebounds")))
        or "most assists" in q
        or "most rebounds" in q
    ):
        return (
            "The available season data does not include complete player box-score "
            "leader tables for that category."
        )
    if any(term in q for term in ("bench", "defense", "rebound", "from three", "shoot well")):
        return (
            "The available season data has scores and play-by-play receipts, but not "
            "complete team/player split tables for that claim."
        )
    if any(term in q for term in ("dominated", "clutch", "blow any big leads", "big leads")):
        return (
            "The available play-by-play can show matching moments, but it is not "
            "complete enough to rank or prove that broader claim confidently."
        )
    return None


async def _generate_llm_answer(
    *,
    question: str,
    season: str,
    games: list[Game],
    docs: list[SearchResult],
    evidence: list[dict[str, Any]] | None = None,
    classifier: QueryClassifierResult | None = None,
    chat_context: list[AnalysisContextMessage] | None = None,
) -> str | None:
    if not _llm_enabled():
        return None
    if not await reserve_ai_budget():
        return None

    system = (
        "You are KnicksIQ, a grounded Knicks analyst. Answer only from the provided "
        "available Knicks game and document context. Do not use live, current, injury, trade, "
        "standings, or outside knowledge. If the context is insufficient, say so. "
        "If the classifier is counterfactual, provide a historical baseline and a "
        "clearly labeled hypothetical adjustment, not a full simulation. "
        "Do not use backend terms like RAG, vector search, embeddings, chunks, Qdrant, "
        "lexical retrieval, seeded data, or cached. Structure the answer as: "
        "Short answer, Key evidence, Receipts, and Limitation only when needed. "
        "Keep the answer concise and mention concrete dates, opponents, scores, "
        "runs, stretches, or play-by-play details when present."
    )
    user = json.dumps(
        _analysis_context(
            question=question,
            season=season,
            games=games,
            docs=docs,
            evidence=evidence,
            classifier=classifier,
            chat_context=chat_context,
        )
    )
    try:
        answer = await get_llm_adapter(response_format_json=False).generate(
            system=system, user=user
        )
        canonical_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", user))
        answer_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", answer))
        if not answer_numbers.issubset(canonical_numbers):
            return None
        ignored_phrases = {"short answer", "key evidence"}
        named_entities = {
            match.group(0).lower()
            for match in re.finditer(r"\b[A-Z][a-z'-]+ [A-Z][a-z'-]+\b", answer)
        } - ignored_phrases
        if any(entity not in user.lower() for entity in named_entities):
            return None
        return answer
    except Exception:  # noqa: B110
        return None


async def _matching_games(db: AsyncSession, question: str, season: str) -> list[Game]:
    stmt = (
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date.desc())
    )
    stmt = restrict_to_active_release(stmt)
    games = (await db.execute(stmt)).scalars().all()
    opponent_ids = team_ids_in_text(question) - {"NYK"}
    return [game for game in games if opponent_ids & {game.home_team_id, game.away_team_id}]


async def _active_data_version(db: AsyncSession) -> str:
    version = (
        await db.execute(select(DatasetRelease.version).where(DatasetRelease.status == "active"))
    ).scalar_one_or_none()
    return version or ("test-seed" if getattr(get_settings(), "test_mode", False) else "unreleased")


def _contextual_question(question: str, context: list[AnalysisContextMessage]) -> str:
    recent = [
        f"{item.role}: {item.content.strip()}"
        for item in context[-6:]
        if item.role in {"user", "assistant"} and item.content.strip()
    ]
    if not recent:
        return question
    return "\n".join([*recent, f"user: {question}"])


@router.post("/query", response_model=AnalysisQueryResponse)
async def query_analysis(
    req: AnalysisQueryRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalysisQueryResponse:
    settings = get_settings()
    redis_degraded = await _rate_limit(request)
    response_metadata = {
        "request_id": getattr(request.state, "request_id", ""),
        "data_version": await _active_data_version(db),
        "degraded": redis_degraded
        or (getattr(settings, "rag_qdrant_enabled", False) and not is_qdrant_healthy()),
    }
    question = req.question.strip()
    context_question = _contextual_question(question, req.context)
    if len(question) > settings.public_chat_max_prompt_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Question is too long",
        )
    if _requires_explicit_refusal(question):
        return AnalysisQueryResponse(
            **response_metadata,
            refused=True,
            route=None,
            classifier={},
            evidence=[],
            warnings=[
                "Question asks outside the available Knicks season data or live/current coverage."
            ],
            answer=(
                "Short answer\n"
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games. I do not have live, current, future, "
                "injury, or trade coverage."
            ),
            citations=[],
            tool_calls=[],
        )
    analytics_t0 = time.perf_counter()
    player_answer = await answer_player_question(
        db,
        question=question,
        season=req.season,
        context=[item.model_dump() for item in req.context],
    )
    if player_answer is not None:
        analytics_payload = AnalyticsPayload.model_validate(player_answer.analytics)
        response = AnalysisQueryResponse(
            **response_metadata,
            answer=player_answer.answer,
            route="table_rag",
            classifier={"kind": "player_intelligence", "is_aggregative": True},
            evidence=[],
            warnings=player_answer.warnings,
            citations=[AnalysisCitation.model_validate(item) for item in player_answer.citations],
            tool_calls=[
                {
                    "tool": "player_analytics",
                    "latency_ms": int((time.perf_counter() - analytics_t0) * 1000),
                    "result_count": len(analytics_payload.results),
                }
            ],
            analytics=analytics_payload,
        )
        return response
    current_supported = _is_supported_question(question)
    contextual_follow_up_supported = _looks_like_follow_up(question) and _is_supported_question(
        context_question
    )
    if not current_supported and not contextual_follow_up_supported:
        response = AnalysisQueryResponse(
            **response_metadata,
            refused=True,
            route=None,
            classifier={},
            evidence=[],
            warnings=[
                "Question asks outside the available Knicks season data or live/current coverage."
            ],
            answer=(
                "Short answer\n"
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games. I do not have live, current, "
                "future, injury, trade, or non-Knicks coverage."
            ),
            citations=[],
            tool_calls=[],
        )
        return response
    effective_question = context_question if contextual_follow_up_supported else question

    cache_key = None
    if not req.context:
        cache_key = answer_cache_key(
            question,
            response_metadata["data_version"],
            getattr(settings, "ai_chat_model", "deterministic"),
        )
        cached = await get_cached_answer(cache_key)
        if cached:
            cached["request_id"] = response_metadata["request_id"]
            cached["degraded"] = response_metadata["degraded"]
            return AnalysisQueryResponse.model_validate(cached)

    tool_calls: list[dict[str, Any]] = []
    classifier = classify_query(effective_question)
    classifier_payload = classifier.as_dict()
    route = "table_rag" if classifier.is_aggregative else "retrieval_rag"
    t0 = time.perf_counter()
    named_opponent_ids = team_ids_in_text(effective_question) - {"NYK"}
    planner = None if named_opponent_ids else await maybe_plan_query(effective_question, classifier)
    if planner:
        tool_calls.append(
            {
                "tool": "llm_planner",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": 1,
            }
        )
        route = planner.route
        classifier_payload.update(planner.as_dict())
    warnings: list[str] = []

    if _unknown_data_question(question):
        limitation = _retrieval_limitation_note(question)
        response = AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(
                direct_answer=(
                    "I can only answer from the games currently in KnicksIQ, and that "
                    "question does not identify an available game."
                ),
                limitation_note=limitation,
            ),
            route=route,
            classifier=classifier_payload,
            evidence=[],
            warnings=[limitation] if limitation else [],
            citations=[],
            tool_calls=tool_calls,
        )
        if cache_key:
            await set_cached_answer(cache_key, response.model_dump(mode="json"))
        return response

    if route == "table_rag":
        t0 = time.perf_counter()
        table_result = await answer_table_question(db, effective_question, season=req.season)
        tool_calls.append(
            {
                "tool": "table_rag",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": len(table_result.evidence),
            }
        )
        citations = [
            AnalysisCitation(
                claim=table_result.answer,
                type="game",
                title=f"{item['date']} NYK vs {item['opponent']}",
                game_id=item["game_id"],
                source_name=item.get("source_name"),
                source_url=item.get("source_url"),
                metadata={
                    "season_type": item["season_type"],
                    "data_status": item["data_status"],
                    "score": item["score"],
                },
            )
            for item in table_result.evidence[:5]
        ]
        response = AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(
                direct_answer=table_result.answer,
                evidence_note=_table_evidence_note(table_result.evidence),
                limitation_note=" ".join(table_result.warnings) if table_result.warnings else None,
            ),
            route=route,
            classifier=classifier_payload,
            evidence=table_result.evidence,
            warnings=table_result.warnings,
            citations=citations,
            tool_calls=tool_calls,
        )
        if cache_key:
            await set_cached_answer(cache_key, response.model_dump(mode="json"))
        return response

    t0 = time.perf_counter()
    games = await _matching_games(db, effective_question, req.season)
    tool_calls.append(
        {
            "tool": "get_games",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(games),
        }
    )

    t0 = time.perf_counter()
    docs = await search_season_docs(db, effective_question, season=req.season, limit=3)
    matching_game_ids = {game.id for game in games}
    if matching_game_ids:
        docs = [doc for doc in docs if int(doc.metadata.get("game_id") or -1) in matching_game_ids]
    tool_calls.append(
        {
            "tool": "search_season_docs",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(docs),
        }
    )

    t0 = time.perf_counter()
    retrieval_trace: list[dict[str, Any]] = []
    possession_chunks, retrieval_filters = await search_possession_chunks(
        db,
        effective_question,
        season=req.season,
        limit=getattr(settings, "rag_retrieval_limit", 5),
        trace=retrieval_trace,
    )
    possession_evidence = [chunk_evidence(chunk) for chunk in possession_chunks]
    tool_calls.extend(retrieval_trace)
    tool_calls.append(
        {
            "tool": "search_possession_chunks",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(possession_chunks),
            "filters": retrieval_filters.as_dict(),
        }
    )

    citations: list[AnalysisCitation] = []
    lines: list[str] = []
    for game in games[:3]:
        lines.append(_score_line(game))
        citations.append(
            AnalysisCitation(
                claim=_score_line(game),
                type="game",
                title=f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
                game_id=game.id,
                source_name=game.source_name,
                source_url=game.source_url,
                metadata={
                    "data_status": game.data_status,
                    "season_type": game.season_type,
                    "source_game_id": game.source_game_id,
                },
            )
        )

    event_ready_game_ids = {g.id for g in games if g.data_status != "summary_only"}
    if event_ready_game_ids and any(
        term in question.lower() for term in ("run", "stretch", "play", "quarter")
    ):
        event_count = (
            (
                await db.execute(
                    select(GameEvent).where(GameEvent.game_id.in_(event_ready_game_ids)).limit(5)
                )
            )
            .scalars()
            .all()
        )
        if event_count:
            lines.append(
                "Event-level play-by-play is available for "
                f"{len(event_ready_game_ids)} matching game(s)."
            )

    for doc in docs:
        citations.append(
            AnalysisCitation(
                claim=doc.text[:240],
                type="document",
                title=doc.title,
                game_id=doc.metadata.get("game_id"),
                source_name=doc.metadata.get("source_name"),
                source_url=doc.metadata.get("source_url"),
                metadata=doc.metadata,
            )
        )

    for evidence_item in possession_evidence[:3]:
        first_description = next(
            (str(row["description"]) for row in evidence_item["rows"] if row.get("description")),
            "Possession-level play-by-play evidence",
        )
        citations.append(
            AnalysisCitation(
                claim=first_description,
                type="possession",
                title=(
                    f"{evidence_item['date']} "
                    f"Q{evidence_item['period_window'][0]} "
                    f"{evidence_item['clock_window'][0]}-{evidence_item['clock_window'][1]}"
                ),
                game_id=evidence_item["game_id"],
                metadata={
                    "possession_id": evidence_item["possession_id"],
                    "players": evidence_item["players"],
                    "teams": evidence_item["teams"],
                    "row_count": len(evidence_item["rows"]),
                },
            )
        )

    if classifier.kind == "counterfactual":
        warnings.append(
            "Counterfactual answer is bounded to the available historical baseline plus a "
            "labeled hypothetical adjustment."
        )
    if not possession_evidence:
        warnings.append("No possession-level evidence matched the available season data.")

    if _unknown_data_question(question):
        lines = [
            "I can only answer from the games currently in KnicksIQ, and that question "
            "does not identify an available game."
        ]
    elif not lines:
        lines.append(
            "I could not find an available Knicks game matching that question in "
            "the selected season."
        )

    fallback_answer = " ".join(lines)
    answer = await _generate_llm_answer(
        question=question,
        season=req.season,
        games=list(games),
        docs=docs,
        evidence=possession_evidence[:3],
        classifier=classifier,
        chat_context=req.context,
    )
    if answer:
        tool_calls.append({"tool": "llm_generate", "model": get_settings().ai_chat_model})

    limitation_note = None
    retrieval_limitation = _retrieval_limitation_note(question)
    if retrieval_limitation:
        warnings.append(retrieval_limitation)
        limitation_note = retrieval_limitation
    elif warnings:
        limitation_note = " ".join(warnings)
    elif not answer and not possession_evidence:
        limitation_note = (
            "The available Knicks game data was not detailed enough to support a more "
            "specific answer."
        )

    response = AnalysisQueryResponse(
        **response_metadata,
        answer=(
            (
                answer
                if "Receipts" in answer or not possession_evidence
                else answer + _possession_evidence_note(possession_evidence)
            )
            if answer
            else _format_answer(
                direct_answer=fallback_answer,
                evidence_note=_possession_evidence_note(possession_evidence),
                limitation_note=limitation_note,
            )
        ),
        route=route,
        classifier=classifier_payload,
        evidence=possession_evidence,
        warnings=warnings,
        citations=citations,
        tool_calls=tool_calls,
    )
    if cache_key:
        await set_cached_answer(cache_key, response.model_dump(mode="json"))
    return response
