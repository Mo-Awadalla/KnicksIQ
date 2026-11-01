"""The identity vocabulary a release mapping is made of.

A mapping is a set of canonical rows, the documents that hang off them and the verdict
one citation resolves to. These types are the mapping's public nouns: they are pure
data with no knowledge of how a mapping is loaded or how a citation is proved, so the
loader, the citation engine and their callers can all name the same things.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal


class MappingError(ValueError):
    pass


@dataclass(frozen=True)
class SourceRow:
    canonical_id: str
    collection: str
    row_sha256: str
    database_row_id: int
    game_id: int
    release_id: int
    runtime_receipt: str | None
    player_id: int | None
    # The verified SQL projection of this row. It is the independent oracle for
    # whole-population recipes; it never stands in for an issued receipt.
    source_row: dict[str, Any] | None = None


@dataclass(frozen=True)
class DocumentIdentity:
    runtime_evidence_id: str
    collection: str
    game_id: int
    point_id: str
    payload_sha256: str


@dataclass(frozen=True)
class CitationResolution:
    """What one citation reference resolves to, or why it does not."""

    reference: str
    kind: Literal["receipt", "calculation", "document", "unresolved"]
    canonical_ids: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    recipe: str | None = None
    problems: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.kind != "unresolved" and not self.problems and not self.unverified


def unresolved(reference: str, problem: str) -> CitationResolution:
    """A reference the mapping cannot place, with the one reason it cannot."""
    return CitationResolution(reference, "unresolved", problems=(problem,))


def calculation(
    reference: str,
    canonical: tuple[str, ...] = (),
    sources: tuple[str, ...] = (),
    problems: tuple[str, ...] = (),
    unverified: tuple[str, ...] = (),
    recipe: str | None = None,
) -> CitationResolution:
    """A calculation citation: proved from its sources, or failing for the recorded reason."""
    return CitationResolution(
        reference,
        "calculation",
        canonical,
        sources,
        recipe,
        problems,
        unverified,
    )


def parse_evidence_reference(reference: str) -> tuple[str, str, int, int] | None:
    """Parse ``<release>:<collection>:<game>:<source>`` and the team/period marker shape."""
    parts = reference.split(":")
    if len(parts) == 5 and parts[3] in {"team", "period"}:
        parts = [parts[0], parts[1], parts[2], parts[4]]
    if len(parts) != 4:
        return None
    release, collection, game, source = parts
    if not release or not game.isdigit() or not source.isdigit():
        return None
    return release, collection, int(game), int(source)


def calculation_digest(
    version: str, subject: str, metric: str, sources: list[str], value: Any
) -> str:
    """The receipt body a calculation citation must carry for its own claim."""
    payload = json.dumps([version, subject, metric, sources, value], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
