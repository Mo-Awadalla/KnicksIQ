"""Failure-mode tests for optional Redis runtime state."""

from __future__ import annotations

from app.services import runtime_store


class _FailingPipeline:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def incr(self, _key):
        return self

    def expire(self, _key, _seconds, *, nx):  # noqa: ARG002
        return self

    async def execute(self):
        raise ConnectionError("redis unavailable")


class _FailingRedis:
    def __init__(self):
        self.closed = False

    def pipeline(self, *, transaction):  # noqa: ARG002
        return _FailingPipeline()

    async def aclose(self):
        self.closed = True


async def test_redis_limit_failure_degrades_and_closes_client(monkeypatch):
    redis = _FailingRedis()

    async def failing_redis():
        return redis

    monkeypatch.setattr(runtime_store, "_redis", failing_redis)

    assert await runtime_store.enforce_redis_limits("anonymous-client") is True
    assert redis.closed is True


def test_answer_cache_key_changes_with_generation_contract(monkeypatch):
    monkeypatch.setattr(
        runtime_store,
        "get_settings",
        lambda: type("Settings", (), {"ip_hash_secret": "test-secret"})(),
    )

    shadow = runtime_store.answer_cache_key(
        "Which games had the wildest swings?",
        "release-1",
        "model-1",
        answer_mode="shadow",
        prompt_version="v1",
        index_version="release-1",
    )
    primary = runtime_store.answer_cache_key(
        "Which games had the wildest swings?",
        "release-1",
        "model-1",
        answer_mode="llm_primary",
        prompt_version="v1",
        index_version="release-1",
    )

    assert shadow != primary
