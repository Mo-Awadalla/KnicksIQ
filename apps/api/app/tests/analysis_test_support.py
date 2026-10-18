"""Shared cache isolation for public analyst endpoint cases."""

from __future__ import annotations

import pytest
from app.api import analysis


@pytest.fixture(autouse=True)
def isolate_response_cache(monkeypatch):
    async def cache_miss(_key):
        return None

    async def discard_cache_write(_key, _value):
        return None

    monkeypatch.setattr(analysis, "get_cached_answer", cache_miss)
    monkeypatch.setattr(analysis, "set_cached_answer", discard_cache_write)


async def _true() -> bool:
    return True
