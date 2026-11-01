"""Private shadow verification: own session, own turn scope, after the client's facts."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease

logger = logging.getLogger(__name__)


def _schedule_shadow_verification(
    background_tasks: BackgroundTasks,
    *,
    request_id: str,
    question: str,
    season: str,
    data_version: str,
    state: dict[str, Any],
    context: list[dict[str, str]],
) -> None:
    """Queue the trial once, for one committed new turn, after the response is sent.

    The turn scope is copied so the verification cannot reach the loop or session that
    produced the committed answer, and it never commits anything back.
    """
    background_tasks.add_task(
        _verify_shadow_turn,
        request_id=request_id,
        question=question,
        season=season,
        data_version=data_version,
        state=copy.deepcopy(state),
        context=copy.deepcopy(context),
    )


async def _verify_shadow_turn(
    *,
    request_id: str,
    question: str,
    season: str,
    data_version: str,
    state: dict[str, Any],
    context: list[dict[str, str]],
) -> None:
    """Run the reserved, validated model path in private and record only diagnostics."""
    from app.services.analyst_loop import AnalystLoop
    from app.services.analyst_tools import AnalystTools

    started = time.monotonic()
    settings = get_settings()
    try:
        # Bounded lifecycle: a provider that never answers cannot pin this task open.
        async with asyncio.timeout(settings.analyst_deadline_seconds):
            async with AsyncSessionLocal() as db:
                release = (
                    await db.execute(
                        select(DatasetRelease).where(
                            DatasetRelease.status == "active",
                            DatasetRelease.validation_passed.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if release is None or release.version != data_version:
                    logger.info(
                        "analyst_shadow_skipped",
                        extra={"request_id": request_id, "reason": "release_changed"},
                    )
                    return
                tools = AnalystTools(db, release, question, season, state)
                tools.request_id = request_id
                await tools.prepare()
                loop = AnalystLoop(tools, context, started=started)
                loop.request_id = request_id
                result = await loop.run(allow_model=True)
                logger.info(
                    "analyst_shadow_verification",
                    extra={
                        "sampled": True,
                        "validated": result["llm_validated"],
                        "outcome": result["outcome"],
                        "degraded": result["degraded"],
                        "model_calls": loop.calls,
                        "tool_rounds": loop.rounds,
                        "data_version": data_version,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "model": settings.ai_chat_model,
                        "prompt_version": settings.analysis_prompt_version,
                    },
                )
    except TimeoutError:
        logger.info(
            "analyst_shadow_timeout",
            extra={
                "request_id": request_id,
                "data_version": data_version,
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
        )
    except asyncio.CancelledError:
        logger.info("analyst_shadow_cancelled", extra={"request_id": request_id})
        raise
    except Exception as exc:  # noqa: BLE001
        # Diagnostics stay private and content-free: a verification failure is not an outage.
        logger.warning(
            "analyst_shadow_failed",
            extra={"request_id": request_id, "error_type": type(exc).__name__},
        )
