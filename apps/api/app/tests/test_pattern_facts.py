"""Deterministic pattern-candidate calculations."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.pattern_facts import generate_pattern_facts


def _rows() -> list[dict]:
    start = date(2026, 1, 1)
    return [
        {
            "game_id": index + 1,
            "date": (start + timedelta(days=index)).isoformat(),
            "player_id": 11,
            "appeared": True,
            "points": 10 + index,
            "home": index % 2 == 0,
            "win": index % 3 != 0,
            "opponent": "BOS" if index < 3 else "TOR",
        }
        for index in range(12)
    ]


def test_pattern_facts_include_reproducible_recent_split_and_streak_metadata():
    facts = generate_pattern_facts(
        _rows(),
        player_id=11,
        metric="points",
        threshold=18,
    )
    by_type = {fact.fact_type: fact for fact in facts}

    trend = by_type["recent_vs_previous"]
    assert trend.values == {
        "recent_average": 19.0,
        "previous_average": 14.0,
        "delta": 5.0,
    }
    assert trend.sample_size == 10
    assert len(trend.game_ids) == 10
    assert trend.calculation_method == ("arithmetic_mean(last_5) - arithmetic_mean(previous_5)")

    streak = by_type["threshold_and_streak"]
    assert streak.values["qualifying_games"] == 4
    assert streak.values["current_streak"] == 4
    assert streak.values["longest_streak"] == 4


def test_small_splits_are_retained_but_visibly_disqualified():
    facts = generate_pattern_facts(
        _rows()[:4],
        player_id=11,
        metric="points",
        minimum_split_sample=3,
    )
    home_road = next(fact for fact in facts if fact.fact_type == "home_vs_road")

    assert home_road.qualified is False
    assert home_road.qualification == "Each side requires at least 3 appearances."


def test_strongest_opponent_split_requires_minimum_sample():
    facts = generate_pattern_facts(
        _rows(),
        player_id=11,
        metric="points",
        minimum_split_sample=3,
    )
    opponent = next(fact for fact in facts if fact.fact_type == "strongest_opponent_split")

    assert opponent.values["opponent_id"] == "TOR"
    assert opponent.sample_size == 9
    assert "require n>=3" in opponent.calculation_method
