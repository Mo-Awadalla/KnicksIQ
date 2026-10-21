"""Acceptance checks for the 20261021 phase-policy correction.

The original checks transcribed claims from the 20261018 run, so they cannot audit a fresh
response. These checks require the regular-season values the lead policy selects (SQL oracle in
queries_core.sql) and the phase statement, and forbid the previously observed wrong artifacts.
Numeric strings are matched as the answer would state them; the oracle values are documented in
failure-modes.md.
"""

from __future__ import annotations

import re

NUMBER = r"-?\d+(?:\.\d+)?"


def _num(value: str | None) -> float | int | None:
    if value is None:
        return None
    number = float(value.replace(",", ""))
    return int(number) if number.is_integer() else number


def _first(pattern: str, answer: str) -> str | None:
    match = re.search(pattern, answer, re.I)
    if not match:
        return None
    return next((group for group in match.groups() if group is not None), None)


def _phase(answer: str) -> str | None:
    text = answer.lower()
    if "regular season" in text or "regular-season" in text:
        return "regular"
    if "all phases" in text or "including playoffs" in text or "overall" in text:
        return "all"
    if "playoffs" in text or "postseason" in text:
        return "playoffs"
    return None


def _record(answer: str):
    match = re.search(r"(?<![\d-])(\d{1,2})\s*[-–]\s*(\d{1,2})(?![\d-])", answer)
    return [int(match.group(1)), int(match.group(2))] if match else None


def _extreme_points(answer: str):
    values = [
        int(v.replace(",", ""))
        for v in re.findall(r"(\d{1,3}(?:,\d{3})*|\d+)\s*points", answer, re.I)
    ]
    values = [value for value in values if value >= 100]
    return max(values) if values else None


def _season_spec(number: str, path: str, extra: list[str] | None = None) -> dict:
    """A regular-season value plus the required phase statement."""
    return {
        "required_terms": ["regular season"],
        "claims": [
            {
                "label": path.split(".")[-1],
                "extract": lambda answer: _num(
                    _first(
                        r"(" + re.escape(number) + r"|" + re.escape(number.replace(",", "")) + r")",
                        answer,
                    )
                ),
                "fn": path,
                "optional": True,
            },
        ],
        "forbidden_terms": extra or [],
    }


SPECS = {
    "exact_statistics-001": {
        "required_terms": ["53", "29", "regular season"],
        "forbidden_terms": ["69-32", "69 wins", "101 games"],
        "claims": [
            {"label": "record", "extract": _record,
             "fn": lambda f: [f["core"]["regular"]["wins"], f["core"]["regular"]["losses"]],
             "optional": True},
        ],
    },
    "exact_statistics-002": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["regular season"],
        "forbidden_terms": ["11,750", "11750", "101 games"],
        "claims": [
            {"label": "points", "extract": lambda a: _num(_first(
                r"([\d,]{4,})\s*(?:total\s+)?points", a)), "fn": "core.regular.points", "optional": True},
        ],
    },
    "exact_statistics-003": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["regular season"],
        "forbidden_terms": ["116.34", "101 games"],
        "claims": [
            {"label": "avg_points", "extract": lambda a: _num(_first(
                r"(" + NUMBER + r")\s*(?:points? per game|ppg)", a)),
             "fn": "core.regular.avg_points", "tol": 0.05, "optional": True},
        ],
    },
    "exact_statistics-004": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["regular season"],
        "forbidden_terms": ["7.94", "101 games"],
        "claims": [
            {"label": "avg_margin", "extract": lambda a: _num(_first(
                r"margin[^.\d]{0,30}(" + NUMBER + ")", a)),
             "fn": "core.regular.avg_margin", "tol": 0.05, "optional": True},
        ],
    },
    "exact_statistics-005": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["30", "regular season"],
        "forbidden_terms": ["37 home"],
        "claims": [],
    },
    "exact_statistics-006": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["23", "regular season"],
        "forbidden_terms": ["32 road"],
        "claims": [],
    },
    "exact_statistics-007": {
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "required_terms": ["29", "regular season"],
        "forbidden_terms": ["32 losses", "0 losses"],
        "claims": [],
    },
    "exact_statistics-008": {
        "required_terms": ["54", "120"],
        "forbidden_terms": ["0 losses in that filtered set"],
        "claims": [
            {"label": "margin", "extract": lambda a: _num(_first(
                r"(\d+)[- ]point|by\s+(\d+)", a)),
             "fn": "extremes.biggest_win.margin", "optional": True},
        ],
    },
    "exact_statistics-009": {
        "required_terms": ["38"],
        "forbidden_terms": ["Knicks wins:", "Knicks losses: 0"],
        "claims": [
            {"label": "loss_margin", "extract": lambda a: _num(_first(
                r"(?:by|lost by)\s+(\d+)|(\d+)[- ]point", a)),
             "fn": lambda f: abs(f["extremes"]["worst_loss"]["margin"]), "optional": True},
        ],
    },
    "exact_statistics-010": {
        "required_terms": ["146"],
        "forbidden_terms": ["highest-scoring individual"],
        "claims": [
            {"label": "team_points", "extract": _extreme_points,
             "fn": "extremes.highest_team_game.pts", "optional": True},
        ],
    },
    "date_range_last_n-006": {
        "required_terms": ["5", "8", "3"],
        "forbidden_terms": ["0 losses", "5 archived away games", "5 games"],
        "claims": [],
    },
    "aliases_typos-004": {
        "required_terms": ["5", "17.4"],
        "forbidden_terms": ["single observed appearance", "single appearance"],
        "claims": [],
    },
    "aliases_typos-006": {
        "required_terms": ["6-3", "2-1", "4-2"],
        "forbidden_terms": [],
        "claims": [],
    },
    "aliases_typos-009": {
        "required_terms": ["2", "11.5"],
        "forbidden_terms": ["rows are missing", "coverage is incomplete"],
        "claims": [],
    },
    "aliases_typos-010": {
        "required_terms": ["19"],
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "forbidden_terms": ["Knicks wins:", "Knicks losses:", "Knicks points:"],
    },
    "turning_points-003": {
        "required_terms": ["14"],
        "decline_verdict": "DECLINE_MISSED_ANSWER",
        "forbidden_terms": ["Knicks wins:", "Knicks losses:", "Knicks points:"],
    },
    "unsupported-006": {
        "verdict": "DECLINE_APPROPRIATE",
        "decline_verdict": "DECLINE_APPROPRIATE",
        "forbidden_terms": ["Knicks wins:", "Knicks losses:", "Knicks points:"],
    },
    "unsupported-007": {
        "verdict": "DECLINE_APPROPRIATE",
        "decline_verdict": "DECLINE_APPROPRIATE",
        "forbidden_terms": ["2025-12-21"],
        "claims": [
            {"label": "latest_date",
             "extract": lambda a: _first(r"latest[^.]*?(\d{4}-\d{2}-\d{2})", a),
             "fn": "extremes.latest_game_date", "optional": True},
        ],
    },
}
