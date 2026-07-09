"""Tests for player + team endpoints."""

from __future__ import annotations


async def test_list_teams(client):
    r = await client.get("/teams")
    assert r.status_code == 200
    teams = r.json()
    assert len(teams) >= 2
    nyk = next(t for t in teams if t["id"] == "NYK")
    assert nyk["name"] == "Knicks"


async def test_get_team(client):
    r = await client.get("/teams/NYK")
    assert r.status_code == 200
    team = r.json()
    assert team["id"] == "NYK"
    assert team["city"] == "New York"


async def test_list_players(client):
    r = await client.get("/players")
    assert r.status_code == 200
    players = r.json()
    assert len(players) >= 5


async def test_list_players_filter_by_team(client):
    r = await client.get("/players?team_id=NYK")
    assert r.status_code == 200
    players = r.json()
    for p in players:
        assert p["team_id"] == "NYK"


async def test_list_players_search(client):
    r = await client.get("/players?search=brunson")
    assert r.status_code == 200
    players = r.json()
    assert any("Brunson" in p["full_name"] for p in players)
