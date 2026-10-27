"""Unsupported held-out v2 questions. Each one must decline without inventing data."""

from __future__ import annotations

from .cases import Case


def _unsupported(question: str) -> Case:
    return Case(
        "unsupported",
        question,
        None,
        False,
        lambda a, phase: ([], [], []),
        {},
    )


UNSUPPORTED: list[Case] = [
    _unsupported("What's the live spread on tonight's game?"),
    _unsupported("Are they favored in the next one?"),
    _unsupported("Any word on the backup center's injury?"),
    _unsupported("Should they trade for a shooter before the deadline?"),
    _unsupported("How many wins will they finish with next season?"),
    _unsupported("Where do they sit in the standings right now?"),
    _unsupported("Did they play last night?"),
    _unsupported("What happened in the 1999 Finals?"),
    _unsupported("Will the coach change the starting lineup tomorrow?"),
    _unsupported("What's the locker room mood after that loss?"),
    _unsupported("Can you pull up tonight's box score?"),
    _unsupported("Who's the best player in the league right now?"),
]
