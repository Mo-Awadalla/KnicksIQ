"""Independent arithmetic over cited rows: formulas, splits and pinned receipts.

Real operations over seeded rows must resolve against a mapping rebuilt from their own
captured snapshots. A recorded numerator, ingredient or denominator is never proof: the
formula is recomputed from the cited rows, so a wrong source, a restated value or a
tampered total fails instead of earning support. A claim whose cited evidence is one
receipt is proved as that receipt, and one that cites a calculation is recomputed.
"""

from __future__ import annotations

import pytest
from app.evaluation.scoring_cases import _claim_payload
from app.services.analyst_calculations import team
from app.services.analyst_comparisons import compare
from app.services.analyst_game_summary import game_summary
from app.services.analyst_team_splits import period_scoring, result_split
from app.services.evidence_contracts import ToolCall
from app.tests.support.evaluation_archive import _tools
from app.tests.support.evaluation_mapping import (
    _calculation_record,
    _calculation_reference,
    _mapping,
    _registry,
    _resolve,
)


async def test_team_record_claims_recompute_from_final_scores(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "What was the Knicks record this season?")
    assert tools.scope is not None
    result = await team(tools, tools.scope)
    claims = {claim.metric_id: claim for claim in result.claims}
    assert {"wins", "losses"} <= set(claims)
    mapping = _mapping(tools, tmp_path)
    for metric, claim in claims.items():
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (metric, resolution.problems)
        assert resolution.unverified == ()
        assert resolution.recipe == "game_result_count"
    pairs = [tools.score(game) for game in tools.games]
    assert claims["wins"].value == sum(own > other for own, other in pairs)
    assert claims["losses"].value == sum(own < other for own, other in pairs)


async def test_team_per_game_claim_recomputes_the_mean(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points per game did the Knicks score?")
    assert tools.scope is not None
    result = await team(tools, tools.scope, "average")
    (claim,) = [item for item in result.claims if item.metric_id == "points_per_game"]
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "game_score_mean"
    scores = [tools.score(game)[0] for game in tools.considered_games(tools.scope)]
    assert claim.value == round(sum(scores) / len(scores), 1)


async def test_player_average_claim_recomputes_from_box_rows(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points per game did Brunson average?")
    result = await tools.execute(
        ToolCall(
            name="get_player_stats",
            question=tools.question,
            metric="points",
            aggregation="average",
        )
    )
    (claim,) = result.claims
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "box_column_mean"
    brunson = [stat for stat, player in tools.rows if player.full_name == "Jalen Brunson"]
    assert claim.value == sum(stat.points for stat in brunson) / len(brunson)


async def test_shooting_split_recomputes_made_and_attempted(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "Did the Knicks shoot better in wins or losses?")
    assert tools.scope is not None
    result = await result_split(tools, tools.scope)
    assert result.claims
    mapping = _mapping(tools, tmp_path)
    for claim in result.claims:
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (claim.filters, resolution.problems)
        assert resolution.recipe == "box_rate_weighted"


async def test_period_scoring_recomputes_from_period_rows(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "What was the Knicks' average first-quarter scoring?")
    assert tools.scope is not None
    result = await period_scoring(tools, tools.scope)
    (claim,) = result.claims
    mapping = _mapping(tools, tmp_path)
    resolution = _resolve(mapping, tools, claim)
    assert resolution.problems == ()
    assert resolution.recipe == "period_points_mean"
    assert claim.value == 25.0


async def test_scoring_comparison_recomputes_points_per_game(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "Compare the Knicks' offense at home and on the road.")
    assert tools.scope is not None and tools.scope.comparison is not None
    result = await compare(tools, tools.scope)
    assert result.claims
    mapping = _mapping(tools, tmp_path)
    for claim in result.claims:
        assert claim.metric_id == "points_per_game"
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (claim.filters, resolution.problems)
        assert resolution.recipe == "game_score_mean"


async def test_bench_comparison_recomputes_per_team_game(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "Was the bench more productive in home or away games?")
    assert tools.scope is not None and tools.scope.comparison is not None
    result = await compare(tools, tools.scope)
    assert result.claims
    mapping = _mapping(tools, tmp_path)
    for claim in result.claims:
        assert claim.metric_id == "bench_points_per_team_game"
        resolution = _resolve(mapping, tools, claim)
        assert resolution.problems == (), (claim.filters, resolution.problems)
        assert resolution.recipe == "bench_points_per_team_game"
        assert claim.value == pytest.approx(40 / 4)
        assert claim.sample_size == 4 and claim.denominator == 4


async def test_a_pinned_game_summary_is_proved_as_a_receipt(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points did Brunson score?")
    assert tools.scope is not None
    game = tools.games[3]
    result = game_summary(tools, tools.scope, [game])
    claims = {claim.metric_id: claim for claim in result.claims}
    assert {"points:game", "rebounds:game", "assists:game", "game_score"} <= set(claims)
    assert claims["points:game"].value == 23
    scoreline = claims["game_score"].value
    assert isinstance(scoreline, dict), scoreline
    assert scoreline["away_team_id"] == "NYK"
    mapping = _mapping(tools, tmp_path)
    for metric, claim in claims.items():
        (reference,) = claim.supporting_evidence_ids
        # One receipt is cited, so the claim is proved as a receipt, not a calculation.
        assert not reference.startswith("calculation:"), metric
        resolution = mapping.resolve_citation(
            reference, _claim_payload(claim), registry=_registry(tools)
        )
        assert resolution.kind == "receipt", metric
        assert resolution.problems == (), (metric, resolution.problems)
        assert resolution.unverified == (), (metric, resolution.unverified)


async def test_game_statline_and_scoreline_recompute_from_their_rows(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points did Brunson score?")
    assert tools.scope is not None
    game = tools.games[3]
    result = game_summary(tools, tools.scope, [game])
    claims = {claim.metric_id: claim for claim in result.claims}
    mapping = _mapping(tools, tmp_path)
    registry = _registry(tools)
    columns = {"points:game": "points", "rebounds:game": "rebounds", "assists:game": "assists"}
    for metric, column in columns.items():
        claim = claims[metric]
        (receipt,) = claim.supporting_evidence_ids
        row = registry[receipt].source_row
        assert row is not None
        value = claim.value
        assert isinstance(value, (int, float)), value
        assert value == row[column]
        subject = claim.subject_id
        assert subject is not None, metric
        cases = ((value, ()), (value + 1, ("calculation_arithmetic_mismatch",)))
        for case, problems in cases:
            restated = claim.model_copy(update={"value": case})
            reference = _calculation_reference(
                subject=subject, metric=metric, sources=[receipt], value=case
            )
            record = _calculation_record(reference, [receipt], sample_size=1, denominator=1.0)
            resolution = mapping.resolve_citation(
                reference, _claim_payload(restated), registry={**registry, reference: record}
            )
            assert resolution.problems == problems, (metric, case, resolution.problems)
            assert resolution.unverified == ()
            assert resolution.recipe == "game_statline"
    score = claims["game_score"]
    (receipt,) = score.supporting_evidence_ids
    score_value = score.value
    assert isinstance(score_value, dict), score_value
    score_subject = score.subject_id
    assert score_subject is not None
    scored = {**score_value, "home_score": score_value["home_score"] + 1}
    cases = ((score_value, ()), (scored, ("calculation_arithmetic_mismatch",)))
    for case, problems in cases:
        restated = score.model_copy(update={"value": case})
        reference = _calculation_reference(
            subject=score_subject, metric="game_score", sources=[receipt], value=case
        )
        record = _calculation_record(reference, [receipt], sample_size=1, denominator=None)
        resolution = mapping.resolve_citation(
            reference, _claim_payload(restated), registry={**registry, reference: record}
        )
        assert resolution.problems == problems, (case, resolution.problems)
        assert resolution.recipe == "game_scoreline"
