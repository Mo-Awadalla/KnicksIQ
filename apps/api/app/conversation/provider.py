from __future__ import annotations

import codecs
import json
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

MAX_STREAM_BYTES = 1_048_576
MAX_EVENT_BYTES = 65_536
MAX_TOOL_CALLS = 16
MAX_TOOL_ARGUMENT_CHARS = 4_096
_LINE_BREAK = re.compile(r"\r\n|\r|\n")

ProviderFailure = Literal[
    "http_status", "protocol", "too_large", "truncated", "upstream_error", "transport"
]


class ProviderError(Exception):
    def __init__(self, kind: ProviderFailure, status: int | None = None):
        super().__init__(kind if status is None else f"{kind}:{status}")
        self.kind: ProviderFailure = kind
        self.status = status


@dataclass
class ToolCallDraft:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class Completion:
    finish: str | None = None
    tool_calls: list[ToolCallDraft] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    terminal_received: bool = False

    @property
    def cost(self) -> float | None:
        if not self.terminal_received:
            return None
        value = (self.usage or {}).get("cost")
        if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
            return float(value)
        return None


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    model: str
    reasoning_effort: str | None
    max_tokens: int


class _Events:
    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self.buffer = ""
        self.data: list[str] = []
        self.size = 0

    def feed(self, chunk: bytes, final: bool = False) -> list[str]:
        try:
            self.buffer += self.decoder.decode(chunk, final=final)
        except UnicodeDecodeError as exc:
            raise ProviderError("protocol") from exc
        held = ""
        if not final and self.buffer.endswith("\r"):
            # A CR may be the first half of a CRLF that arrives in the next fragment.
            self.buffer, held = self.buffer[:-1], "\r"
        lines = _LINE_BREAK.split(self.buffer)
        self.buffer = "" if final else lines.pop()
        if len(self.buffer) > MAX_EVENT_BYTES:
            raise ProviderError("too_large")
        self.buffer += held
        events: list[str] = []
        for line in lines + ([""] if final else []):
            self._line(line, events)
        return events

    def _line(self, line: str, events: list[str]) -> None:
        if not line:
            if self.data:
                events.append("\n".join(self.data))
            self.data, self.size = [], 0
            return
        if line.startswith(":"):
            return
        name, _, value = line.partition(":")
        if name != "data":
            return
        value = value[1:] if value.startswith(" ") else value
        self.size += len(value)
        if self.size > MAX_EVENT_BYTES:
            raise ProviderError("too_large")
        self.data.append(value)


def _merge_tool_calls(completion: Completion, deltas: Any) -> None:
    if not isinstance(deltas, list):
        raise ProviderError("protocol")
    for delta in deltas:
        if not isinstance(delta, dict) or not isinstance(delta.get("index", 0), int):
            raise ProviderError("protocol")
        index = delta.get("index", 0)
        draft = next((call for call in completion.tool_calls if call.index == index), None)
        if draft is None:
            if len(completion.tool_calls) >= MAX_TOOL_CALLS:
                raise ProviderError("too_large")
            draft = ToolCallDraft(index=index)
            completion.tool_calls.append(draft)
        if isinstance(delta.get("id"), str):
            draft.id = delta["id"][:128]
        function = delta.get("function") or {}
        if not isinstance(function, dict):
            raise ProviderError("protocol")
        if isinstance(function.get("name"), str):
            draft.name = (draft.name + function["name"])[:128]
        if isinstance(function.get("arguments"), str):
            draft.arguments += function["arguments"]
            if len(draft.arguments) > MAX_TOOL_ARGUMENT_CHARS:
                raise ProviderError("too_large")


def _packet(completion: Completion, packet: Any) -> str:
    if not isinstance(packet, dict):
        raise ProviderError("protocol")
    if packet.get("error") is not None:
        raise ProviderError("upstream_error")
    if isinstance(packet.get("usage"), dict):
        completion.usage = packet["usage"]
    choices = packet.get("choices")
    if choices is None or choices == []:
        return ""
    if not isinstance(choices, list) or not isinstance(choices[0], dict):
        raise ProviderError("protocol")
    choice = choices[0]
    delta = choice.get("delta") or {}
    if not isinstance(delta, dict):
        raise ProviderError("protocol")
    if delta.get("tool_calls") is not None:
        _merge_tool_calls(completion, delta["tool_calls"])
    finish = choice.get("finish_reason")
    if isinstance(finish, str) and finish:
        completion.finish = finish
    content = delta.get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderError("protocol")
    return content or ""


def request_body(
    config: ProviderConfig, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.7,
        "max_tokens": config.max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = True
    if "openrouter.ai" in config.base_url:
        body["provider"] = {"allow_fallbacks": True, "sort": "latency"}
        body["usage"] = {"include": True}
        if config.reasoning_effort is not None:
            body["reasoning"] = {"effort": config.reasoning_effort}
    return body


async def stream_completion(
    client: httpx.AsyncClient,
    config: ProviderConfig,
    body: dict[str, Any],
    completion: Completion,
) -> AsyncGenerator[str, None]:
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Accept": "text/event-stream"}
    try:
        async with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code != 200:
                raise ProviderError("http_status", response.status_code)
            events = _Events()
            received = 0
            done = False
            async for chunk in response.aiter_raw():
                received += len(chunk)
                if received > MAX_STREAM_BYTES:
                    raise ProviderError("too_large")
                for data in events.feed(chunk):
                    if data.strip() == "[DONE]":
                        done = True
                        break
                    try:
                        packet = json.loads(data)
                    except ValueError as exc:
                        raise ProviderError("protocol") from exc
                    text = _packet(completion, packet)
                    if text:
                        yield text
                if done:
                    break
            if not done:
                for data in events.feed(b"", final=True):
                    if data.strip() == "[DONE]":
                        done = True
            if not done:
                raise ProviderError("truncated")
            if completion.finish is None:
                raise ProviderError("protocol")
            completion.terminal_received = True
    except httpx.RemoteProtocolError as exc:
        raise ProviderError("truncated") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("transport") from exc
