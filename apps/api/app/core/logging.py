"""Configure structlog exception rendering without message text or frame locals."""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.tracebacks import ExceptionDictTransformer
from structlog.typing import EventDict, ExcInfo, WrappedLogger

from app.core.config import get_settings

_REDACTED = "<redacted>"
_EXCEPTION_TRANSFORMER = ExceptionDictTransformer(show_locals=False)


def _message_digest(value: object) -> str:
    """Return a correlation digest for redacted exception text."""
    try:
        text = str(value)
    except Exception:  # noqa: BLE001
        return ""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _scrub_stack(stack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(stack, dict):
        return stack
    message = stack.get("exc_value")
    stack["exc_value"] = _REDACTED
    if message:
        stack["exc_value_digest"] = _message_digest(message)
    notes = stack.get("exc_notes")
    if isinstance(notes, list):
        stack["exc_notes"] = [_REDACTED for _ in notes]
    syntax_error = stack.get("syntax_error")
    if isinstance(syntax_error, dict):
        syntax_error.pop("line", None)
    for frame in stack.get("frames") or []:
        if isinstance(frame, dict):
            frame.pop("locals", None)
    nested = stack.get("exceptions")
    if isinstance(nested, list):
        for trace in nested:
            if not isinstance(trace, dict):
                continue
            for inner in trace.get("stacks") or []:
                _scrub_stack(inner)
    return stack


def _scrub_exception_payload(
    _logger: WrappedLogger, _name: str, event_dict: EventDict
) -> EventDict:
    stacks = event_dict.get("exception")
    if isinstance(stacks, list):
        event_dict["exception"] = [_scrub_stack(stack) for stack in stacks]
    return event_dict


def _format_stack(stack: dict[str, Any]) -> str:
    lines = ["Traceback (most recent call last):"]
    for frame in stack.get("frames") or []:
        filename = frame.get("filename")
        if not filename:
            continue
        lines.append(f'  File "{filename}", line {frame.get("lineno")}, in {frame.get("name")}')
    lines.append(f"{stack.get('exc_type') or 'Exception'}: {_REDACTED}")
    return "\n".join(lines) + "\n"


def _console_exception_formatter(sio: TextIO, exc_info: ExcInfo) -> None:
    """Development renderer that prints frames without locals or messages."""
    for stack in _EXCEPTION_TRANSFORMER(exc_info):
        sio.write("\n" + _format_stack(_scrub_stack(stack)))


def configure_logging() -> None:
    """Configure structlog to emit JSON in production, pretty in dev."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_json and not settings.debug:
        processors = shared_processors + [
            structlog.processors.ExceptionRenderer(_EXCEPTION_TRANSFORMER),
            _scrub_exception_payload,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=_console_exception_formatter,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
