"""Load the already-approved archive into the isolated Docker staging database."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, engine
from app.services.release_bundle import load_release_bundle

APPROVED_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"


async def main() -> None:
    settings = get_settings()
    if settings.environment != "staging" or urlsplit(settings.db_url).hostname != "postgres":
        raise RuntimeError("This initializer is only for the local Docker staging database")
    try:
        async with AsyncSessionLocal() as session:
            result = await load_release_bundle(
                session,
                Path("/staging/archive.json.gz"),
                expected_sha256=APPROVED_SHA256,
                activate=True,
            )
        print(json.dumps(asdict(result), sort_keys=True))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
