"""One durable authority for evaluation attempts and upper-cost accounting."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation import ledger_state as protocol


class LedgerError(RuntimeError):
    """The ledger cannot be read, written or trusted."""


class ProviderBudgetExhausted(LedgerError):
    """No further request fits the approved attempt or dollar budget."""


class LedgerSealed(LedgerError):
    """The terminal seal forbids further mutation."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def read_records(path: Path) -> tuple[protocol.LedgerRecord, ...]:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise LedgerError(f"ledger {path} is unreadable") from exc
    try:
        return protocol.parse_records(raw)
    except protocol.StateError as exc:
        raise LedgerError(str(exc)) from exc


def _append(fd: int, payload: dict[str, Any]) -> None:
    encoded = memoryview(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    while encoded:
        written = os.write(fd, encoded)
        if written <= 0:
            raise OSError("Ledger write made no progress")
        encoded = encoded[written:]
    os.fsync(fd)


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1 << 16)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


@contextmanager
def _exclusive(path: Path) -> Iterator[int]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    except OSError as exc:
        raise LedgerError(f"ledger {path} cannot be opened") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield fd
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class AttemptLedger:
    def __init__(self, path: Path, *, binding: protocol.LedgerBinding) -> None:
        self.path = Path(path)
        self.binding = binding
        self._lock = threading.Lock()

    def _snapshot(self, fd: int) -> protocol.LedgerState:
        try:
            return protocol.replay(protocol.parse_records(_read_fd(fd)), self.binding)
        except protocol.StateError as exc:
            raise LedgerError(str(exc)) from exc

    def _commit(
        self,
        fd: int,
        current: protocol.LedgerState,
        kind: str,
        **fields: Any,
    ) -> None:
        payload = {
            "schema": protocol.LEDGER_SCHEMA,
            "kind": kind,
            "run_id": self.binding.run_id,
            "config_sha256": self.binding.config_sha256,
            "pid": os.getpid(),
            "at": _now(),
            **fields,
        }
        try:
            record = protocol.LedgerRecord.from_payload(payload)
            protocol.replay(current.records + (record,), self.binding)
        except protocol.StateError as exc:
            raise LedgerError(str(exc)) from exc
        _append(fd, payload)

    def snapshot(self) -> protocol.LedgerState:
        with self._lock, _exclusive(self.path) as fd:
            return self._snapshot(fd)

    def records(self) -> tuple[protocol.LedgerRecord, ...]:
        return self.snapshot().records

    @property
    def used(self) -> int:
        return len(self.snapshot().attempts)

    @property
    def sealed(self) -> bool:
        return self.snapshot().sealed

    def claim(self) -> int:
        with self._lock, _exclusive(self.path) as fd:
            current = self._snapshot(fd)
            if current.sealed:
                raise LedgerSealed("sealed approval cannot serve a new candidate")
            if current.claim is not None:
                return 1
            self._commit(
                fd,
                current,
                "claim",
                approval_sha256=self.binding.approval_sha256,
                max_attempts=self.binding.max_attempts,
                spend_bound=self.binding.spend_bound.payload(),
                model=self.binding.model,
                base_url=self.binding.base_url,
            )
            return 1

    def admit(
        self,
        *,
        stage: str,
        model: str,
        base_url: str,
        request_sha256: str,
        output_limit: int,
    ) -> int:
        with self._lock, _exclusive(self.path) as fd:
            current = self._snapshot(fd)
            if current.sealed:
                raise LedgerSealed("sealed run cannot admit another request")
            if current.claim is None:
                raise LedgerError("guard was not claimed before admission")
            reason = protocol.admission_denial(
                len(current.attempts),
                current.upper_cost_nano_usd,
                self.binding,
            )
            if reason is not None:
                self._commit(
                    fd,
                    current,
                    "refused",
                    reason=reason,
                    model=model,
                    base_url=base_url,
                )
                raise ProviderBudgetExhausted(f"{reason}; request refused before the network")
            seq = len(current.attempts) + 1
            self._commit(
                fd,
                current,
                "admitted",
                seq=seq,
                stage=stage,
                model=model,
                base_url=base_url,
                request_sha256=request_sha256,
                reserved_nano_usd=self.binding.spend_bound.reservation_nano_usd,
                output_limit=output_limit,
            )
            return seq

    def settle(self, seq: int, usage: Any) -> bool:
        with self._lock, _exclusive(self.path) as fd:
            current = self._snapshot(fd)
            if type(seq) is not int or not 1 <= seq <= len(current.attempts):
                raise LedgerError("settlement does not name an admitted sequence")
            attempt = current.attempts[seq - 1]
            counts = self.binding.spend_bound.usage(
                usage,
                output_limit=attempt.output_limit,
            )
            existing = current.settlements.get(seq)
            if existing is not None:
                if counts is not None and (
                    existing.prompt_tokens,
                    existing.completion_tokens,
                ) != (counts.prompt_tokens, counts.completion_tokens):
                    raise LedgerError("settlement conflicts with recorded usage")
                return False
            if current.sealed:
                raise LedgerSealed("sealed run cannot receive a new settlement")
            if counts is None:
                return False
            self._commit(
                fd,
                current,
                "settled",
                seq=seq,
                request_sha256=attempt.request_sha256,
                prompt_tokens=counts.prompt_tokens,
                completion_tokens=counts.completion_tokens,
                charged_nano_usd=self.binding.spend_bound.charge(counts),
            )
            return True

    def refuse(self, *, reason: str, model: str, base_url: str) -> None:
        with self._lock, _exclusive(self.path) as fd:
            current = self._snapshot(fd)
            if current.sealed:
                raise LedgerSealed("sealed run cannot append a refusal")
            self._commit(
                fd,
                current,
                "refused",
                reason=reason,
                model=model,
                base_url=base_url,
            )

    def seal(self) -> bool:
        with self._lock, _exclusive(self.path) as fd:
            current = self._snapshot(fd)
            if current.sealed:
                return False
            if current.claim is None:
                raise LedgerError("unclaimed ledger cannot be sealed")
            self._commit(fd, current, "sealed")
            return True


@dataclass(frozen=True)
class Attestation:
    run_id: str
    admitted: int
    refused: int
    sealed: bool
    claims: int
    cap: int
    max_total_nano_usd: int
    reservation_nano_usd: int
    settled_attempts: int
    settled_upper_nano_usd: int | None
    outstanding_nano_usd: int | None
    upper_cost_nano_usd: int | None
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "evaluation-attestation-v2",
            "run_id": self.run_id,
            "admitted": self.admitted,
            "refused": self.refused,
            "cap": self.cap,
            "sealed": self.sealed,
            "claims": self.claims,
            "max_total_nano_usd": self.max_total_nano_usd,
            "reservation_nano_usd": self.reservation_nano_usd,
            "settled_attempts": self.settled_attempts,
            "settled_upper_nano_usd": self.settled_upper_nano_usd,
            "outstanding_nano_usd": self.outstanding_nano_usd,
            "upper_cost_nano_usd": self.upper_cost_nano_usd,
            "problems": list(self.problems),
            "attested": self.ok,
        }


def attest(
    ledger: AttemptLedger,
    *,
    require_sealed: bool = True,
) -> Attestation:
    binding = ledger.binding
    spend = binding.spend_bound
    problems: list[str] = []
    try:
        current = ledger.snapshot()
    except (LedgerError, OSError) as exc:
        current = None
        problems.append(f"ledger_unreadable:{exc}")

    if current is not None:
        if current.claim is None:
            problems.append("guard_never_bound")
        if not current.attempts:
            problems.append("no_attempts_admitted")
        if current.refused:
            problems.append("attempts_refused")
        if require_sealed and not current.sealed:
            problems.append("ledger_not_sealed")

    return Attestation(
        run_id=binding.run_id,
        admitted=len(current.attempts) if current else 0,
        refused=current.refused if current else 0,
        sealed=current.sealed if current else False,
        claims=int(current.claim is not None) if current else 0,
        cap=binding.max_attempts,
        max_total_nano_usd=spend.max_total_nano_usd,
        reservation_nano_usd=spend.reservation_nano_usd,
        settled_attempts=len(current.settlements) if current else 0,
        settled_upper_nano_usd=current.settled_upper_nano_usd if current else None,
        outstanding_nano_usd=current.outstanding_nano_usd if current else None,
        upper_cost_nano_usd=current.upper_cost_nano_usd if current else None,
        problems=tuple(problems),
    )
