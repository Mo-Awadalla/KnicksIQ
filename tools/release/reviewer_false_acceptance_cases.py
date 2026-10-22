"""Mutation cases for the reviewer false-acceptance measurement.

Every case edits a recorded correct answer without moving any number outside the trusted
set, so `review_issues` returns no issues. See the runner module for the gate rationale per
class.
"""

from __future__ import annotations

from dataclasses import dataclass

CLASSES: dict[str, str] = {
    "number_swapped_other_metric": (
        "A value is replaced by another trusted claim value for a different metric. "
        "numeric_issues compares Decimal values and ignores metric_id."
    ),
    "wrong_subject": (
        "Only the player or team subject changes; every number is unchanged and trusted. "
        "The gate has no subject check."
    ),
    "wrong_phase_or_window": (
        "Only home/road or playoffs/regular-season wording changes; every number stays "
        "trusted. Filters and season_type are reviewer-visible, not gate-checked."
    ),
    "wins_losses_swapped": (
        "Both numbers are supplied claim values. The gate checks presence, not which value "
        "is wins and which is losses."
    ),
    "per_game_total_confusion": (
        "The value is unchanged and trusted; only the per-game versus total wording changes. "
        "The gate does not inspect units."
    ),
    "unsupported_causal_or_ranking": (
        "The added sentence contains no number tokens, so numeric_issues has nothing to "
        "check. Declared claim references are unchanged."
    ),
    "coincident_percent": (
        "The percent token equals an integer value of an unrelated trusted claim or sample "
        "size, so _explained accepts it by value before percent conversion."
    ),
}

# Higher rank is a worse false acceptance, used to order the sample list.
CLASS_RANK = {
    "wrong_subject": 0,
    "wins_losses_swapped": 1,
    "wrong_phase_or_window": 2,
    "per_game_total_confusion": 3,
    "number_swapped_other_metric": 4,
    "coincident_percent": 5,
    "unsupported_causal_or_ranking": 6,
}


@dataclass(frozen=True)
class Case:
    case_id: str
    class_name: str
    unit_id: str
    why_gate_passes: str
    edits: tuple[tuple[str, str], ...] = ()
    append: str = ""


CASES: tuple[Case, ...] = (
    Case(
        case_id="metric_swap_ppg_to_margin",
        class_name="number_swapped_other_metric",
        unit_id="exact_statistics-003",
        why_gate_passes="7.94 is the margin_per_game claim value; the gate matches values.",
        edits=(("averaged 116.34 points per game", "averaged 7.94 points per game"),),
    ),
    Case(
        case_id="metric_swap_total_points_to_margin",
        class_name="number_swapped_other_metric",
        unit_id="exact_statistics-002",
        why_gate_passes="802 is the team margin claim value and therefore trusted.",
        edits=(("scored 11,750 total points", "scored 802 total points"),),
    ),
    Case(
        case_id="metric_swap_margin_to_ppg",
        class_name="number_swapped_other_metric",
        unit_id="exact_statistics-004",
        why_gate_passes="116.34 is within half a hundredth of the points_per_game claim.",
        edits=(
            (
                "average margin was 7.94 points per game",
                "average margin was 116.34 points per game",
            ),
        ),
    ),
    Case(
        case_id="subject_swap_scorers",
        class_name="wrong_subject",
        unit_id="comparisons-002",
        why_gate_passes="Only player names move; 26.5 and 19.2 remain supplied claim values.",
        edits=(
            ("Jalen Brunson averaged 26.5", "Jalen Brunson averaged 19.2"),
            ("Karl-Anthony Towns averaged 19.2", "Karl-Anthony Towns averaged 26.5"),
        ),
    ),
    Case(
        case_id="subject_swap_brunson_to_towns",
        class_name="wrong_subject",
        unit_id="date_range_last_n-003",
        why_gate_passes="Only the name changes; 32.6, 5 and the dates stay trusted.",
        edits=(("Jalen Brunson averaged 32.6", "Karl-Anthony Towns averaged 32.6"),),
    ),
    Case(
        case_id="subject_swap_knicks_to_celtics",
        class_name="wrong_subject",
        unit_id="exact_statistics-005",
        why_gate_passes="Only the team name changes; 37 is a supplied wins claim value.",
        edits=(("The Knicks won 37 home games", "The Celtics won 37 home games"),),
    ),
    Case(
        case_id="phase_home_to_road",
        class_name="wrong_phase_or_window",
        unit_id="exact_statistics-005",
        why_gate_passes="Only home/road wording changes; 37 remains the trusted wins value.",
        edits=(("won 37 home games", "won 37 road games"),),
    ),
    Case(
        case_id="phase_playoffs_to_regular",
        class_name="wrong_phase_or_window",
        unit_id="date_range_last_n-003",
        why_gate_passes="Only phase wording changes; 32.6, 5 and the dates stay trusted.",
        edits=(("2025-26 playoffs", "2025-26 regular season"),),
    ),
    Case(
        case_id="phase_road_to_home",
        class_name="wrong_phase_or_window",
        unit_id="exact_statistics-006",
        why_gate_passes="Only road/home wording changes; 32 remains the trusted wins value.",
        edits=(("won 32 road games", "won 32 home games"),),
    ),
    Case(
        case_id="record_swap_season",
        class_name="wins_losses_swapped",
        unit_id="exact_statistics-001",
        why_gate_passes="Both 69 and 32 are supplied wins/losses claim values.",
        edits=(("went 69-32", "went 32-69"),),
    ),
    Case(
        case_id="record_swap_last_five",
        class_name="wins_losses_swapped",
        unit_id="date_range_last_n-001",
        why_gate_passes="Both 4 and 1 are supplied wins/losses claim values.",
        edits=(("went 4-1", "went 1-4"),),
    ),
    Case(
        case_id="record_swap_january",
        class_name="wins_losses_swapped",
        unit_id="date_range_last_n-004",
        why_gate_passes="Both 7 and 8 are supplied wins/losses claim values.",
        edits=(("went 7-8", "went 8-7"),),
    ),
    Case(
        case_id="unit_per_game_as_total",
        class_name="per_game_total_confusion",
        unit_id="exact_statistics-003",
        why_gate_passes="116.34 is the trusted points_per_game value; only unit wording moves.",
        edits=(("averaged 116.34 points per game", "scored 116.34 total points"),),
    ),
    Case(
        case_id="unit_total_as_per_game",
        class_name="per_game_total_confusion",
        unit_id="exact_statistics-002",
        why_gate_passes="11,750 is the trusted total points value; only unit wording moves.",
        edits=(
            (
                "scored 11,750 total points across 101 archived games",
                "averaged 11,750 points per game across 101 archived games",
            ),
        ),
    ),
    Case(
        case_id="unit_window_ppg_as_total",
        class_name="per_game_total_confusion",
        unit_id="date_range_last_n-002",
        why_gate_passes="114.1 is the trusted points_per_game value; only unit wording moves.",
        edits=(("averaged 114.1 points per game", "scored 114.1 total points"),),
    ),
    Case(
        case_id="causal_defense_ranking",
        class_name="unsupported_causal_or_ranking",
        unit_id="exact_statistics-001",
        why_gate_passes="The added sentence has no numbers; declared claims are unchanged.",
        append=" That record proves their defense is the best in the league.",
    ),
    Case(
        case_id="causal_offense_ranking",
        class_name="unsupported_causal_or_ranking",
        unit_id="comparisons-002",
        why_gate_passes="The added sentence has no numbers; declared claims are unchanged.",
        append=" Brunson's scoring average is why the Knicks had the best offense in the league.",
    ),
    Case(
        case_id="causal_schedule_ranking",
        class_name="unsupported_causal_or_ranking",
        unit_id="date_range_last_n-004",
        why_gate_passes="The added sentence has no numbers; declared claims are unchanged.",
        append=(
            " Their January schedule was the easiest in the league, which caused the "
            "winning record."
        ),
    ),
    Case(
        case_id="percent_from_wins_value",
        class_name="coincident_percent",
        unit_id="exact_statistics-005",
        why_gate_passes="37% equals the trusted home wins value, so the gate accepts it.",
        append=" They shot 37% from three-point range over that stretch.",
    ),
    Case(
        case_id="percent_from_losses_value",
        class_name="coincident_percent",
        unit_id="exact_statistics-007",
        why_gate_passes="32% equals the trusted losses value, so the gate accepts it.",
        append=" They converted 32% of their three-point attempts.",
    ),
    Case(
        case_id="percent_from_sample_size",
        class_name="coincident_percent",
        unit_id="comparisons-002",
        why_gate_passes="93% equals the trusted sample_size value, so the gate accepts it.",
        append=" They shot 93% from the free-throw line.",
    ),
)
