"""Exact clocks must not be discarded, guessed across periods or normalized incorrectly.

Failure modes are lost literal times, a different quarter with the same clock,
ambiguous multi-clock questions, invalid regulation/overtime clocks, and unequal
zero-padded source representations of the same instant.
"""

from __future__ import annotations

import pytest
from app.services.archive_clock import GameMoment, moment_from_question


@pytest.mark.parametrize(
    "question,periods,expected",
    [
        ("Describe the play at 11:20 left in quarter 1.", [1], (1, 680)),
        ("What happened with 00:13 remaining in quarter 4?", [4], (4, 13)),
        ("Describe the play at 1:20 left.", [2], (2, 80)),
        ("Describe the play at 5:00 left in overtime.", [5], (5, 300)),
        ("Describe the play at 12:00 left.", [1], (1, 720)),
        ("Describe the fourth quarter play at 00:28, and its score.", [4], (4, 28)),
        ("Compare fourth quarter plays at 00:28 and at 00:08.", [4], None),
        ("Describe the fourth quarter play at 0:00.5.", [4], None),
        ("Compare 11:20 and 9:30.", [1], None),
        ("Compare plays at 11:20 left and at 9:30 left.", [1], None),
        ("Describe the play at 1:20 left.", [1, 2], None),
        ("Describe the play at 1:20 left.", [], None),
        ("Describe the play at 12:01 left.", [1], None),
        ("Describe the play at 5:01 left in overtime.", [5], None),
        ("Describe the play at 1:99 left.", [1], None),
        ("The game starts at 7:30 tonight.", [1], None),
        ("Describe the play at 0:00.5 left.", [4], None),
    ],
)
def test_only_a_unique_valid_explicit_game_clock_becomes_a_hard_scope(question, periods, expected):
    moment = moment_from_question(question, periods)
    actual = None if moment is None else (moment.period, moment.seconds_remaining)
    assert actual == expected


def test_clock_match_does_not_admit_another_period_or_instant():
    moment = GameMoment(period=4, seconds_remaining=80)
    assert moment.matches({"period": 4, "clock": "01:20"})
    assert moment.matches({"period": 4, "clock": "1:20"})
    assert not moment.matches({"period": 3, "clock": "01:20"})
    assert not moment.matches({"period": 4, "clock": "01:21"})


@pytest.mark.parametrize("period,seconds", [(0, 1), (1, -1), (1, 721), (5, 301)])
def test_invalid_game_instants_are_not_constructible(period, seconds):
    with pytest.raises(ValueError):
        GameMoment(period=period, seconds_remaining=seconds)
