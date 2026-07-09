"""Local embedding helpers for RAG retrieval."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings

BGE_LARGE_DIMENSION = 1024


def _preferred_device() -> str | None:
    try:
        import torch
    except Exception:  # noqa: BLE001
        return None
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return None


@lru_cache(maxsize=1)
def _load_model():
    """Load the embedding model lazily so disabled paths have no startup cost."""
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    device = _preferred_device()
    if device:
        model = SentenceTransformer(settings.rag_embedding_model, device=device)
    else:
        model = SentenceTransformer(settings.rag_embedding_model)
    model.max_seq_length = min(model.max_seq_length, settings.rag_embedding_max_seq_length)
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed text with a cached local BGE model."""
    if not texts:
        return []
    settings = get_settings()
    vectors = _load_model().encode(
        texts,
        batch_size=settings.rag_embedding_batch_size,
        normalize_embeddings=True,
        convert_to_numpy=False,
        show_progress_bar=False,
    )
    return [list(map(float, vector)) for vector in vectors]
