"""Sweep player-mention resolution against the local release.

No model calls. Every first name, last name, initial plus surname, full name, nickname and
three typo variants of every player with a box score row on the active release are resolved
through ``resolve_query``. Expected mentions are built from the release, not from the
resolver's alias helpers.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    uv run --package knicksiq-api python \
    docs/release-evidence/llm-primary-20261021/w3-resolve/sweep_players.py --out out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.player import Player
from app.services.query_resolution import resolve_query

try:
    from app.services.query_text import normalize as _normalize
except ImportError:
    from app.services.query_resolution import _normalize
from sqlalchemy import select

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# Nicknames a Knicks fan uses for the current roster, plus the curated aliases in code.
NICKNAMES = {
    "jb": "Jalen Brunson",
    "brunson": "Jalen Brunson",
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "og": "OG Anunoby",
    "deuce": "Miles McBride",
    "mitch": "Mitchell Robinson",
}
CONCURRENCY = 8


@dataclass
class Row:
    kind: str
    player_id: int
    full_name: str
    team_id: str
    token: str
    question: str
    expected: str
    resolved_ids: list[int] = field(default_factory=list)
    resolved_names: list[str] = field(default_factory=list)
    clarification: bool = False
    options: list[str] = field(default_factory=list)
    status: str = ""


def _parts(full_name: str) -> tuple[list[str], str, str]:
    raw = full_name.strip()
    parts = _normalize(raw).split()
    if not parts:
        return [], "", ""
    if " " not in raw and "-" in raw:
        return parts, "", " ".join(parts)
    if len(parts) == 1:
        return parts, "", parts[0]
    surname_index = len(parts) - 2 if parts[-1] in SUFFIXES and len(parts) > 1 else len(parts) - 1
    return parts, " ".join(parts[:surname_index]), parts[surname_index]


def _typo_variants(token: str) -> list[tuple[str, str]]:
    if len(token) < 4:
        return []
    middle = len(token) // 2
    variants = [
        ("typo_delete", token[:middle] + token[middle + 1 :]),
        ("typo_transpose", token[:1] + token[2] + token[1] + token[3:]),
        ("typo_substitute", token[:-1] + "z"),
    ]
    return [(kind, value) for kind, value in variants if value != token]


def _alias_groups(players: list[Player]) -> tuple[dict[str, set[int]], dict[int, str]]:
    groups: dict[str, set[int]] = defaultdict(set)
    names = {player.id: player.full_name for player in players}
    given_counts: Counter[str] = Counter()
    for player in players:
        parts, given, _ = _parts(player.full_name)
        if len(parts) > 1 and len(given.replace(" ", "")) >= 3:
            given_counts[given] += 1
    for player in players:
        parts, given, surname = _parts(player.full_name)
        if not parts:
            continue
        groups[" ".join(parts)].add(player.id)
        groups[surname].add(player.id)
        if len(parts) > 1:
            groups[f"{parts[0][0]} {surname}"].add(player.id)
            if given_counts[given] == 1:
                groups[given].add(player.id)
    for nickname, target in NICKNAMES.items():
        for player in players:
            if player.full_name == target:
                groups[_normalize(nickname)].add(player.id)
    return groups, names


GIVEN_INDEX: dict[str, set[int]] = defaultdict(set)


def _expect(
    groups: dict[str, set[int]],
    names: dict[int, str],
    players_by_id: dict[int, Player],
    token: str,
    *,
    bare: bool = True,
) -> tuple[list[int] | None, list[str] | None]:
    matches = set(groups.get(_normalize(token), set()))
    if bare:
        matches.update(GIVEN_INDEX.get(_normalize(token), set()))
    if not matches:
        return None, None
    if len(matches) == 1:
        return sorted(matches), None
    knicks = [player_id for player_id in matches if players_by_id[player_id].team_id == "NYK"]
    if len(knicks) == 1:
        return sorted(knicks), None
    return None, sorted(names[player_id] for player_id in matches)


def _classify(
    row: Row,
    expected_ids: list[int] | None,
    expected_options: list[str] | None,
    intended: int,
) -> str:
    if expected_ids is not None:
        if row.resolved_ids == expected_ids and not row.clarification:
            return "ok"
        if row.clarification:
            return "spurious_ambiguity" if names_of(intended) in row.options else "wrong_ambiguity"
        if row.resolved_ids:
            return "wrong_player"
        return "typo_unresolved" if row.kind.startswith("typo") else "unresolved"
    if expected_options is not None:
        if not row.clarification:
            return "silent_ambiguity" if row.resolved_ids else "unresolved"
        return "ok" if row.options == expected_options else "wrong_ambiguity"
    # An unanchored typo: any other player is wrong, asking without the intended player is
    # wrong, and staying unresolved is only a miss.
    if row.clarification:
        return "ok" if names_of(intended) in row.options else "wrong_ambiguity"
    if not row.resolved_ids:
        return "typo_unresolved"
    return "ok" if row.resolved_ids == [intended] else "wrong_player"


def names_of(player_id: int) -> str:
    return names_of.names.get(player_id, str(player_id))


names_of.names = {}  # type: ignore[attr-defined]


async def _one(session_factory, sem: asyncio.Semaphore, row: Row, expected_ids, expected_options):
    async with sem, session_factory() as db:
        resolved = await resolve_query(db, row.question, intent="analyst", data_version=RELEASE)
    row.resolved_ids = resolved.player_ids
    row.resolved_names = [names_of(player_id) for player_id in resolved.player_ids]
    row.clarification = resolved.requires_clarification
    row.options = resolved.clarification_options
    row.status = _classify(row, expected_ids, expected_options, row.player_id)
    return row


RELEASE = ""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    global RELEASE
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(DatasetRelease.status == "active").limit(1)
            )
        ).scalar_one()
        RELEASE = release.version
        players = list(
            (
                await db.execute(
                    select(Player)
                    .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                    .where(PlayerGameStat.release_id == release.id)
                    .distinct()
                    .order_by(Player.full_name)
                )
            ).scalars()
        )
    groups, names = _alias_groups(players)
    names_of.names = names
    for player in players:
        _, given, _ = _parts(player.full_name)
        if given:
            GIVEN_INDEX[given].add(player.id)
    by_id = {player.id: player for player in players}
    rows: list[tuple[Row, list[int] | None, list[str] | None]] = []

    def add(kind: str, player: Player, token: str, question: str) -> None:
        expected_ids, expected_options = _expect(
            groups, names, by_id, token, bare=question.strip() == token
        )
        rows.append(
            (
                Row(
                    kind,
                    player.id,
                    player.full_name,
                    player.team_id,
                    token,
                    question,
                    "ambiguous" if expected_options else "unique",
                ),
                expected_ids,
                expected_options,
            )
        )

    for player in players:
        parts, given, surname = _parts(player.full_name)
        add("full", player, player.full_name, player.full_name)
        add(
            "full_template",
            player,
            player.full_name,
            f"How many points did {player.full_name} score?",
        )
        if given and len(given.replace(" ", "")) >= 3:
            add("first", player, given.title(), given.title())
            add(
                "first_template",
                player,
                given.title(),
                f"Did {given.title()} play well against Toronto?",
            )
        add("last", player, surname.title(), surname.title())
        add(
            "last_template",
            player,
            surname.title(),
            f"Did {surname.title()} play well against Toronto?",
        )
        add("last_points", player, surname.title(), f"How many points did {surname.title()} score?")
        add(
            "initial",
            player,
            f"{parts[0][0].upper()} {surname.title()}",
            f"{parts[0][0].upper()} {surname.title()}",
        )
        for typo_kind, token in _typo_variants(surname):
            if _normalize(token) in groups and player.id not in groups[_normalize(token)]:
                rows.append(
                    (
                        Row(
                            typo_kind,
                            player.id,
                            player.full_name,
                            player.team_id,
                            token,
                            token,
                            "collision",
                        ),
                        None,
                        None,
                    )
                )
                continue
            rows.append(
                (
                    Row(
                        typo_kind, player.id, player.full_name, player.team_id, token, token, "typo"
                    ),
                    [player.id],
                    None,
                )
            )
    for nickname, target in NICKNAMES.items():
        player = next((item for item in players if item.full_name == target), None)
        if player is None:
            continue
        add("nickname", player, nickname, nickname)
        add("nickname_template", player, nickname, f"Did {nickname} play well against Toronto?")
    if args.limit:
        rows = rows[: args.limit]

    sem = asyncio.Semaphore(CONCURRENCY)
    rows = await asyncio.gather(
        *(
            _one(AsyncSessionLocal, sem, row, expected_ids, expected_options)
            for row, expected_ids, expected_options in rows
        )
    )
    for row in rows:
        if row.expected == "collision":
            row.status = "skipped_collision"
    player_rows: list[dict[str, Any]] = [
        {
            "kind": row.kind,
            "player": row.full_name,
            "team": row.team_id,
            "token": row.token,
            "question": row.question,
            "expected": row.expected,
            "resolved_ids": row.resolved_ids,
            "resolved_names": row.resolved_names,
            "clarification": row.clarification,
            "options": row.options,
            "status": row.status,
        }
        for row in rows
    ]
    counts = Counter(row["status"] for row in player_rows)
    summary = {
        "release": RELEASE,
        "players": len(players),
        "cases": len(player_rows),
        "status": dict(sorted(counts.items())),
        "wrong_player": [row for row in player_rows if row["status"] == "wrong_player"],
        "wrong_ambiguity": [row for row in player_rows if row["status"] == "wrong_ambiguity"],
        "silent_ambiguity": [row for row in player_rows if row["status"] == "silent_ambiguity"],
        "spurious_ambiguity": [row for row in player_rows if row["status"] == "spurious_ambiguity"],
        "typo_unresolved": [row for row in player_rows if row["status"] == "typo_unresolved"],
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "players": player_rows}, indent=1))
    print(
        json.dumps(
            {key: summary[key] for key in ("release", "players", "cases", "status")}, indent=1
        )
    )
    for key in ("wrong_player", "wrong_ambiguity", "silent_ambiguity", "spurious_ambiguity"):
        print(key, len(summary[key]))
        for row in summary[key][:8]:
            print(
                " ",
                row["kind"],
                row["player"],
                "<-",
                row["token"],
                "->",
                row["resolved_names"],
                row["options"][:4],
            )


if __name__ == "__main__":
    asyncio.run(main())
