"""Window, filter and game-reference workflows through the public endpoint."""

from app.tests.support.analyst_protocol import local_redis as local_redis
from app.tests.support.analytics_workflows import ask, comparison_archive, scope_archive


def claims(body):
    return {
        claim["metric_id"]: claim
        for citation in body["citations"]
        if (claim := citation["metadata"].get("claim"))
    }


async def test_final_regular_window_excludes_playoffs(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(
        client, "What was their record over the final 2 regular-season games?", version
    )
    result = claims(body)
    assert (result["wins"]["value"], result["losses"]["value"]) == (1, 1)
    assert result["wins"]["game_ids"] == sorted(ids[d] for d in ("2026-02-10", "2026-02-20"))
    assert ids["2026-06-10"] not in result["wins"]["game_ids"]
    assert result["wins"]["release_id"] == version


async def test_after_all_star_record_uses_post_break_population(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(client, "What was their record after the All-Star break?", version)
    result = claims(body)
    assert set(result) == {"wins", "losses"}
    assert (result["wins"]["value"], result["losses"]["value"]) == (1, 1)
    expected = sorted(ids[day] for day in ("2026-02-20", "2026-06-10"))
    assert result["wins"]["game_ids"] == expected
    assert result["losses"]["game_ids"] == expected
    assert result["wins"]["release_id"] == result["losses"]["release_id"] == version


async def test_road_wins_inside_month_keep_both_filters(client, monkeypatch):
    version, ids = await scope_archive(monkeypatch)
    body = await ask(client, "How many road games did they win in January?", version)
    claim = claims(body)["wins"]
    assert claim["value"] == 1
    assert claim["game_ids"] == [ids["2026-01-03"]]
    assert claim["release_id"] == version


async def test_last_window_average_margin_uses_requested_games(client, monkeypatch):
    version, ids = await comparison_archive(monkeypatch)
    body = await ask(client, "What was their average margin over the last 2 games?", version)
    claim = claims(body)["margin_per_game"]
    assert claim["value"] == -0.5
    assert claim["denominator"] == 2
    assert claim["game_ids"] == sorted(ids[d] for d in ("2026-02-20", "2026-06-10"))
    assert claim["release_id"] == version


async def test_game_reference_requires_anchor_and_inherits_a_verified_game(
    client, local_redis, monkeypatch
):
    version, ids = await scope_archive(monkeypatch)
    unanchored = await ask(client, "How did JB play in that game?", version)
    assert unanchored["outcome"] == "clarify" and not claims(unanchored)
    first = await client.post(
        "/analysis/query",
        json={"question": "What happened on 2026-01-11?", "turn_id": "scope-anchor-first-001"},
    )
    assert first.status_code == 200
    anchor = first.json()
    assert anchor["state_committed"]
    second = await client.post(
        "/analysis/query",
        json={
            "question": "How did JB play in that game?",
            "turn_id": "scope-anchor-next-0001",
            "session_token": anchor["session_token"],
            "expected_revision": anchor["revision"],
        },
    )
    assert second.status_code == 200
    body = second.json()
    result = claims(body)
    assert (
        result["points:game"]["value"],
        result["rebounds:game"]["value"],
        result["assists:game"]["value"],
    ) == (15, 4, 10)
    assert all(claim["game_ids"] == [ids["2026-01-11"]] for claim in result.values())
    assert all(claim["release_id"] == version for claim in result.values())
