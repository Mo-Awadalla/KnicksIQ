from collections import Counter

from app.evaluation.build_candidate_set import build


def test_candidate_set_has_requested_shape_and_distribution():
    cases = build()
    assert len(cases) == 120
    assert Counter(case["category"] for case in cases) == {
        "exact_statistics": 25,
        "date_range_last_n": 15,
        "comparisons": 15,
        "single_game_narrative": 20,
        "turning_points": 10,
        "follow_ups": 10,
        "aliases_typos": 10,
        "unsupported": 15,
    }
    required = {
        "question",
        "expected_route",
        "relevant_evidence_ids",
        "required_facts",
        "answerable",
        "filters",
    }
    assert all(required <= case.keys() for case in cases)
