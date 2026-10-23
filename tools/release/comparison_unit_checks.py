"""Check physical source units against externally pinned independent evidence.

No application unit builder, SQL importer or retrieval implementation is used.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

FAMILIES = {
    "quarter": ("q3_fewest_points", "q3_worst_margin"),
    "deficit": (
        "largest_observed_deficit",
        "largest_deficit_later_tied",
        "largest_deficit_later_led",
        "largest_deficit_in_eventual_win",
    ),
    "runs": (
        "knicks_largest_unanswered_run",
        "opponent_largest_unanswered_run",
        "knicks_largest_unrestricted_net_gain",
        "largest_unrestricted_margin_decline",
    ),
    "collapse": (
        "largest_positive_lead_surrendered",
        "largest_positive_lead_surrendered_in_final_loss",
        "largest_unrestricted_margin_decline",
    ),
}
TITLES = {
    "quarter": "Worst third quarter: fewest Knicks points versus worst scoring margin",
    "deficit": "Largest deficit: observed versus erased to a tie, lead or eventual win",
    "runs": (
        "Biggest Knicks scoring run and most damaging opponent run: unanswered points "
        "versus unrestricted net margins; a damage criterion still needs clarification"
    ),
    "collapse": "Worst collapse: positive lead surrendered versus unrestricted margin decline",
}
COMMON = {
    "recipe",
    "unit_type",
    "data_version",
    "team_ids",
    "canonical_sources",
    "text",
    "semantic_summary",
    "source_document_id",
}
EVENT_FIELDS = (
    "canonical_id",
    "sequence",
    "period",
    "clock",
    "team_id",
    "nba_player_id",
    "points",
    "score_before",
    "score_after",
    "primary_action_sha256",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def references(rows: list[dict]) -> list[str]:
    refs = set()
    for row in rows:
        for measure in row["measures"].values():
            for boundary in measure["boundaries"]:
                refs.update(boundary.get("period_sources", []))
                refs.update(boundary.get("scoring_sources", []))
                refs.update(
                    boundary[k] for k in ("source", "start_source", "end_source") if k in boundary
                )
    return sorted(refs)


class ComparisonProof:
    def __init__(
        self, path: Path, expected_sha256: str, data: dict, version: str, bundle_sha256: str
    ):
        raw_proof = path.read_bytes()
        require(
            hashlib.sha256(raw_proof).hexdigest() == expected_sha256,
            "Comparison proof pointer changed",
        )
        proof = json.loads(raw_proof)
        require(
            set(proof["paths"])
            == set(proof["expected_hashes"])
            == {"bundle", "trajectories", "source_review", "comparisons"},
            "Incomplete pinned proof",
        )
        raw = {name: Path(value).read_bytes() for name, value in proof["paths"].items()}
        require(
            all(
                hashlib.sha256(value).hexdigest() == proof["expected_hashes"][name]
                for name, value in raw.items()
            ),
            "Pinned comparison evidence changed",
        )
        hashes = proof["expected_hashes"]
        require(hashes["bundle"] == bundle_sha256, "Foreign comparison bundle")
        self.report, review = json.loads(raw["comparisons"]), json.loads(raw["source_review"])
        trajectories = [json.loads(line) for line in raw["trajectories"].splitlines()]
        self.records = {r["nba_game_id"]: r for r in trajectories}
        self.games = {g["nba_game_id"]: g for g in data["games"]}
        self.compared = {g["nba_game_id"]: g for g in self.report["games"]}
        reviewed = {g["nba_game_id"]: g for g in review["sources"]}
        require(
            len(self.records)
            == len(trajectories)
            == len(self.games)
            == len(self.compared)
            == len(reviewed)
            and set(self.records) == set(self.games) == set(self.compared) == set(reviewed),
            "Incomplete verified source population",
        )
        require(
            self.report["status"] == "COMPLETE_PINNED_MEASURE_COMPARISONS"
            and review["status"] == "PER_ACTION_SCORING_SOURCE_VERIFIED"
            and self.report["data_version"] == review["data_version"] == version
            and self.report["trajectories_sha256"]
            == review["trajectories_sha256"]
            == hashes["trajectories"]
            and self.report["source_review_sha256"] == hashes["source_review"]
            and review["bundle_sha256"] == bundle_sha256
            and self.report["gold_approved"] is False
            and self.report["metric_defaults"] is None,
            "Unverified comparison evidence lineage",
        )
        events = {(r["nba_game_id"], r["sequence"]): r for r in data["events"]}
        periods = {
            f"period:{r['nba_game_id']}:{r['team_id']}:{r['period']}": r
            for r in data["period_scores"]
        }
        for identity, record in self.records.items():
            require(
                record["game_row_sha256"] == digest(self.games[identity])
                and record["source_document_id"] == reviewed[identity]["source_document_id"]
                and record["source_document_id"]
                == "derived-score-trajectory:"
                + digest({k: v for k, v in record.items() if k != "source_document_id"})
                and record["primary_capture_sha256"]
                == reviewed[identity]["primary_capture_sha256"],
                "Verified game or primary capture identity changed",
            )
            for event in record["events"]:
                require(
                    event["canonical_row_sha256"] == digest(events[(identity, event["sequence"])]),
                    "Verified event no longer represents approved canonical bytes",
                )
            for period in record["period_receipts"]:
                require(
                    period["row_sha256"] == digest(periods[period["canonical_id"]])
                    and period["points"] == periods[period["canonical_id"]]["points"],
                    "Unsupported period receipt",
                )
        self.provenance = {
            "comparison_sha256": hashes["comparisons"],
            "source_review_sha256": hashes["source_review"],
            "trajectories_sha256": hashes["trajectories"],
            "bundle_sha256": bundle_sha256,
            "recipe": "nba-action-scoring-trajectory-v1",
        }
        self.margin_groups = defaultdict(set)
        for identity, game in self.games.items():
            self.margin_groups[abs(game["home_score"] - game["away_score"])].add(identity)
        self.expected = (
            {
                ("measure", scope, family)
                for scope in ("complete_archive", "regular_season", "postseason")
                for family in FAMILIES
            }
            | {("single", identity) for identity in self.games}
            | {("story", margin) for margin, ids in self.margin_groups.items() if len(ids) > 1}
        )
        self.seen = set()

    def witnesses(self, rows: list[dict]) -> dict:
        used = set(references(rows))
        return {
            e["canonical_id"]: {k: e[k] for k in EVENT_FIELDS}
            for row in rows
            for e in self.records[row["nba_game_id"]]["events"]
            if e["canonical_id"] in used
        }

    def game_identity(self, row: dict, sql_games: dict) -> None:
        sql_id, nba_id = row["game_id"], row["nba_game_id"]
        require(
            type(sql_id) is int and sql_id > 0 and nba_id in self.games,
            "Invalid represented game identity",
        )
        require(
            sql_games.setdefault(sql_id, nba_id) == nba_id,
            "Conflicting represented SQL game identity",
        )
        require(
            sum(value == nba_id for value in sql_games.values()) == 1,
            "NBA game maps to multiple SQL identities",
        )

    def population(self, payload: dict, rows: list[dict]) -> None:
        games = [self.games[row["nba_game_id"]] for row in rows]
        require(
            payload["game_ids"] == sorted(row["game_id"] for row in rows)
            and payload["dates"] == sorted({g["game_date"] for g in games})
            and payload["season_types"] == sorted({g["season_type"] for g in games})
            and payload["team_ids"]
            == sorted({t for g in games for t in (g["home_team_id"], g["away_team_id"])}),
            "Incomplete aggregate population metadata",
        )

    def check(self, payload: dict, sql_games: dict) -> None:
        kind = payload["unit_type"]
        require(
            payload["provenance"] == self.provenance and payload["gold_approved"] is False,
            "Foreign comparison provenance or invented gold approval",
        )
        require(
            payload["season"] == next(iter(self.games.values()))["season"], "Foreign source season"
        )
        if kind == "game_scoring_comparison":
            identity = payload["nba_game_id"]
            game, compared, record = (
                self.games[identity],
                self.compared[identity],
                self.records[identity],
            )
            self.game_identity(payload, sql_games)
            require(
                payload["game_ids"] == [payload["game_id"]]
                and payload["date"] == game["game_date"]
                and payload["season_type"] == game["season_type"]
                and payload["team_ids"] == [game["home_team_id"], game["away_team_id"]],
                "Wrong single-game scope",
            )
            body = {
                **{
                    k: game[k] for k in ("home_team_id", "away_team_id", "home_score", "away_score")
                },
                "period_rows": record["period_receipts"],
                "measures": compared["measures"],
                "definitions": self.report["definitions"],
                "witness_events": self.witnesses([compared]),
            }
            refs = sorted(
                {
                    f"game:{identity}",
                    *(p["canonical_id"] for p in record["period_receipts"]),
                    *references([compared]),
                }
            )
            expected_text = (
                f"Knicks NYK game {identity}, {game['game_date']}, {game['season_type']}. "
                "Complete game scoring comparisons and descriptive story: final/period scores, "
                "all maximum unanswered scoring runs, deficits and explicitly "
                "unrestricted margins. "
                "No causal assertions or metric default.\n" + encoded(body)
            )
            fields = {
                "game_id",
                "game_ids",
                "nba_game_id",
                "date",
                "season",
                "season_type",
                "provenance",
                "metric_defaults",
                "gold_approved",
                *body,
            }
            key = ("single", identity)
        elif payload["aggregate_kind"] == "measure_comparison":
            scope, family = payload["population_scope"], payload["measure_family"]
            require(
                scope in self.report["populations"] and family in FAMILIES,
                "Unknown comparison scope or family",
            )
            keys = FAMILIES[family]
            expected_ids = [
                ref.removeprefix("game:")
                for ref in self.report["populations"][scope]["game_sources"]
            ]
            rows = payload["comparison_rows"]
            require(
                [r["nba_game_id"] for r in rows] == expected_ids,
                "Incomplete comparison game population",
            )
            for row in rows:
                self.game_identity(row, sql_games)
                compared = self.compared[row["nba_game_id"]]
                require(
                    row
                    == {
                        "nba_game_id": row["nba_game_id"],
                        "game_id": row["game_id"],
                        "game_date": compared["game_date"],
                        "season_type": compared["season_type"],
                        "measures": {k: compared["measures"][k] for k in keys},
                    },
                    "Incorrect represented comparison measure",
                )
            self.population(payload, rows)
            body = {
                "definitions": {k: self.report["definitions"][k] for k in keys},
                "comparison_rows": rows,
                "extrema": {k: self.report["populations"][scope]["extrema"][k] for k in keys},
                "witness_events": self.witnesses(rows),
            }
            refs = references(rows)
            expected_text = (
                f"{TITLES[family]}. NYK Knicks {payload['season']}; "
                f"{scope}, complete population of {len(rows)} games. "
                "Quantitative alternatives only. No metric, window or season-scope default; "
                "no causal assertions.\n" + encoded(body)
            )
            fields = {
                "aggregate_kind",
                "measure_family",
                "population_scope",
                "season",
                "game_ids",
                "dates",
                "season_types",
                "provenance",
                "metric_defaults",
                "gold_approved",
                *body,
            }
            if family == "quarter":
                fields |= {"start_period", "end_period"}
                require(
                    payload["start_period"] == payload["end_period"] == 3,
                    "Wrong comparison period scope",
                )
            key = ("measure", scope, family)
        else:
            require(
                kind == "multigame_aggregate"
                and payload["aggregate_kind"] == "selected_game_stories",
                "Unknown derived source variant",
            )
            rows = payload["story_rows"]
            require(len(rows) > 1, "Missing story tie population")
            margin = rows[0]["final_margin"]
            require(
                {r["nba_game_id"] for r in rows} == self.margin_groups[margin]
                and len(rows) == len(self.margin_groups[margin]),
                "Incomplete tied story population",
            )
            require(
                [r["nba_game_id"] for r in rows]
                == sorted(
                    self.margin_groups[margin], key=lambda i: (self.games[i]["game_date"], i)
                ),
                "Wrong story ordering",
            )
            for row in rows:
                self.game_identity(row, sql_games)
                game, record = self.games[row["nba_game_id"]], self.records[row["nba_game_id"]]
                expected = {
                    "game_id": row["game_id"],
                    "nba_game_id": row["nba_game_id"],
                    **{
                        k: game[k]
                        for k in (
                            "game_date",
                            "season_type",
                            "home_team_id",
                            "away_team_id",
                            "home_score",
                            "away_score",
                        )
                    },
                    "final_margin": abs(game["home_score"] - game["away_score"]),
                    "period_rows": record["period_receipts"],
                }
                require(row == expected, "Unsupported story fact")
            self.population(payload, rows)
            body = {"story_rows": rows}
            refs = sorted(
                {f"game:{r['nba_game_id']}" for r in rows}
                | {
                    p["canonical_id"]
                    for r in rows
                    for p in self.records[r["nba_game_id"]]["period_receipts"]
                }
            )
            expected_text = (
                "Closest Knicks NYK game descriptive story within this selected "
                "tied-final-margin population. "
                "Every selected game and period is represented; no causal assertion or "
                "comparison outside this supplied population.\n" + encoded(rows)
            )
            fields = {
                "aggregate_kind",
                "season",
                "game_ids",
                "dates",
                "season_types",
                "provenance",
                "gold_approved",
                *body,
            }
            key = ("story", margin)
        require(set(payload) == COMMON | fields, "Unknown or missing derived source fields")
        require(
            all(payload[k] == value for k, value in body.items()),
            "Missing or unsupported physical source facts",
        )
        require(
            payload["canonical_sources"] == refs,
            "Inflated or omitted fine-grained source references",
        )
        require(
            payload["text"] == payload["semantic_summary"] == expected_text,
            "Unsupported or physically omitted source text",
        )
        if "metric_defaults" in fields:
            require(payload["metric_defaults"] is None, "Invented metric default")
        require(
            key in self.expected and key not in self.seen,
            "Duplicate or unknown comparison source unit",
        )
        self.seen.add(key)

    def finish(self) -> dict:
        require(self.seen == self.expected, "Missing full comparison and story unit inventory")
        return {
            "comparison_units": sum(k[0] == "measure" for k in self.seen),
            "game_story_units": sum(k[0] == "single" for k in self.seen),
            "tied_story_units": sum(k[0] == "story" for k in self.seen),
        }
