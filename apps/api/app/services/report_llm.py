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
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings


class LLMAdapter(ABC):
    """Interface for a report-generating LLM."""

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
    """Minimal OpenAI-compatible chat completions adapter."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        response_format_json: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.response_format_json = response_format_json

    async def generate(self, *, system: str, user: str) -> str:
        import asyncio

        return await asyncio.to_thread(self._generate_sync, system, user)

    def _generate_sync(self, system: str, user: str) -> str:
        payload_body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if self.response_format_json:
            payload_body["response_format"] = {"type": "json_object"}
        payload = json.dumps(payload_body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req,
                timeout=self.timeout_seconds,
                context=_ssl_context(),
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI provider request failed: {exc}") from exc
        return body["choices"][0]["message"]["content"]


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
        adjustments.append(
            "Reduce live-ball turnovers through simplified half-court sets."
        )
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
