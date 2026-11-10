"""One-game player answers and follow-ups through the public analyst endpoint."""

import pytest
from app.tests.support.analyst_protocol import local_redis as local_redis
from app.tests.support.analytics_workflows import ask, player_archive


def claims(body):
    return {
        claim["metric_id"]: claim
        for citation in body["citations"]
        if (claim := citation["metadata"].get("claim"))
    }


async def test_game_summary_uses_the_selected_box_score_and_scoreline(client, monkeypatch):
    version, ids = await player_archive(monkeypatch)
    body = await ask(client, "What did Towns do in the biggest win?", version)
    result = claims(body)
    assert set(result) == {"points:game", "rebounds:game", "assists:game", "game_score"}
    assert (
        result["points:game"]["value"],
        result["rebounds:game"]["value"],
        result["assists:game"]["value"],
    ) == (18, 10, 3)
    assert result["game_score"]["value"]["home_score"] == 113
    assert result["game_score"]["value"]["away_score"] == 100
    for claim in result.values():
        assert claim["game_ids"] == [ids["2026-01-03"]]
        assert claim["release_id"] == version
    assert "18 points" in body["answer"] and "10 rebounds" in body["answer"]
    assert "per appearance" not in body["answer"].lower()


async def test_requested_measure_does_not_add_unrequested_statline(client, monkeypatch):
    version, _ = await player_archive(monkeypatch)
    body = await ask(client, "How many points did Towns score in the biggest win?", version)
    assert set(claims(body)) == {"points:total"}
    assert claims(body)["points:total"]["value"] == 18
    assert "rebounds" not in body["answer"].lower()
    assert "assists" not in body["answer"].lower()


async def test_requested_average_stays_an_average(client, monkeypatch):
    version, _ = await player_archive(monkeypatch)
    body = await ask(client, "What was Towns' scoring average in the biggest win?", version)
    assert set(claims(body)) == {"points:average"}
    assert claims(body)["points:average"]["value"] == 18
    assert "rebounds" not in body["answer"].lower()


async def test_key_sequence_without_event_measure_clarifies(client, monkeypatch):
    from app.tests.support.analytics_workflows import scope_archive

    version, _ = await scope_archive(monkeypatch)
    body = await ask(client, "What was the key sequence in the Boston loss on 2026-01-11?", version)
    assert body["outcome"] == "clarify"
    assert not claims(body)


@pytest.mark.parametrize(
    "question", ["What was Towns' stat line?", "What did Towns do in that game?"]
)
async def test_unanchored_game_summary_clarifies(client, monkeypatch, question):
    version, _ = await player_archive(monkeypatch)
    body = await ask(client, question, version)
    assert body["outcome"] == "clarify"
    assert not claims(body)


async def test_game_summary_does_not_invent_a_quality_judgment(client, monkeypatch):
    version, _ = await player_archive(monkeypatch)
    body = await ask(client, "Did Towns play well in the biggest win?", version)
    assert claims(body)["points:game"]["value"] == 18
    assert not any(
        word in body["answer"].lower() for word in ("well", "great", "badly", "poorly", "excellent")
    )


async def test_new_game_and_season_followups_do_not_reuse_old_anchor(
    client, local_redis, monkeypatch
):
    version, ids = await player_archive(monkeypatch)
    first = await client.post(
        "/analysis/query",
        json={
            "question": "What did Towns do in the biggest win?",
            "turn_id": "game-summary-first-001",
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["data_version"] == version and first_body["state_committed"]
    assert claims(first_body)["points:game"]["value"] == 18
    second = await client.post(
        "/analysis/query",
        json={
            "question": "What did Towns do on 2026-01-01?",
            "turn_id": "game-summary-second-01",
            "session_token": first_body["session_token"],
            "expected_revision": first_body["revision"],
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["state_committed"]
    assert claims(second_body)["points:game"]["value"] == 16
    assert all(claim["game_ids"] == [ids["2026-01-01"]] for claim in claims(second_body).values())
    third = await client.post(
        "/analysis/query",
        json={
            "question": "What was his average points over the whole season?",
            "turn_id": "game-summary-third-001",
            "session_token": second_body["session_token"],
            "expected_revision": second_body["revision"],
        },
    )
    assert third.status_code == 200
    season = claims(third.json())["points:average"]
    assert season["value"] == 17
    assert season["sample_size"] == 3
    assert season["game_ids"] == sorted(ids.values())
    assert season["release_id"] == version
