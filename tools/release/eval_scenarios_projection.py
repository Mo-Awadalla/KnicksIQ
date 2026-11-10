"""Projection scenarios: facts the scorer derives from a record's own evidence.

A projected fact is never typed in the runtime response. The scorer has to derive
the scoreline, the game count and the loss sign from the verified receipt, the
record's population and its considered dates, and still hold them to the same
scope and display invariants as a typed fact. Each scenario runs the real
``app.evaluation.cli`` against synthetic labels and a loopback mapping.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py games_count_scope
"""

from __future__ import annotations

from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    load,
    run_score,
    scored_game_row,
    synthetic_mapping,
    synthetic_questions,
    write_dataset,
)
from eval_scenario_records import (
    answer_response,
    baseline_observations,
    claim,
    observation,
    receipt_record,
)
from eval_scenario_support import RELEASE, expect, failures


def scenario_games_count_projected(directory: Path) -> list[str]:
    """A recorded team record states its own population; that population is the count."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] == "answer-006":
            expectation = case["proposed_expectation"]
            expectation["canonical_facts"] = [
                {
                    "metric": "wins",
                    "value": 1,
                    "scope": "archive",
                    "subject": "team:NYK",
                    "canonical_evidence_ids": ["game:0022500006"],
                },
                {
                    "metric": "games",
                    "value": 1,
                    "scope": "archive",
                    "subject": "team:NYK",
                    "canonical_evidence_ids": ["game:0022500006"],
                },
            ]
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[5] = observation(
        "answer-006",
        answer_response(
            game=108,
            value=1,
            claims=[
                claim(game=108, value=1, metric="wins", unit="wins", sample_size=1),
            ],
            text="Synthetic 1 win over 1 archived game.",
        ),
    )

    def score(count: int) -> dict | None:
        edited = load(expectations_path)
        for case in edited["cases"]:
            if case["id"] == "answer-006":
                case["proposed_expectation"]["canonical_facts"][1]["value"] = count
        dump(expectations_path, edited)
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
        return report

    matched = score(1)
    if matched is not None:
        expect(
            failures(matched, "answer-006") == [],
            "a game count is projected from the recorded team record's own population",
            problems,
        )
    overstated = score(2)
    if overstated is not None:
        expect(
            "denominator_mismatch" in failures(overstated, "answer-006"),
            "a game count the record's population does not support fails",
            problems,
        )
    return problems


def scenario_games_count_display(directory: Path) -> list[str]:
    """A projected game count must be stated in the answer, not just inferable."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] != "answer-011":
            continue
        case["proposed_expectation"]["canonical_facts"] = [
            {
                "metric": "wins",
                "value": 7,
                "scope": "archive",
                "subject": "team:NYK",
                "canonical_evidence_ids": ["game:0022500011"],
            },
            {
                "metric": "games",
                "value": 15,
                "scope": "archive",
                "subject": "team:NYK",
                "canonical_evidence_ids": ["game:0022500011"],
            },
        ]
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())

    def score(text: str) -> dict | None:
        observations[10] = observation(
            "answer-011",
            answer_response(
                game=113,
                value=7,
                claims=[claim(game=113, value=7, metric="wins", unit="wins", sample_size=15)],
                text=text,
            ),
        )
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
        return report

    stated = score("Synthetic 7 wins over 15 considered games.")
    if stated is not None:
        expect(
            failures(stated, "answer-011") == [],
            "a stated game count is credited",
            problems,
        )
    silent = score("Synthetic 7 wins in the archived season.")
    if silent is not None:
        expect(
            any(
                item["code"] == "claim_not_displayed" and item.get("fact_index") == 1
                for item in [c for c in silent["cases"] if c["id"] == "answer-011"][0]["failures"]
            ),
            "a game count the answer never states is not credited",
            problems,
        )
    return problems


def scenario_games_count_scope(directory: Path) -> list[str]:
    """A projected game count answers to the same scope as the record it reads."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] != "answer-010":
            continue
        expectation = case["proposed_expectation"]
        expectation["canonical_facts"] = [
            {
                "metric": "wins",
                "value": 7,
                "scope": "archive",
                "subject": "team:NYK",
                "canonical_evidence_ids": ["game:0022500010"],
            },
            {
                "metric": "games",
                "value": 15,
                "scope": "January 2026",
                "subject": "team:NYK",
                "canonical_evidence_ids": ["game:0022500010"],
            },
        ]
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())

    def score(window: dict[str, str]) -> dict | None:
        observations[9] = observation(
            "answer-010",
            answer_response(
                game=112,
                value=7,
                claims=[
                    claim(
                        game=112,
                        value=7,
                        metric="wins",
                        unit="wins",
                        sample_size=15,
                        window={**window, "considered_games": 15},
                    )
                ],
                text="Synthetic 7 wins over 15 considered games.",
            ),
        )
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
        return report

    def case_of(report: dict) -> dict:
        return [item for item in report["cases"] if item["id"] == "answer-010"][0]

    inside = score({"date_start": "2026-01-02", "date_end": "2026-01-30"})
    if inside is not None:
        expect(
            failures(inside, "answer-010") == [],
            "a games count projected from a January record is the January count",
            problems,
        )
    outside = score({"date_start": "2025-12-02", "date_end": "2025-12-30"})
    if outside is not None:
        expect(
            any(
                item["code"] == "window_mismatch" and item.get("fact_index") == 1
                for item in case_of(outside)["failures"]
            ),
            "a games count whose record is outside the stated month fails",
            problems,
        )
    return problems


def scenario_margin_extreme_projection(directory: Path) -> list[str]:
    """A largest-loss claim states a deficit; only that operation carries the sign."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] == "answer-004":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {
                    "metric": "margin",
                    "value": -38,
                    "subject": "team:NYK",
                    "canonical_evidence_ids": ["game:0022500004"],
                }
            )
    dump(expectations_path, expectations)
    row = scored_game_row(
        106,
        home_team="DET",
        home_score=118,
        away_team="NYK",
        away_score=80,
        game_date="2026-02-06",
    )
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping(game_rows={106: row}))
    receipt = f"{RELEASE}:game:106"
    story = (
        "The Knicks' largest loss in the available 2025-26 archive was 2026-02-06 "
        "against DET: NYK 80, DET 118, a 38-point margin."
    )
    observations = baseline_observations(synthetic_questions())

    def score(metric: str, operation: str, value: int) -> dict | None:
        observations[3] = observation(
            "answer-004",
            answer_response(
                game=106,
                value=value,
                claims=[
                    claim(
                        game=106,
                        value=value,
                        metric=metric,
                        unit="points",
                        sample_size=1,
                        eligibility={
                            "appearance": "minutes > 0",
                            "operation": operation,
                        },
                    )
                ],
                receipt=receipt,
                evidence=[receipt_record(receipt, source_row=row)],
                text=story,
            ),
        )
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
        return report

    loss = score("loss_margin", "largest_loss_margin", 38)
    if loss is not None:
        expect(
            failures(loss, "answer-004") == [],
            "a largest-loss deficit projects the verified loss operation's sign",
            problems,
        )
    unverified = score("loss_margin", "team_aggregate", 38)
    if unverified is not None:
        expect(
            "numeric_mismatch" in failures(unverified, "answer-004"),
            "without the loss operation the deficit is not signed",
            problems,
        )
    win = score("win_margin", "largest_win_margin", 38)
    if win is not None:
        expect(
            "numeric_mismatch" in failures(win, "answer-004"),
            "a win margin is never projected onto a negative margin",
            problems,
        )
    return problems


def scenario_scope_windows_from_population(directory: Path) -> list[str]:
    """A stated window is proved by the record's own considered dates, not endpoints."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    scopes = {
        "answer-007": "January 2026",
        "answer-008": "before All-Star break",
        "answer-009": "after February 15, 2026 (including postseason)",
    }
    for case in expectations["cases"]:
        scope = scopes.get(case["id"])
        if scope:
            case["proposed_expectation"]["canonical_facts"][0]["scope"] = scope
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())

    def record(case_id: str, game: int, value: int, **kwargs) -> None:
        index = int(case_id.rsplit("-", 1)[1]) - 1
        observations[index] = observation(
            case_id,
            answer_response(
                game=game,
                value=value,
                claims=[claim(game=game, value=value, **kwargs)],
                text=f"Synthetic wins {value}.",
            ),
        )

    def score() -> dict | None:
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
        return report

    january = {"date_start": "2026-01-02", "date_end": "2026-01-30", "considered_games": 15}
    record("answer-007", 109, 67, window=january)
    record(
        "answer-008",
        110,
        68,
        window={"date_start": "2025-12-02", "date_end": "2026-02-06", "considered_games": 15},
    )
    record(
        "answer-009",
        111,
        69,
        window={"date_start": "2026-02-19", "date_end": "2026-06-13", "considered_games": 46},
        season_type=None,
    )
    inside = score()
    if inside is not None:
        expect(
            failures(inside, "answer-007") == [],
            "a January window holds when every considered date is inside January",
            problems,
        )
        expect(
            failures(inside, "answer-008") == [],
            "a before-all-star window holds when it ends before the break",
            problems,
        )
        expect(
            failures(inside, "answer-009") == [],
            "a postseason window holds from its own considered dates",
            problems,
        )
    record("answer-007", 109, 67, window={"date_start": "2025-12-02", "date_end": "2026-01-30"})
    record("answer-009", 111, 69, window={"date_start": "2026-02-19", "date_end": "2026-06-13"})
    outside = score()
    if outside is not None:
        expect(
            "window_mismatch" in failures(outside, "answer-007"),
            "a window that starts in December is not January",
            problems,
        )
        expect(
            "window_mismatch" in failures(outside, "answer-009"),
            "a window that never includes the postseason does not claim it",
            problems,
        )
    return problems
