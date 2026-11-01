from __future__ import annotations

from app.tests.test_metric_authority import _claims, _deterministic, _seed


async def test_assist_threshold_counts_and_describes_assists(db_session):
    release = await _seed(
        db_session,
        [
            ("2025-11-01", "NYK", "BOS", 110, 100),
            ("2025-11-05", "NYK", "DET", 110, 100),
            ("2025-11-09", "NYK", "MIA", 110, 100),
        ],
        box={"Jalen Brunson": [(35, 30, 5, 1, 3), (35, 30, 10, 1, 3), (35, 30, 12, 1, 3)]},
    )
    _, _, result = await _deterministic(
        db_session, release, "How many games did Brunson have at least 10 assists?"
    )
    claim = _claims(result)["assists:threshold"][0]
    assert claim["value"] == 2
    assert claim["denominator"] == 3
    assert "assists" in claim["statement"]
