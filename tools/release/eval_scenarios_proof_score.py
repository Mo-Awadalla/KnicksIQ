"""Candidate-proof scoring scenarios: a signed run scores, a tampered one does not.

The fixture is real: an approval, one admitted upstream attempt on a loopback
fake wire, a collection from a candidate that signs every response, and a sealed
ledger. Each scenario then changes one thing about the committed evidence and
requires the scorer to refuse exactly that, per observation.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py collect_service_proven
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.candidate_proof import generate_keypair
from eval_scenario_support import expect
from eval_scenarios_budget_support import CASES, reported
from eval_scenarios_proof_support import proven_run, rows_of, score_service, write_rows


def scenario_collect_service_proven(directory: Path) -> list[str]:
    """A signed collection proves every row, then scores offline from the bound key."""
    problems: list[str] = []
    run = proven_run(directory)
    expect(reported(run["spent"], problems).get("ok") is True, "one attempt is admitted", problems)
    collected = run["collected"]
    expect(collected.returncode == 0, f"collect failed: {collected.stderr[-800:]}", problems)
    rows = rows_of(run["responses"]) if run["responses"].exists() else []
    expect(len(rows) == CASES, f"one record per case: {len(rows)}", problems)
    unproven = [row["case_id"] for row in rows if row.get("proof") is None]
    expect(not unproven, f"every row carries its own proof: {unproven[:3]}", problems)
    if rows:
        nonces = {row["proof"]["nonce"] for row in rows if row.get("proof")}
        expect(len(nonces) == len(rows), "every row answers its own challenge nonce", problems)
        expect(
            all(row.get("run", {}).get("run_id") == run["binding"].run_id for row in rows),
            "every row carries the run identity",
            problems,
        )
        expect(
            all(row["proof"]["scope"] == "local_fake" for row in rows if row.get("proof")),
            "the loopback upstream keeps its local_fake proof scope",
            problems,
        )
    if collected.returncode == 0:
        summary = json.loads(collected.stdout)
        expect(
            summary.get("proofs_verified") == CASES,
            f"the summary counts verified proofs: {summary.get('proofs_verified')}",
            problems,
        )
    report_path = directory / "report.json"
    scored = score_service(run, run["responses"], report_path)
    expect(scored.returncode == 0, f"score failed: {scored.stderr[-800:]}", problems)
    if report_path.exists():
        report = json.loads(report_path.read_text())
        codes = [item["code"] for item in report["blockers"]]
        expect("service_evidence_local_fake" in codes, f"a fake upstream blocks: {codes}", problems)
        expect(
            "service_proof_missing" not in codes and "service_proof_signature_invalid" not in codes,
            f"proven rows are accepted: {codes}",
            problems,
        )
        expect(
            report["profile"]["proofs_verified"] == CASES,
            f"the report counts verified proofs: {report['profile']}",
            problems,
        )
        expect(
            report["profile"]["proof_scope"] == "service",
            f"the proof scope is stated explicitly: {report['profile']}",
            problems,
        )
    return problems


def scenario_score_rejects_unproven_rows(directory: Path) -> list[str]:
    """Changed question, changed response, missing proof, replay and mixed rows all fail."""
    problems: list[str] = []
    run = proven_run(directory)
    expect(
        run["collected"].returncode == 0,
        f"collect failed: {run['collected'].stderr[-600:]}",
        problems,
    )
    original = rows_of(run["responses"]) if run["responses"].exists() else []
    if len(original) < 4:
        return ["the proven fixture produced too few rows to tamper with"]

    def scored(rows: list[dict[str, Any]], name: str) -> tuple[int, list[str], str]:
        path = write_rows(directory / f"{name}.jsonl", rows)
        output = directory / f"{name}.report.json"
        result = score_service(run, path, output)
        codes = (
            [item["code"] for item in json.loads(output.read_text())["blockers"]]
            if output.exists()
            else []
        )
        return result.returncode, codes, result.stderr or ""

    def copy() -> list[dict[str, Any]]:
        return json.loads(json.dumps(original))

    changed_question = copy()
    changed_question[0]["request"]["question"] += " (x)"
    code, codes, _ = scored(changed_question, "changed-question")
    expect(code == 0, "a changed question still scores, as a blocked report", problems)
    expect(
        "service_proof_request_mismatch" in codes,
        f"a changed question is not this run's answer: {codes}",
        problems,
    )

    changed_response = copy()
    changed_response[0]["response"]["answer"] = "Tampered."
    code, codes, _ = scored(changed_response, "changed-response")
    expect(code == 0, "a changed response still scores, as a blocked report", problems)
    expect(
        "service_proof_response_mismatch" in codes,
        f"a changed response is not this run's answer: {codes}",
        problems,
    )

    missing = copy()
    missing[1].pop("proof", None)
    code, codes, _ = scored(missing, "missing-proof")
    expect(code == 0, "a missing proof still scores, as a blocked report", problems)
    expect("service_proof_missing" in codes, f"an unproven row is blocked: {codes}", problems)
    missing_report = json.loads((directory / "missing-proof.report.json").read_text())
    missing_case = next(item for item in missing_report["cases"] if item["id"] == "answer-002")
    expect(missing_case["verified"] is False, "an unproven response earns no case credit", problems)

    replayed = copy()
    replayed[1]["proof"] = json.loads(json.dumps(replayed[0]["proof"]))
    code, codes, _ = scored(replayed, "replayed")
    expect(code == 0, "a replayed proof still scores, as a blocked report", problems)
    expect("service_proof_replayed" in codes, f"a reused nonce is a replay: {codes}", problems)

    mixed = copy()
    mixed[2].pop("run", None)
    code, codes, _ = scored(mixed, "mixed-rows")
    expect(code == 0, "a mixed file still scores, as a blocked report", problems)
    expect(
        "service_run_binding_missing" in codes,
        f"a row with no run stamp is blocked: {codes}",
        problems,
    )

    foreign = copy()
    foreign[3]["proof"]["public_key"] = generate_keypair().public_key
    code, codes, _ = scored(foreign, "wrong-key")
    expect(code == 0, "a foreign key still scores, as a blocked report", problems)
    expect(
        "service_proof_signature_invalid" in codes,
        f"a proof naming another key is not evidence: {codes}",
        problems,
    )

    mismatched = copy()
    mismatched[0]["run"]["run_id"] = "run-" + "0" * 16
    path = write_rows(directory / "stamp-disagrees.jsonl", mismatched)
    refused = score_service(run, path, directory / "stamp-disagrees.report.json")
    expect(
        refused.returncode == 2,
        f"a stamp that disagrees with the proof refuses the file: {refused.stderr[-300:]}",
        problems,
    )
    expect("disagree" in (refused.stderr or ""), f"{refused.stderr[-300:]}", problems)
    return problems
