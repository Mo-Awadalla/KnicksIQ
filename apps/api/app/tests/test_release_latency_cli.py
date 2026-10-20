"""CLI regressions specified before aligning the owner-approved latency gate.

Failure matrix: valid 4-15s observations rejected by the stale gate; the exact
15s boundary or higher accepted; an absent latency measurement accepted.
Artifacts are synthetic boundary checks, not performance or owner approval.
"""

import json
import subprocess
import sys

import pytest
from app.tests.test_release_stages import ready_record


@pytest.mark.parametrize(
    ("latency_ms", "eligible"),
    [(10_500, True), (14_999.9, True), (15_000, False), (15_000.1, False), (None, False)],
)
def test_readiness_cli_applies_approved_fifteen_second_limit(tmp_path, latency_ms, eligible):
    record = ready_record(tmp_path)
    metrics = record["checks"]["warm_load"]["metrics"]
    if latency_ms is None:
        del metrics["analyst_p95_ms"]
    else:
        metrics["analyst_p95_ms"] = latency_ms
    path = tmp_path / "synthetic-release-record.json"
    path.write_text(json.dumps(record))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.release_evidence",
            str(path),
            "--root",
            str(tmp_path),
            "--readiness",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    observed = json.loads(result.stdout)
    (tmp_path / "latency-cli-result.json").write_text(
        json.dumps(
            {
                "scope": "Synthetic CLI policy boundary, not measured performance or approval",
                "analyst_p95_ms": latency_ms,
                "exit_code": result.returncode,
                "result": observed,
            },
            indent=2,
        )
        + "\n"
    )
    assert result.returncode == (0 if eligible else 1), result.stdout + result.stderr
    assert observed["eligible"] is eligible
