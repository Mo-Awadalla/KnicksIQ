"""Public analyst chat endpoints."""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.llm_planner import maybe_plan_query
from app.services.possession_chunks import chunk_evidence
from app.services.query_classifier import QueryClassifierResult, classify_query
from app.services.rag import SearchResult, search_possession_chunks, search_season_docs
from app.services.report_llm import get_llm_adapter
from app.services.table_rag import answer_table_question

router = APIRouter(prefix="/analysis", tags=["analysis"])

_WINDOW_SECONDS = 60
_requests_by_client: dict[str, deque[float]] = defaultdict(deque)


class AnalysisContextMessage(BaseModel):
    role: str
    content: str = Field(..., min_length=1, max_length=2000)


class AnalysisQueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    season: str = "2025-26"
    context: list[AnalysisContextMessage] = Field(default_factory=list)


class AnalysisCitation(BaseModel):
    type: str
    title: str
    game_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisQueryResponse(BaseModel):
    answer: str
    route: str | None = None
    classifier: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    citations: list[AnalysisCitation]
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    refused: bool = False


def _client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> None:
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return
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
    team_terms = ("knick", "nyk")
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
        "loss",
        "losing",
        "longest",
        "margin",
        "offense",
        "player",
        "playoff",
        "point",
        "possession",
        "quarter",
        "rebound",
        "record",
        "run",
        "score",
        "season",
        "shot",
        "streak",
        "stretch",
        "turnover",
        "win",
        "worst",
    )
    return any(term in q for term in team_terms) and any(
        term in q for term in basketball_terms
    )


def _looks_like_follow_up(question: str) -> bool:
    q = question.lower().strip()
    return (
        q.startswith(("what about", "how about", "why", "what happened then"))
        or q
        in {
            "that game",
            "those games",
            "that one",
            "tell me more",
            "explain",
            "nice",
        }
    )


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
    return settings.ai_provider.lower() not in {"mock", "none", "disabled"} and bool(
        settings.ai_api_key
    )


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
    return f"\n\nEvidence used: {len(evidence)} cached game row(s): {examples}{suffix}."


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
    return "\n\nEvidence used: " + "; ".join(notes) + "."


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

    system = (
        "You are KnicksIQ, a grounded Knicks analyst. Answer only from the provided "
        "cached game and document context. Do not use live, current, injury, trade, "
        "standings, or outside knowledge. If the context is insufficient, say so. "
        "If the classifier is counterfactual, provide a historical baseline and a "
        "clearly labeled hypothetical adjustment, not a full simulation. "
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
        return await get_llm_adapter(response_format_json=False).generate(system=system, user=user)
    except Exception:  # noqa: B110
        return None


async def _matching_games(
    db: AsyncSession, question: str, season: str
) -> list[Game]:
    stmt = (
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date.desc())
        .limit(10)
    )
    games = (await db.execute(stmt)).scalars().all()
    q = question.upper()
    team_hits = [g for g in games if g.home_team_id in q or g.away_team_id in q]
    return team_hits or games[:5]


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
    _rate_limit(request)
    question = req.question.strip()
    context_question = _contextual_question(question, req.context)
    if len(question) > settings.public_chat_max_prompt_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Question is too long",
        )
    current_supported = _is_supported_question(question)
    contextual_follow_up_supported = (
        _looks_like_follow_up(question) and _is_supported_question(context_question)
    )
    if not current_supported and not contextual_follow_up_supported:
        return AnalysisQueryResponse(
            refused=True,
            route=None,
            classifier={},
            evidence=[],
            warnings=[
                "Question asks outside cached Knicks season scope or live/current coverage."
            ],
            answer=(
                "I can only answer grounded questions about cached Knicks 2025-26 "
                "regular-season or playoff games. I do not have live, current, "
                "future, injury, trade, or non-Knicks coverage."
            ),
            citations=[],
            tool_calls=[],
        )
    effective_question = context_question if contextual_follow_up_supported else question

    tool_calls: list[dict[str, Any]] = []
    classifier = classify_query(effective_question)
    classifier_payload = classifier.as_dict()
    route = "table_rag" if classifier.is_aggregative else "retrieval_rag"
    t0 = time.perf_counter()
    planner = await maybe_plan_query(effective_question, classifier)
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
        return AnalysisQueryResponse(
            answer=table_result.answer + _table_evidence_note(table_result.evidence),
            route=route,
            classifier=classifier_payload,
            evidence=table_result.evidence,
            warnings=table_result.warnings,
            citations=citations,
            tool_calls=tool_calls,
        )

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
            await db.execute(
                select(GameEvent).where(GameEvent.game_id.in_(event_ready_game_ids)).limit(5)
            )
        ).scalars().all()
        if event_count:
            lines.append(
                "For event-level context, cached play-by-play is available for "
                f"{len(event_ready_game_ids)} matching game(s)."
            )

    for doc in docs:
        citations.append(
            AnalysisCitation(
                type="document",
                title=doc.title,
                game_id=doc.metadata.get("game_id"),
                source_name=doc.metadata.get("source_name"),
                source_url=doc.metadata.get("source_url"),
                metadata=doc.metadata,
            )
        )

    for evidence_item in possession_evidence[:3]:
        citations.append(
            AnalysisCitation(
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
            "Counterfactual answer is bounded to cached historical baseline plus a "
            "labeled hypothetical adjustment."
        )
    if not possession_evidence:
        warnings.append("No possession-level evidence matched the metadata filters.")

    if not lines:
        lines.append(
            "I could not find a cached Knicks game matching that question in the selected season."
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

    return AnalysisQueryResponse(
        answer=(answer or fallback_answer) + _possession_evidence_note(possession_evidence),
        route=route,
        classifier=classifier_payload,
        evidence=possession_evidence,
        warnings=warnings,
        citations=citations,
        tool_calls=tool_calls,
    )
