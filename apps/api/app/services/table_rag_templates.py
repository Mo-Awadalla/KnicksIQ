"""Explicit aggregate templates for known TableRAG intents."""

from __future__ import annotations

from typing import Any


def template_intent(question: str) -> str | None:
    q = question.lower()
    if "losing streak" in q or ("longest" in q and "streak" in q):
        return "longest_losing_streak"
    if (
        "worst loss" in q
        or "biggest loss" in q
        or "lost by the most" in q
        or ("beat the knicks" in q and "most" in q)
    ):
        return "largest_loss_margin"
    if "best" in q or "biggest game" in q or "biggest win" in q or "biggest blowout" in q:
        return "largest_win_margin"
    if "record" in q or "wins" in q or "losses" in q:
        return "record"
    if "average" in q or "avg" in q or "per game" in q:
        return "points_average"
    if "total" in q or "how many" in q:
        return "points_total"
    return None


def polars_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return common aggregate values with Polars when available."""
    if not rows:
        return None
    try:
        import polars as pl
    except ImportError:
        return None
    frame = pl.DataFrame(rows)
    return {
        "games": int(frame.height),
        "wins": int(frame.filter(pl.col("knicks_win")).height),
        "losses": int(frame.filter(~pl.col("knicks_win")).height),
        "points_for": int(frame["knicks_score"].sum()),
        "points_against": int(frame["opponent_score"].sum()),
        "avg_for": float(frame["knicks_score"].mean()),
        "avg_against": float(frame["opponent_score"].mean()),
    }
