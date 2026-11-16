from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

MAX_MESSAGE_CHARS = 1200
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

InterruptedReason = Literal[
    "disconnected", "expired", "unavailable", "budget", "deadline", "incomplete"
]
RejectionCode = Literal[
    "invalid_token",
    "revision_conflict",
    "request_conflict",
    "reply_pending",
    "conversation_busy",
    "conversation_full",
    "not_retryable",
    "not_pending",
    "rate_limited",
    "unavailable",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _canonical_uuid(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("Use the canonical lowercase UUID form")
    return value


CommandId = Annotated[str, AfterValidator(_canonical_uuid)]


class MessageCommand(_Strict):
    kind: Literal["message"]
    request_id: CommandId
    expected_revision: int = Field(ge=0)
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]

    @property
    def target(self) -> str:
        return self.message


class RetryCommand(_Strict):
    kind: Literal["retry"]
    request_id: CommandId
    expected_revision: int = Field(ge=0)
    exchange_id: CommandId

    @property
    def target(self) -> str:
        return self.exchange_id


class CancelCommand(_Strict):
    request_id: CommandId
    expected_revision: int = Field(ge=0)


def command_digest(command: MessageCommand | RetryCommand) -> str:
    body = json.dumps(
        [command.kind, command.expected_revision, command.target], separators=(",", ":")
    )
    return hashlib.sha256(body.encode()).hexdigest()


class Reply(_Strict):
    status: Literal["writing", "complete", "stopped", "interrupted"]
    id: str
    text: str
    reason: InterruptedReason | None = None

    def public(self) -> dict[str, Any]:
        body: dict[str, Any] = {"status": self.status, "id": self.id, "text": self.text}
        if self.status == "interrupted":
            body["reason"] = self.reason or "incomplete"
        return body


class Exchange(_Strict):
    id: str
    message: str
    reply: Reply

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "message": self.message, "reply": self.reply.public()}


class Snapshot(_Strict):
    revision: int = Field(ge=0)
    exchanges: tuple[Exchange, ...] = ()

    def public(self) -> dict[str, Any]:
        return {"revision": self.revision, "exchanges": [item.public() for item in self.exchanges]}


class Rejected(Exception):
    def __init__(self, code: RejectionCode, current_revision: int | None = None):
        super().__init__(code)
        self.code: RejectionCode = code
        self.current_revision = current_revision
