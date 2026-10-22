"""LLM adapter — abstract base + a deterministic mock.

The mock generates a report by templating the actual game data:
real scoring runs, real bad stretches, real play-by-play snippets.
It produces a structured Postgame Autopsy without calling an LLM,
which keeps the system deterministic in dev and tests.

To swap in a real LLM, subclass `LLMAdapter` and inject it.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.core.config import get_settings
from app.services.llm_wire import PROTOCOLS, Request, priced


class LLMAdapter(ABC):
    """Interface for a report-generating LLM."""

    max_tokens: int = 500
    timeout_seconds: float = 20
    response_schema: dict[str, Any] | None = None
    last_metadata: dict[str, Any] = {}

    @abstractmethod
    async def generate(self, *, system: str, user: str) -> str:
        """Return the raw LLM response. Implementations should return JSON."""


class MockLLMAdapter(LLMAdapter):
    """Deterministic, template-based report generator.

    Given the structured context (game summary + runs + bad stretches +
    snippets), it produces a JSON report. The output is intentionally
    bland but factually correct — the structure is what matters for
    Phase 5; the prose quality arrives when a real LLM is wired in.
    """

    async def generate(self, *, system: str, user: str) -> str:
        ctx = json.loads(user)
        return json.dumps(_build_report(ctx))


class OpenAICompatibleLLMAdapter(LLMAdapter):
    """OpenAI-compatible adapter; the wire protocol is chosen per model (see llm_wire)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        response_format_json: bool = True,
        max_tokens: int = 500,
        reasoning_effort: str | None = None,
        provider_order: list[str] | None = None,
        provider_sort: str | None = "latency",
        provider_allow_fallbacks: bool = True,
        protocols: Mapping[str, str] | None = None,
        prices: dict[str, list[float]] | None = None,
        user_agent: str = "knicksiq/1.0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.response_format_json = response_format_json
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.provider_order = list(provider_order or [])
        self.provider_sort = provider_sort
        self.provider_allow_fallbacks = provider_allow_fallbacks
        self.protocols = dict(protocols or {})
        self.prices = dict(prices or {})
        self.user_agent = user_agent
        # A random id for host-side routing and caching; never a user token. Go rejects any
        # request without one, so every adapter starts with its own; the analyst loop
        # replaces it with one id per turn.
        self.session_id: str | None = uuid.uuid4().hex
        self.response_schema: dict[str, Any] | None = None
        self.last_metadata: dict[str, Any] = {}

    async def generate(self, *, system: str, user: str) -> str:
        import asyncio

        return await asyncio.to_thread(self._generate_sync, system, user)

    def _provider(self) -> dict[str, Any]:
        provider: dict[str, Any] = {"allow_fallbacks": self.provider_allow_fallbacks}
        if self.provider_sort and self.provider_sort != "none":
            provider["sort"] = self.provider_sort
        if self.provider_order:
            provider["order"] = self.provider_order
        return provider

    def _generate_sync(self, system: str, user: str) -> str:
        protocol = self.protocols.get(self.model, "chat")
        build, parse = PROTOCOLS[protocol]
        path, payload_body = build(
            Request(
                model=self.model,
                system=system,
                user=user,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
                response_schema=self.response_schema,
                json_object=self.response_format_json,
                openrouter="openrouter.ai" in self.base_url,
                provider=self._provider(),
            )
        )
        payload = json.dumps(payload_body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.session_id:
            headers["x-opencode-session"] = self.session_id
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=payload, headers=headers, method="POST"
        )
        sent_at = time.monotonic()
        first_byte_at: float | None = None
        try:
            with urllib.request.urlopen(
                req,
                timeout=self.timeout_seconds,
                context=_ssl_context(),
            ) as response:
                # urlopen returns once response headers arrive, which is the earliest
                # observable byte without streaming. A non-streaming provider may send
                # them only after generation, so treat this as an upper-bound TTFB.
                first_byte_at = time.monotonic()
                raw = response.read()
                body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if not detail:
                detail = str(exc.reason)
            raise RuntimeError(
                f"AI provider request failed (HTTP {exc.code}): {detail[:1000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI provider request failed: {exc}") from exc
        if not isinstance(body, dict):
            raise RuntimeError("AI provider returned a non-object response")
        if body.get("error") is not None:
            detail = json.dumps(body["error"], ensure_ascii=False)
            raise RuntimeError(f"AI provider returned an error: {detail[:1000]}")
        reply = parse(body)
        content = reply.content
        usage = reply.usage
        if usage.get("cost") is None:
            cost = priced(usage, self.model, self.prices)
            if cost is not None:
                usage["cost"] = cost
        self.last_metadata = {key: body.get(key) for key in ("id", "model", "provider")}
        self.last_metadata.update(
            {
                "protocol": protocol,
                "usage": usage,
                "finish_reason": reply.finish_reason,
                "content_kind": (
                    "string"
                    if isinstance(content, str) and content
                    else "empty_string"
                    if content == ""
                    else "null"
                    if content is None
                    else type(content).__name__
                ),
                "reasoning_chars": reply.reasoning_chars,
                "message_keys": reply.message_keys,
                **reply.extra,
                "request_bytes": len(payload),
                "response_bytes": len(raw),
                "http_ttfb_ms": round((first_byte_at - sent_at) * 1000, 1)
                if first_byte_at is not None
                else None,
                "http_elapsed_ms": round((time.monotonic() - sent_at) * 1000, 1),
                "max_tokens": self.max_tokens,
            }
        )
        if not isinstance(content, str) or not content:
            # Keep the cause in the error: an empty completion is usually a token ceiling or
            # a provider fault, and the two need different fixes.
            raise RuntimeError(
                "AI provider response omitted message content "
                f"(finish_reason={reply.finish_reason}, protocol={protocol}, "
                f"provider={self.last_metadata.get('provider')}, "
                f"model={self.last_metadata.get('model')}, max_tokens={self.max_tokens}, "
                f"usage={json.dumps(usage, separators=(',', ':'))[:500]}, "
                f"content_kind={self.last_metadata['content_kind']}, "
                f"message_keys={reply.message_keys})"
            )
        return content


def get_llm_adapter(*, response_format_json: bool = True) -> LLMAdapter:
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return MockLLMAdapter()
    if settings.ai_provider.lower() in {"mock", "none", "disabled"}:
        return MockLLMAdapter()
    if not settings.ai_api_key:
        return MockLLMAdapter()
    return OpenAICompatibleLLMAdapter(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_chat_model,
        timeout_seconds=settings.ai_request_timeout_seconds,
        response_format_json=response_format_json,
        max_tokens=getattr(settings, "rag_generation_max_output_tokens", 500),
        reasoning_effort=settings.ai_reasoning_effort,
        provider_order=getattr(settings, "openrouter_provider_order", []),
        provider_sort=getattr(settings, "openrouter_provider_sort", "latency"),
        provider_allow_fallbacks=getattr(settings, "openrouter_provider_allow_fallbacks", True),
        protocols=settings.ai_model_protocols,
        prices=settings.ai_model_prices,
        user_agent=settings.ai_user_agent,
    )


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _build_report(ctx: dict[str, Any]) -> dict[str, Any]:
    """Build a structured report from the assembled context."""
    game = ctx["game"]
    runs: list[dict] = ctx.get("scoring_runs", [])
    stretches: list[dict] = ctx.get("bad_stretches", [])

    home = game["home_team_id"]
    away = game["away_team_id"]
    home_score = game["home_score"]
    away_score = game["away_score"]
    margin = home_score - away_score
    winner = home if margin > 0 else away

    # Turning point: the worst opponent run, if any, else the best Knicks run.
    opponent_runs = [r for r in runs if r["team_id"] != "NYK" and r["score_delta"] >= 6]
    knicks_runs = [r for r in runs if r["team_id"] == "NYK" and r["score_delta"] >= 6]
    opponent_runs.sort(key=lambda r: -r["score_delta"])
    knicks_runs.sort(key=lambda r: -r["score_delta"])

    if opponent_runs:
        op = opponent_runs[0]
        turning_point = (
            f"{op['team_id']} went on a {op['points_for']}-{op['points_against']} run "
            f"in Q{op['period']} from {op['start_clock']} to {op['end_clock']} — "
            f"this stretch was decisive."
        )
    elif knicks_runs:
        op = knicks_runs[0]
        turning_point = (
            f"Knicks' {op['points_for']}-{op['points_against']} run in Q{op['period']} "
            f"from {op['start_clock']} to {op['end_clock']} set the tone."
        )
    else:
        turning_point = "No decisive scoring run emerged from the play-by-play."

    # Worst Knicks stretch.
    worst = stretches[0] if stretches else None
    if worst:
        worst_stretch = (
            f"Q{worst['period']} {worst['start_clock']}-{worst['end_clock']}: "
            f"{worst['summary']} (causes: {', '.join(worst['likely_causes'])})"
        )
    else:
        worst_stretch = "No clear bad stretch was identified."

    # Best Knicks stretch.
    if knicks_runs:
        best = knicks_runs[0]
        best_stretch = (
            f"Knicks' {best['points_for']}-{best['points_against']} run in "
            f"Q{best['period']} ({best['start_clock']}-{best['end_clock']}) "
            f"was the most productive stretch."
        )
    else:
        best_stretch = "No standout Knicks run was identified."

    # Adjustments.
    adjustments = []
    if any(
        "drought" in (s.get("summary", "") + " ".join(s.get("likely_causes", []))).lower()
        for s in stretches
    ):
        adjustments.append(
            "Earlier ball movement to break offensive droughts — consider running a higher tempo."
        )
    if any("turnovers" in " ".join(s.get("likely_causes", [])).lower() for s in stretches):
        adjustments.append("Reduce live-ball turnovers through simplified half-court sets.")
    if not adjustments:
        adjustments.append("Maintain the current rotation; no glaring adjustments needed.")

    summary = (
        f"{winner} won {max(home_score, away_score)}-{min(home_score, away_score)} on "
        f"{game.get('game_date', 'an unspecified date')}. "
        f"{'Margin: ' + str(abs(margin)) + '.' if abs(margin) > 0 else ''}"
    )

    return {
        "title": f"Postgame Autopsy: {home} vs {away}",
        "summary": summary,
        "turning_point": turning_point,
        "best_stretch": best_stretch,
        "worst_stretch": worst_stretch,
        "player_notes": [
            "Player-level analysis requires richer box score data (Phase 6+).",
        ],
        "suggested_adjustments": adjustments,
    }
