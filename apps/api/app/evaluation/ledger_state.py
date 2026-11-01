"""Decode and replay the append-only evaluation budget."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from app.evaluation.spend_bound import MAX_ATTEMPTS, SpendBound, SpendError

LEDGER_SCHEMA = "evaluation-attempt-ledger-v2"

_COMMON = {"schema", "kind", "run_id", "config_sha256", "pid", "at"}
_KIND_FIELDS = {
    "claim": {
        "approval_sha256",
        "max_attempts",
        "spend_bound",
        "model",
        "base_url",
    },
    "admitted": {
        "seq",
        "stage",
        "model",
        "base_url",
        "request_sha256",
        "reserved_nano_usd",
        "output_limit",
    },
    "settled": {
        "seq",
        "request_sha256",
        "prompt_tokens",
        "completion_tokens",
        "charged_nano_usd",
    },
    "refused": {"reason", "model", "base_url"},
    "sealed": set(),
}
_INTEGER_FIELDS = {
    "pid",
    "max_attempts",
    "seq",
    "reserved_nano_usd",
    "output_limit",
    "prompt_tokens",
    "completion_tokens",
    "charged_nano_usd",
}
_ZERO_ALLOWED = {"completion_tokens", "charged_nano_usd"}
_HASH_FIELDS = {"config_sha256", "approval_sha256", "request_sha256"}


class StateError(ValueError):
    """The persisted budget cannot be trusted."""


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class LedgerBinding:
    run_id: str
    config_sha256: str
    approval_sha256: str
    max_attempts: int
    model: str
    base_url: str
    spend_bound: SpendBound

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise StateError("run identity is missing")
        if not _hash(self.config_sha256) or not _hash(self.approval_sha256):
            raise StateError("ledger binding digests are missing")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= MAX_ATTEMPTS:
            raise StateError("attempt cap is outside the approved profile")
        if not isinstance(self.model, str) or not self.model:
            raise StateError("model is missing")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise StateError("provider origin is missing")


@dataclass(frozen=True)
class LedgerRecord:
    kind: str
    run_id: str
    config_sha256: str
    pid: int
    at: str
    approval_sha256: str = ""
    max_attempts: int = 0
    spend_bound: SpendBound | None = None
    seq: int = 0
    stage: str = ""
    model: str = ""
    base_url: str = ""
    request_sha256: str = ""
    reserved_nano_usd: int = 0
    output_limit: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    charged_nano_usd: int = 0
    reason: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> LedgerRecord:
        if not isinstance(payload, dict):
            raise StateError("ledger record is not an object")
        kind = payload.get("kind")
        if not isinstance(kind, str) or kind not in _KIND_FIELDS:
            raise StateError("ledger record has an unknown kind")
        if payload.get("schema") != LEDGER_SCHEMA:
            raise StateError("ledger schema is not supported")
        if set(payload) != _COMMON | _KIND_FIELDS[kind]:
            raise StateError("ledger record has missing or unexpected fields")

        data = {key: value for key, value in payload.items() if key != "schema"}
        for key, value in data.items():
            if key == "spend_bound":
                continue
            if key in _INTEGER_FIELDS:
                minimum = 0 if key in _ZERO_ALLOWED else 1
                if type(value) is not int or value < minimum:
                    raise StateError(f"ledger field {key} is not a valid integer")
            elif not isinstance(value, str) or not value.strip():
                raise StateError(f"ledger field {key} is missing")
            if key in _HASH_FIELDS and not _hash(value):
                raise StateError(f"ledger field {key} is not a digest")
        try:
            datetime.fromisoformat(data["at"])
        except ValueError as exc:
            raise StateError("ledger timestamp is invalid") from exc
        if "spend_bound" in data:
            try:
                data["spend_bound"] = SpendBound.from_dict(data["spend_bound"])
            except SpendError as exc:
                raise StateError("ledger spend profile is invalid") from exc
        return cls(**data)


def parse_records(raw: bytes) -> tuple[LedgerRecord, ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise StateError("ledger ends with an incomplete record")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StateError("ledger is not UTF-8") from exc
    records: list[LedgerRecord] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise StateError(f"ledger line {number} is empty")
        try:
            records.append(LedgerRecord.from_payload(json.loads(line)))
        except (json.JSONDecodeError, StateError) as exc:
            raise StateError(f"ledger line {number} is invalid: {exc}") from exc
    return tuple(records)


@dataclass(frozen=True)
class LedgerState:
    records: tuple[LedgerRecord, ...]
    claim: LedgerRecord | None
    attempts: tuple[LedgerRecord, ...]
    settlements: Mapping[int, LedgerRecord]
    refused: int
    sealed: bool
    settled_upper_nano_usd: int
    outstanding_nano_usd: int

    @property
    def upper_cost_nano_usd(self) -> int:
        return self.settled_upper_nano_usd + self.outstanding_nano_usd


def admission_denial(
    attempt_count: int,
    upper_cost_nano_usd: int,
    binding: LedgerBinding,
) -> str | None:
    if attempt_count >= binding.max_attempts:
        return "attempt_budget_exhausted"
    spend = binding.spend_bound
    if upper_cost_nano_usd + spend.reservation_nano_usd > spend.max_total_nano_usd:
        return "dollar_budget_exhausted"
    return None


def replay(records: tuple[LedgerRecord, ...], binding: LedgerBinding) -> LedgerState:
    claim: LedgerRecord | None = None
    attempts: list[LedgerRecord] = []
    settlements: dict[int, LedgerRecord] = {}
    refused = 0
    sealed = False
    settled_upper = 0
    spend = binding.spend_bound
    reservation = spend.reservation_nano_usd

    for position, record in enumerate(records):
        if record.run_id != binding.run_id or record.config_sha256 != binding.config_sha256:
            raise StateError("ledger belongs to a different run configuration")
        if sealed:
            raise StateError("ledger has a record after its terminal seal")

        if record.kind == "claim":
            if position != 0 or claim is not None:
                raise StateError("ledger claim is not unique and first")
            actual = (
                record.approval_sha256,
                record.max_attempts,
                record.model,
                record.base_url,
                record.spend_bound,
            )
            expected = (
                binding.approval_sha256,
                binding.max_attempts,
                binding.model,
                binding.base_url,
                spend,
            )
            if actual != expected:
                raise StateError("ledger claim does not match the issued binding")
            claim = record
            continue

        if claim is None:
            raise StateError("ledger event precedes its claim")

        if record.kind == "admitted":
            if record.seq != len(attempts) + 1:
                raise StateError("admission sequence has a gap or duplicate")
            if record.model != binding.model or record.base_url != binding.base_url:
                raise StateError("admission names an unapproved provider or model")
            if record.reserved_nano_usd != reservation:
                raise StateError("admission does not reserve the whole context")
            if not 1 <= record.output_limit <= spend.max_completion_tokens:
                raise StateError("admission output limit exceeds its profile")
            outstanding = (len(attempts) - len(settlements)) * reservation
            if admission_denial(len(attempts), settled_upper + outstanding, binding):
                raise StateError("ledger admitted beyond an approved budget")
            attempts.append(record)

        elif record.kind == "settled":
            if record.seq > len(attempts) or record.seq in settlements:
                raise StateError("settlement is unknown or duplicated")
            attempt = attempts[record.seq - 1]
            if record.request_sha256 != attempt.request_sha256:
                raise StateError("settlement references a different request")
            usage = spend.usage(
                {
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                },
                output_limit=attempt.output_limit,
            )
            if usage is None:
                raise StateError("settlement contains invalid token usage")
            charged = spend.charge(usage)
            if charged != record.charged_nano_usd or charged > reservation:
                raise StateError("settlement charge does not reproduce its usage")
            settlements[record.seq] = record
            settled_upper += charged

        elif record.kind == "refused":
            if record.model != binding.model or record.base_url != binding.base_url:
                # A guard denial may describe the rejected model or origin.
                if record.reason not in {
                    "model_not_approved",
                    "origin_not_approved",
                }:
                    raise StateError("budget refusal names a different provider")
            refused += 1

        elif record.kind == "sealed":
            sealed = True

    outstanding = (len(attempts) - len(settlements)) * reservation
    return LedgerState(
        records=records,
        claim=claim,
        attempts=tuple(attempts),
        settlements=MappingProxyType(settlements),
        refused=refused,
        sealed=sealed,
        settled_upper_nano_usd=settled_upper,
        outstanding_nano_usd=outstanding,
    )
