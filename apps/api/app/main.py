"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, engine
from app.core.logging import configure_logging, get_logger
from app.core.seed_loader import seed_all
from app.models import Base
from app.models.game import Game


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    settings = get_settings()
    logger = get_logger("knicksiq.api")
    configure_logging()
    logger.info(
        "knicksiq.api.starting",
        environment=settings.environment,
        test_mode=settings.test_mode,
    )

    if settings.test_mode or settings.seed_on_startup:
        # In test mode we share an in-memory SQLite DB. Create the
        # schema up front so tests can use it without migrations.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSessionLocal() as session:
            game_count = (
                await session.execute(select(func.count()).select_from(Game))
            ).scalar_one()
            if game_count == 0:
                counts = await seed_all(session)
                logger.info("knicksiq.api.seeded", **counts)
            else:
                logger.info("knicksiq.api.seed_skipped", games=game_count)

    yield

    logger.info("knicksiq.api.stopping")
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="KnicksIQ API",
        description="KnicksIQ FastAPI backend — Knicks postgame intelligence platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
