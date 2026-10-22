"""Offline rescoring for the recorded follow-up session artifact.

The live harness stores one citation row per claim (metric, value, phase, game count) and
drops receipt text. A rescore therefore rebuilds the claim corpus in the emitted statement
shape, restores the numbers the live run already proved backed from its recorded checks, and
re-tests only the tokens the old scorer rejected. Used by ``followup_bench.py --responses``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from analyst_checks import _extract
from analyst_scoring import score_response
from followup_oracle import (
    compare_scope,
    expectation_case,
    expectation_checks,
    expectation_for,
    scoped,
)


def _reconstruct_citations(turn: dict, entity: str | None) -> list[dict]:
    """Rebuild the corpus the live scorer saw, as far as the artifact allows.

    The artifact keeps one citation row per claim (metric, value, phase, game count) but not
    the claim statement, and drops the receipt text entirely. Claims are rebuilt in the shape
    the tool emitted. Numbers the live run already backed are restored from its recorded
    ``checks`` so a rescore changes only the tokens the old scorer rejected; the previously
    unbacked tokens are left to the real claim values below.
    """
    subject = f"player:{entity}" if entity and entity != "Knicks" else "team:NYK"
    owner = entity or "Knicks"
    citations = []
    for item in turn.get("citations") or []:
        value = item.get("value")
        if value is None:
            continue
        metric = item.get("metric")
        label = str(metric or "value").replace("_", " ")
        season = item.get("season_type") or ""
        games = int(item.get("games") or 0)
        citations.append(
            {
                "claim": (f"{owner} {season} {label}: {value} over {games} archived games."),
                "type": "verified_claim",
                "metadata": {
                    "claim": {
                        "subject_id": subject,
                        "metric_id": metric,
                        "value": value,
                        "unit": label,
                        "population": "available release archive",
                        "filters": {},
                        "season_type": season,
                        "season": "2025-26",
                        "sample_size": games,
                        "denominator": games if str(metric or "").endswith("_per_game") else None,
                        "window": None,
                        "game_ids": [],
                    }
                },
            }
        )
    checks = turn.get("checks") or {}
    pending = Counter(checks.get("unbacked_numbers") or [])
    text: list[str] = []
    numbers: list[float] = []
    for token in _extract(str(turn.get("answer") or "")):
        if token.kind == "season":
            continue
        if pending[token.raw]:
            pending[token.raw] -= 1
            continue
        if token.kind == "date":
            text.append(token.raw)
        elif token.kind == "pair":
            numbers.extend(token.values)
        elif token.value is not None:
            numbers.append(token.value)
    unbacked_entities = set(checks.get("unbacked_entities") or [])
    text.extend(
        name for name in checks.get("detected_entities") or [] if name not in unbacked_entities
    )
    if numbers or text:
        statement = " ".join(text) or "restored receipts"
        citations.append(
            {
                "claim": statement,
                "type": "receipt",
                "metadata": {"claim": {"statement": statement, "values": numbers, "game_ids": []}},
            }
        )
    return citations


def _offline_turn(
    stored: dict,
    spec: dict,
    archive,
    ids: dict[str, int],
    teams: dict[str, str],
    values: Any,
) -> dict:
    expectation = expectation_for(spec, archive, ids, teams)
    case = expectation_case(expectation)
    answer = str(stored.get("answer") or "")
    response = {
        "answer": answer,
        "citations": _reconstruct_citations(stored, expectation.entity),
        "warnings": stored.get("warnings") or [],
        "refused": stored.get("refused", False),
        "degraded": stored.get("degraded", False),
        "llm_validated": stored.get("llm_validated"),
        "outcome": "live",
    }
    score = score_response(
        case,
        response,
        universe=values.universe,
        archive=values.archive,
        scoped=scoped(answer, case, values),
        strict=True,
    )
    checks = expectation_checks(answer, expectation, teams)
    if expectation.kind == "decline":
        expected_ok = score["checks"]["declined"]
    else:
        expected_ok = bool(
            checks.get("decline")
            or checks.get("record_ok")
            or checks.get("fact_ok")
            or checks.get("value_ok")
        )
    honest_ok = score["meets_expectation"]
    scope_issues = (
        []
        if expectation.kind == "decline" or not stored.get("state_committed")
        else compare_scope(stored.get("actual_scope") or {}, expectation.scope, archive)
    )
    body = {
        "degraded": stored.get("degraded"),
        "refused": stored.get("refused"),
        "_score": score,
    }
    cause = classify(
        stored.get("status") or 0,
        body,
        honest_ok,
        expected_ok,
        scope_issues,
        stored.get("revision_ok", True),
    )
    return {
        **stored,
        "cause": cause,
        "expected": {
            "kind": expectation.kind,
            "fact": expectation.fact,
            "record": expectation.record,
            "scope": expectation.scope,
        },
        "expected_checks": checks,
        "expected_ok": expected_ok,
        "honest_ok": honest_ok,
        "failures": score["failures"],
        "checks": score["checks"],
        "scope_issues": scope_issues,
    }


def run_offline(sessions: list[dict], recorded: dict, archive, ids, teams, values) -> dict:
    results: dict[str, list[dict]] = {}
    for session in sessions:
        runs = recorded.get("sessions", {}).get(session["id"]) or []
        rescored = []
        for run in runs:
            turns = [
                _offline_turn(stored, spec, archive, ids, teams, values)
                for stored, spec in zip(run.get("turns") or [], session["turns"], strict=False)
            ]
            integrity = run.get("integrity") or {}
            integrity_ok = bool(
                integrity.get("single_token")
                and integrity.get("consecutive")
                and integrity.get("all_200_settled")
            )
            rescored.append(
                {
                    **run,
                    "turns": turns,
                    "pass": integrity_ok and all(turn["cause"] == "ok" for turn in turns),
                }
            )
        results[session["id"]] = rescored
    return results


def classify(
    status: int,
    body: dict,
    honest_ok: bool,
    expected_ok: bool,
    scope_issues: list[str],
    revision_ok: bool,
) -> str:
    if status != 200:
        return f"pipeline:http_{status}"
    if body.get("degraded"):
        return "pipeline:degraded"
    if not revision_ok:
        return "session:revision"
    if scope_issues and not (honest_ok and expected_ok):
        if body.get("refused"):
            return "scope+decline"
        return "scope"
    if honest_ok and expected_ok:
        return "ok"
    failures = (body.get("_score") or {}).get("failures") or []
    if "declined:phrase:decline" in failures or "declined:field:refused" in failures:
        return "answer:declined"
    if "not_validated" in failures:
        return "answer:not_validated"
    return "answer:value"
