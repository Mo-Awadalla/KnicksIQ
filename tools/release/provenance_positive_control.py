"""Authentic positive control: grade real recorded answers against the current mapping.

This is the positive control the evaluation contract needs. It drives the application
over ASGI against one explicit loopback database, sends the operation families the
product advertises, and grades each delivered receipt with the real evaluator:

* every citation reference resolves through the verified runtime mapping;
* every receipt is content-verified by rehashing its own returned row snapshot;
* every calculation is checked against its recorded arithmetic and expansion;
* a canonical scoreline is projected from the verified game receipt it cites.

Nothing here approves a label, contacts a provider or writes to the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "apps" / "api"
DEFAULT_MAPPING = REPO / "release-artifacts/production-completion-20261030/runtime-mapping.json"
DEFAULT_OUTPUT = (
    REPO / "release-artifacts/production-completion-20261030/provenance-positive-control.json"
)

QUESTIONS = (
    "What was the Knicks record this season?",
    "How many games did the Knicks win?",
    "Who beat the Knicks by the most points?",
    "What was their best win?",
    "How many points per game did the Knicks score?",
    "How many points did Jalen Brunson average?",
    "How did the Knicks shoot from three in wins and losses?",
    "What was the Knicks' point differential in wins and losses?",
    "How many points did the Knicks score in the first quarter?",
)

for _secret in (
    "SENTRY_DSN",
    "REDIS_URL",
    "OPENROUTER_API_KEY",
    "AI_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "ADMIN_API_KEY",
    "DB_URL",
):
    os.environ.pop(_secret, None)
sys.path.insert(0, str(API_ROOT))


def _configure(dsn: str) -> None:
    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    if url.get_backend_name() != "postgresql":
        raise SystemExit("refused: only an explicit PostgreSQL DSN is supported")
    if (url.host or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("refused: only a loopback database is allowed")
    os.environ.update(
        DB_URL=url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
        TEST_MODE="false",
        ENVIRONMENT="development",
        LOG_JSON="false",
        DEBUG="false",
        REDIS_URL="redis://127.0.0.1:1/0",
        RAG_QDRANT_ENABLED="false",
        ANALYST_EVIDENCE_LOOP_ENABLED="true",
        ANALYSIS_ANSWER_MODE="deterministic",
        REQUIRE_ACTIVE_RELEASE="true",
    )


def _scoreline_fact(reference: str, record: Any, mapping: Any) -> tuple[dict[str, Any] | None, str]:
    """The canonical scoreline of the game a verified receipt stands for, or why not."""
    from app.evaluation.assertion_checks import SCORELINE_FIELDS
    from app.evaluation.observations import canonical_digest

    resolution = mapping.resolve_citation(reference, None)
    if not resolution.resolved or not resolution.canonical_ids:
        return None, "unresolved"
    canonical = resolution.canonical_ids[0]
    row = mapping.rows.get(canonical)
    if row is None:
        return None, "unmapped"
    if record is None or record.source_row is None or record.row_sha256 != row.row_sha256:
        return None, "unverified"
    if canonical_digest(record.source_row) != row.row_sha256:
        return None, "tampered"
    projection = {key: record.source_row.get(key) for key in SCORELINE_FIELDS}
    if any(value is None for value in projection.values()):
        return None, "incomplete"
    return projection, "projected"


async def _grade(mapping: Any, questions: tuple[str, ...]) -> dict[str, Any]:
    from app.evaluation.observations import EvidenceRecord, canonical_digest
    from app.evaluation.scoring_cases import _content_problem
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app()
    cases: list[dict[str, Any]] = []
    async with AsyncClient(transport=ASGITransport(app), base_url="https://test") as client:
        for index, question in enumerate(questions):
            response = await client.post(
                "/analysis/query",
                json={
                    "question": question,
                    "season": "2025-26",
                    "turn_id": f"positive-control-{index:02d}0000",
                    "expected_revision": 0,
                },
            )
            body = response.json()
            if response.status_code != 200:
                cases.append(
                    {
                        "question": question,
                        "status": response.status_code,
                        "error": body.get("error"),
                        "claims": [],
                    }
                )
                continue
            registry: dict[str, Any] = {}
            malformed: list[str] = []
            for item in body.get("evidence") or []:
                try:
                    registry[item["evidence_id"]] = EvidenceRecord.from_dict(item)
                except Exception as exc:  # noqa: BLE001 - recorded, never fatal
                    malformed.append(f"{type(exc).__name__}:{exc}")
            claims: list[dict[str, Any]] = []
            for citation in body.get("citations") or []:
                metadata = citation.get("metadata") or {}
                claim = metadata.get("claim")
                reference = metadata.get("evidence_id")
                if not claim or not reference:
                    continue
                resolution = mapping.resolve_citation(reference, claim, registry=registry)
                blocker = _content_problem(reference, resolution, mapping, registry)
                record = registry.get(reference)
                entry: dict[str, Any] = {
                    "claim_id": claim.get("claim_id"),
                    "metric": claim.get("metric_id"),
                    "value": claim.get("value"),
                    "unit": claim.get("unit"),
                    "reference": reference,
                    "kind": resolution.kind,
                    "canonical_ids": list(resolution.canonical_ids),
                    "resolution_problems": list(resolution.problems),
                    "content_blocker": blocker,
                    "receipt_content_verified": bool(
                        record is not None
                        and record.source_row is not None
                        and record.row_sha256
                        and canonical_digest(record.source_row) == record.row_sha256
                    ),
                }
                if record is not None and record.numerator is not None and record.denominator:
                    expected = record.numerator / record.denominator
                    entry["arithmetic"] = {
                        "numerator": record.numerator,
                        "denominator": record.denominator,
                        "reproduces_value": abs(expected - float(claim.get("value") or 0))
                        <= _tolerance(record.value_decimals),
                    }
                if record is not None and record.made is not None and record.attempted:
                    entry["percentage_arithmetic"] = {
                        "made": record.made,
                        "attempted": record.attempted,
                        "reproduces_value": abs(
                            100.0 * record.made / record.attempted - float(claim.get("value") or 0)
                        )
                        <= _tolerance(record.value_decimals),
                    }
                if record is not None and record.sample_size is not None:
                    entry["population_bounded"] = record.sample_size <= len(
                        record.source_evidence_ids
                    )
                sources = list(claim.get("supporting_evidence_ids") or [])
                if record is not None and record.source_evidence_ids:
                    sources = list(record.source_evidence_ids)
                projection = None
                state = "no_sources"
                for source in sources:
                    if source.startswith("calculation:"):
                        continue
                    projection, state = _scoreline_fact(source, registry.get(source), mapping)
                    if projection is not None:
                        break
                if projection is not None or state != "no_sources":
                    entry["scoreline_source"] = {"state": state, "projection": projection}
                if projection is not None and entry["metric"] in {"win_margin", "loss_margin"}:
                    own = (
                        projection["home_score"]
                        if projection["home_team_id"] == "NYK"
                        else projection["away_score"]
                    )
                    other = (
                        projection["away_score"]
                        if projection["home_team_id"] == "NYK"
                        else projection["home_score"]
                    )
                    expected_margin = (
                        own - other if entry["metric"] == "win_margin" else other - own
                    )
                    entry["margin_from_scoreline"] = {
                        "value": expected_margin,
                        "matches_claim": abs(expected_margin - float(claim["value"])) <= 1e-9,
                    }
                if record is not None and record.source_evidence_ids:
                    entry["expansion_content_verified"] = sum(
                        1
                        for source in record.source_evidence_ids
                        if (source_record := registry.get(source)) is not None
                        and source_record.source_row is not None
                        and source_record.row_sha256
                        and canonical_digest(source_record.source_row) == source_record.row_sha256
                    )
                claims.append(entry)
            cases.append(
                {
                    "question": question,
                    "status": response.status_code,
                    "outcome": body.get("outcome"),
                    "route": body.get("route"),
                    "degraded": body.get("degraded"),
                    "answer": body.get("answer"),
                    "evidence_entries": len(body.get("evidence") or []),
                    "malformed_evidence": malformed,
                    "claims": claims,
                }
            )
    return {
        "scope": (
            "local ASGI application, local isolated PostgreSQL, deterministic analyst path; "
            "no provider, no label approval, no release activation"
        ),
        "recorded_at": datetime.now(UTC).isoformat(),
        "mapping_version": mapping.version,
        "mapping_release_id": mapping.release_id,
        "mapping_rows": len(mapping.rows),
        "cases": cases,
    }


def _tolerance(decimals: int | None) -> float:
    if decimals is None or not 0 <= decimals <= 4:
        return 1e-6
    return 0.5 * 10**-decimals + 1e-9


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grade real recorded answers against the verified runtime mapping."
    )
    parser.add_argument("--dsn", required=True, help="explicit loopback PostgreSQL DSN")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if not args.mapping.exists():
        print(f"mapping not found: {args.mapping}", file=sys.stderr)
        return 1
    _configure(args.dsn)
    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    from app.evaluation.mapping import load_mapping

    mapping = load_mapping(args.mapping)
    report = asyncio.run(_grade(mapping, QUESTIONS))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    graded = [claim for case in report["cases"] for claim in case["claims"]]
    verified = sum(
        1 for claim in graded if not claim["content_blocker"] and not claim["resolution_problems"]
    )
    arithmetic = [
        claim for claim in graded if "arithmetic" in claim or "percentage_arithmetic" in claim
    ]
    arithmetic_ok = sum(
        1
        for claim in arithmetic
        if (claim.get("arithmetic") or claim.get("percentage_arithmetic"))["reproduces_value"]
    )
    print(
        f"questions={len(report['cases'])} claims={len(graded)} verified={verified} "
        f"arithmetic_checked={len(arithmetic)} arithmetic_ok={arithmetic_ok}"
    )
    print(f"wrote {args.output}")
    return 0 if verified == len(graded) and arithmetic_ok == len(arithmetic) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
