"""Wire formats for OpenAI-compatible hosts, one entry per protocol.

Some models on a host answer only the Responses API (OpenCode Go serves gpt-6-luna that way)
while others answer Chat Completions. Each protocol builds its request and parses its reply
into one normalized shape, so callers, traces and the budget ledger never branch on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Protocol = Literal["chat", "responses"]


@dataclass(frozen=True)
class Request:
    model: str
    system: str
    user: str
    max_tokens: int
    reasoning_effort: str | None
    response_schema: dict[str, Any] | None
    json_object: bool
    openrouter: bool
    provider: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: object
    finish_reason: str | None
    usage: dict[str, Any]
    reasoning_chars: int | None
    message_keys: list[str]
    extra: dict[str, Any]


def _chat_request(req: Request) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": req.system},
            {"role": "user", "content": req.user},
        ],
        "temperature": 0,
        "max_tokens": req.max_tokens,
    }
    if req.openrouter:
        body["provider"] = dict(req.provider)
        if req.reasoning_effort is not None:
            body["reasoning"] = {"effort": req.reasoning_effort}
    elif req.reasoning_effort is not None:
        # Hosts other than OpenRouter take the OpenAI top-level field; DeepSeek otherwise
        # thinks by default and spends the completion budget before any JSON.
        body["reasoning_effort"] = req.reasoning_effort
    if req.response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "analyst", "strict": True, "schema": req.response_schema},
        }
    elif req.json_object:
        body["response_format"] = {"type": "json_object"}
    if req.openrouter and "response_format" in body:
        body["provider"]["require_parameters"] = True
    return "/chat/completions", body


def _chat_reply(body: dict[str, Any]) -> Reply:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"AI provider response omitted choices: {str(body)[:1000]}")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    raw_message = choice.get("message")
    message: dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
    reasoning = message.get("reasoning") or message.get("reasoning_content")
    return Reply(
        content=message.get("content"),
        finish_reason=choice.get("finish_reason"),
        usage=dict(body.get("usage") or {}),
        reasoning_chars=len(reasoning) if isinstance(reasoning, str) else None,
        message_keys=sorted(message),
        extra={
            "native_finish_reason": choice.get("native_finish_reason"),
            "choice_keys": sorted(choice),
        },
    )


def _responses_request(req: Request) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "model": req.model,
        "input": [
            {"role": "system", "content": req.system},
            {"role": "user", "content": req.user},
        ],
        "max_output_tokens": req.max_tokens,
    }
    if req.reasoning_effort is not None:
        body["reasoning"] = {"effort": req.reasoning_effort}
    if req.response_schema is not None:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "analyst",
                "strict": True,
                "schema": req.response_schema,
            }
        }
    elif req.json_object:
        body["text"] = {"format": {"type": "json_object"}}
    return "/responses", body


def _responses_reply(body: dict[str, Any]) -> Reply:
    messages = [item for item in body.get("output") or [] if item.get("type") == "message"]
    parts = [part for item in messages for part in item.get("content") or []]
    texts = [part.get("text") for part in parts if part.get("type") == "output_text"]
    reasoning = [item for item in body.get("output") or [] if item.get("type") == "reasoning"]
    incomplete = (body.get("incomplete_details") or {}).get("reason")
    raw = body.get("usage") or {}
    # Normalized to Chat Completions names so traces and cost accounting stay uniform.
    usage = {
        "prompt_tokens": raw.get("input_tokens"),
        "completion_tokens": raw.get("output_tokens"),
        "total_tokens": raw.get("total_tokens"),
        "completion_tokens_details": {
            "reasoning_tokens": (raw.get("output_tokens_details") or {}).get("reasoning_tokens")
        },
    }
    if raw.get("cost") is not None:
        usage["cost"] = raw["cost"]
    status = body.get("status")
    return Reply(
        content="".join(t for t in texts if isinstance(t, str)) if texts else None,
        finish_reason=(
            "length"
            if incomplete == "max_output_tokens"
            else "stop"
            if status == "completed"
            else incomplete or status
        ),
        usage=usage,
        reasoning_chars=len(reasoning) or None,
        message_keys=sorted({key for item in messages for key in item}),
        extra={"status": status},
    )


PROTOCOLS: dict[str, tuple[Callable[[Request], tuple[str, dict[str, Any]]], Callable]] = {
    "chat": (_chat_request, _chat_reply),
    "responses": (_responses_request, _responses_reply),
}


def priced(usage: dict[str, Any], model: str, prices: dict[str, list[float]]) -> float | None:
    """Cost from token counts and a USD-per-million [input, output] price, when the host
    reports none. A subscription host still draws its allowance at these list prices."""
    price = prices.get(model)
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not price or prompt is None or completion is None:
        return None
    return round((prompt * price[0] + completion * price[1]) / 1_000_000, 10)
