"""Single-game player lines, per-game lists and scoring outputs."""

from __future__ import annotations

import re

from model import Session, number
from verify_common import scope_for
from verify_player import player_before, player_near, stat_atom


def verify_player_lines(s: Session) -> None:
    _lines_with_units(s)
    _lines_with_dates(s)
    _game_by_game_lists(s)
    _top_scoring_lists(s)
    _slash_lines(s)

def _resolve_game(s: Session, date: str | None, opp: str | None, player: str, pos: int) -> dict | None:
    rows = s.oracle.player_rows(player, season_type=None)
    candidates = rows
    if date:
        candidates = [r for r in candidates if r["game"].date == date]
    if opp:
        candidates = [r for r in candidates if r["game"].opp == opp]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        scope = scope_for(s, pos)
        rows2 = s.oracle.player_rows(player, **scope.filters())
        return rows2[0] if len(rows2) == 1 else None
    return None

def _mark_line(s: Session, player: str, row: dict | None, fields: dict[str, object], pos: int) -> None:
    if row is None:
        return
    sql = s.oracle._player_sql(player, True, {})
    for atom, key, claimed in fields:
        if atom is None or not s.free(atom):
            continue
        expected = row.get(key)
        s.mark(atom, claimed, expected, f"{player} {row['game'].date} vs {row['game'].opp} {key}", sql)

def _lines_with_units(s: Session) -> None:
    pattern = re.compile(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s*:?\s*,?\s*"
        r"(?P<p>\d+)\s+points?,\s*(?P<r>\d+)\s+rebounds?"
        r"(?:,\s*(?P<a>\d+)\s+assists?)?(?:,?\s*(?:and\s+)?(?P<t>\d+)\s+turnovers?)?"
        r"[^.\n]{0,80}?(?:on\s+(?P<date>\d{4}-\d{2}-\d{2}))?"
        r"[^.\n]{0,40}?(?:vs\.?|against)\s+(?P<opp>[A-Za-z]{3})\b"
        r"(?:\s+on\s+(?P<date2>\d{4}-\d{2}-\d{2}))?",
        re.I,
    )
    for m in pattern.finditer(s.text):
        player = player_before(s.text, m.start("p"), window=140)
        if not player:
            continue
        date = m.group("date") or m.group("date2")
        if not date:
            dm = re.search(r"\d{4}-\d{2}-\d{2}", m.group(0))
            date = dm.group(0) if dm else None
        fields = {}
        for group, key in (("p", "points"), ("r", "rebounds"), ("a", "assists"), ("t", "turnovers")):
            if m.group(group):
                atom = stat_atom(s, m, group)
                fields[key] = (atom, int(m.group(group)))
        row = _resolve_game(s, date, m.group("opp").upper(), player, m.start())
        if row is None:
            continue
        sql = s.oracle._player_sql(player, True, {})
        for key, (atom, claimed) in fields.items():
            if atom:
                s.mark(atom, claimed, row[key], f"{player} {row['game'].date} vs {row['game'].opp} {key}", sql)

def _lines_with_dates(s: Session) -> None:
    # "22 points (2025-12-21 vs MIA)" and "(47 points on 2025-12-21 vs MIA)"
    pattern = re.compile(
        r"(?P<p>\d+)\s+points?\s*\((?P<date>\d{4}-\d{2}-\d{2})\s+vs\.?\s+(?P<opp>[A-Z]{3})\)",
        re.I,
    )
    for m in pattern.finditer(s.text):
        player = player_before(s.text, m.start("p"), window=160)
        if not player:
            continue
        atom = stat_atom(s, m, "p")
        row = _resolve_game(s, m.group("date"), m.group("opp").upper(), player, m.start())
        if atom and row:
            s.mark(atom, int(m.group("p")), row["points"],
                   f"{player} {row['game'].date} vs {row['game'].opp} points",
                   s.oracle._player_sql(player, True, {}))
    # "47 points on 2025-12-21 vs MIA"
    pattern = re.compile(
        r"(?P<p>\d+)\s+points?\s+on\s+(?P<date>\d{4}-\d{2}-\d{2})\s+(?:vs\.?|against)\s+(?P<opp>[A-Z]{3})",
        re.I,
    )
    for m in pattern.finditer(s.text):
        player = player_before(s.text, m.start("p"), window=160)
        if not player:
            continue
        atom = stat_atom(s, m, "p")
        row = _resolve_game(s, m.group("date"), m.group("opp").upper(), player, m.start())
        if atom and row:
            s.mark(atom, int(m.group("p")), row["points"],
                   f"{player} {row['game'].date} vs {row['game'].opp} points",
                   s.oracle._player_sql(player, True, {}))
    # "39 points (2025-11-14 vs MIA)" style without the word points? covered.
    # "47-point game on DATE vs OPP"
    pattern = re.compile(
        r"(?P<p>\d+)-point game on\s+(?P<date>20\d{2}-\d{2}-\d{2})\s+"
        r"(?:vs\.?|against)\s+(?P<opp>[A-Z]{3})",
        re.I,
    )
    for m in pattern.finditer(s.text):
        player = player_before(s.text, m.start("p"), window=200)
        if not player:
            continue
        atom = stat_atom(s, m, "p")
        row = _resolve_game(s, m.group("date"), m.group("opp").upper(), player, m.start())
        if atom and row:
            s.mark(atom, int(m.group("p")), row["points"],
                   f"{player} {row['game'].date} vs {row['game'].opp} points",
                   s.oracle._player_sql(player, True, {}))
    # "47-point, 8-assist, 0-turnover game on DATE against OPP"
    pattern = re.compile(
        r"(?P<p>\d+)-point,\s*(?P<a>\d+)-assist,\s*(?P<t>\d+)-turnover game on\s+"
        r"(?P<date>\d{4}-\d{2}-\d{2})[^.\n]{0,20}?(?:vs\.?|against)\s+(?P<opp>[A-Z]{3})",
        re.I,
    )
    for m in pattern.finditer(s.text):
        player = player_before(s.text, m.start("p"), window=160)
        if not player:
            continue
        atom = stat_atom(s, m, "p")
        row = _resolve_game(s, m.group("date"), m.group("opp").upper(), player, m.start())
        if atom and row:
            s.mark(atom, int(m.group("p")), row["points"],
                   f"{player} {row['game'].date} vs {row['game'].opp} points",
                   s.oracle._player_sql(player, True, {}))

def _game_by_game_lists(s: Session) -> None:
    for m in re.finditer(
        r"Game-by-game:\s*((?:\d+(?:\.\d+)?\s*(?:,\s*|\s+and\s+)?)+?)(?:\s*points?)?[.\n]",
        s.text, re.I,
    ):
        player = player_before(s.text, m.start(), window=200) or player_near(s.text, m.start(), window=180)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        values = [r["points"] for r in stats["rows"]]
        if scope.last_n:
            values = values[-scope.last_n:]
        nums = [a for a in s.inside(m.start(1), m.end(1)) if a.kind == "number"]
        if len(nums) == len(values):
            for atom, expected in zip(nums, values):
                s.mark(atom, number(atom.raw), expected,
                       f"{player} per-game points {scope.filters()}", stats["sql"])

def _top_scoring_lists(s: Session) -> None:
    # "Brunson's top scoring outputs reaching 47, 42 and 40 points and Towns' reaching 39, 37 and 35"
    for m in re.finditer(
        r"(?P<a>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s+top scoring (?:outputs|games)[^.]{0,80}?"
        r"reaching\s+(?P<va>\d+),\s*(?P<vb>\d+)\s+and\s+(?P<vc>\d+)\s+points"
        r"[^.]{0,40}?(?P<b>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s+reaching\s+"
        r"(?P<wd>\d+),\s*(?P<we>\d+)\s+and\s+(?P<wf>\d+)\s+points",
        s.text, re.I,
    ):
        pa = player_near(s.text, m.start("a") + 1, window=30)
        pb = player_near(s.text, m.start("b") + 1, window=30)
        if not pa or not pb:
            continue
        for name, groups in ((pa, ("va", "vb", "vc")), (pb, ("wd", "we", "wf"))):
            values = [r["points"] for r in s.oracle.player_rows(name, season_type="regular")]
            for group in groups:
                atom = stat_atom(s, m, group)
                if atom:
                    claimed = int(m.group(group))
                    s.mark(atom, claimed, claimed if claimed in values else None,
                           f"{name} single-game scoring value",
                           s.oracle._player_sql(name, True, {}),
                           status="verified" if claimed in values else "wrong")
    # "top scoring games include 47 points (date vs opp), 42 (...), and 40 twice (...)"
    for m in re.finditer(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s+top scoring games include\s+"
        r"(?P<p1>\d+)\s+points\s*\((?P<d1>[^)]*)\)[,;]\s*"
        r"(?P<p2>\d+)\s+\((?P<d2>[^)]*)\)[,;]?\s*and\s+"
        r"(?P<p3>\d+)\s+twice\s*\((?P<d3>[^)]*)\)",
        s.text, re.I,
    ):
        name = player_near(s.text, m.start("name") + 1, window=30)
        if not name:
            continue
        for group, date_group in (("p1", "d1"), ("p2", "d2")):
            dm = re.search(r"\d{4}-\d{2}-\d{2}", m.group(date_group))
            if not dm:
                continue
            row = _resolve_game(s, dm.group(0), None, name, m.start())
            atom = stat_atom(s, m, group)
            if atom and row:
                s.mark(atom, int(m.group(group)), row["points"],
                       f"{name} {row['game'].date} points", s.oracle._player_sql(name, True, {}))
        dm = re.search(r"\d{4}-\d{2}-\d{2}", m.group("d3"))
        if dm:
            row = _resolve_game(s, dm.group(0), None, name, m.start())
            if row:
                count = sum(
                    1 for r in s.oracle.player_rows(name, season_type="regular")
                    if r["points"] == int(m.group("p3"))
                )
                atom = stat_atom(s, m, "p3")
                if atom:
                    s.mark(atom, int(m.group("p3")), int(m.group("p3")) if count >= 2 else None,
                           f"{name} repeated scoring output", s.oracle._player_sql(name, True, {}))

def _slash_lines(s: Session) -> None:
    # "22 pts/8 reb (Nov 30)" with the player named earlier.
    for m in re.finditer(
        r"(?P<p>\d+)\s*pts?/(?P<r>\d+)\s*reb(?:/(?P<a>\d+)\s*ast)?\s*\((?P<md>[A-Z][a-z]{2,8}\.?\s+\d{1,2})\)",
        s.text,
    ):
        player = player_before(s.text, m.start("p"), window=2000)
        if not player:
            continue
        date = _month_day_date(s, m.group("md"))
        row = _resolve_game(s, date, None, player, m.start())
        if row is None:
            continue
        for group, key in (("p", "points"), ("r", "rebounds"), ("a", "assists")):
            if not m.group(group):
                continue
            atom = stat_atom(s, m, group)
            if atom:
                s.mark(atom, int(m.group(group)), row[key],
                       f"{player} {row['game'].date} {key}", s.oracle._player_sql(player, True, {}))

def _month_day_date(s: Session, text: str) -> str | None:
    m = re.search(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2})", text)
    if not m:
        return None
    from model import parse_month
    month = parse_month(m.group(1))
    year = 2025 if month >= 8 else 2026
    return f"{year:04d}-{month:02d}-{int(m.group(2)):02d}"
