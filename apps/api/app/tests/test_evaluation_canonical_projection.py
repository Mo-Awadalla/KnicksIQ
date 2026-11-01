"""Canonical identity: a delivered claim is credited only as the fact's own value.

The fact is the approved identity. A player it names, or the player its structured
value names, is verified through the mapping rather than accepted from the answer; a
team fact with no team subject stays unverifiable; and a canonical NBA id is compared
as that id, never rewritten into the runtime's SQL id. The producer cases grade the
claims the real one-game summary emits against the seeded rows themselves, so a
source-id/NBA-id swap cannot pass.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from app.evaluation.assertion_checks import FactCheck, check_fact, numeric_tokens
from app.evaluation.labels import CanonicalFact
from app.evaluation.mapping import RuntimeMapping, load_mapping
from app.evaluation.observations import Observation, TypedClaim, canonical_digest
from app.evaluation.observations_records import EvidenceRecord
from app.services.analyst_game_summary import game_summary
from app.services.evidence_contracts import VerifiedClaim
from app.tests.support.evaluation_archive import _tools
from app.tests.support.evaluation_mapping import _mapping as producer_mapping
from app.tests.support.evaluation_mapping import _registry

VERSION = "2025-26.projection-test"
NBA_GAME = "0022500622"
SCORELINE = {
    "nba_game_id": NBA_GAME,
    "home_team_id": "NYK",
    "away_team_id": "BKN",
    "home_score": 120,
    "away_score": 66,
    "game_date": "2026-01-21",
}
SCORE_ANSWER = "Jalen Brunson led with 618 assists; won 120-66 by 54."


def _game_row(runtime_id: int, digest: str = "a" * 64) -> dict:
    return {
        "collection": "games",
        "row_sha256": digest,
        "database_row_id": runtime_id,
        "game_id": runtime_id,
        "release_id": 1,
        "runtime_receipt": f"{VERSION}:game:{runtime_id}",
        "player_id": None,
    }


def _mapping(tmp_path: Path, rows: dict[str, dict] | None = None) -> RuntimeMapping:
    payload = {
        "scope": "projection control",
        "version": VERSION,
        "release_id": 1,
        "bundle_sha256": "f" * 64,
        "verified_source_references": 0,
        "rows": rows if rows is not None else {f"game:{NBA_GAME}": _game_row(44)},
        "players": {
            "1628973": {"id": 134, "name": "Jalen Brunson"},
            "1626157": {"id": 135, "name": "Karl-Anthony Towns"},
        },
    }
    path = tmp_path / "runtime-mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_mapping(path)


def _claim(**overrides: object) -> TypedClaim:
    body: dict[str, object] = {
        "claim_id": "claim:one-game",
        "subject_id": "player:134",
        "metric_id": "points:game",
        "value": 23,
        "unit": "points",
        "population": "available release archive",
        "filters": {},
        "season": "2025-26",
        "season_type": "regular",
        "game_ids": (44,),
        "window": None,
        "sample_size": 1,
        "denominator": 1.0,
        "release_id": VERSION,
        "supporting_evidence_ids": (f"{VERSION}:game:44:player:134",),
        "statement": "Jalen Brunson: 23 points.",
    }
    body.update(overrides)
    return TypedClaim(**body)  # type: ignore[arg-type]


def _observation(
    claims: tuple[TypedClaim, ...], answer: str, *, season: str = "2025-26"
) -> Observation:
    return Observation(
        case_id="projection",
        turn_id="turn",
        request_id="req",
        outcome="answer",
        answer=answer,
        claims=claims,
        citations=(),
        analytics_status=None,
        analytics_result_count=0,
        traces=(),
        degraded=False,
        refused=False,
        route="factual_fallback",
        llm_validated=False,
        latency_ms=10.0,
        http_status=200,
        response_sha256="0" * 64,
        request={"question": "How many points did Brunson score?", "season": season},
        sent_request_id="req",
        evidence={},
    )


def _fact(**fields: object) -> CanonicalFact:
    return CanonicalFact.from_dict(0, fields)


def _check(
    fact: CanonicalFact, claim: TypedClaim, mapping: RuntimeMapping, answer: str | None = None
) -> FactCheck:
    text = answer if answer is not None else claim.statement
    return check_fact(fact, _observation((claim,), text), mapping, numeric_tokens(text))


def _codes(check: FactCheck) -> set[str]:
    return {failure.code for failure in check.failures}


def _one_game_fact(
    *,
    metric: str = "Jalen Brunson: total points",
    value: int = 23,
    evidence: tuple[str, ...] = (f"box:{NBA_GAME}:1628973",),
    **fields: object,
) -> CanonicalFact:
    body: dict[str, object] = {
        "metric": metric,
        "scope": "archive",
        "value": value,
        "canonical_evidence_ids": list(evidence),
        "player_name": "Jalen Brunson",
        "appearances": 1,
    }
    body.update(fields)
    return _fact(**body)


def test_a_named_player_is_verified_through_the_mapping(tmp_path: Path) -> None:
    check = _check(_one_game_fact(), _claim(), _mapping(tmp_path))
    assert check.passed, check.failures


def test_the_right_number_for_another_player_fails(tmp_path: Path) -> None:
    check = _check(_one_game_fact(player_name="Karl-Anthony Towns"), _claim(), _mapping(tmp_path))
    assert _codes(check) == {"entity_mismatch"}


def test_a_subject_the_mapping_cannot_place_is_unverifiable(tmp_path: Path) -> None:
    check = _check(_one_game_fact(), _claim(subject_id="player:9999"), _mapping(tmp_path))
    assert _codes(check) == {"subject_unverifiable"}


def test_a_name_the_mapping_does_not_know_never_matches(tmp_path: Path) -> None:
    check = _check(_one_game_fact(player_name="Josh Hart"), _claim(), _mapping(tmp_path))
    assert _codes(check) == {"entity_mismatch"}


def test_a_subject_that_conflicts_with_the_named_player_fails(tmp_path: Path) -> None:
    fact = _one_game_fact(subject="team:NYK")
    check = _check(fact, _claim(subject_id="team:NYK"), _mapping(tmp_path))
    assert _codes(check) == {"entity_mismatch"}


def test_a_consistent_team_subject_still_passes(tmp_path: Path) -> None:
    fact = _one_game_fact(subject="team:NYK", player_name=None)
    check = _check(fact, _claim(subject_id="team:NYK"), _mapping(tmp_path))
    assert check.passed, check.failures


def test_a_team_fact_without_a_subject_stays_unverifiable(tmp_path: Path) -> None:
    fact = _fact(
        metric="wins", scope="archive", value=63, canonical_evidence_ids=[f"game:{NBA_GAME}"]
    )
    claim = _claim(
        subject_id="team:NYK",
        metric_id="wins",
        value=63,
        unit="wins",
        statement="The Knicks won 63 games.",
    )
    assert _codes(_check(fact, claim, _mapping(tmp_path))) == {"subject_unverifiable"}


def _leader_fact(**value_overrides: object) -> CanonicalFact:
    return _fact(
        metric="assists leader",
        scope="archive",
        value={"name": "Jalen Brunson", "total": 618, **value_overrides},
        canonical_evidence_ids=[f"box:{NBA_GAME}:1628973"],
    )


def _leader_claim(**value_overrides: object) -> TypedClaim:
    return _claim(
        metric_id="assists:leader",
        value={"name": "Jalen Brunson", "total": 618, **value_overrides},
        unit="assists",
        statement="Jalen Brunson led the Knicks in assists with 618.",
    )


def test_a_leader_is_identified_by_the_name_its_value_declares(tmp_path: Path) -> None:
    check = _check(_leader_fact(), _leader_claim(), _mapping(tmp_path))
    assert check.passed, check.failures


def test_a_leader_naming_another_player_with_the_same_total_fails(tmp_path: Path) -> None:
    claim = _leader_claim(name="Karl-Anthony Towns")
    assert _codes(_check(_leader_fact(), claim, _mapping(tmp_path))) == {"numeric_mismatch"}


def test_canonical_game_ids_are_never_translated_into_sql_ids(tmp_path: Path) -> None:
    mapping = _mapping(tmp_path)
    fact = _fact(
        metric="game_score",
        scope="archive",
        value=dict(SCORELINE),
        canonical_evidence_ids=[f"game:{NBA_GAME}"],
    )
    canonical = _claim(metric_id="game_score", value=dict(SCORELINE), unit="game", denominator=None)
    assert _check(fact, canonical, mapping, SCORE_ANSWER).passed
    swapped = _claim(
        metric_id="game_score",
        value={**SCORELINE, "nba_game_id": 44},
        unit="game",
        denominator=None,
    )
    assert _codes(_check(fact, swapped, mapping, SCORE_ANSWER)) == {"numeric_mismatch"}


def test_canonical_player_ids_are_never_translated_into_sql_ids(tmp_path: Path) -> None:
    mapping = _mapping(tmp_path)
    asserted = {**SCORELINE, "nba_player_id": "1628973"}
    fact = _fact(
        metric="game_score",
        scope="archive",
        value=dict(asserted),
        canonical_evidence_ids=[f"game:{NBA_GAME}"],
    )
    sql_id = _claim(
        metric_id="game_score",
        value={**asserted, "nba_player_id": 134},
        unit="game",
        denominator=None,
    )
    assert _codes(_check(fact, sql_id, mapping, SCORE_ANSWER)) == {"numeric_mismatch"}
    canonical = _claim(metric_id="game_score", value=dict(asserted), unit="game", denominator=None)
    assert _check(fact, canonical, mapping, SCORE_ANSWER).passed


@pytest.mark.parametrize(
    "reference",
    [
        f"game:{NBA_GAME}",
        f"box:{NBA_GAME}:1628973",
        f"team_box:{NBA_GAME}:NYK",
        f"period:{NBA_GAME}:NYK:3",
    ],
)
def test_every_canonical_source_prefix_names_its_game(tmp_path: Path, reference: str) -> None:
    fact = _one_game_fact(evidence=(reference,))
    assert _check(fact, _claim(), _mapping(tmp_path)).passed


@pytest.mark.parametrize(
    "reference",
    ["game:", "box:0022500622", f"shot:{NBA_GAME}", f"period:{NBA_GAME}:NYK"],
)
def test_a_malformed_or_unknown_reference_fails(tmp_path: Path, reference: str) -> None:
    fact = _one_game_fact(evidence=(reference,))
    assert _codes(_check(fact, _claim(), _mapping(tmp_path))) == {"evidence_scope_mismatch"}


@pytest.mark.parametrize(
    ("metric", "claim_metric", "unit"),
    [
        ("Jalen Brunson: total points", "points:game", "points"),
        ("Jalen Brunson: total rebounds", "rebounds:game", "rebounds"),
        ("Jalen Brunson: total assists", "assists:game", "assists"),
    ],
)
def test_one_game_count_forms_verify_total_facts(
    tmp_path: Path, metric: str, claim_metric: str, unit: str
) -> None:
    fact = _one_game_fact(metric=metric)
    assert _check(fact, _claim(metric_id=claim_metric, unit=unit), _mapping(tmp_path)).passed


def test_an_average_form_never_stands_for_a_one_game_total(tmp_path: Path) -> None:
    claim = _claim(metric_id="points:average", unit="points per appearance")
    codes = _codes(_check(_one_game_fact(), claim, _mapping(tmp_path)))
    assert codes == {"no_typed_claim_for_fact"}


def test_a_one_game_form_carries_its_own_season(tmp_path: Path) -> None:
    claim = _claim()
    observation = _observation((claim,), claim.statement, season="2024-25")
    check = check_fact(
        _one_game_fact(), observation, _mapping(tmp_path), numeric_tokens(claim.statement)
    )
    assert _codes(check) == {"season_mismatch"}


def test_a_one_game_form_carries_its_own_population(tmp_path: Path) -> None:
    rows = {
        f"game:{NBA_GAME}": _game_row(44),
        "game:0022500623": _game_row(45, "b" * 64),
    }
    fact = _one_game_fact()
    assert _codes(_check(fact, _claim(game_ids=(44, 45)), _mapping(tmp_path, rows))) == {
        "evidence_scope_mismatch"
    }


def test_another_dict_claim_never_stands_in_for_the_scoreline(tmp_path: Path) -> None:
    row = {**_game_row(44, canonical_digest(SCORELINE)), "source_row": SCORELINE}
    mapping = _mapping(tmp_path, {f"game:{NBA_GAME}": row})
    fact = _fact(
        metric="game_score",
        scope="archive",
        value=dict(SCORELINE),
        canonical_evidence_ids=[f"game:{NBA_GAME}"],
    )
    leader = _leader_claim()
    margin = _claim(metric_id="margin", value=54, unit="points", statement="Won by 54.")
    base = _observation((leader, margin), SCORE_ANSWER)
    observation = Observation(
        **{
            **base.__dict__,
            "evidence": {
                leader.supporting_evidence_ids[0]: EvidenceRecord.from_dict(
                    {
                        "evidence_id": leader.supporting_evidence_ids[0],
                        "release_id": VERSION,
                        "text": "row",
                        "source_row": SCORELINE,
                        "row_sha256": canonical_digest(SCORELINE),
                    }
                )
            },
        }
    )
    check = check_fact(fact, observation, mapping, numeric_tokens(SCORE_ANSWER))
    assert check.passed, check.failures


def _typed(claims: Sequence[VerifiedClaim]) -> tuple[TypedClaim, ...]:
    """The observation parser's own conversion of delivered claims."""
    return tuple(TypedClaim.from_dict(claim.model_dump(mode="json")) for claim in claims)


def _producer_observation(tools, claims: tuple[TypedClaim, ...]) -> Observation:
    answer = " ".join(claim.statement for claim in claims)
    return Observation(
        case_id="producer",
        turn_id="turn",
        request_id="req",
        outcome="answer",
        answer=answer,
        claims=claims,
        citations=(),
        analytics_status=None,
        analytics_result_count=0,
        traces=(),
        degraded=False,
        refused=False,
        route="factual_fallback",
        llm_validated=False,
        latency_ms=10.0,
        http_status=200,
        response_sha256="0" * 64,
        request={"question": tools.question, "season": tools.release.season},
        sent_request_id="req",
        evidence=_registry(tools),
    )


async def test_real_one_game_claims_verify_as_their_own_row_values(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points did Brunson score?")
    assert tools.scope is not None
    game = tools.games[3]
    result = game_summary(tools, tools.scope, [game])
    by_metric = {claim.metric_id: claim for claim in result.claims}
    assert {"points:game", "rebounds:game", "assists:game", "game_score"} <= set(by_metric)
    stat, player = next(
        pair
        for pair in tools.rows
        if pair[0].game_id == game.id and pair[1].full_name == "Jalen Brunson"
    )
    assert player.nba_player_id != player.id and game.nba_game_id != str(game.id)
    claims = _typed(result.claims)
    observation = _producer_observation(tools, claims)
    mapping = producer_mapping(tools, tmp_path)
    tokens = numeric_tokens(observation.answer)
    for column in ("points", "rebounds", "assists"):
        fact = _fact(
            metric=f"Jalen Brunson: total {column}",
            scope="archive",
            value=getattr(stat, column),
            canonical_evidence_ids=[f"box:{game.nba_game_id}:{player.nba_player_id}"],
            player_name=player.full_name,
            appearances=1,
        )
        check = check_fact(fact, observation, mapping, tokens)
        assert check.passed, (column, check.failures)
        delivered = next(claim for claim in claims if claim.metric_id == f"{column}:game")
        assert check.matched_claim_id == delivered.claim_id
    score = _fact(
        metric="game_score",
        scope="archive",
        value={
            "nba_game_id": game.nba_game_id,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "game_date": game.game_date.isoformat(),
        },
        canonical_evidence_ids=[f"game:{game.nba_game_id}"],
    )
    check = check_fact(score, observation, mapping, tokens)
    assert check.passed, check.failures


async def test_a_real_claim_carrying_a_sql_id_as_the_nba_id_fails(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points did Brunson score?")
    assert tools.scope is not None
    game = tools.games[3]
    result = game_summary(tools, tools.scope, [game])
    payloads = []
    canonical_score = None
    for claim in result.claims:
        raw = claim.model_dump(mode="json")
        if raw["metric_id"] == "game_score":
            canonical_score = dict(raw["value"])
            raw["value"] = {**raw["value"], "nba_game_id": game.id}
        payloads.append(raw)
    observation = _producer_observation(
        tools, tuple(TypedClaim.from_dict(item) for item in payloads)
    )
    mapping = producer_mapping(tools, tmp_path)
    assert canonical_score is not None
    fact = _fact(
        metric="game_score",
        scope="archive",
        value=canonical_score,
        canonical_evidence_ids=[f"game:{game.nba_game_id}"],
    )
    check = check_fact(fact, observation, mapping, numeric_tokens(observation.answer))
    assert _codes(check) == {"numeric_mismatch"}


async def test_a_real_claim_for_another_player_fails(db_session, tmp_path) -> None:
    tools = await _tools(db_session, "How many points did Brunson score?")
    assert tools.scope is not None
    game = tools.games[3]
    result = game_summary(tools, tools.scope, [game])
    stat, player = next(
        pair
        for pair in tools.rows
        if pair[0].game_id == game.id and pair[1].full_name == "Jalen Brunson"
    )
    observation = _producer_observation(tools, _typed(result.claims))
    mapping = producer_mapping(tools, tmp_path)
    fact = _fact(
        metric="Mikal Bridges: total points",
        scope="archive",
        value=stat.points,
        canonical_evidence_ids=[f"box:{game.nba_game_id}:{player.nba_player_id}"],
        player_name="Mikal Bridges",
        appearances=1,
    )
    check = check_fact(fact, observation, mapping, numeric_tokens(observation.answer))
    assert _codes(check) == {"entity_mismatch"}
