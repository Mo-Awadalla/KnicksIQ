"""Final score, team-labelled score and score-list verification."""

from __future__ import annotations

import re
from typing import Any

from model import Session, number
from scope import Scope, team_mentions
from verify_common import pair_atom, scope_for, scalar_atom


FINAL_PATTERNS = [
    (re.compile(r"\b(?:won|lost|win|loss|beat|defeated)\b[^.\n]{0,40}?(\d{1,3})\s*-\s*(\d{1,3})", re.I), "nyk"),
    (re.compile(r"\b(\d{1,3})\s*-\s*(\d{1,3})\s+(?:win|loss|victory|defeat)\b", re.I), "nyk"),
    (re.compile(r"\b(?:victory|defeat|win|loss)\b[^.\n]{0,20}?(\d{1,3})\s*-\s*(\d{1,3})", re.I), "nyk"),
]


def _final_game(s: Session, pos: int, scope: Scope, first: int, second: int) -> Any:
    tail = s.text[pos:pos + 32]
    dm = re.search(r"\((?:[A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:,\s+20\d{2})?|20\d{2}-\d{2}-\d{2})\)", tail)
    if dm:
        inner = dm.group(0).strip("()")
        iso = re.search(r"20\d{2}-\d{2}-\d{2}", inner)
        if iso:
            scope.start = scope.end = iso.group(0)
        else:
            from model import MONTH_DAY, parse_month
            md = re.search(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2})", inner)
            if md:
                month = parse_month(md.group(1))
                year = 2025 if month >= 8 else 2026
                scope.start = scope.end = f"{year:04d}-{month:02d}-{int(md.group(2)):02d}"
    candidates = s.oracle.games_for(
        season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
        start=scope.start, end=scope.end, last_n=scope.last_n,
        first_n=scope.first_n, result=scope.result,
    )
    matches = [
        g for g in candidates
        if (g.nyk_score, g.opp_score) in {(first, second), (second, first)}
    ]
    return matches[0] if len(matches) == 1 else (matches or [None])[0]


def verify_final_scores(s: Session) -> None:
    for pattern, orient in FINAL_PATTERNS:
        for m in pattern.finditer(s.text):
            atom = pair_atom(s, m, 1, 2)
            if atom is None or not s.free(atom):
                continue
            first, second = int(m.group(1)), int(m.group(2))
            if first > 200 or second > 200 or second == 0:
                continue
            between = s.text[m.start():m.start(1)].lower()
            if re.search(r"deficit|lead|down|trailed|points|run|margin|score", between):
                continue
            if re.search(r"\([A-Z][a-z]{2,8}|\),", between):
                continue
            scope = scope_for(s, m.start())
            head = s.text[max(0, m.start() - 60):m.start() + 10]
            subjects = re.findall(rf"({TEAM_TOKEN})\s+(?:won|lost|beat|defeated|win|loss)\b", head, re.I)
            abbr = _abbr(s, subjects[-1]) if subjects else None
            confident = abbr is not None
            if abbr is None:
                before = s.text[max(0, m.start() - 90):m.start()]
                if not re.search(r"(?:loss|win)\s+was\s+(?:vs\.?|at|against)\s+\w+\s*\(?$", before, re.I):
                    found = team_mentions(before, s.oracle.team_aliases)
                    if found and not re.search(r"\b(?:NYK|Knicks|New York)\b", before):
                        abbr = found[-1][1]
            if abbr and abbr != "NYK":
                first, second = second, first
            game = _final_game(s, m.start(), scope, first, second)
            if game is None:
                s.mark(atom, atom.raw, None, "no matching final score",
                       s.oracle._team_sql(scope.filters()), status="unverified")
            else:
                exact = (first, second) == (game.nyk_score, game.opp_score)
                reversed_ok = (second, first) == (game.nyk_score, game.opp_score)
                ok = exact or (reversed_ok and not confident)
                detail = "" if exact else "orientation not stated; score pair matches the game"
                s.mark(atom, atom.raw, game.score_text, f"final score {game.date} vs {game.opp}",
                       "select home_score, away_score from games where id=" + str(game.id),
                       status="verified" if ok else "wrong", detail=detail)
    # Team-labelled finals: NYK 105-95, BOS 123-117.
    for m in re.finditer(r"\b(?:NYK|New York|Knicks)\s+(\d{1,3})\s*[-,]\s*(\d{1,3})\b", s.text, re.I):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        first, second = int(m.group(1)), int(m.group(2))
        scope = scope_for(s, m.start())
        game = _final_game(s, m.start(), scope, first, second)
        if game is not None:
            s.mark(atom, atom.raw, game.score_text, f"final score {game.date} vs {game.opp}",
                   "select home_score, away_score from games where id=" + str(game.id),
                   status="verified" if game.score_text == atom.raw else "wrong")




TEAM_TOKEN = r"(?:NYK|New York|Knicks|BOS|Boston|ATL|Atlanta|CHA|Charlotte|CHI|Chicago|TOR|Toronto|SAS|San Antonio|MIA|Miami|BKN|Brooklyn|DET|Detroit|UTA|Utah|PHX|Phoenix|CLE|Cleveland|PHI|Philadelphia|LAL|Lakers|LAC|Clippers|DEN|Denver|IND|Indiana|ORL|Orlando|WAS|Washington)"


def _abbr(s: Session, token: str) -> str | None:
    return s.oracle.team_aliases.get(token) or s.oracle.team_aliases.get(token.title())


def verify_team_labelled_scores(s: Session) -> None:
    for m in re.finditer(rf"\b({TEAM_TOKEN})\s+(\d{{1,3}})\s*,\s*({TEAM_TOKEN})\s+(\d{{1,3}})", s.text):
        t1, v1, t2, v2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        a1, a2 = _abbr(s, t1), _abbr(s, t2)
        if not a1 or not a2 or "NYK" not in (a1, a2):
            continue
        scope = scope_for(s, m.start())
        game = _final_game(s, m.start(), scope, v1 if a1 == "NYK" else v2, v1 if a2 == "NYK" else v2)
        if game is None:
            continue
        for group, expected, fact in ((2, game.nyk_score if a1 == "NYK" else game.opp_score, f"{t1} score"),
                                      (4, game.nyk_score if a2 == "NYK" else game.opp_score, f"{t2} score")):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, int(m.group(group)), expected, f"final score {game.date} vs {game.opp}",
                       "select home_score, away_score from games where id=" + str(game.id),
                       status="verified" if int(m.group(group)) == expected else "wrong")
    for m in re.finditer(rf"\b({TEAM_TOKEN})\s+(\d{{1,3}})\s+at\s+({TEAM_TOKEN})\s+(\d{{1,3}})", s.text):
        t1, v1, t2, v2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        a1, a2 = _abbr(s, t1), _abbr(s, t2)
        if not a1 or not a2 or "NYK" not in (a1, a2):
            continue
        scope = scope_for(s, m.start())
        nyk, opp = (v1, v2) if a1 == "NYK" else (v2, v1)
        game = _final_game(s, m.start(), scope, nyk, opp)
        if game is None:
            continue
        for group, expected in ((2, nyk if a1 == "NYK" else opp), (4, nyk if a2 == "NYK" else opp)):
            atom = scalar_atom(s, m, group)
            if atom and s.free(atom) and atom.kind == "number":
                s.mark(atom, int(m.group(group)), expected, f"final score {game.date} vs {game.opp}",
                       "select home_score, away_score from games where id=" + str(game.id),
                       status="verified" if int(m.group(group)) == expected else "wrong")
    for m in re.finditer(r"(?:at|vs\.?)\s+[A-Z]{3}\s*\((\d{1,3})\s*-\s*(\d{1,3})\)", s.text):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        scope = scope_for(s, m.start())
        games = s.oracle.games_for(
            season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
            start=scope.start, end=scope.end, last_n=scope.last_n,
            first_n=scope.first_n, result=scope.result,
        )
        match = next((g for g in games if (g.nyk_score, g.opp_score) == (int(m.group(1)), int(m.group(2)))), None)
        if match:
            s.mark(atom, atom.raw, match.score_text, f"game score {match.date} vs {match.opp}",
                   "select home_score, away_score from games where id=" + str(match.id), status="verified")
    for m in re.finditer(r"\bNYK\s+(\d{1,3})\s*-\s*(\d{1,3})", s.text):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        scope = scope_for(s, m.start())
        game = _final_game(s, m.start(), scope, int(m.group(1)), int(m.group(2)))
        if game:
            s.mark(atom, atom.raw, game.score_text, f"final score {game.date} vs {game.opp}",
                   "select home_score, away_score from games where id=" + str(game.id),
                   status="verified" if game.score_text == atom.raw else "wrong")


def verify_score_lists(s: Session) -> None:
    for m in re.finditer(r"(?:final scores were|game results|final scores:)\s*", s.text, re.I):
        tail = s.text[m.end():m.end() + 300]
        base = m.end()
        pairs = list(re.finditer(r"(\d{1,3})\s*-\s*(\d{1,3})", tail))
        if not pairs:
            continue
        scope = scope_for(s, m.start())
        games = s.oracle.games_for(
            season_type=scope.season_type, opp=scope.opp, loc=scope.loc,
            start=scope.start, end=scope.end, last_n=scope.last_n,
            first_n=scope.first_n, result=scope.result,
        )
        used = set()
        for pm in pairs:
            atom = s.atom_at(base + pm.start(1), base + pm.end(2))
            if atom is None or not s.free(atom):
                continue
            match = None
            for game in games:
                if game.id in used:
                    continue
                if (game.nyk_score, game.opp_score) == (int(pm.group(1)), int(pm.group(2))):
                    match = game
                    break
            if match:
                used.add(match.id)
                s.mark(atom, atom.raw, match.score_text, f"final score list {match.date} vs {match.opp}",
                       "select home_score, away_score from games where id=" + str(match.id),
                       status="verified")
            else:
                s.mark(atom, atom.raw, None, "final score list", s.oracle._team_sql(scope.filters()),
                       status="unverified")


