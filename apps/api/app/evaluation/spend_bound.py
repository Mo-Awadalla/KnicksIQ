"""The price and request contract for one approved evaluation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any

MAX_ATTEMPTS = 720
MAX_TOTAL_NANO_USD = 2_000_000_000
MODEL_CONTEXT_TOKENS = 1_048_576
MAX_COMPLETION_TOKENS = 1_200
PROMPT_NANO_USD_PER_TOKEN = 45
COMPLETION_NANO_USD_PER_TOKEN = 500

PROVIDER_MODEL = "deepseek/deepseek-v4.1-flash"
PROVIDER_BASE_URL = "https://openrouter.ai/api/v1"
ELIGIBLE_PROVIDER_TAGS = (
    "open-inference/fp4",
    "morph/fp8",
    "baidu/fp8",
    "wafer/us",
)


class SpendError(ValueError):
    """The spend contract or external accounting data is unusable."""


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpendError("request contains a duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise SpendError("request contains a non-finite JSON number")


@dataclass(frozen=True)
class ReportedUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class SpendBound:
    max_total_nano_usd: int
    model_context_tokens: int
    max_completion_tokens: int
    prompt_nano_usd_per_token: int
    completion_nano_usd_per_token: int
    provider_tags: tuple[str, ...]
    pricing_sha256: str
    endpoints_sha256: str

    def __post_init__(self) -> None:
        expected = (
            ("model_context_tokens", MODEL_CONTEXT_TOKENS),
            ("max_completion_tokens", MAX_COMPLETION_TOKENS),
            ("prompt_nano_usd_per_token", PROMPT_NANO_USD_PER_TOKEN),
            ("completion_nano_usd_per_token", COMPLETION_NANO_USD_PER_TOKEN),
        )
        for name, required in expected:
            value = getattr(self, name)
            if type(value) is not int or value != required:
                raise SpendError(f"{name} does not match the verified price profile")
        if (
            type(self.max_total_nano_usd) is not int
            or self.max_total_nano_usd < self.reservation_nano_usd
            or self.max_total_nano_usd > MAX_TOTAL_NANO_USD
        ):
            raise SpendError("total spend limit is outside the operator authorization")
        if self.provider_tags != ELIGIBLE_PROVIDER_TAGS:
            raise SpendError("provider tags do not match the verified endpoint profile")
        if not _hash(self.pricing_sha256) or not _hash(self.endpoints_sha256):
            raise SpendError("price evidence digests are missing")

    @classmethod
    def from_dict(cls, value: Any) -> SpendBound:
        names = {field.name for field in fields(cls)}
        if not isinstance(value, dict) or set(value) != names:
            raise SpendError("spend_bound has missing or unexpected fields")
        tags = value["provider_tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise SpendError("provider_tags must be an ordered list of strings")
        return cls(**{**value, "provider_tags": tuple(tags)})

    def payload(self) -> dict[str, Any]:
        return {**asdict(self), "provider_tags": list(self.provider_tags)}

    @property
    def reservation_nano_usd(self) -> int:
        return (
            self.model_context_tokens * self.prompt_nano_usd_per_token
            + self.max_completion_tokens * self.completion_nano_usd_per_token
        )

    def provider_preferences(self) -> dict[str, Any]:
        return {
            "only": list(self.provider_tags),
            "allow_fallbacks": False,
            "sort": "latency",
            "require_parameters": True,
            "max_price": {
                "prompt": self.prompt_nano_usd_per_token / 1000,
                "completion": self.completion_nano_usd_per_token / 1000,
                "request": 0,
            },
        }

    def prepare(self, body: dict[str, Any]) -> None:
        body["provider"] = self.provider_preferences()
        body["reasoning"] = {"effort": "none"}

    def validate_request(self, raw: bytes, *, model: str) -> int:
        try:
            body = json.loads(
                raw,
                object_pairs_hook=_object,
                parse_constant=_nonfinite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpendError("request is not a JSON object") from exc
        if not isinstance(body, dict):
            raise SpendError("request is not a JSON object")

        required = {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "provider",
            "reasoning",
        }
        allowed = required | {"response_format"}
        if not required <= set(body) or set(body) - allowed:
            raise SpendError("request has missing or unapproved top-level parameters")
        if body["model"] != model:
            raise SpendError("serialized request names a different model")

        maximum = body["max_tokens"]
        if type(maximum) is not int or not 1 <= maximum <= self.max_completion_tokens:
            raise SpendError("completion limit exceeds the approved profile")

        temperature = body["temperature"]
        if type(temperature) not in (int, float) or temperature != 0:
            raise SpendError("request temperature differs from the approved profile")

        messages = body["messages"]
        if not isinstance(messages, list) or len(messages) != 2:
            raise SpendError("request must contain the two text messages")
        for message, role in zip(messages, ("system", "user"), strict=True):
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] != role
                or not isinstance(message["content"], str)
                or not message["content"]
            ):
                raise SpendError("request contains an unapproved message or modality")

        if body["reasoning"] != {"effort": "none"}:
            raise SpendError("reasoning must be explicitly disabled")

        provider = body["provider"]
        expected = self.provider_preferences()
        if not isinstance(provider, dict) or set(provider) != set(expected):
            raise SpendError("provider routing parameters differ from the approved profile")
        prices = provider.get("max_price")
        if not isinstance(prices, dict) or set(prices) != {"prompt", "completion", "request"}:
            raise SpendError("provider price ceilings are missing")
        for value in prices.values():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise SpendError("provider price ceiling is not a finite number")
        if provider != expected:
            raise SpendError("provider routing or prices differ from the approved profile")

        response_format = body.get("response_format")
        if response_format is not None and (
            not isinstance(response_format, dict)
            or response_format.get("type") not in {"json_object", "json_schema"}
        ):
            raise SpendError("response format is outside the approved profile")
        return maximum

    def usage(self, value: Any, *, output_limit: int) -> ReportedUsage | None:
        if not isinstance(value, Mapping):
            return None
        prompt = value.get("prompt_tokens")
        completion = value.get("completion_tokens")
        if (
            type(prompt) is not int
            or not 1 <= prompt <= self.model_context_tokens
            or type(completion) is not int
            or not 0 <= completion <= output_limit
        ):
            return None
        if "total_tokens" in value:
            total = value["total_tokens"]
            if type(total) is not int or total != prompt + completion:
                return None
        details = value.get("completion_tokens_details")
        if details is not None:
            if not isinstance(details, Mapping):
                return None
            if "reasoning_tokens" in details:
                reasoning = details["reasoning_tokens"]
                if type(reasoning) is not int or reasoning != 0:
                    return None
        return ReportedUsage(prompt, completion)

    def charge(self, usage: ReportedUsage) -> int:
        return (
            usage.prompt_tokens * self.prompt_nano_usd_per_token
            + usage.completion_tokens * self.completion_nano_usd_per_token
        )
