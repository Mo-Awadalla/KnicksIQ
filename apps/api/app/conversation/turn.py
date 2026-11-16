from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

import httpx
from app.conversation import persona
from app.conversation.facts import FactDesk, wants_facts
from app.conversation.gate import Violation
from app.conversation.provider import (
    Completion,
    ProviderConfig,
    ProviderError,
    ToolCallDraft,
    request_body,
    stream_completion,
)
from app.conversation.publication import Publication
from app.conversation.store import Attempt, ConversationStore, Fenced, StoreUnavailable
from app.core.config import Settings
from app.core.logging import get_logger
from app.services.analyst_budget import BudgetReservation

MAX_REPLY_CHARS = 4_000
OUTPUT_TOKENS_PER_CALL = 600
MAX_LOOKUPS_PER_ROUND = 3
FINALIZE_SECONDS = 5.0
GENERATION_MARGIN_SECONDS = 3.0

Emit = Callable[[str, dict[str, Any]], None]
logger = get_logger("knicksiq.conversation")


def lease_seconds(settings: Settings) -> float:
    return settings.analyst_deadline_seconds + FINALIZE_SECONDS


def provider_config(settings: Settings) -> ProviderConfig | None:
    if settings.ai_provider.lower() in {"mock", "none", "disabled"} or not settings.ai_api_key:
        return None
    allowed = settings.openrouter_allowed_models
    if allowed and settings.ai_chat_model not in allowed:
        return None
    return ProviderConfig(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_chat_model,
        reasoning_effort=settings.ai_reasoning_effort,
        max_tokens=OUTPUT_TOKENS_PER_CALL,
    )


class _Stop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Quality:
    calls: int = 0
    tool_rounds: int = 0
    prefetch: bool = False
    continuations: int = 0
    truncated: bool = False
    violations: list[str] = field(default_factory=list)


class Turn:
    def __init__(self, store: ConversationStore, attempt: Attempt, settings: Settings, emit: Emit):
        self.store, self.attempt, self.settings, self.emit = store, attempt, settings, emit
        self.desk = FactDesk(
            settings.dataset_season,
            attempt.facts_state,
            settings.analyst_evidence_tokens,
            attempt.request_id,
        )
        self.publication = Publication(self.desk.facts, self.desk.lexicon)
        self.text = ""
        self.quality = Quality()

    async def run(self) -> None:
        status, reason, fenced = "interrupted", "unavailable", False
        generation = max(1.0, self.settings.analyst_deadline_seconds - GENERATION_MARGIN_SECONDS)
        try:
            async with asyncio.timeout(generation):
                status, reason = await self._generate()
        except Fenced:
            fenced = True
        except _Stop as stop:
            reason = stop.reason
        except TimeoutError:
            reason = "deadline"
        except asyncio.CancelledError:
            reason = "disconnected"
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
        except (ProviderError, StoreUnavailable):
            reason = "unavailable"
        except Exception as exc:
            logger.error("conversation.turn_failed", error_type=type(exc).__name__)
        await self._finalize(status, reason, fenced)

    async def _finalize(self, status: str, reason: str, fenced: bool) -> None:
        request_id = self.attempt.request_id
        try:
            async with asyncio.timeout(FINALIZE_SECONDS):
                await self.desk.close()
                if fenced:
                    raise Fenced()
                snapshot = await self.store.settle(
                    self.attempt,
                    status,
                    reason if status == "interrupted" else "",
                    self.text,
                    self.desk.persisted_state(),
                )
            self.emit("settled", {"request_id": request_id, "snapshot": snapshot.public()})
            outcome = status
        except Fenced:
            self.emit("recovery", {"request_id": request_id, "code": "fenced", "retryable": False})
            outcome = "fenced"
        except Exception:
            self.emit(
                "recovery",
                {"request_id": request_id, "code": "outcome_unknown", "retryable": False},
            )
            outcome = "outcome_unknown"
        q = self.quality
        logger.info(
            "conversation.turn",
            command_id=request_id,
            outcome=outcome,
            reason=reason if status == "interrupted" else None,
            calls=q.calls,
            tool_rounds=q.tool_rounds,
            lookups=self.desk.lookups,
            prefetch=q.prefetch,
            violations=q.violations,
            continuations=q.continuations,
            truncated=q.truncated,
            reply_chars=len(self.text),
        )

    async def _publish(self, sentence: str) -> None:
        chunk = sentence if self.text else sentence.lstrip()
        if self.text and not self.text[-1].isspace() and not chunk[:1].isspace():
            chunk = " " + chunk
        if len(self.text) + len(chunk) > MAX_REPLY_CHARS:
            self.quality.truncated = True
            raise _Stop("incomplete")
        await self.store.checkpoint(self.attempt, self.text + chunk)
        self.text += chunk
        self.emit("delta", {"request_id": self.attempt.request_id, "text": chunk})

    async def _generate(self) -> tuple[str, str]:
        settings = self.settings
        config = provider_config(settings)
        if config is None:
            return "interrupted", "unavailable"
        messages = persona.conversation(
            self.attempt.history, self.attempt.message, settings.analyst_input_tokens
        )
        if wants_facts(self.attempt.message):
            self.quality.prefetch = True
            self.emit("checking", {"request_id": self.attempt.request_id})
            found = await self.desk.lookup(self.attempt.message)
            if found["status"] == "found":
                messages.insert(-1, persona.facts_note(found["facts"], found.get("message")))
            elif found["status"] == "unavailable":
                messages.insert(-1, persona.unavailable_note())
        timeout = httpx.Timeout(settings.ai_request_timeout_seconds, connect=5.0)
        async with httpx.AsyncClient(
            timeout=timeout, trust_env=False, follow_redirects=False
        ) as client:
            while True:
                if self.quality.calls >= settings.analyst_max_model_calls:
                    return "interrupted", "incomplete"
                offer_tools = self.quality.tool_rounds < settings.analyst_max_tool_rounds
                completion, said, violation = await self._call(
                    client, config, messages, offer_tools
                )
                if violation is not None:
                    self.quality.violations.append(violation.reason)
                    if self.quality.continuations:
                        return "interrupted", "incomplete"
                    self.quality.continuations += 1
                    if self.text:
                        messages.append({"role": "assistant", "content": self.text})
                    messages.append(persona.continuation_note(violation))
                    continue
                if completion.tool_calls:
                    self.quality.tool_rounds += 1
                    self.emit("checking", {"request_id": self.attempt.request_id})
                    messages.append(self._assistant_tools(said, completion.tool_calls))
                    messages.extend(await self._answer(completion.tool_calls))
                    continue
                if completion.finish == "stop":
                    return "complete", ""
                self.quality.truncated = True
                return "interrupted", "incomplete"

    async def _call(
        self,
        client: httpx.AsyncClient,
        config: ProviderConfig,
        messages: list[dict[str, Any]],
        offer_tools: bool,
    ) -> tuple[Completion, str, Violation | None]:
        reservation = await BudgetReservation.reserve(self.settings.analyst_call_reservation_usd)
        if reservation is None:
            raise _Stop("budget")
        self.quality.calls += 1
        completion = Completion()
        said = ""
        violation: Violation | None = None
        body = request_body(config, messages, [persona.LOOKUP_TOOL] if offer_tools else None)
        try:
            async with aclosing(stream_completion(client, config, body, completion)) as stream:
                async for text in stream:
                    said += text
                    for compiled in self.publication.feed(text):
                        if isinstance(compiled, Violation):
                            violation = compiled
                            break
                        await self._publish(compiled)
                    if violation is not None:
                        break
            if violation is None and completion.finish in {"stop", "tool_calls"}:
                for compiled in self.publication.end():
                    if isinstance(compiled, Violation):
                        violation = compiled
                        break
                    await self._publish(compiled)
        finally:
            await reservation.settle(completion.cost)
        return completion, said, violation

    @staticmethod
    def _assistant_tools(said: str, calls: list[ToolCallDraft]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": said or None,
            "tool_calls": [
                {
                    "id": call.id or f"call_{call.index}",
                    "type": "function",
                    "function": {"name": call.name or "unknown", "arguments": call.arguments},
                }
                for call in calls
            ],
        }

    async def _answer(self, calls: list[ToolCallDraft]) -> list[dict[str, Any]]:
        results = []
        for position, call in enumerate(calls):
            content = await self._tool_result(call, position)
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id or f"call_{call.index}",
                    "content": json.dumps(content, ensure_ascii=False),
                }
            )
        return results

    async def _tool_result(self, call: ToolCallDraft, position: int) -> dict[str, Any]:
        if self.quality.tool_rounds > self.settings.analyst_max_tool_rounds:
            return {"status": "error", "error": "lookup limit reached for this reply"}
        if call.name != "lookup":
            return {"status": "error", "error": "unsupported tool"}
        try:
            arguments = json.loads(call.arguments)
        except ValueError:
            arguments = None
        question = arguments.get("question") if isinstance(arguments, dict) else None
        if not isinstance(question, str) or not question.strip():
            return {"status": "error", "error": "invalid arguments: a question is required"}
        if position >= MAX_LOOKUPS_PER_ROUND:
            return {"status": "error", "error": "too many lookups at once; ask one question"}
        return await self.desk.lookup(question)
