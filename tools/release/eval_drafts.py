"""DRAFT adjudications for the unresolved semantic cases and the owner-decision-3 disposition review.

Rendered by `compute_launch_set.py`; every target and number is computed from the reviewed bundle.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from launch_set_data import Bundle, Game, event_ref

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/release-evidence/evaluation-contract-20261019"
DRAFT_HEADER = (
    "DRAFT pending owner approval. Not used by the builder until copied into adjudications.json."
)


def _ties(games: list[Game], key: Callable[[Game], int]) -> tuple[int, list[Game]]:
    best = max(key(g) for g in games)
    return best, [g for g in games if key(g) == best]


def _refs(games: list[Game]) -> list[str]:
    return [g.ref for g in games]


def _labels(games: list[Game]) -> str:
    return "; ".join(f"`{g.ref}` {g.label}" for g in games)


def _unverified(b: Bundle) -> str:
    bad = [g for g in b.games if not g.scoreboard_ok]
    if not bad:
        return ""
    return (
        f" Excluded {len(bad)} game(s) whose source scoreboard is not monotonic, which the app's "
        f"run tools also refuse: {_labels(bad)}."
    )


def _season_superlative(b: Bundle, key: Callable[[Game], int], what: str) -> tuple[list[Game], str]:
    value, games = _ties(b.verified(), key)
    return games, f"{what} = {value} over {len(b.verified())} verified games: {_labels(games)}."


def _run_detail(game: Game, team: str) -> str:
    points, start, end = game.max_run(team)
    return f"{points} unanswered points, `{event_ref(game, start)}` to `{event_ref(game, end)}`"


def adjudications(b: Bundle) -> tuple[dict[str, dict], dict[str, str]]:
    """Case id -> adjudication entry, and case id -> computation text for the Markdown."""
    entries: dict[str, dict] = {}
    computed: dict[str, str] = {}

    def put(case: str, games: list[Game], basis: str, computation: str) -> None:
        entries[case] = {"semantic_targets": _refs(games), "decision_basis": basis}
        computed[case] = computation

    games, text = _season_superlative(
        b,
        Game.max_deficit_erased,
        "Largest NYK deficit later tied or overturned (play-by-play margin)",
    )
    put(
        "turning_points-005",
        games,
        "Draft: 'largest deficit erased' is the biggest NYK play-by-play deficit after which the game was "
        "tied or NYK led; one game fits, so the analyst answers with it (owner decision 3).",
        text + _unverified(b),
    )
    games, text = _season_superlative(
        b, lambda g: g.max_run("OPP")[0], "Largest unanswered opponent run"
    )
    put(
        "turning_points-007",
        games,
        "Draft: 'most damaging opponent run' is read as the largest unanswered opponent scoring run of "
        "the season; the analyst should state that definition and answer with that game.",
        text + " " + "; ".join(_run_detail(g, "OPP") for g in games) + "." + _unverified(b),
    )
    games, text = _season_superlative(
        b, lambda g: g.max_run("NYK")[0], "Largest unanswered NYK run"
    )
    put(
        "aliases_typos-005",
        games,
        "Draft: 'Knics' resolves to the Knicks; 'biggest run' is the largest unanswered NYK scoring "
        "run of the season, stated with that definition.",
        text + " " + "; ".join(_run_detail(g, "NYK") for g in games) + "." + _unverified(b),
    )
    games, text = _season_superlative(
        b, Game.max_lead_lost, "Largest NYK lead after which the opponent led (lead change)"
    )
    put(
        "aliases_typos-010",
        games,
        "Draft: 'collpase' resolves to collapse, which owner decision 3 measures by play-by-play lead "
        "changes: the largest NYK lead the opponent later overturned.",
        text + _unverified(b),
    )

    atl = b.vs("ATL")
    scope = f"All {len(atl)} NYK-ATL games (regular season and playoffs): {_labels(atl)}."
    for case, phrase in (
        ("single_game_narrative-003", "the fourth quarter against Atlanta"),
        ("single_game_narrative-009", "how the Knicks closed the Atlanta game"),
        ("single_game_narrative-016", "turnovers in the Atlanta game"),
        ("turning_points-010", "late-game turning points against Atlanta"),
    ):
        put(
            case,
            atl,
            f"Draft: nothing in '{phrase}' narrows the {len(atl)} Atlanta games, so the analyst asks "
            "which one and every Atlanta game is a candidate (owner decisions 2 and 3).",
            scope,
        )
    lost_lead = [g for g in atl if g.max_lead_lost() > 0]
    put(
        "turning_points-003",
        lost_lead,
        "Draft: 'collapse' uses play-by-play lead changes (owner decision 3); only Atlanta games where "
        "the Knicks led and Atlanta later led are candidates.",
        f"{len(lost_lead)} of {len(atl)} Atlanta games have an NYK lead later overturned: "
        + "; ".join(f"`{g.ref}` {g.label}, lead {g.max_lead_lost()} lost" for g in lost_lead)
        + ". Not fitting: "
        + _labels([g for g in atl if g not in lost_lead])
        + ".",
    )
    put(
        "aliases_typos-006",
        atl,
        "Draft: 'v ATL' resolves to Atlanta; the record question covers every Atlanta game, so all are "
        "targets (owner decision 2, k = target count).",
        scope + f" Record {sum(g.won for g in atl)}-{sum(not g.won for g in atl)}.",
    )
    closest = min(abs(g.nyk - g.opp) for g in b.games)
    tied = [g for g in b.games if abs(g.nyk - g.opp) == closest]
    put(
        "single_game_narrative-006",
        tied,
        f"Draft: {len(tied)} games share the smallest final margin, so the analyst asks which one and "
        "lists exactly those games (owner decision 3).",
        f"Smallest final margin = {closest}: {_labels(tied)}.",
    )
    entries["aliases_typos-003"] = {
        **json.loads((CONTRACT / "adjudications.json").read_text())["aliases_typos-003"],
        "context_free_clarification": True,
    }
    computed["aliases_typos-003"] = "No context messages; no game evidence is a correct retrieval."
    return entries, computed


# Owner decision 3: case id -> (opponent, criterion name). Criteria come from the question wording.
NARROWING: dict[str, tuple[str, str]] = {
    "single_game_narrative-001": ("BOS", "lead_lost"),
    "single_game_narrative-004": ("CHI", "won"),
    "single_game_narrative-017": ("CHI", "ever_led"),
    "single_game_narrative-020": ("BOS", "lost"),
    "turning_points-001": ("BOS", "max_nyk_run"),
    "turning_points-003": ("ATL", "lead_lost"),
    "turning_points-006": ("BOS", "lost"),
    "turning_points-008": ("CHA", "lead_lost"),
    "turning_points-009": ("TOR", "comeback"),
}
CRITERIA: dict[str, str] = {
    "lead_lost": "NYK led and the opponent later led (play-by-play)",
    "won": "NYK won (final score)",
    "lost": "NYK lost (final score)",
    "ever_led": "NYK held a lead at some point (play-by-play)",
    "comeback": "NYK trailed and later led (play-by-play)",
    "max_nyk_run": "game holding the largest unanswered NYK run against this opponent",
}


def _fits(b: Bundle, opponent: str, criterion: str) -> list[Game]:
    games = b.vs(opponent)
    if criterion == "max_nyk_run":
        return _ties([g for g in games if g.scoreboard_ok], lambda g: g.max_run("NYK")[0])[1]
    test: dict[str, Callable[[Game], bool]] = {
        "lead_lost": lambda g: g.max_lead_lost() > 0,
        "won": lambda g: g.won,
        "lost": lambda g: not g.won,
        "ever_led": Game.ever_led,
        "comeback": Game.came_back,
    }
    return [g for g in games if test[criterion](g)]


def narrow_first(b: Bundle, cases: list[dict], drafts: dict[str, dict]) -> list[dict]:
    """Rows for every clarify case whose wording or draft adjudication narrows the candidates."""
    rows = []
    for case in cases:
        cid = case["id"]
        if cid in NARROWING:
            opponent, criterion = NARROWING[cid]
            games = _fits(b, opponent, criterion)
            rule = f"{opponent}: {CRITERIA[criterion]}"
        elif cid in drafts and case["disposition"] == "clarify" and drafts[cid]["semantic_targets"]:
            games = [b.by_id[r.split(":")[1]] for r in drafts[cid]["semantic_targets"]]
            rule = "draft adjudication above"
        else:
            continue
        current = len(case["semantic_targets"])
        proposed = "answer" if len(games) == 1 else "clarify"
        rows.append(
            {
                "id": cid,
                "question": case["question"],
                "current": case["disposition"],
                "proposed": proposed,
                "rule": rule,
                "current_targets": current,
                "fitting": games,
            }
        )
    return rows


def render(b: Bundle, cases: list[dict]) -> tuple[str, str]:
    entries, computed = adjudications(b)
    by_id = {c["id"]: c for c in cases}
    lines = [
        "# Adjudication drafts, 2026-10-20",
        "",
        f"> **{DRAFT_HEADER}**",
        "",
        "Generated by `tools/release/compute_launch_set.py --write` from "
        "`release-artifacts/2025-26/reliability-approved-20260928.json.gz` (SHA-256 `549af2ed...`). "
        "Rerun without `--write` to recompute and assert every target and number. No model calls.",
        "",
        "Machine file: `adjudications-draft.json`, same schema as `adjudications.json`. Targets follow "
        "each question's scope and are never capped to 5 (owner decision 2).",
        "",
        "## Unresolved semantic cases",
        "",
    ]
    for cid, entry in entries.items():
        case = by_id[cid]
        targets = ", ".join(f"`{t}`" for t in entry["semantic_targets"]) or "none"
        lines += [
            f"### `{cid}`: {case['question']}",
            "",
            f"- Disposition in contract: `{case['disposition']}`",
            f"- Proposed targets ({len(entry['semantic_targets'])}): {targets}",
            f"- Computation: {computed[cid]}",
            f"- Decision basis: {entry['decision_basis']}",
        ]
        if entry.get("context_free_clarification"):
            lines.append("- `context_free_clarification: true` (already ruled by the owner)")
        lines.append("")
    rows = narrow_first(b, cases, entries)
    lines += [
        "## Disposition changes under narrow-first (owner decision 3)",
        "",
        "Clarify cases among the 120 whose wording narrows the candidate games. One fit: the analyst "
        "answers directly. Several: it asks, listing only those. Cases whose wording narrows nothing "
        "(for example 'What decided the Knicks game against Toronto?') keep every opponent game and "
        "stay `clarify`. These are proposals for owner review; `expectations.json` is unchanged.",
        "",
        "| Case | Question | Rule | Current targets | Fitting games | Disposition |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        change = (
            row["current"]
            if row["current"] == row["proposed"]
            else (f"**{row['current']} -> {row['proposed']}**")
        )
        fitting = "<br>".join(f"`{g.ref}` {g.label}" for g in row["fitting"])
        lines.append(
            f"| `{row['id']}` | {row['question']} | {row['rule']} | {row['current_targets']} | "
            f"{fitting} | {change} |"
        )
    changed = [r["id"] for r in rows if r["current"] != r["proposed"]]
    lines += ["", f"Disposition changes proposed: {len(changed)} ({', '.join(changed)}).", ""]
    return "\n".join(lines), json.dumps(entries, indent=2, sort_keys=True) + "\n"
