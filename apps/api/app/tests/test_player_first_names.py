from __future__ import annotations

import pytest
from app.models.player import Player
from app.services.query_players import resolve_player_mentions
from app.tests.test_metric_authority import _claims, _deterministic, _seed


async def test_unique_first_name_keeps_player_average_not_team_score(db_session):
    release = await _seed(
        db_session,
        [("2025-11-01", "NYK", "TOR", 110, 100), ("2025-11-05", "TOR", "NYK", 100, 120)],
        box={"Mikal Bridges": [(35, 18, 3, 2, 5), (35, 22, 3, 2, 5)]},
    )
    tools, _, result = await _deterministic(
        db_session, release, "How many points did Mikal average against Toronto?"
    )
    claim = _claims(result)["points:average"][0]
    assert claim["value"] == 20
    assert claim["sample_size"] == 2
    scope = tools.scope
    assert scope is not None
    assert claim["subject_id"] == f"player:{scope.player_ids[0]}"


@pytest.mark.parametrize("other_team", ["NYK", "BOS"])
def test_shared_first_name_produces_choices_without_selecting_player(other_team):
    players = [
        Player(id=1001, full_name="Alex One", team_id="NYK"),
        Player(id=1002, full_name="Alex Two", team_id=other_team),
    ]
    resolved, choices = resolve_player_mentions(
        "How many points did Alex score?", players, typo_threshold=0.85, allow_fuzzy=False
    )
    assert resolved == []
    assert choices == ["Alex One", "Alex Two"]


async def test_broad_player_performance_keeps_explicit_opponent_population(db_session):
    release = await _seed(
        db_session,
        [("2025-11-01", "NYK", "TOR", 110, 100), ("2025-11-05", "TOR", "NYK", 100, 120)],
        box={"Mikal Bridges": [(35, 18, 3, 2, 5), (35, 22, 3, 2, 5)]},
    )
    _, _, result = await _deterministic(db_session, release, "Did Mikal play well against Toronto?")
    claim = _claims(result)["points:average"][0]
    assert claim["value"] == 20
    assert claim["sample_size"] == 2
