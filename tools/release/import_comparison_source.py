"""Import hash-pinned comparisons into an explicitly selected local SQLite store.

No provider, dense retrieval, canonical archive rewrite or target approval.
An empty store may be initialized only at a previously nonexistent path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import get_settings
from app.models import Base
from app.models.dataset_release import DatasetRelease
from app.services.comparison_sources import import_comparison_source
from app.services.rag_index import build_rag_artifacts
from app.services.release_bundle import load_release_bundle
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def run(args: argparse.Namespace) -> None:
    database = args.database.resolve()
    if args.initialize_empty:
        if database.exists():
            raise ValueError("Initialization refuses an existing database")
        database.parent.mkdir(parents=True, exist_ok=True)
    elif not database.is_file():
        raise ValueError("Database must exist or require --initialize-empty")
    args.out_dir.mkdir(parents=True, exist_ok=False)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    try:
        if args.initialize_empty:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            if args.initialize_empty:
                await load_release_bundle(
                    db, args.bundle, expected_sha256=args.bundle_sha256, activate=True
                )
            source = await import_comparison_source(
                db,
                bundle=args.bundle,
                trajectories=args.trajectories,
                source_review=args.source_review,
                comparisons=args.comparisons,
                expected_hashes={
                    name: getattr(args, f"{name}_sha256")
                    for name in ("bundle", "trajectories", "source_review", "comparisons")
                },
            )
            release = await db.get(DatasetRelease, source.release_id)
            assert release is not None
            get_settings().rag_qdrant_enabled = False
            manifest = await build_rag_artifacts(
                db, season=args.season, data_version=release.version, out_dir=args.out_dir / "index"
            )
            result = {
                "status": "IMPORTED_VERIFIED_COMPARISONS_LOCAL_ONLY",
                "data_version": release.version,
                "database": str(database),
                "release_id": release.id,
                "comparison_sha256": source.source_sha256,
                "source_review_sha256": source.source_review_sha256,
                "trajectories_sha256": source.trajectories_sha256,
                "bundle_sha256": source.bundle_sha256,
                "index_manifest": manifest,
                "gold_approved": False,
                "production_ready": False,
            }
            (args.out_dir / "import-result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--initialize-empty", action="store_true")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--season", required=True)
    for name in ("bundle", "trajectories", "source_review", "comparisons"):
        flag = name.replace("_", "-")
        parser.add_argument(f"--{flag}", type=Path, required=True)
        parser.add_argument(f"--{flag}-sha256", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
