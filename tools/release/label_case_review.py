"Evidence accumulation, disposition, and owner-pending review output for one question."

from __future__ import annotations

import json
from collections import Counter

from label_narratives import (
    review_aliases_typos,
    review_follow_ups,
    review_single_game_narrative,
    review_turning_points,
    review_unsupported,
)
from label_statistics import (
    review_comparisons,
    review_date_range_last_n,
    review_exact_statistics,
)

CATEGORY_REVIEWERS = {
    "exact_statistics": review_exact_statistics,
    "date_range_last_n": review_date_range_last_n,
    "comparisons": review_comparisons,
    "single_game_narrative": review_single_game_narrative,
    "turning_points": review_turning_points,
    "follow_ups": review_follow_ups,
    "aliases_typos": review_aliases_typos,
    "unsupported": review_unsupported,
}


class CaseReview:
    def __init__(self, canonical):
        self.canonical = canonical
        self.facts = []
        self.evidence = []
        self.notes = []
        self.disposition = "answer"
        self.route = "table_rag"

    def fact(self, metric, value, rows, collection="games", scope=None):
        refs = self.canonical.evidence(rows, collection)
        self.facts.append(
            {
                "metric": metric,
                "value": value,
                "scope": scope or "archive",
                "canonical_evidence_ids": [r["canonical_id"] for r in refs],
            }
        )
        self.evidence.extend(refs)

    def record(self, rows, scope="archive"):
        for metric, value in self.canonical.record(rows).items():
            self.fact(metric, value, rows, scope=scope)

    def average(self, rows, score_fn, metric, scope="archive"):
        numerator = sum(score_fn(row) for row in rows)
        value = round(numerator / len(rows), 4) if rows else None
        self.fact(metric, value, rows, scope=scope)
        self.facts[-1]["numerator"] = numerator
        self.facts[-1]["denominator"] = len(rows)

    def player_stat(self, name, metric, mode="average", games=None, last=None, scope=None):
        rows = self.canonical.player(name, games, last)
        if not rows:
            raise ValueError(f"No appearances for {name}")
        values = [r[metric] for r in rows]
        value = sum(values) if mode == "total" else round(sum(values) / len(values), 4)
        if mode == "double_doubles":
            value = sum(
                sum(r[k] >= 10 for k in ("points", "rebounds", "assists", "steals", "blocks")) >= 2
                for r in rows
            )
        elif mode == "starts":
            value = sum(bool(r["starter"]) for r in rows)
        elif mode == "percentage":
            value = round(
                sum(r["three_pointers_made"] for r in rows)
                / sum(r["three_pointers_attempted"] for r in rows)
                * 100,
                4,
            )
        full_name = self.canonical.names[rows[0]["nba_player_id"]]
        label = f"{full_name}: {mode} {metric}"
        self.fact(label, value, rows, "player_game_stats", scope)
        self.facts[-1]["player_name"] = full_name
        self.facts[-1]["appearances"] = len(rows)
        if mode == "average":
            self.facts[-1]["numerator"] = sum(values)
            self.facts[-1]["denominator"] = len(rows)

    def leader(self, metric, rows):
        ids = {r["nba_game_id"] for r in rows}
        relevant = [
            r
            for r in self.canonical.data["player_game_stats"]
            if r["nba_game_id"] in ids
            and r["team_id"] == "NYK"
            and (float(r.get("minutes") or 0) > 0)
        ]
        totals = Counter()
        for r in relevant:
            totals[r["nba_player_id"]] += r[metric]
        maximum = max(totals.values())
        for pid, total in sorted(totals.items()):
            if total == maximum:
                own = [r for r in relevant if r["nba_player_id"] == pid]
                self.fact(
                    f"{metric} leader",
                    {"name": self.canonical.names[pid], "total": total},
                    own,
                    "player_game_stats",
                )
        self.notes.append(
            f"Leader defined by total {metric}; all Knicks players compared, ties retained."
        )

    def scorelines(self, rows):
        for row in rows:
            self.fact(
                "game_score",
                {
                    k: row[k]
                    for k in (
                        "nba_game_id",
                        "game_date",
                        "home_team_id",
                        "away_team_id",
                        "home_score",
                        "away_score",
                    )
                },
                [row],
            )

    def clarify(self, reason, rows=None):
        self.disposition, self.route = ("clarify", None)
        self.notes.append(reason)
        if rows is not None:
            self.scorelines(rows)

    def refuse(self, reason):
        self.disposition, self.route = ("refuse", None)
        self.notes.append(reason)

    def review_case(self, case):
        category, number = case["id"].rsplit("-", 1)
        handler = CATEGORY_REVIEWERS.get(category)
        if handler is None:
            raise ValueError(category)
        handler(self, int(number))
        unique_evidence = {r["canonical_id"]: r for r in self.evidence}
        factual_text = [
            f"{f['scope']} — {f['metric']}: {json.dumps(f['value'], ensure_ascii=False)}"
            for f in self.facts
        ]
        proposed = {
            "disposition": self.disposition,
            "answerable": self.disposition == "answer",
            "expected_route": self.route,
            "canonical_facts": self.facts,
            "required_facts": factual_text if self.disposition == "answer" else [],
            "claims": [
                {
                    "text": text,
                    "accepted_phrasings": [],
                    "evidence_ids": f["canonical_evidence_ids"],
                }
                for text, f in zip(factual_text, self.facts, strict=True)
            ]
            if self.disposition == "answer"
            else [],
            "canonical_evidence_ids": sorted(unique_evidence),
            "notes": self.notes,
        }
        differences = []
        if proposed["answerable"] != case["answerable"]:
            differences.append("original_answerability_requires_adjudication")
        if proposed["expected_route"] != case["expected_route"]:
            differences.append("original_route_requires_adjudication")
        if self.disposition == "clarify":
            differences.append("question_requires_scope_or_definition")
        if not differences and (not self.facts) and (self.disposition == "answer"):
            raise ValueError(f"Missing facts: {case['id']}")
        return {
            **case,
            "label_status": "agent_reviewed_owner_pending",
            "agent_review": {
                "status": "completed",
                "method": (
                    "independent canonical row arithmetic and question-by-question semantic review"
                ),
                "no_application_answer_used": True,
            },
            "owner_approval": None,
            "proposed_label": proposed,
            "canonical_sources": list(unique_evidence.values()),
            "discrepancies": differences,
            "remaining_owner_decisions": [
                (
                    "Approve or revise proposed disposition, metric/denominator and "
                    "canonical facts in category batch."
                ),
                (
                    "Approve accepted answer phrasings and claim-level citation mappings "
                    "after verified target identity."
                ),
            ],
        }
