"""Tool-call logging.

The MCP server logs every tool invocation to the `tool_calls` table
in the API's database. This gives the API and dashboard a complete
record of which tools the LLM used, with what inputs, and how
long they took.

For Phase 4 we keep this in-memory via Python's logging module —
persistence to the `tool_calls` table arrives in a later phase.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("knicksiq.mcp")


@contextmanager
def tool_call(name: str, **params: Any):
    """Context manager that logs a tool call's start, end, and duration."""
    call_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    logger.info("tool_call.start", extra={"id": call_id, "tool": name, "params": params})
    error: str | None = None
    try:
        yield call_id
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        logger.exception(
            "tool_call.error",
            extra={"id": call_id, "tool": name, "error": error},
        )
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "tool_call.end",
            extra={
                "id": call_id,
                "tool": name,
                "duration_ms": duration_ms,
                "status": "error" if error else "ok",
            },
        )
