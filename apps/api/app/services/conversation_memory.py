"""Bounded, UTF-8-safe transcript context. Verified facts live in session state."""

from __future__ import annotations

import json
from typing import Any

HISTORY_MESSAGES = 10
HISTORY_BYTES = 2_000
MIN_EXCERPT_BYTES = 96


def _prefix(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def bounded_history(messages: list[Any]) -> list[dict[str, str]]:
    """Keep every prior turn's opening, then restore newest detail within the allowance."""
    prior = messages[-HISTORY_MESSAGES:]
    source = [
        {
            "role": item["role"] if isinstance(item, dict) else item.role,
            "content": item["content"] if isinstance(item, dict) else item.content,
        }
        for item in prior
    ]
    result = [
        {"role": item["role"], "content": _prefix(item["content"], MIN_EXCERPT_BYTES)}
        for item in source
    ]

    def size() -> int:
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    if size() > HISTORY_BYTES:
        raise ValueError("Mandatory conversation excerpts exceed history allowance")
    for index in range(len(result) - 1, -1, -1):
        full = source[index]["content"]
        if result[index]["content"] == full:
            continue
        low = len(result[index]["content"].encode("utf-8"))
        high = len(full.encode("utf-8"))
        while low < high:
            mid = (low + high + 1) // 2
            result[index]["content"] = _prefix(full, mid)
            if size() <= HISTORY_BYTES:
                low = mid
            else:
                high = mid - 1
        result[index]["content"] = _prefix(full, low)
    return result
