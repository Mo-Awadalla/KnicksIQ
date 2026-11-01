"""The approved run a recorded response was collected under.

Collection under an approved run stamps every record with that run's identity, so
a provider-free recording cannot be relabelled as service evidence later and a
meter from one run cannot be attached to another run's responses. The stamp is
read as data at the response boundary and never inferred.

A stamp names a run; it does not prove one. The candidate's own signature is the
part it cannot borrow: :func:`record_binding` reads both halves of a record's
binding together and refuses a record whose proof names a different run, so a
row can never carry one run's meter under another run's signature. Either half
may be absent (a provider-free recording has neither); what exists must agree.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.evaluation.candidate_proof import ProofError, ResponseProof

_HEX = re.compile(r"^[0-9a-f]{64}$")
SCOPES = frozenset({"provider", "local_fake"})


class RunStampError(ValueError):
    """A response record's run stamp cannot be read without guessing."""


@dataclass(frozen=True)
class RunStamp:
    run_id: str
    approval_sha256: str
    config_sha256: str
    scope: str

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "approval_sha256": self.approval_sha256,
            "config_sha256": self.config_sha256,
            "scope": self.scope,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> RunStamp | None:
        raw = record.get("run")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise RunStampError("record run stamp is not an object")
        stamp = cls(
            run_id=str(raw.get("run_id") or ""),
            approval_sha256=str(raw.get("approval_sha256") or ""),
            config_sha256=str(raw.get("config_sha256") or ""),
            scope=str(raw.get("scope") or ""),
        )
        if not stamp.run_id or not _HEX.match(stamp.approval_sha256):
            raise RunStampError("record run stamp is incomplete")
        if not _HEX.match(stamp.config_sha256):
            raise RunStampError("record run stamp carries no verified configuration")
        if stamp.scope not in SCOPES:
            raise RunStampError("record run stamp carries no collection scope")
        return stamp


@dataclass(frozen=True)
class RecordBinding:
    """Both halves of a record's binding: the run it claims and the signature it carries."""

    stamp: RunStamp | None = None
    proof: ResponseProof | None = None

    def __post_init__(self) -> None:
        stamp, proof = self.stamp, self.proof
        if stamp is None or proof is None:
            return
        mismatched = [
            name
            for name, left, right in (
                ("run_id", stamp.run_id, proof.run_id),
                ("approval_sha256", stamp.approval_sha256, proof.approval_sha256),
                ("config_sha256", stamp.config_sha256, proof.config_sha256),
                ("scope", stamp.scope, proof.scope),
            )
            if left != right
        ]
        if mismatched:
            raise RunStampError(
                "the record's run stamp and candidate proof disagree on " + ", ".join(mismatched)
            )


def record_binding(record: Mapping[str, Any]) -> RecordBinding:
    """Read both halves of one record's binding; either may be absent, neither may be wrong."""
    return RecordBinding(
        stamp=RunStamp.from_record(dict(record)),
        proof=ResponseProof.from_record(record),
    )


__all__ = ["ProofError", "RecordBinding", "RunStamp", "RunStampError", "record_binding"]
