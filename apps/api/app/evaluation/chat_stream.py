"""Evaluation transport boundary for the public chat event stream."""

from __future__ import annotations

import json
from typing import Any

EVENTS = {"accepted", "checking", "delta", "settled", "recovery", "evaluation_proof"}


def frame(raw: str) -> tuple[str, dict[str, Any]] | None:
    name, data = "", []
    for line in raw.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if not data:
        return None
    payload = json.loads("\n".join(data))
    if name not in EVENTS or not isinstance(payload, dict):
        raise ValueError("invalid chat event")
    return name, payload


def response_from_events(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    settled = [data for name, data in events if name == "settled"]
    if not settled:
        recovery = [data for name, data in events if name == "recovery"]
        if recovery:
            return {
                "request_id": recovery[-1]["request_id"],
                "recovery": recovery[-1],
                "delta_count": sum(name == "delta" for name, _ in events),
            }
    if len(settled) != 1:
        raise ValueError("chat stream did not settle exactly once")
    terminal = settled[0]
    snapshot = terminal["snapshot"]
    request_id = terminal["request_id"]
    exchange = next(item for item in snapshot["exchanges"] if item["reply"]["id"] == request_id)
    reply = exchange["reply"]
    return {
        "request_id": request_id,
        "text": reply["text"],
        "status": reply["status"],
        "reason": reply.get("reason"),
        "revision": snapshot["revision"],
        "snapshot": snapshot,
        "delta_count": sum(name == "delta" for name, _ in events),
    }


async def stream_turn(
    client: Any, command: dict[str, Any], token: str
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    events = []
    async with client.stream(
        "POST", "/chat/turns", json=command, headers={"X-Chat-Token": token}
    ) as response:
        response.raise_for_status()
        lines = []
        async for line in response.aiter_lines():
            if line:
                lines.append(line)
            else:
                event = frame("\n".join(lines))
                if event:
                    events.append(event)
                lines = []
        if lines:
            raise ValueError("unterminated chat frame")
    body = response_from_events(events)
    if "snapshot" not in body:
        raise ValueError("chat stream requires recovery")
    return body, events
