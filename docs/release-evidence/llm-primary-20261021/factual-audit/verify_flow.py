"""Play-by-play verification: deficits, leads, ties and period labels."""

from __future__ import annotations

import re

import flow
import verify_runs
from model import Session, number, tolerance
from scope import Scope, team_mentions
from verify_common import candidates, pair_atom, periods_of, scope_for, scalar_atom
from verify_runs import _mark_clock


def verify_comebacks(s: Session) -> None:
    for m in re.finditer(
        r"(?:largest\s+)?deficit(?:\s+(?:erased|overcome))?"
        r"(?:\s+in\s+(?:a|the)\s+(?:\w+\s+)?(?:win|loss))?"
        r"(?:\s+was|\s+of|\s+reached)?\s*(\d{1,3})(?:\s+points?)?",
        s.text, re.I,
    ):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        scope = scope_for(s, m.start())
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            cb = flow.comeback(plays, bool(periods_of(scope)))
            if cb and cb["deficit"] == int(m.group(1)):
                matches.append((game, cb, "comeback"))
            if not game.win:
                deficit = -min((p.margin_after for p in plays), default=0)
                if deficit == int(m.group(1)):
                    matches.append((game, {"deficit": deficit}, "loss deficit"))
        if matches:
            game, cb, kind = matches[0]
            s.mark(atom, int(m.group(1)), cb["deficit"], f"{kind} {game.date} vs {game.opp}",
                   "select ... game_events", status="verified")
        elif len(games) == 1:
            s.mark(atom, int(m.group(1)), None, "no matching deficit",
                   "select ... game_events", status="wrong", detail="deficit not found")
        else:
            s.mark(atom, int(m.group(1)), None, "ambiguous deficit game",
                   "select ... game_events", status="unverified")
    for m in re.finditer(r"(\d{1,3})-point deficit", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            cb = flow.comeback(plays, bool(periods_of(scope)))
            if cb and cb["deficit"] == int(m.group(1)):
                matches.append((game, cb))
        if matches:
            game, cb = matches[0]
            s.mark(atom, int(m.group(1)), cb["deficit"], f"comeback {game.date} vs {game.opp}",
                   "select ... game_events", status="verified")
        elif len(games) == 1:
            s.mark(atom, int(m.group(1)), None, "comeback", "select ... game_events", status="wrong")
        else:
            s.mark(atom, int(m.group(1)), None, "ambiguous comeback", "select ... game_events",
                   status="unverified")
    for m in re.finditer(r"trailed by as many as\s+(\d{1,3})", s.text, re.I):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            deficit = -min((p.margin_after for p in plays), default=0)
            if deficit == int(m.group(1)):
                matches.append(game)
        if matches:
            s.mark(atom, int(m.group(1)), int(m.group(1)), f"largest deficit {matches[0].date}",
                   "select ... game_events", status="verified")
    # "trailed by N at Qp clock (A-B)" / "trailed by N points at Qp clock (A-B)"
    for m in re.finditer(r"trailed by\s+(\d{1,3})(?:\s+points?)?\s+at\s+Q([1-4])\s+(\d{1,2}:\d{2})\s*\((\d{1,3})\s*-\s*(\d{1,3})\)", s.text, re.I):
        value = int(m.group(1))
        games, scope = candidates(s, m.start())
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            play = flow.play_at(plays, int(m.group(2)), m.group(3))
            if play and -play.margin_after == value and flow.snapshot_matches(play, int(m.group(4)), int(m.group(5))):
                atom = scalar_atom(s, m, 1)
                if atom and s.free(atom):
                    s.mark(atom, value, value, f"deficit at Q{m.group(2)} {m.group(3)} {game.date}",
                           "select ... game_events", status="verified")
                break
    # "down A-B at Qp clock" deficit size is implied by the snapshot, no separate atom.
    # Comeback scoring: "outscoring OPP A-B" after a comeback or run.
    for m in re.finditer(r"outscoring\s+(?:[A-Z]{2,4}|[A-Z][a-z]+)\s+(\d{1,3})\s*-\s*(\d{1,3})", s.text, re.I):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            cb = flow.comeback(plays, bool(periods_of(scope)))
            if cb and (cb["nyk_points"], cb["opp_points"]) == (int(m.group(1)), int(m.group(2))):
                matches.append((game, cb))
        if matches:
            game, cb = matches[0]
            s.mark(atom, atom.raw, f'{cb["nyk_points"]}-{cb["opp_points"]}',
                   f"comeback scoring {game.date} vs {game.opp}", "select ... game_events", status="verified")
        else:
            s.mark(atom, atom.raw, None, "comeback scoring", "select ... game_events", status="unverified")


def verify_leads(s: Session) -> None:
    for m in re.finditer(
        r"(?:largest|biggest)\s+lead(?:\s+was|\s+of)?\s+(\d{1,3})\s+points?", s.text, re.I,
    ):
        atom = scalar_atom(s, m, 1)
        if atom is None or not s.free(atom) or atom.kind != "number":
            continue
        games, scope = candidates(s, m.start())
        if not games:
            continue
        values = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            values.append((max((p.margin_after for p in plays), default=0), game))
        claimed = int(m.group(1))
        exact = [game for value, game in values if value == claimed]
        if exact:
            s.mark(atom, claimed, claimed, f"largest lead {exact[0].date} vs {exact[0].opp}",
                   "select ... game_events", status="verified")
        elif len(games) == 1:
            value, game = values[0]
            s.mark(atom, claimed, value, f"largest lead {game.date} vs {game.opp}",
                   "select ... game_events", status="wrong",
                   detail=f"largest lead {value}")
        else:
            s.mark(atom, claimed, None, "ambiguous largest lead", "select ... game_events",
                   status="unverified")


def verify_lost_leads(s: Session) -> None:
    patterns = [
        r"(?:largest\s+)?lead(?:\s+lost)?(?:\s+was|\s+lost)?\s+(\d{1,3})\s+points?",
        r"led by as many as\s+(\d{1,3})",
        r"lost a\s+(\d{1,3})-point lead",
        r"surrendered a\s+(\d{1,3})-point lead",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, s.text, re.I):
            phrase = m.group(0)
            if re.search(r"(?:largest|biggest)\s+lead", phrase, re.I) and not re.search(
                r"lost|surrendered", phrase, re.I
            ):
                continue
            atom = scalar_atom(s, m, 1)
            if atom is None or not s.free(atom) or atom.kind != "number":
                continue
            games, scope = candidates(s, m.start())
            matches = []
            for game in games:
                plays = flow.plays_for(s.oracle, game, periods_of(scope))
                lost = flow.lost_lead(plays, game)
                if lost and lost["lead"] == int(m.group(1)):
                    matches.append((game, lost))
            if matches:
                game, lost = matches[0]
                s.mark(atom, int(m.group(1)), lost["lead"], f"lost lead {game.date} vs {game.opp}",
                       "select ... game_events", status="verified")
            elif len(games) == 1:
                s.mark(atom, int(m.group(1)), None, "lost lead", "select ... game_events",
                       status="wrong", detail="lead not found")
            else:
                s.mark(atom, int(m.group(1)), None, "ambiguous lost lead", "select ... game_events",
                       status="unverified")


def verify_go_ahead(s: Session) -> None:
    for m in re.finditer(
        r"(?:took|went ahead for good|led for good|went ahead)\s+(?:the lead\s+)?(?:for good\s+)?"
        r"(?:at\s+)?(?:Q([1-4])\s+)?(\d{1,2}:\d{2})?\s*\(?(\d{1,3})\s*-\s*(\d{1,3})\)?",
        s.text, re.I,
    ):
        atom = pair_atom(s, m, 3, 4)
        if atom is None or not s.free(atom):
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            ahead = flow.go_ahead(plays, game)
            if ahead is None:
                continue
            if not flow.snapshot_matches(ahead, int(m.group(3)), int(m.group(4))):
                continue
            if m.group(1) and ahead.period != int(m.group(1)):
                continue
            if m.group(2) and flow.normalize_clock(ahead.clock) != flow.normalize_clock(m.group(2)):
                continue
            matches.append((game, ahead))
        if matches:
            game, ahead = matches[0]
            s.mark(atom, atom.raw, f"{ahead.nyk_after}-{ahead.opp_after}",
                   f"go-ahead {game.date} vs {game.opp}", "select ... game_events", status="verified")
            _mark_clock(s, m.start(), m.end(), ahead.period, ahead.clock,
                        f"go-ahead clock {game.date}", "select ... game_events")
        elif len(games) == 1:
            s.mark(atom, atom.raw, None, "go-ahead", "select ... game_events", status="wrong")
        else:
            s.mark(atom, atom.raw, None, "ambiguous go-ahead", "select ... game_events", status="unverified")


def verify_ties(s: Session) -> None:
    for m in re.finditer(
        r"(?:first\s+)?(?:tying|tied|tie)\s+(?:at|or led at)\s*\(?(\d{1,3})\s*-\s*(\d{1,3})\)?",
        s.text, re.I,
    ):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            tie = flow.first_tie(plays, int(m.group(1)), int(m.group(2)))
            if tie:
                matches.append((game, tie))
        if matches:
            game, tie = matches[0]
            s.mark(atom, atom.raw, f"{tie.nyk_after}-{tie.opp_after}",
                   f"first tie {game.date} vs {game.opp}", "select ... game_events", status="verified")
            _mark_clock(s, m.start(), m.end(), tie.period, tie.clock,
                        f"tie clock {game.date}", "select ... game_events")
        elif len(games) == 1:
            s.mark(atom, atom.raw, None, "first tie", "select ... game_events", status="wrong")
        else:
            s.mark(atom, atom.raw, None, "ambiguous tie", "select ... game_events", status="unverified")
    for m in re.finditer(r"(?:first )?tied or led at[^\n.]{0,30}?\((\d{1,3})\s*-\s*(\d{1,3})\)", s.text, re.I):
        atom = pair_atom(s, m, 1, 2)
        if atom is None or not s.free(atom):
            continue
        games, scope = candidates(s, m.start())
        matches = []
        for game in games:
            plays = flow.plays_for(s.oracle, game, periods_of(scope))
            cb = flow.comeback(plays, bool(periods_of(scope)))
            if cb and (cb["end"].nyk_after, cb["end"].opp_after) == (int(m.group(1)), int(m.group(2))):
                matches.append((game, cb["end"]))
        if matches:
            game, end = matches[0]
            s.mark(atom, atom.raw, f"{end.nyk_after}-{end.opp_after}",
                   f"first lead after comeback {game.date}", "select ... game_events", status="verified")
        elif len(games) == 1:
            s.mark(atom, atom.raw, None, "first lead after comeback", "select ... game_events",
                   status="wrong")
        else:
            s.mark(atom, atom.raw, None, "ambiguous first lead", "select ... game_events",
                   status="unverified")


def verify_period_labels(s: Session) -> None:
    for atom in s.atoms:
        if atom.kind != "period" or not s.free(atom):
            continue
        period = int(atom.values[0])
        games, scope = candidates(s, atom.start)
        ok = any(g.periods.get(period) for g in games) if games else 1 <= period <= 4
        s.mark(atom, period, period if ok else None, "period label",
               "select distinct period from period_scores", status="verified" if ok else "wrong")


def verify_flow(s: Session) -> None:
    verify_period_labels(s)
    verify_runs.verify_snapshots(s)
    verify_runs.verify_runs(s)
    verify_comebacks(s)
    verify_leads(s)
    verify_lost_leads(s)
    verify_go_ahead(s)
    verify_ties(s)
