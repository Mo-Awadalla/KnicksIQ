"""Native team-threshold and player-leader facts through the analyst HTTP loop."""

from datetime import UTC, date, datetime

from app.core.db import AsyncSessionLocal
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_analyst_payload_http import (
    SyntheticAdapter,
    assert_committed_replay,
    configure,
    exchange,
    save_receipt,
)
from sqlalchemy import select

VERSION = "population-facts-http-test"
PLAYER_LINES = {
    "Jalen Brunson": "jalen",
    "Josh Hart": "hart",
    "Karl-Anthony Towns": "towns",
    "OG Anunoby": "og",
}
GAMES = [
    {
        "date": date(2025, 12, 21),
        "opponent": "MIA",
        "knicks": 132,
        "opponent_score": 125,
        "stats": {
            "jalen": (47, 5),
            "hart": (12, 10),
            "towns": (18, 9),
            "og": (8, 8),
        },
    },
    {
        "date": date(2025, 12, 25),
        "opponent": "CLE",
        "knicks": 130,
        "opponent_score": 122,
        "stats": {
            "jalen": (34, 6),
            "hart": (14, 8),
            "towns": (15, 12),
            "og": (6, 5),
        },
    },
    {
        "date": date(2026, 1, 28),
        "opponent": "TOR",
        "knicks": 125,
        "opponent_score": 124,
        "stats": {
            "jalen": (21, 4),
            "hart": (10, 9),
            "towns": (12, 22),
            "og": (8, 11),
        },
    },
    {
        "date": date(2026, 2, 4),
        "opponent": "DEN",
        "knicks": 128,
        "opponent_score": 126,
        "stats": {
            "jalen": (42, 5),
            "hart": (9, 7),
            "towns": (16, 11),
            "og": (7, 10),
        },
    },
    {
        "date": date(2026, 3, 13),
        "opponent": "IND",
        "knicks": 131,
        "opponent_score": 129,
        "stats": {
            "jalen": (30, 4),
            "hart": (9, 11),
            "towns": (18, 17),
            "og": (12, 22),
        },
    },
]


async def seed_population_release() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        release = DatasetRelease(
            version=VERSION,
            season="2025-26",
            source="test",
            manifest_sha256="c" * 64,
            validation_passed=True,
            status="active",
            activated_at=datetime.now(UTC),
        )
        db.add(release)
        await db.flush()
        players = {
            player.full_name: player
            for player in (
                await db.execute(select(Player).where(Player.full_name.in_(PLAYER_LINES)))
            ).scalars()
        }
        assert set(players) == set(PLAYER_LINES)
        for index, row in enumerate(GAMES):
            game = Game(
                release_id=release.id,
                nba_game_id=f"population-{index}",
                season=release.season,
                game_date=row["date"],
                home_team_id="NYK",
                away_team_id=row["opponent"],
                home_score=row["knicks"],
                away_score=row["opponent_score"],
                status="final",
                season_type="regular",
                source_name="test",
                source_game_id=f"population-{index}",
            )
            db.add(game)
            await db.flush()
            for name, player in players.items():
                points, rebounds = row["stats"][PLAYER_LINES[name]]
                db.add(
                    PlayerGameStat(
                        release_id=release.id,
                        game_id=game.id,
                        player_id=player.id,
                        team_id="NYK",
                        minutes=30,
                        points=points,
                        rebounds=rebounds,
                    )
                )
        superseded = DatasetRelease(
            version=f"{VERSION}-superseded",
            season="2025-26",
            source="test",
            manifest_sha256="d" * 64,
            validation_passed=True,
            status="superseded",
            activated_at=datetime.now(UTC),
        )
        db.add(superseded)
        await db.flush()
        future_game = Game(
            release_id=superseded.id,
            nba_game_id="population-superseded",
            season=superseded.season,
            game_date=date(2026, 3, 14),
            home_team_id="NYK",
            away_team_id="MIA",
            home_score=250,
            away_score=100,
            status="final",
            season_type="regular",
            source_name="test",
            source_game_id="population-superseded",
        )
        db.add(future_game)
        await db.flush()
        for player in players.values():
            db.add(
                PlayerGameStat(
                    release_id=superseded.id,
                    game_id=future_game.id,
                    player_id=player.id,
                    team_id="NYK",
                    minutes=30,
                    points=100,
                    rebounds=30,
                )
            )

        await db.commit()
        return {name: player.id for name, player in players.items()}


def tool_result(receipt: dict) -> dict:
    tools = receipt["capture"]["tools"]
    assert len(tools) == 1
    return tools[0]["result"]


async def request(
    client, redis, monkeypatch, tmp_path, record_property, name, question, *, metric=None
):
    configure(monkeypatch)
    adapter = SyntheticAdapter(
        {
            "name": "get_team_stats",
            "question": question,
            "metric": metric,
            "aggregation": "total",
        }
    )
    monkeypatch.setattr(analyst_loop, "get_llm_adapter", lambda: adapter)
    receipt = await exchange(client, redis, adapter, name, question)
    save_receipt(tmp_path, record_property, name, receipt)
    assert_committed_replay(receipt)
    return receipt


async def test_team_threshold_counts_times_with_strict_and_inclusive_boundaries_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    strict = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "team-score-over-130",
        "How many times did the Knicks score more than 130 points?",
    )
    inclusive = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "team-score-at-least-130",
        "How many times did the Knicks score at least 130 points?",
    )
    strict_claims = tool_result(strict)["claims"]
    inclusive_claims = tool_result(inclusive)["claims"]
    assert len(strict_claims) == len(inclusive_claims) == 1
    assert strict_claims[0]["metric_id"] == inclusive_claims[0]["metric_id"] == "games:count"
    assert strict_claims[0]["value"] == 2
    assert inclusive_claims[0]["value"] == 3
    assert strict_claims[0]["sample_size"] == inclusive_claims[0]["sample_size"] == len(GAMES)
    assert strict_claims[0]["eligibility"]["score_predicate"] == {
        "subject_id": "team:NYK",
        "metric_id": "points",
        "operator": ">",
        "cutoff": 130,
    }
    assert inclusive_claims[0]["eligibility"]["score_predicate"] == {
        "subject_id": "team:NYK",
        "metric_id": "points",
        "operator": ">=",
        "cutoff": 130,
    }


async def test_scoped_game_rebound_leader_uses_all_knicks_player_rows_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    receipt = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "miami-december-21-rebound-leader",
        "Who had the most rebounds for the Knicks against Miami on December 21?",
        metric="leaders",
    )
    result = tool_result(receipt)
    claim = next(c for c in result["claims"] if c["metric_id"] == "rebounds:leaders")
    assert claim["value"] == {"leaders": ["Josh Hart"], "total": 10}
    assert claim["game_ids"] and len(claim["game_ids"]) == 1
    player_evidence = {
        item["metadata"]["player"]: item["metadata"]["rebounds"]
        for item in result["evidence"]
        if item["metadata"].get("subject_id")
    }
    assert player_evidence == {
        "Jalen Brunson": 5,
        "Josh Hart": 10,
        "Karl-Anthony Towns": 9,
        "OG Anunoby": 8,
    }
    assert claim["subject_id"] == "team:NYK"


async def test_single_game_points_high_is_not_a_season_total_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    receipt = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "single-game-points-high",
        "What was the most points a Knick scored in one game this season?",
        metric="leaders",
    )
    claim = next(
        c for c in tool_result(receipt)["claims"] if c["metric_id"] == "points:single_game_high"
    )
    assert claim["value"] == {
        "maximum": 47,
        "rows": [
            {
                "player": "Jalen Brunson",
                "date": "2025-12-21",
                "opponent": "MIA",
                "value": 47,
            }
        ],
    }
    assert claim["sample_size"] == len(GAMES) * len(PLAYER_LINES)
    assert claim["denominator"] is None
    player_rows = [
        item for item in tool_result(receipt)["evidence"] if item["metadata"].get("subject_id")
    ]
    assert len(player_rows) == len(GAMES) * len(PLAYER_LINES)


async def test_single_game_rebound_high_preserves_tied_rows_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    receipt = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "single-game-rebound-high-ties",
        "What was the most rebounds a Knick had in a single game?",
        metric="leaders",
    )
    claim = next(
        c for c in tool_result(receipt)["claims"] if c["metric_id"] == "rebounds:single_game_high"
    )
    assert claim["value"] == {
        "maximum": 22,
        "rows": [
            {
                "player": "Karl-Anthony Towns",
                "date": "2026-01-28",
                "opponent": "TOR",
                "value": 22,
            },
            {
                "player": "OG Anunoby",
                "date": "2026-03-13",
                "opponent": "IND",
                "value": 22,
            },
        ],
    }
    evidence = tool_result(receipt)["evidence"]
    player_rows = [item for item in evidence if item["metadata"].get("subject_id")]
    assert len(player_rows) == len(GAMES) * len(PLAYER_LINES)
    assert {
        (item["metadata"]["player"], item["metadata"]["date"], item["metadata"]["rebounds"])
        for item in player_rows
        if item["metadata"]["rebounds"] == 22
    } == {
        ("Karl-Anthony Towns", "2026-01-28", 22),
        ("OG Anunoby", "2026-03-13", 22),
    }


async def test_christmas_day_scoring_leader_uses_date_scoped_player_rows_http(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    await seed_population_release()
    receipt = await request(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        "christmas-day-scoring-leader",
        "Who led the Knicks in scoring on Christmas Day?",
        metric="leaders",
    )
    result = tool_result(receipt)
    assert result["scope"]["date_start"] == result["scope"]["date_end"] == "2025-12-25"
    claim = next(c for c in result["claims"] if c["metric_id"] == "points:leaders")
    assert claim["value"] == {"leaders": ["Jalen Brunson"], "total": 34}
    assert claim["game_ids"] and len(claim["game_ids"]) == 1
