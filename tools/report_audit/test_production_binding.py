"""Offline checks only: no production connections or provider calls."""

from bind_production import compare


def test_row_comparison_is_order_independent_and_keeps_duplicate_counts():
    assert compare([{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 1}])["matches"]
    result = compare([{"id": 1}, {"id": 1}], [{"id": 1}])
    assert not result["matches"]
    assert result["missing_or_changed"] == 1


def test_changed_row_is_visible_and_not_normalized_to_expected_value():
    result = compare([{"points": 16}], [{"points": 17}])
    assert result["missing_or_changed"] == result["unexpected"] == 1
    assert result["expected_rows_sha256"] != result["actual_rows_sha256"]


def test_observed_hash_inventory_cannot_be_claimed_as_fresh_row_verification():
    from audit import digest
    from bind_observed import bind_observed
    from test_audit import valid_payload

    baseline = valid_payload()
    report = baseline["data"]["reports"][0]
    row = {k: v for k, v in report.items() if k != "nba_game_id"}
    row.update(game_id=7, release_id=1)
    observed = {
        "release": {"id": 1, "version": "test"},
        "report_hashes": [{"id": 80, "game_id": 7, "content_sha256": digest(row)}],
        "report80": report,
    }
    result = bind_observed(baseline, observed)
    assert result["stored_hash_inventory_matches"]
    assert result["public_report80_narrative_matches"]
    assert not result["fresh_full_report_rows_verified"]
    assert not result["fresh_canonical_rows_verified"]
    observed["report_hashes"][0]["content_sha256"] = "changed"
    assert not bind_observed(baseline, observed)["stored_hash_inventory_matches"]
