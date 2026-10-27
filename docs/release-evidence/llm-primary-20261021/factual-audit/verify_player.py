"""Player aggregate and single-game line verification."""

from __future__ import annotations

import re

from model import Session, number
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
    # "NAME averaged X points per appearance across N observed appearances ..."
    for m in re.finditer(
        r"(?P<name>[A-Z][A-Za-z.'\- ]{2,30}?)\s+averaged\s+(?P<value>\d+(?:\.\d+)?)\s+"
        r"points per appearance\s+across\s+(?P<n>\d+)\s+observed appearances",
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
