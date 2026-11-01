"""Local embedding helpers for RAG retrieval."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings

BGE_LARGE_DIMENSION = 1024


def _preferred_device() -> str | None:
    configured = get_settings().rag_embedding_device
    if configured:
        return configured
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
    current_max_length = model.max_seq_length or settings.rag_embedding_max_seq_length
    model.max_seq_length = min(current_max_length, settings.rag_embedding_max_seq_length)
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
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    if hasattr(vectors, "tolist"):
        return vectors.tolist()
    return [list(map(float, vector)) for vector in vectors]


def embedding_profile() -> dict[str, str | int]:
    settings = get_settings()
    model = _load_model()
    first = model[0]
    config = getattr(first.auto_model, "config", None)
    revision = getattr(config, "_commit_hash", None)
    dimension = model.get_sentence_embedding_dimension()
    sequence_length = model.max_seq_length
    if not revision or not isinstance(dimension, int) or not isinstance(sequence_length, int):
        raise ValueError("Resolved embedding revision, dimension and sequence length are required")
    return {
        "model": settings.rag_embedding_model,
        "revision": str(revision),
        "dimension": dimension,
        "max_sequence_length": sequence_length,
    }
