"""Opt-in, process-internal evaluation capture; never attached to public responses.

A runner owns the context and private artifact destination. No HTTP parameter or
production configuration can enable capture. ContextVars isolate concurrent turns.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

_active: ContextVar[dict[str, Any] | None] = ContextVar("evaluation_capture", default=None)


@contextmanager
def capture_turn() -> Iterator[dict[str, Any]]:
    capture: dict[str, Any] = {"searches": [], "tools": [], "turn": {}}
    token = _active.set(capture)
    try:
        yield capture
    finally:
        _active.reset(token)


def record_search(value: dict[str, Any]) -> None:
    capture = _active.get()
    if capture is not None:
        capture["searches"].append(deepcopy(value))


def record_tool(value: dict[str, Any]) -> None:
    capture = _active.get()
    if capture is not None:
        capture["tools"].append(deepcopy(value))


def record_turn(value: dict[str, Any]) -> None:
    capture = _active.get()
    if capture is not None:
        capture["turn"].update(deepcopy(value))
