"""Canonical stat names independent from storage column names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StatDefinition:
    key: str
    label: str
    kind: Literal["count", "minutes", "percentage", "ratio", "derived"]
    columns: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    decimals: int = 1
    materiality: float = 0.0


_DEFINITIONS = (
    StatDefinition("points", "Points", "count", ("points",), ("point", "pts"), 1, 3),
    StatDefinition(
        "rebounds", "Rebounds", "count", ("rebounds",), ("rebound", "rebs", "boards"), 1, 2
    ),
    StatDefinition("assists", "Assists", "count", ("assists",), ("assist", "asts"), 1, 2),
    StatDefinition("steals", "Steals", "count", ("steals",), ("steal", "stls"), 1, 0.5),
    StatDefinition("blocks", "Blocks", "count", ("blocks",), ("block", "blks"), 1, 0.5),
    StatDefinition("turnovers", "Turnovers", "count", ("turnovers",), ("turnover", "tos"), 1, 1),
    StatDefinition("personal_fouls", "Personal fouls", "count", ("personal_fouls",), ("fouls",), 1),
    StatDefinition(
        "plus_minus", "Plus/minus", "count", ("plus_minus",), ("+/-", "plus minus"), 1, 5
    ),
    StatDefinition("minutes", "Minutes", "minutes", ("minutes",), ("mins",), 1, 3),
    StatDefinition(
        "field_goals_made", "Field goals made", "count", ("field_goals_made",), ("fgm",), 1
    ),
    StatDefinition(
        "field_goals_attempted",
        "Field goals attempted",
        "count",
        ("field_goals_attempted",),
        ("fga",),
        1,
    ),
    StatDefinition(
        "threes_made",
        "Threes made",
        "count",
        ("three_pointers_made",),
        ("3pm", "three pointers made", "three-pointers made"),
        1,
    ),
    StatDefinition(
        "threes_attempted", "Threes attempted", "count", ("three_pointers_attempted",), ("3pa",), 1
    ),
    StatDefinition(
        "free_throws_made", "Free throws made", "count", ("free_throws_made",), ("ftm",), 1
    ),
    StatDefinition(
        "free_throws_attempted",
        "Free throws attempted",
        "count",
        ("free_throws_attempted",),
        ("fta",),
        1,
    ),
    StatDefinition(
        "offensive_rebounds", "Offensive rebounds", "count", ("offensive_rebounds",), ("oreb",), 1
    ),
    StatDefinition(
        "defensive_rebounds", "Defensive rebounds", "count", ("defensive_rebounds",), ("dreb",), 1
    ),
    StatDefinition(
        "field_goal_percentage",
        "Field goal percentage",
        "percentage",
        ("field_goals_made", "field_goals_attempted"),
        ("fg%", "field goal percentage"),
        1,
        5,
    ),
    StatDefinition(
        "three_point_percentage",
        "Three-point percentage",
        "percentage",
        ("three_pointers_made", "three_pointers_attempted"),
        ("3p%", "three point percentage", "from three"),
        1,
        5,
    ),
    StatDefinition(
        "free_throw_percentage",
        "Free throw percentage",
        "percentage",
        ("free_throws_made", "free_throws_attempted"),
        ("ft%",),
        1,
        5,
    ),
    StatDefinition(
        "true_shooting_percentage",
        "True shooting percentage",
        "derived",
        ("points", "field_goals_attempted", "free_throws_attempted"),
        ("ts%", "true shooting", "efficient", "efficiency"),
        1,
        5,
    ),
    StatDefinition(
        "effective_field_goal_percentage",
        "Effective field goal percentage",
        "derived",
        ("field_goals_made", "three_pointers_made", "field_goals_attempted"),
        ("efg%", "effective field goal percentage"),
        1,
        5,
    ),
    StatDefinition(
        "assist_turnover_ratio",
        "Assist-to-turnover ratio",
        "ratio",
        ("assists", "turnovers"),
        ("ast/to", "assist turnover ratio", "assist-to-turnover ratio"),
        2,
    ),
    StatDefinition(
        "points_per_36",
        "Points per 36",
        "derived",
        ("points", "minutes"),
        ("points per 36", "pts/36"),
        1,
    ),
    StatDefinition(
        "rebounds_per_36",
        "Rebounds per 36",
        "derived",
        ("rebounds", "minutes"),
        ("rebounds per 36", "reb/36"),
        1,
    ),
    StatDefinition(
        "assists_per_36",
        "Assists per 36",
        "derived",
        ("assists", "minutes"),
        ("assists per 36", "ast/36"),
        1,
    ),
    StatDefinition(
        "points_standard_deviation",
        "Points standard deviation",
        "derived",
        ("points",),
        ("scoring standard deviation", "points standard deviation"),
        1,
    ),
    StatDefinition(
        "points_floor",
        "Lowest scoring game",
        "derived",
        ("points",),
        ("lowest scoring game", "scoring floor"),
        1,
    ),
    StatDefinition(
        "double_doubles",
        "Double-doubles",
        "derived",
        ("points", "rebounds", "assists", "steals", "blocks"),
        ("double double", "double-double", "double doubles", "double-doubles"),
        0,
    ),
    StatDefinition(
        "triple_doubles",
        "Triple-doubles",
        "derived",
        ("points", "rebounds", "assists", "steals", "blocks"),
        ("triple double", "triple-double", "triple doubles", "triple-doubles"),
        0,
    ),
)

STAT_REGISTRY = {definition.key: definition for definition in _DEFINITIONS}
_ALIASES = {
    alias.lower(): definition.key
    for definition in _DEFINITIONS
    for alias in (definition.key, definition.label, *definition.aliases)
}


def resolve_stat(value: str) -> str | None:
    """Resolve a public spelling to a canonical stat key."""
    return _ALIASES.get(value.strip().lower().replace("-", " ")) or _ALIASES.get(
        value.strip().lower()
    )


def stat_keys_in_text(text: str) -> list[str]:
    lowered = text.lower()
    found: list[tuple[int, int, str]] = []
    for alias, key in _ALIASES.items():
        position = lowered.find(alias)
        if position >= 0:
            found.append((position, -len(alias), key))
    return list(dict.fromkeys(key for _, _, key in sorted(found)))
