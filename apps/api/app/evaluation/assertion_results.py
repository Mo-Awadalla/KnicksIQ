"""The result vocabulary the typed assertion checks report through.

Both the value checks and the scope checks produce these, so the record lives below
them instead of inside one of their modules. A check that passes carries no failure;
a check that cannot be proved carries the reason it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssertionFailure:
    code: str
    detail: str = ""
    fact_index: int | None = None


@dataclass(frozen=True)
class FactCheck:
    fact_index: int
    matched_claim_id: str | None
    failures: tuple[AssertionFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures
