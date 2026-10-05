"""Internal counted OpenRouter transport; no default live-price verifier.

The caller must supply a per-request verifier that checks the actual payload,
current conservative provider bounds and real monthly allowance. This class
cannot certify those facts itself. Its journal supplements normal Redis budget
reservation, and all analyst calls must share that same goal journal.
"""

import json
from collections.abc import Awaitable, Callable
from decimal import ROUND_CEILING, Decimal
from typing import Any

import httpx

from app.evaluation.verification_budget import VerificationBudget
from app.services.evidence_contracts import Action, AnswerReview, ProposedAnswer
from app.services.report_llm import LLMAdapter

MODEL = "deepseek/deepseek-v4.1-flash"
_PROTOCOL_MODELS = {model.__name__: model for model in (Action, ProposedAnswer, AnswerReview)}


class CountedVerificationAdapter(LLMAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        budget: VerificationBudget,
        stage: str,
        verify_request: Callable[[dict[str, Any]], Awaitable[int]],
        reasoning_effort: str | None = None,
        on_failure: Callable[[str], None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.on_failure = on_failure
        self.api_key = api_key
        self.budget = budget
        self.stage = stage
        self.verify_request = verify_request
        self.reasoning_effort = reasoning_effort
        self.transport = transport
        self.last_metadata = {}
        self.response_schema = None

    async def generate(self, *, system: str, user: str) -> str:
        try:
            try:
                prompt = json.loads(user)
            except json.JSONDecodeError:
                prompt = None
            protocol = None
            if isinstance(prompt, dict) and isinstance(prompt.get("schema"), dict):
                protocol = _PROTOCOL_MODELS.get(prompt["schema"].get("title"))
                if protocol is None:
                    raise ValueError("Unknown counted analyst protocol")
            content = await self._generate(system=system, user=user)
            if protocol is not None:
                # Parsing outside this boundary would let later paid cases run
                # after malformed output had already failed the analyst loop.
                protocol.model_validate_json(content)
            return content
        except BaseException as exc:
            if self.on_failure is not None:
                self.on_failure(type(exc).__name__)
            raise

    async def _generate(self, *, system: str, user: str) -> str:
        self.last_metadata = {}
        payload: dict[str, Any] = {
            "model": MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "provider": {"allow_fallbacks": True, "sort": "latency", "require_parameters": True},
            "response_format": {"type": "json_object"},
        }
        if self.reasoning_effort is not None:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "analyst", "strict": True, "schema": self.response_schema},
            }
        # A missing/unavailable verifier fails before reservation or transmission.
        bound = await self.verify_request(payload)

        async def send() -> dict:
            async with httpx.AsyncClient(
                transport=self.transport,
                follow_redirects=False,
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, dict) or body.get("error") is not None:
                raise ValueError("Invalid provider completion")
            self.last_metadata = {
                key: body.get(key) for key in ("id", "model", "provider", "usage")
            }
            if body.get("model") != MODEL:
                raise ValueError("Provider changed the authorized model")
            usage = body.get("usage")
            raw_cost = usage.get("cost") if isinstance(usage, dict) else None
            if type(raw_cost) not in {int, float}:
                raise ValueError("Missing provider cost")
            cost = Decimal(str(raw_cost))
            if not cost.is_finite() or cost < 0:
                raise ValueError("Invalid provider cost")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("Missing provider completion")
            message = choices[0].get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content:
                raise ValueError("Missing provider completion text")
            return {
                "cost_nusd": int((cost * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING)),
                "content": content,
            }

        result = await self.budget.call(self.stage, bound, send)
        return result["content"]


class CountedRun:
    """Explicit execution dependency, never constructed from an approval boolean.

    Environment verification must resolve isolated resource identities, candidate,
    real monthly accounting, current price bounds, and any billed dependencies.
    The CLI has no default implementation: unavailable verification stays blocked.
    """

    subject_namespace: str | None

    def __init__(
        self,
        *,
        api_key: str,
        budget: VerificationBudget,
        verify_environment: Callable[[dict[str, Any]], Awaitable[None]],
        verify_request: Callable[[dict[str, Any]], Awaitable[int]],
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key, self.budget = api_key, budget
        self.verify_environment, self.verify_request = verify_environment, verify_request
        self.transport = transport
        self.failure: str | None = None

    def check(self) -> None:
        if self.failure or self.budget.snapshot()["stopped"]:
            raise ValueError("Counted verification stopped after provider/accounting failure")

    def failed(self, error: str) -> None:
        self.failure = error

    def adapter(self, stage: str, reasoning_effort: str | None) -> CountedVerificationAdapter:
        self.check()
        return CountedVerificationAdapter(
            api_key=self.api_key,
            budget=self.budget,
            stage=stage,
            verify_request=self.verify_request,
            transport=self.transport,
            reasoning_effort=reasoning_effort,
            on_failure=self.failed,
        )
