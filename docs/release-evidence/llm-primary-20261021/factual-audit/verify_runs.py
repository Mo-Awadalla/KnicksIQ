"""Snapshot and run verification."""

from __future__ import annotations

import re

import flow
from model import Session, number
from scope import Scope, team_mentions
from verify_common import candidates, pair_atom, periods_of, scope_for, scalar_atom


def _mark_clock(s: Session, start: int, end: int, period: int | None, clock: str | None, fact: str, sql: str) -> None:
    for atom in s.inside(start, end):
        if atom.kind != "clock":
            continue
        claimed_period, claimed_clock = atom.values
        ok = (period is None or claimed_period is None or claimed_period == period) and (
            clock is None or flow.normalize_clock(claimed_clock) == flow.normalize_clock(clock)
        )
        s.mark(atom, f"Q{claimed_period} {claimed_clock}", f"Q{period} {clock}" if period else clock,
               fact, sql, status="verified" if ok else "wrong")


def _mark_last_clock(s: Session, start: int, end: int, period: int, clock: str, fact: str, sql: str) -> None:
    atoms = [a for a in s.inside(start, end) if a.kind == "clock"]
    if not atoms:
        return
    atom = atoms[-1]
    claimed_period, claimed_clock = atom.values
    ok = (claimed_period is None or claimed_period == period) and flow.normalize_clock(claimed_clock) == flow.normalize_clock(clock)
    s.mark(atom, f"Q{claimed_period} {claimed_clock}", f"Q{period} {clock}", fact, sql,
           status="verified" if ok else "wrong")


def _mark_clocks(s: Session, start: int, end: int, expected: list[tuple[int, str]], fact: str, sql: str) -> None:
    atoms = [a for a in s.inside(start, end) if a.kind == "clock"]
    for atom, (period, clock) in zip(atoms, expected):
        claimed_period, claimed_clock = atom.values
        ok = (claimed_period is None or claimed_period == period) and flow.normalize_clock(claimed_clock) == flow.normalize_clock(clock)
        s.mark(atom, f"Q{claimed_period} {claimed_clock}", f"Q{period} {clock}", fact, sql,
               status="verified" if ok else "wrong")


def _mark_pair_status(s: Session, atom, expected_text: str, status: str, fact: str, sql: str, detail: str = "") -> None:
    s.mark(atom, atom.raw, expected_text, fact, sql, status=status, detail=detail)


def verify_snapshots(s: Session) -> None:
    patterns = [
        re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})\s+at\s+Q([1-4])\s+(\d{1,2}:\d{2})"),
        re.compile(r"Q([1-4])\s+(\d{1,2}:\d{2})\s*\((\d{1,3})\s*-\s*(\d{1,3})\)"),
        re.compile(r"(?:down|trailing)\s+(\d{1,3})\s*-\s*(\d{1,3})\s+at\s+Q([1-4])\s+(\d{1,2}:\d{2})"),
    ]
    for pattern in patterns:
        for m in pattern.finditer(s.text):
            groups = m.groups()
            if pattern is patterns[1]:
                period, clock, a, b = int(groups[0]), groups[1], int(groups[2]), int(groups[3])
                g1, g2 = 3, 4
            else:
                a, b, period, clock = int(groups[0]), int(groups[1]), int(groups[2]), groups[3]
                g1, g2 = 1, 2
            atom = pair_atom(s, m, g1, g2)
            if atom is None or not s.free(atom):
                continue
            scope = scope_for(s, m.start())
            following = s.text[m.end():m.end() + 40]
            im = re.search(r"^\s*(?:on|in the)\s+(20\d{2}-\d{2}-\d{2})", following)
            if im:
                scope.start = scope.end = im.group(1)
            games = s.oracle.games_for(**scope.filters())
            matches = []
            for game in games:
                plays = flow.plays_for(s.oracle, game, periods_of(scope))
                for play in flow.plays_at(plays, period, clock):
                    if flow.snapshot_matches(play, a, b):
                        matches.append((game, play))
                        break
            if matches:
                game, play = matches[0]
                s.mark(atom, atom.raw, f"{play.nyk_after}-{play.opp_after} at Q{period} {clock}",
                       f"scoreboard at Q{period} {clock} {game.date} vs {game.opp}",
                       "select period, clock, home_score, away_score from game_events where game_id=" + str(game.id),
                       status="verified")
                _mark_clock(s, m.start(), m.end(), period, clock,
                            f"scoreboard clock {game.date} vs {game.opp}",
                            "select period, clock from game_events where game_id=" + str(game.id))
            elif len(games) == 1:
                _mark_pair_status(s, atom, "no matching snapshot", "wrong",
                                  f"scoreboard at Q{period} {clock}", "select ... game_events",
                                  "no play with that clock and score")
            else:
                s.mark(atom, atom.raw, None, "ambiguous snapshot game",
                       "select ... game_events", status="unverified")


def verify_runs(s: Session) -> None:
    for m in re.finditer(r"(?<![\d.])(\d{1,3})\s*-\s*(0)(?![\d.])", s.text):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        value = int(m.group(1))
        before = s.text[max(0, m.start() - 160):m.start()]
        after = s.text[m.end():m.end() + 180]
        clause = re.split(r"(?<=[.!?])\s|\n", after, maxsplit=1)[0]
        team = _run_team(s, m.start(), before, after)
        scope = scope_for(s, m.start())
        im = re.search(r"20\d{2}-\d{2}-\d{2}", clause)
        if im:
            scope.start = scope.end = im.group(0)
        found = team_mentions(clause[:80], s.oracle.team_aliases)
        if found:
            scope.opp = found[0][1]
        games = s.oracle.games_for(**scope.filters())
        start_clock = re.search(r"Q([1-4])\s+(\d{1,2}:\d{2})", clause)
        end_clock = None
        if start_clock:
            rest = clause[start_clock.end():]
            end_clock = re.search(r"Q([1-4])\s+(\d{1,2}:\d{2})", rest)
        score_before = re.search(r"(\d{1,3})\s*-\s*(\d{1,3})\s+to\s+(\d{1,3})\s*-\s*(\d{1,3})", clause)
        if not score_before:
            score_before = re.search(r"from\s+(\d{1,3})\s*-\s*(\d{1,3})\s+to\s+(\d{1,3})\s*-\s*(\d{1,3})", clause)
        if not score_before:
            score_before = re.search(r"turning\s+(?:a\s+)?(\d{1,3})\s*-\s*(\d{1,3})[^.\n]{0,30}?into\s+(?:a\s+)?(\d{1,3})\s*-\s*(\d{1,3})", clause)
        matches = []
        comeback_context = bool(re.search(r"outscor|stretch|comeback|tying|tied", before[-70:].lower() + after[:60].lower()))
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            # A run paired with its start/end score identifies its team: only one
            # side's score moved, so the snapshot decides who scored.
            candidate_runs = [
                run for run in flow.runs(plays, bool(periods_of(scope)))
                if run.points == value and (score_before is not None or run.team == team)
            ]
            if not candidate_runs and score_before is None:
                cb = flow.comeback(plays, bool(periods_of(scope)))
                if cb and cb["opp_points"] == 0 and cb["nyk_points"] == value and team == "NYK":
                    candidate_runs = [flow.Run("NYK", value, cb["low"], cb["end"])]
                elif cb and cb["run"] and cb["run"].team == team and cb["run"].points == value:
                    candidate_runs = [cb["run"]]
            for run in candidate_runs:
                if start_clock and (run.start.period, flow.normalize_clock(run.start.clock)) != (
                    int(start_clock.group(1)), flow.normalize_clock(start_clock.group(2))
                ):
                    continue
                if end_clock:
                    rest = after[start_clock.end():]
                    em = re.search(r"Q([1-4])\s+(\d{1,2}:\d{2})", rest)
                    if em and (run.end.period, flow.normalize_clock(run.end.clock)) != (
                        int(em.group(1)), flow.normalize_clock(em.group(2))
                    ):
                        continue
                if score_before:
                    a, b, c, d = (int(x) for x in score_before.groups())
                    if {run.start.nyk_before, run.start.opp_before} != {a, b}:
                        continue
                    if {run.end.nyk_after, run.end.opp_after} != {c, d}:
                        continue
                matches.append((game, run))
                break
        if matches:
            game, run = matches[0]
            expected = f"{run.points}-0 Q{run.start.period} {run.start.clock} to Q{run.end.period} {run.end.clock}"
            s.mark(atom, atom.raw, expected, f"{run.team} run {game.date} vs {game.opp}",
                   "select sequence, period, clock, home_score, away_score from game_events where game_id=" + str(game.id),
                   status="verified")
            _mark_clocks(s, m.end(), m.end() + len(clause),
                         [(run.start.period, run.start.clock), (run.end.period, run.end.clock)],
                         f"run clocks {game.date}", "select ... game_events")
            if not start_clock:
                _mark_last_clock(s, max(0, m.start() - 80), m.start(),
                                 run.end.period, run.end.clock,
                                 f"run end clock {game.date}", "select ... game_events")
            _mark_run_snapshots(s, m.end(), clause, run)
        elif len(games) == 1:
            _mark_pair_status(s, atom, "no matching run", "wrong", f"{team} run", "select ... game_events",
                              "no consecutive run of that length")
        else:
            s.mark(atom, atom.raw, None, "ambiguous run game", "select ... game_events", status="unverified")


def _run_team(s: Session, pos: int, before: str, after: str = "") -> str:
    head = after[:40]
    tail_nyk = re.search(r"\b(?:knicks|nyk|new york)\b", head, re.I)
    tail_opps = team_mentions(head, s.oracle.team_aliases)
    # "a 7-0 Knicks burst": the team named right after the run wins.
    if tail_nyk and (not tail_opps or tail_nyk.start() <= tail_opps[0][0]):
        return "NYK"
    if tail_opps and re.search(r"\brun\b|\bby\b", head[:30].lower()):
        return tail_opps[0][1]
    low = before.lower()
    if re.search(r"outscor", low[-50:]):
        return "NYK"
    recent = before[-80:]
    nyk = list(re.finditer(r"\b(?:knicks|nyk|new york)\b", recent, re.I))
    opps = team_mentions(recent, s.oracle.team_aliases)
    if opps and (not nyk or opps[-1][0] > nyk[-1].start()):
        return opps[-1][1]
    return "NYK"


def _mark_run_snapshots(s: Session, base: int, clause: str, run: flow.Run) -> None:
    sm = re.search(r"(\d{1,3})\s*-\s*(\d{1,3})\s+to\s+(\d{1,3})\s*-\s*(\d{1,3})", clause)
    if not sm:
        sm = re.search(r"from\s+(\d{1,3})\s*-\s*(\d{1,3})\s+to\s+(\d{1,3})\s*-\s*(\d{1,3})", clause)
    if not sm:
        sm = re.search(r"turning\s+(?:a\s+)?(\d{1,3})\s*-\s*(\d{1,3})[^.\n]{0,30}?into\s+(?:a\s+)?(\d{1,3})\s*-\s*(\d{1,3})", clause)
    if not sm:
        return
    atoms = [a for a in s.inside(base + sm.start(), base + sm.end()) if a.kind == "pair"]
    expected = [
        (run.start.nyk_before, run.start.opp_before, "run start score"),
        (run.end.nyk_after, run.end.opp_after, "run end score"),
    ]
    for atom, (nyk, opp, fact) in zip(atoms, expected):
        from model import number
        claimed = tuple(number(v) for v in atom.values)
        ok = claimed == (nyk, opp)
        s.mark(atom, atom.raw, f"{nyk}-{opp}", fact, "select ... game_events",
               status="verified" if ok else "wrong")


