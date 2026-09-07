"""Hand-calculated label-review checks independent of application answer generation."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "draft_labels", Path(__file__).with_name("draft_labels.py")
)
labels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labels)


def fixture():
    games = [
        {
            "nba_game_id": str(i),
            "game_date": f"2026-01-{i:02}",
            "home_team_id": "NYK",
            "away_team_id": "BOS",
            "home_score": 10 + i,
            "away_score": 10,
            "season_type": "regular",
        }
        for i in range(1, 8)
    ]
    return {
        "data": {
            "games": games,
            "players": [{"nba_player_id": 1, "full_name": "Jalen Brunson"}],
            "teams": [{"id": "NYK", "conference": "East"}, {"id": "BOS", "conference": "East"}],
            "player_game_stats": [
                {
                    "nba_game_id": str(i),
                    "nba_player_id": 1,
                    "team_id": "NYK",
                    "minutes": 20 if i != 6 else 0,
                    "points": i if i != 6 else 0,
                }
                for i in range(1, 8)
            ],
        }
    }


def case(id, question, answerable=True, route="table_rag"):
    return {
        "id": id,
        "category": id.rsplit("-", 1)[0],
        "question": question,
        "answerable": answerable,
        "expected_route": route,
    }


def test_player_last_n_counts_appearances_not_team_games():
    rows, _ = labels.review_cases(
        fixture(), [case("date_range_last_n-003", "Brunson last 5 games")]
    )
    fact = rows[0]["proposed_label"]["canonical_facts"][0]
    # Appearances are 1,2,3,4,5,7; last five are 2+3+4+5+7 = 21, not last five team games.
    assert fact["numerator"] == 21
    assert fact["denominator"] == 5
    assert fact["value"] == 4.2
    assert "box:2:1" in fact["canonical_evidence_ids"]
    assert "box:6:1" not in fact["canonical_evidence_ids"]


def test_owner_pending_review_preserves_original_labels_and_input():
    payload = fixture()
    original = case("comparisons-007", "Compare the two Knicks games against Boston.")
    before = labels.digest(payload)
    rows, _ = labels.review_cases(payload, [original])
    result = rows[0]
    for key, value in original.items():
        assert result[key] == value
    assert result["label_status"] == "agent_reviewed_owner_pending"
    assert result["owner_approval"] is None
    assert result["proposed_label"]["disposition"] == "clarify"
    assert labels.digest(payload) == before


def test_numeric_average_keeps_exact_fraction_for_review():
    rows, _ = labels.review_cases(fixture(), [case("exact_statistics-003", "Average points?")])
    fact = rows[0]["proposed_label"]["canonical_facts"][0]
    assert fact["value"] == 14
    assert fact["numerator"] == 98
    assert fact["denominator"] == 7
