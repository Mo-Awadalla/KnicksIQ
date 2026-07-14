"""Offline commands for deterministic release artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services.release_bundle import (
    build_bundle,
    load_release_bundle,
    read_bundle,
    validate_bundle,
)

from worker_app.core.db import AsyncSessionLocal


def build_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Validated release JSON")
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-unreviewed-reports", action="store_true")
    args = parser.parse_args()
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    sha256 = build_bundle(json.loads(args.source.read_text()), temporary)
    validation = validate_bundle(
        read_bundle(temporary, sha256),
        require_reviewed_reports=not args.allow_unreviewed_reports,
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {"path": str(args.output), "sha256": sha256, "validation": validation},
            sort_keys=True,
        )
    )


def validate_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--allow-unreviewed-reports", action="store_true")
    args = parser.parse_args()
    result = validate_bundle(
        read_bundle(args.bundle, args.sha256),
        require_reviewed_reports=not args.allow_unreviewed_reports,
    )
    print(json.dumps(result, sort_keys=True))


def load_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            result = await load_release_bundle(
                db, args.bundle, expected_sha256=args.sha256, activate=args.activate
            )
            print(json.dumps(result.__dict__, sort_keys=True))

    asyncio.run(run())
