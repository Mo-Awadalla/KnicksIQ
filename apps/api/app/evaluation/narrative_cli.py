"""CLI boundary for separately labelled, real document retrieval evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.evaluation.narrative_benchmark import NarrativeBenchmark, NarrativeError, load_benchmark
from app.evaluation.narrative_collection import collect_narrative
from app.evaluation.narrative_scoring import score_narrative
from app.evaluation.scoring_metrics import SEMANTIC_THRESHOLD

FIELDS = ("narrative_labels", "narrative_profile", "narrative_observations", "narrative_approval")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    for field in FIELDS:
        parser.add_argument("--" + field.replace("_", "-"), type=Path)


def labels_digest(args: argparse.Namespace) -> str | None:
    labels = getattr(args, "narrative_labels", None)
    configured = any(getattr(args, field, None) is not None for field in FIELDS)
    if labels is None:
        if configured:
            raise NarrativeError("Narrative evidence requires its frozen source labels")
        return None
    return hashlib.sha256(Path(labels).read_bytes()).hexdigest()


def load(args: argparse.Namespace, *, primary_identity_sha256: str) -> NarrativeBenchmark | None:
    if labels_digest(args) is None:
        return None
    if not getattr(args, "documents", None) or not getattr(args, "narrative_profile", None):
        raise NarrativeError("Narrative evidence requires --documents and --narrative-profile")
    return load_benchmark(
        Path(args.narrative_labels),
        Path(args.documents),
        Path(args.mapping),
        Path(args.narrative_profile),
        primary_identity_sha256=primary_identity_sha256,
        approval_path=(Path(args.narrative_approval) if args.narrative_approval else None),
    )


async def _collect(benchmark: NarrativeBenchmark, path: Path) -> None:
    engine = create_async_engine(get_settings().db_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await collect_narrative(benchmark, db, path)
    finally:
        await engine.dispose()


def evaluate(
    args: argparse.Namespace,
    *,
    primary_identity_sha256: str,
    collect: bool = False,
) -> dict[str, Any] | None:
    benchmark = load(args, primary_identity_sha256=primary_identity_sha256)
    if benchmark is None:
        if collect:
            raise NarrativeError("Real narrative collection requires source labels")
        return None
    observations = getattr(args, "narrative_observations", None)
    if observations is None:
        raise NarrativeError("Narrative scoring requires --narrative-observations")
    path = Path(observations)
    if collect:
        asyncio.run(_collect(benchmark, path))
    return score_narrative(benchmark, path, threshold=SEMANTIC_THRESHOLD)
