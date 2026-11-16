import json
import subprocess
import sys

import pytest
from app.services.release_evidence import validate_record


def test_empty_evidence_fails_closed(tmp_path):
    record = tmp_path / "release.json"
    record.write_text("{}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.release_evidence",
            str(record),
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["eligible"] is False


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


@pytest.mark.parametrize(
    "cutoff,model,blocked",
    [("2", "approved", False), ("3", "approved", True), ("2", "other", True)],
)
def test_launch_policy_checks_the_deployment_blueprint(tmp_path, cutoff, model, blocked):
    (tmp_path / "render.yaml").write_text(
        "services:\n  - name: knicksiq-api\n    envVars:\n"
        f"      - key: OPENROUTER_MONTHLY_CUTOFF_USD\n        value: '{cutoff}'\n"
        f"      - key: AI_CHAT_MODEL\n        value: {model}\n"
        "      - key: OPENROUTER_ALLOWED_MODELS\n        value: '[\"approved\"]'\n"
    )
    failures = validate_record({}, tmp_path)
    assert any("blueprint" in failure for failure in failures) is blocked


@pytest.mark.parametrize("content", [None, "services: [", "services: []", "null"])
def test_missing_or_invalid_deployment_blueprint_blocks_launch(tmp_path, content):
    if content is not None:
        (tmp_path / "render.yaml").write_text(content)
    assert any("blueprint" in failure for failure in validate_record({}, tmp_path))
