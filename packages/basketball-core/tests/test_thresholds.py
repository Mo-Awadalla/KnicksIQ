import pytest
from basketball_core.analytics.thresholds import StatThreshold, parse_stat_threshold


@pytest.mark.parametrize(
    "text,stat,comparison,value",
    [
        ("Which games did Jalen Brunson score more than 40 points?", "points", "gt", 40),
        ("Brunson games with over 40 points", "points", "gt", 40),
        ("In how many games did Brunson score at least 40?", "points", "gte", 40),
        ("How many 40+ point games did Brunson have?", "points", "gte", 40),
        ("Games where Brunson scored 40 or more points", "points", "gte", 40),
        ("Games where Brunson scored 40 points or more", "points", "gte", 40),
        ("How many games did Hart score fewer than 10 points?", "points", "lt", 10),
        ("How many games did Hart score under 10?", "points", "lt", 10),
        ("Which games did Towns grab more than 15 rebounds?", "rebounds", "gt", 15),
        ("How many games did Brunson have at least 10 assists?", "assists", "gte", 10),
        ("Games with 3+ steals for Hart", "steals", "gte", 3),
        ("How many games did Robinson have more than 4 blocks?", "blocks", "gt", 4),
        ("Which games did Bridges make at least 5 three-pointers?", "threes_made", "gte", 5),
        ("Which games did Bridges hit more than 4 threes?", "threes_made", "gt", 4),
    ],
)
def test_threshold_phrases_select_comparison_and_registry_stat(text, stat, comparison, value):
    assert parse_stat_threshold(text) == StatThreshold(stat, comparison, value)


@pytest.mark.parametrize(
    "text",
    [
        "How many points did Brunson average?",
        "What did Brunson score in his last 10 games?",
        "How did Brunson play on 2026-02-04?",
        "Who scored the most points?",
    ],
)
def test_text_without_a_stat_threshold_is_not_parsed(text):
    assert parse_stat_threshold(text) is None


@pytest.mark.parametrize(
    "comparison,observed,expected",
    [
        ("gt", 40, False),
        ("gt", 41, True),
        ("gte", 40, True),
        ("gte", 39, False),
        ("lt", 40, False),
        ("lt", 39, True),
    ],
)
def test_boundary_40_follows_the_requested_comparison(comparison, observed, expected):
    assert StatThreshold("points", comparison, 40).meets({"points": observed}) is expected
