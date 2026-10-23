import asyncio

from app.core.db import AsyncSessionLocal
from app.services.query_policy import names_phase
from app.services.query_resolution import resolve_query

CASES = [
    ("How did they play in November?", None, False),
    ("How did the Knicks play in the fourth quarter against Boston?", None, False),
    ("How did they play in wins at home?", None, False),
    ("How did they do in the play-in?", "play_in", True),
    ("What was their record in the play in tournament?", "play_in", True),
    ("Did they win the play in game?", "play_in", True),
    ("How did they play in the playoffs?", "playoffs", True),
]


async def main() -> None:
    bad = 0
    async with AsyncSessionLocal() as db:
        for question, expected_type, expected_named in CASES:
            scope = await resolve_query(
                db, question, intent="get_team_stats", data_version="2025-26.20260928.1"
            )
            got_type = scope.season_type if expected_type else scope.season_type == "play_in"
            ok_type = got_type == expected_type if expected_type else got_type is False
            ok_named = names_phase(question) == expected_named
            bad += not (ok_type and ok_named)
            print(
                "OK " if ok_type and ok_named else "BAD",
                question,
                scope.season_type,
                names_phase(question),
            )
    print("FAILURES", bad)


asyncio.run(main())
