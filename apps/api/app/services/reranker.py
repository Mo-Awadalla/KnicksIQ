"""Optional local cross-encoder reranking for hybrid RAG candidates."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class TextCandidate(Protocol):
    text: str


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(get_settings().rag_reranker_model)


def rerank_candidates[T](
    query: str,
    candidates: list[T],
    *,
    top_n: int,
    model=None,
) -> list[T]:
    if not candidates or top_n <= 0:
        return []
    try:
        scorer = model or _load_model()
        pairs = [(query, getattr(candidate, "text", "")) for candidate in candidates]
        scores = scorer.predict(pairs)
        ranked = sorted(
            zip(candidates, scores, range(len(candidates)), strict=True),
            key=lambda item: (-float(item[1]), item[2]),
        )
        return [candidate for candidate, _score, _idx in ranked[:top_n]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("reranker_failed", exc_info=exc)
        return candidates[:top_n]
