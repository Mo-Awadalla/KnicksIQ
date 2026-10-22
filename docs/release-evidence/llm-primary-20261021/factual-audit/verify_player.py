"""Player aggregate and single-game line verification."""

from __future__ import annotations

import re

from model import Session, number
from scope import Scope
from verify_common import scope_for, scalar_atom


PLAYER_ALIASES = {
    "Jalen Brunson": ["Jalen Brunson", "Brunson", "JB"],
    "Karl-Anthony Towns": ["Karl-Anthony Towns", "Towns", "KAT"],
    "Josh Hart": ["Josh Hart", "Hart"],
    "Mikal Bridges": ["Mikal Bridges", "Bridges", "Mikal"],
    "OG Anunoby": ["OG Anunoby", "Anunoby", "OG"],
}


def players_in(text: str) -> list[tuple[int, str]]:
    found = []
    for canonical, aliases in PLAYER_ALIASES.items():
        for alias in aliases:
            pattern = r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])"
            for m in re.finditer(pattern, text, re.I):
                found.append((m.start(), canonical))
    return sorted(found)


def player_near(text: str, pos: int, window: int = 200) -> str | None:
    rows = [(abs(start - pos), start, name) for start, name in players_in(text) if abs(start - pos) <= window]
    return min(rows)[2] if rows else None


def player_before(text: str, pos: int, window: int = 140) -> str | None:
    rows = [(start, name) for start, name in players_in(text) if 0 <= pos - start <= window]
    return max(rows)[1] if rows else None


def stat_atom(s: Session, m: re.Match, group: int):
    atom = scalar_atom(s, m, group)
    if atom is None or not s.free(atom) or atom.kind != "number":
        return None
    return atom


def _player_scope(s: Session, pos: int, player: str, appearances: bool = True) -> tuple[dict, Scope]:
    scope = scope_for(s, pos)
    scope.player = player
    return scope, scope


def verify_player_aggregates(s: Session) -> None:
    # "NAME averaged X points per game/appearance over his last N observed appearances"
    for m in re.finditer(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?)\s+averaged\s+(?P<value>\d+(?:\.\d+)?)\s+points?"
        r"(?:\s+per\s+(?:game|appearance))?[^.\n]{0,60}?last\s+(?P<n>\d+)\s+(?:observed\s+)?(?:appearances|games)",
        s.text, re.I,
    ):
        player = player_near(s.text, m.start("name") + 1, window=30)
        if not player:
            continue
        scope = scope_for(s, m.start())
        scope.last_n = int(m.group("n"))
        stats = s.oracle.player_scope(player, **scope.filters())
        atom = stat_atom(s, m, "value")
        if atom:
            s.mark(atom, number(m.group("value")), stats["avg_points"],
                   f"{player} points per appearance last {scope.last_n} {scope.filters()}", stats["sql"])
        atom = stat_atom(s, m, "n")
        if atom:
            s.mark(atom, int(m.group("n")), stats["appearances"],
                   f"{player} appearances last {scope.last_n}", stats["sql"])
    # "NAME: X points per appearance across N observed appearances ... opponent"
    for m in re.finditer(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?):\s*(?P<value>\d+(?:\.\d+)?)\s+points per appearance"
        r"\s+across\s+(?P<n>\d+)\s+observed appearances",
        s.text, re.I,
    ):
        player = player_near(s.text, m.start("name") + 1, window=30)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        for group, expected in (("value", stats["avg_points"]), ("n", stats["appearances"])):
            atom = stat_atom(s, m, group)
            if atom:
                s.mark(atom, number(m.group(group)), expected,
                       f"{player} points per appearance {scope.filters()}", stats["sql"])
    # "NAME faced OPP in N observed ... games (range), averaging X points per appearance"
    for m in re.finditer(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?)\s+faced\s+[^\n.]{0,80}?in\s+(?P<n>\d+)\s+observed[^\n.]{0,80}?"
        r"averaging\s+(?P<value>\d+(?:\.\d+)?)\s+points per appearance",
        s.text, re.I,
    ):
        player = player_near(s.text, m.start("name") + 1, window=30)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        for group, expected in (("n", stats["appearances"]), ("value", stats["avg_points"])):
            atom = stat_atom(s, m, group)
            if atom:
                s.mark(atom, number(m.group(group)), expected,
                       f"{player} opponent split {scope.filters()}", stats["sql"])
    # Rebound comparison: "11.9 vs 7.4. Towns' mark came across 75; Hart's across 66."
    for m in re.finditer(
        r"(?P<a>[A-Z][A-Za-z.'\- ]{2,30}?)\s+averaged more rebounds per appearance than\s+"
        r"(?P<b>[A-Z][A-Za-z.'\- ]{2,30}?):\s*(?P<va>\d+(?:\.\d+)?)\s+vs\s+(?P<vb>\d+(?:\.\d+)?)",
        s.text, re.I,
    ):
        pa = player_near(s.text, m.start("a") + 1, window=30)
        pb = player_near(s.text, m.start("b") + 1, window=30)
        if not pa or not pb:
            continue
        scope = scope_for(s, m.start())
        sa = s.oracle.player_scope(pa, **scope.filters())
        sb = s.oracle.player_scope(pb, **scope.filters())
        for group, expected, stats, name in (
            ("va", sa["avg_rebounds"], sa, pa), ("vb", sb["avg_rebounds"], sb, pb),
        ):
            atom = stat_atom(s, m, group)
            if atom:
                s.mark(atom, number(m.group(group)), expected,
                       f"{name} rebounds per appearance {scope.filters()}", stats["sql"])
        tail = s.text[m.end():m.end() + 180]
        nums = list(re.finditer(r"(\d+)\s+observed appearances", tail))
        if len(nums) >= 2:
            for match, expected, stats, name in (
                (nums[0], sa["appearances"], sa, pa), (nums[1], sb["appearances"], sb, pb),
            ):
                atom = s.atom_at(m.end() + match.start(1), m.end() + match.end(1))
                if atom and s.free(atom):
                    s.mark(atom, int(match.group(1)), expected,
                           f"{name} appearances {scope.filters()}", stats["sql"])
    # "Towns' mark came across 75 observed appearances; Hart's across 66."
    for m in re.finditer(r"\b(?:mark came across\s+)?(\d+)\s+observed appearances|['’]s across\s+(\d+)", s.text, re.I):
        raw_group = 1 if m.group(1) else 2
        atom = stat_atom(s, m, raw_group)
        if not atom:
            continue
        player = player_before(s.text, m.start(), window=200)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        s.mark(atom, int(m.group(raw_group)), stats["appearances"],
               f"{player} appearances {scope.filters()}", stats["sql"])
    # "across N observed appearances" with nearest player
    for m in re.finditer(r"\bacross\s+(\d+)\s+observed appearances", s.text, re.I):
        atom = stat_atom(s, m, 1)
        if not atom:
            continue
        player = player_before(s.text, m.start(), window=160) or player_near(s.text, m.start(), window=160)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        s.mark(atom, int(m.group(1)), stats["appearances"],
               f"{player} appearances {scope.filters()}", stats["sql"])
    # "averaging X points per appearance" nearest player
    for m in re.finditer(r"averaging\s+(\d+(?:\.\d+)?)\s+points per appearance", s.text, re.I):
        atom = stat_atom(s, m, 1)
        if not atom:
            continue
        player = player_before(s.text, m.start(), window=160) or player_near(s.text, m.start(), window=160)
        if not player:
            continue
        scope = scope_for(s, m.start())
        stats = s.oracle.player_scope(player, **scope.filters())
        s.mark(atom, number(m.group(1)), stats["avg_points"],
               f"{player} points per appearance {scope.filters()}", stats["sql"])
    # "NAME's highest observed scoring output (47) exceeds OTHER's (39)"
    for m in re.finditer(
        r"(?P<a>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s+highest observed scoring output[^.\n]{0,40}?\((?P<va>\d+)\)"
        r"[^.\n]{0,40}?exceeds\s+(?P<b>[A-Z][A-Za-z.'\- ]{2,30}?)(?:'s)?\s+\((?P<vb>\d+)\)",
        s.text, re.I,
    ):
        pa = player_near(s.text, m.start("a") + 1, window=30)
        pb = player_near(s.text, m.start("b") + 1, window=30)
        if not pa or not pb:
            continue
        for group, name in (("va", pa), ("vb", pb)):
            atom = stat_atom(s, m, group)
            if not atom:
                continue
            values = [r["points"] for r in s.oracle.player_rows(name, season_type="regular")]
            s.mark(atom, int(m.group(group)), max(values) if values else None,
                   f"{name} maximum single-game points", s.oracle._player_sql(name, True, {}))


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


def _line_fact(s: Session, player: str, row: dict, claimed: dict[str, int], sql: str) -> None:
    pass


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
