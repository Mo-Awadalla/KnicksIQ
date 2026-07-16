"""Player-intelligence formula and detector semantics."""

from basketball_core.analytics import (
    FactCandidate,
    aggregate_rows,
    build_fact_catalog,
    count_double_doubles,
    fact_fingerprint,
    linear_slope,
    robust_outlier_scores,
    score_fact_candidate,
)


def test_weighted_percentages_and_total_minute_per_36() -> None:
    rows = [
        {
            "points": 18,
            "minutes": 18,
            "field_goals_made": 6,
            "field_goals_attempted": 10,
            "free_throws_attempted": 4,
        },
        {
            "points": 18,
            "minutes": 36,
            "field_goals_made": 3,
            "field_goals_attempted": 10,
            "free_throws_attempted": 0,
        },
    ]
    values = aggregate_rows(
        rows,
        ["field_goal_percentage", "true_shooting_percentage", "points_per_36"],
    )
    assert values["field_goal_percentage"] == 45
    assert values["points_per_36"] == 24
    assert round(values["true_shooting_percentage"] or 0, 3) == 82.721


def test_zero_denominators_are_null_and_multi_category_doubles_include_defense() -> None:
    values = aggregate_rows(
        [{"points": 0, "minutes": 0, "assists": 0, "turnovers": 0}],
        [
            "field_goal_percentage",
            "true_shooting_percentage",
            "points_per_36",
            "assist_turnover_ratio",
        ],
    )
    assert set(values.values()) == {None}
    assert count_double_doubles(
        {"points": 10, "rebounds": 2, "assists": 2, "steals": 10, "blocks": 10}
    ) == (True, True)


def test_robust_outliers_trend_and_fact_score_are_deterministic() -> None:
    scores = robust_outlier_scores([8, 9, 10, 11, 30])
    assert scores[-1] > 0
    assert linear_slope([1, 2, 3, 4]) == 1
    candidate = FactCandidate(
        fact_type="test",
        player_ids=(1,),
        stat_keys=("points",),
        timeframe={"kind": "full_archive"},
        statement="Test",
        result={"delta": 4},
        source_game_ids=(1, 2),
        sample_size=2,
        components={
            name: 1
            for name in (
                "magnitude",
                "rarity",
                "sample_quality",
                "recency",
                "coverage",
                "basketball_relevance",
                "novelty",
                "interpretability",
            )
        },
        penalties={"small_sample": 0.2},
    )
    assert score_fact_candidate(candidate)[0] == 0.8
    assert fact_fingerprint(candidate) == fact_fingerprint(candidate)


def test_offline_catalog_contains_required_windows_and_stable_fingerprints() -> None:
    games = [
        {
            "nba_game_id": f"game-{index}",
            "game_date": (
                f"2026-{1 if index < 8 else 2:02d}-{index if index < 8 else index - 7:02d}"
            ),
            "season_type": "regular" if index < 13 else "playoffs",
        }
        for index in range(1, 15)
    ]
    stats = [
        {
            "nba_game_id": f"game-{index}",
            "nba_player_id": 1,
            "team_id": "NYK",
            "minutes": 30,
            "points": 10 if index <= 4 else 25,
            "rebounds": 8,
            "assists": 6,
            "three_pointers_made": 2,
            "field_goals_attempted": 12,
            "free_throws_attempted": 3,
        }
        for index in range(1, 15)
    ]
    players = [{"nba_player_id": 1, "full_name": "Test Player"}]
    first = build_fact_catalog(games, stats, players)
    second = build_fact_catalog(games, stats, players)
    assert [row["fingerprint"] for row in first] == [row["fingerprint"] for row in second]
    labels = {row["timeframe"]["label"] for row in first}
    assert {
        "2025-26 regular season",
        "full 2025-26 archive",
        "latest 10 Knicks games",
        "2026-01",
        "2026-02",
        "Test Player latest 10 appearances",
    }.issubset(labels)
