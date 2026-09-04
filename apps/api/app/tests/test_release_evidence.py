from app.services.release_evidence import validate_record


def test_empty_evidence_fails_closed(tmp_path):
    failures = validate_record({}, tmp_path)
    assert "missing exact tested Git commit" in failures
    assert any("missing ranked retrieval traces" in failure for failure in failures)
    assert any("owner approval" in failure for failure in failures)


def test_boolean_status_does_not_replace_hashed_evidence(tmp_path):
    record = {
        "tested_commit": "a" * 40,
        "checks": {
            "backend": {
                "status": "passed",
                "tested_commit": "a" * 40,
                "path": "missing.json",
                "sha256": "b" * 64,
            },
        },
    }
    assert "backend: evidence content hash mismatch or missing file" in validate_record(
        record, tmp_path
    )
