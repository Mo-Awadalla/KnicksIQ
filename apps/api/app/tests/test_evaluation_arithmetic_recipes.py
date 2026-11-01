"""The binding between one calculation receipt and the claim it proves.

Each case writes one small mapping by hand, so the receipt's own digest, sample,
denominator and ingredients can be varied against the formula. A derived ratio is
weighted rather than a mean of ratios, a tautological numerator proves nothing, a
tampered denominator fails the population, a projection that contradicts its own digest
is rejected at load, and a delta with no window is unverified rather than credited.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evaluation.mapping import load_mapping
from app.evaluation.mapping_identity import MappingError
from app.tests.support.evaluation_archive import VERSION
from app.tests.support.evaluation_mapping import (
    _calculation_record,
    _calculation_reference,
    _claim,
    _entry,
    _row_record,
    _write_mapping,
)


def test_derived_ratio_average_is_weighted_not_a_mean_of_ratios(tmp_path: Path) -> None:
    rows = [
        {
            "nba_game_id": "0022500011",
            "nba_player_id": 1628973,
            "minutes": 30,
            "assists": 6,
            "turnovers": 2,
        },
        {
            "nba_game_id": "0022500012",
            "nba_player_id": 1628973,
            "minutes": 30,
            "assists": 4,
            "turnovers": 3,
        },
    ]
    receipts = [f"{VERSION}:game:{index}:player:7" for index in (11, 12)]
    games = [
        {"nba_game_id": "0022500011", "home_team_id": "NYK", "home_score": 110, "away_score": 100},
        {"nba_game_id": "0022500012", "home_team_id": "NYK", "home_score": 111, "away_score": 101},
    ]
    mapping = _write_mapping(
        tmp_path,
        {
            "game:0022500011": _entry("games", games[0], row_id=11, game_id=11, receipt="r11"),
            "game:0022500012": _entry("games", games[1], row_id=12, game_id=12, receipt="r12"),
            "box:0022500011:1628973": _entry(
                "player_game_stats", rows[0], row_id=101, game_id=11, receipt=receipts[0]
            ),
            "box:0022500012:1628973": _entry(
                "player_game_stats", rows[1], row_id=102, game_id=12, receipt=receipts[1]
            ),
        },
        {"1628973": {"id": 7, "name": "Jalen Brunson"}},
    )
    registry = {
        receipts[0]: _row_record(receipts[0], rows[0]),
        receipts[1]: _row_record(receipts[1], rows[1]),
    }
    weighted = 10 / 5
    cases = (
        (weighted, ()),
        ((3.0 + 4 / 3) / 2, ("calculation_arithmetic_mismatch",)),
    )
    for value, problems in cases:
        reference = _calculation_reference(
            subject="player:7",
            metric="assist_turnover_ratio:average",
            sources=receipts,
            value=value,
        )
        record = _calculation_record(reference, receipts, sample_size=2, denominator=2.0)
        resolution = mapping.resolve_citation(
            reference,
            _claim(
                subject="player:7",
                metric="assist_turnover_ratio:average",
                value=value,
                denominator=2.0,
                sample_size=2,
            ),
            registry={**registry, reference: record},
        )
        assert resolution.problems == problems, (value, resolution.problems)
        assert resolution.unverified == ()
        assert resolution.recipe == "box_assist_turnover", value


def test_mapping_rejects_a_projection_that_does_not_match_its_digest(tmp_path: Path) -> None:
    projection = {"nba_game_id": "0022500003", "home_score": 112, "away_score": 104}
    row = _entry("games", projection, row_id=1, game_id=1, receipt=f"{VERSION}:game:1")
    row["source_row"] = {**projection, "home_score": 120}
    path = tmp_path / "runtime-mapping.json"
    path.write_text(
        json.dumps({"version": VERSION, "release_id": 1, "rows": {"game:0022500003": row}}),
        encoding="utf-8",
    )
    with pytest.raises(MappingError):
        load_mapping(path)


def test_a_rate_recipe_citing_final_scores_is_invalid(tmp_path: Path) -> None:
    projection = {
        "nba_game_id": "0022500003",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "home_score": 112,
        "away_score": 104,
    }
    receipt = f"{VERSION}:game:1"
    mapping = _write_mapping(
        tmp_path,
        {"game:0022500003": _entry("games", projection, row_id=1, game_id=1, receipt=receipt)},
    )
    value = 40.0
    reference = _calculation_reference(
        subject="team:NYK", metric="three_pointers_made:percentage", sources=[receipt], value=value
    )
    record = _calculation_record(
        reference, [receipt], sample_size=1, denominator=1.0, decimals=4, made=4, attempted=10
    )
    resolution = mapping.resolve_citation(
        reference,
        _claim(
            subject="team:NYK",
            metric="three_pointers_made:percentage",
            value=value,
            denominator=1.0,
            sample_size=1,
        ),
        registry={receipt: _row_record(receipt, projection), reference: record},
    )
    assert resolution.problems == ("calculation_expansion_mismatch",)
    assert resolution.unverified == ()


def test_a_tautological_numerator_never_proves_the_mean(tmp_path: Path) -> None:
    projection = {
        "nba_game_id": "0022500003",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "home_score": 112,
        "away_score": 104,
    }
    receipt = f"{VERSION}:game:1"
    mapping = _write_mapping(
        tmp_path,
        {"game:0022500003": _entry("games", projection, row_id=1, game_id=1, receipt=receipt)},
    )
    value = 26.0
    reference = _calculation_reference(
        subject="team:NYK", metric="points_per_game", sources=[receipt], value=value
    )
    record = _calculation_record(
        reference, [receipt], sample_size=1, denominator=1.0, numerator=26.0, decimals=1
    )
    resolution = mapping.resolve_citation(
        reference,
        _claim(
            subject="team:NYK",
            metric="points_per_game",
            value=value,
            denominator=1.0,
            sample_size=1,
        ),
        registry={receipt: _row_record(receipt, projection), reference: record},
    )
    assert resolution.problems == ("calculation_arithmetic_mismatch",)


def test_a_tampered_denominator_fails_the_population(tmp_path: Path) -> None:
    projection = {
        "nba_game_id": "0022500003",
        "home_team_id": "NYK",
        "away_team_id": "BOS",
        "home_score": 112,
        "away_score": 104,
    }
    receipt = f"{VERSION}:game:1"
    mapping = _write_mapping(
        tmp_path,
        {"game:0022500003": _entry("games", projection, row_id=1, game_id=1, receipt=receipt)},
    )
    value = 56.0
    reference = _calculation_reference(
        subject="team:NYK", metric="points_per_game", sources=[receipt], value=value
    )
    record = _calculation_record(
        reference, [receipt], sample_size=1, denominator=2.0, numerator=112.0, decimals=1
    )
    resolution = mapping.resolve_citation(
        reference,
        _claim(
            subject="team:NYK",
            metric="points_per_game",
            value=value,
            denominator=2.0,
            sample_size=1,
        ),
        registry={receipt: _row_record(receipt, projection), reference: record},
    )
    assert "calculation_population_mismatch" in resolution.problems


def test_a_delta_without_a_window_is_unverified_not_credited(tmp_path: Path) -> None:
    projection = {
        "nba_game_id": "0022500003",
        "nba_player_id": 1628973,
        "points": 30,
        "rebounds": 4,
        "assists": 6,
        "turnovers": 2,
        "steals": 1,
        "blocks": 0,
    }
    receipt = f"{VERSION}:game:1:player:7"
    mapping = _write_mapping(
        tmp_path,
        {
            "box:0022500003:1628973": _entry(
                "player_game_stats", projection, row_id=7, game_id=1, receipt=receipt
            )
        },
    )
    value = 5.0
    reference = _calculation_reference(
        subject="player:7", metric="points:delta", sources=[receipt], value=value
    )
    record = _calculation_record(reference, [receipt], sample_size=1, denominator=1.0)
    resolution = mapping.resolve_citation(
        reference,
        _claim(
            subject="player:7",
            metric="points:delta",
            value=value,
            denominator=1.0,
            sample_size=1,
        ),
        registry={receipt: _row_record(receipt, projection), reference: record},
    )
    assert resolution.problems == ()
    assert resolution.unverified == ("calculation_window_unverified",)
    assert not resolution.resolved
