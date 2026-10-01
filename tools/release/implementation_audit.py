"""Execute the confirmed release plan's offline review and feasibility stages.

This command deliberately has no provider, credential, database, approval,
freeze, deployment, or ranked-retrieval path. A successful audit can establish
that semantic closure is blocked. It does not establish a passing release.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from draft_labels import Canonical, digest, review_cases

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = "bf4439bbcd69e328c1d65c52e9a73dcbe4942cbe"
BUNDLE_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
QUESTIONS_SHA256 = "a546b99c36fedb59a475479016b0338fe113c4478d5165c4a5073d144ffdf482"
RECORD_SHA256 = "4bb12b3d3ad565c521d16cc99e7c5c7de2850269c7f4a99eb98ac8b7820607b3"
HANDOFF_SHA256 = "dba6dfe625e30a32d9c6f540f5c0d39eed2036dfd7be18fecaf1be6262375bef"
CLARIFICATIONS = {
    "single_game_narrative-018": (
        "Should worst third quarter mean fewest Knicks points or worst quarter margin? "
        "Which game or date/season scope should I compare?"
    ),
    "turning_points-005": (
        "Which game or season scope should I use? Should largest deficit include all observed "
        "deficits or only erased deficits? Does erased mean tied, regained the lead, or an "
        "eventual win?"
    ),
    "turning_points-007": (
        "For this season, what boundaries define an opponent run, and should damage mean "
        "unanswered points, net scoring change, or another stated measure?"
    ),
    "aliases_typos-005": (
        "Should biggest run mean unanswered Knicks points or net gain over a defined window? "
        "Which game or season scope and window should I use?"
    ),
    "aliases_typos-010": (
        "Should worst collapse mean a lead surrendered or a scoring-margin decline? "
        "Which interval and game/season scope should I use, and must the game end in a loss?"
    ),
}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def contained(root: Path, relative: str) -> Path:
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes retained root")
    return result


def verify_baseline(evidence_root: Path, expected_bundle: str) -> tuple[dict, dict]:
    package = evidence_root / "release-artifacts/rc-20260930"
    record_path = package / "release-record.json"
    if file_hash(record_path) != RECORD_SHA256:
        raise ValueError("Retained release record binding changed")
    record = read_json(record_path)
    if record["tested_commit"] != CANDIDATE or record["status"] != "BLOCKED_NOT_READY":
        raise ValueError("Unexpected retained release candidate/status")
    checksums = {}
    for line in (package / "SHA256SUMS").read_text().splitlines():
        expected, relative = line.split(maxsplit=1)
        relative = relative.removeprefix("*")
        if relative in checksums or file_hash(contained(package, relative)) != expected:
            raise ValueError(f"Retained package checksum mismatch: {relative}")
        checksums[relative] = expected
    manifest = read_json(package / "artifact-manifest.json")
    if len(checksums) != 485 or manifest["file_count"] != 484:
        raise ValueError("Retained package inventory changed")
    seen = set()
    for item in manifest["files"]:
        path = contained(package, item["path"])
        if (
            item["path"] in seen
            or path.stat().st_size != item["bytes"]
            or checksums.get(item["path"]) != item["sha256"]
        ):
            raise ValueError("Retained manifest mismatch")
        seen.add(item["path"])
    if len(seen) != 484:
        raise ValueError("Retained manifest incomplete")
    refs = read_json(package / "release-package-integrity.json")["references"]
    for ref in refs:
        if file_hash(contained(evidence_root, ref["path"])) != ref["expected_sha256"]:
            raise ValueError(f"Retained record reference changed: {ref['path']}")
    bundle_path = evidence_root / "release-artifacts/2025-26/reliability-approved-20260928.json.gz"
    if expected_bundle != BUNDLE_SHA256 or file_hash(bundle_path) != expected_bundle:
        raise ValueError("Approved bundle binding changed")
    payload = json.loads(gzip.decompress(bundle_path.read_bytes()))
    return payload, {
        "status": "passed",
        "verified_checksum_files": len(checksums),
        "verified_record_references": len(refs),
        "record_sha256": file_hash(record_path),
        "manifest_sha256": file_hash(package / "artifact-manifest.json"),
        "checksums_sha256": file_hash(package / "SHA256SUMS"),
        "bundle_sha256": file_hash(bundle_path),
        "tested_commit": CANDIDATE,
    }


def boston_maxima(canonical: Canonical, game: dict) -> list[dict]:
    """Independent canonical arithmetic; no legacy window or analyst output."""
    events = sorted(
        (e for e in canonical.data["events"] if e["nba_game_id"] == game["nba_game_id"]),
        key=lambda e: e["sequence"],
    )
    sequences = [e["sequence"] for e in events]
    if not events or len(set(sequences)) != len(sequences):
        raise ValueError("Missing or duplicate Boston event order")
    previous = (0, 0)
    runs, scoring = [], []
    points = 0
    before = previous
    boston = 0 if game["home_team_id"] == "BOS" else 1
    for event in events:
        current = (event["home_score"], event["away_score"])
        current = previous if current == (0, 0) else current
        change = tuple(a - b for a, b in zip(current, previous, strict=True))
        if min(change) < 0 or all(value > 0 for value in change):
            raise ValueError("Ambiguous/corrected Boston scoreboard; no run certification")
        if change[1 - boston] > 0:
            if scoring:
                runs.append((points, before, previous, scoring))
            points, scoring = 0, []
        elif change[boston] > 0:
            if not scoring:
                before = previous
            scoring.append(event)
            points += change[boston]
        previous = current
    if scoring:
        runs.append((points, before, previous, scoring))
    if previous != (game["home_score"], game["away_score"]) or not runs:
        raise ValueError("Boston scoreboard coverage/final mismatch")
    maximum = max(run[0] for run in runs)
    result = []
    for points, before, after, scoring in runs:
        if points != maximum:
            continue
        first, last = scoring[0], scoring[-1]
        result.append(
            {
                "nba_game_id": game["nba_game_id"],
                "points": points,
                "knicks_points": 0,
                "start_sequence": first["sequence"],
                "end_sequence": last["sequence"],
                "start_period": first["period"],
                "end_period": last["period"],
                "start_clock": first["clock"],
                "end_clock": last["clock"],
                "score_before": {"home": before[0], "away": before[1]},
                "score_after": {"home": after[0], "away": after[1]},
                "scoring_events": [
                    {
                        "canonical_id": f"event:{game['nba_game_id']}:{e['sequence']}",
                        "row_sha256": digest(e),
                        "row": e,
                    }
                    for e in scoring
                ],
                "definition": (
                    "Consecutive Boston scoring events without intervening Knicks points; "
                    "any Knicks point ends a run; quarter breaks/zero-point events do not."
                ),
                "causal_claim": False,
            }
        )
    return result


def narrative_facts(canonical: Canonical, games: list[dict]) -> list[dict]:
    facts = []
    for game in games:
        gid = game["nba_game_id"]
        facts.append(
            {
                "metric": "game_score",
                "value": {
                    key: game[key]
                    for key in (
                        "nba_game_id",
                        "game_date",
                        "home_team_id",
                        "away_team_id",
                        "home_score",
                        "away_score",
                    )
                },
                "scope": "archive",
                "canonical_evidence_ids": [f"game:{gid}"],
            }
        )
        periods = sorted(
            (r for r in canonical.data["period_scores"] if r["nba_game_id"] == gid),
            key=lambda r: (r["period"], r["team_id"]),
        )
        for row in periods:
            facts.append(
                {
                    "metric": "quarter_points",
                    "value": row["points"],
                    "scope": {"game": gid, "team": row["team_id"], "period": row["period"]},
                    "canonical_evidence_ids": [f"period:{gid}:{row['team_id']}:{row['period']}"],
                }
            )
    return facts


def review_expectations(payload: dict, questions: list[dict], historical: dict) -> list[dict]:
    labels, _ = review_cases(payload, questions)
    canonical = Canonical(payload)
    # Index actual canonical rows rather than extending a manifest mapping on trust.
    source_rows = {}
    for collection in ("games", "player_game_stats", "team_game_stats", "period_scores"):
        for source in canonical.data[collection]:
            ref = canonical.evidence([source], collection)[0]
            source_rows[ref["canonical_id"]] = ref
    for source in canonical.data["events"]:
        ref = f"event:{source['nba_game_id']}:{source['sequence']}"
        if ref in source_rows:
            raise ValueError("Duplicate canonical event identity")
        source_rows[ref] = {
            "canonical_id": ref,
            "collection": "events",
            "row_sha256": digest(source),
        }
    old = {case["id"]: case for case in historical["cases"]}
    if len(old) != 120 or set(old) != {q["id"] for q in questions}:
        raise ValueError("Historical review population mismatch")
    rows = []
    for label, original in zip(labels, questions, strict=True):
        previous = old[label["id"]]
        if previous["question"] != original["question"]:
            raise ValueError("Historical question mismatch")
        proposed = label["proposed_label"]
        # Recompute arithmetic before applying only the confirmed policy changes.
        if proposed["canonical_facts"] != previous["proposed_expectation"]["canonical_facts"]:
            raise ValueError(f"Canonical fact audit differs from retained review: {label['id']}")
        row = {
            "id": label["id"],
            "question": original["question"],
            "context": original.get("context", []),
            "original_question": original,
            "semantic_member": original["answerable"]
            and original["expected_route"] == "retrieval_rag",
            "disposition": proposed["disposition"],
            "facts": proposed["canonical_facts"],
            "canonical_sources": label["canonical_sources"],
            "prior_proposal_sha256": digest(previous["proposed_expectation"]),
            "decision_basis": proposed["notes"],
            "required_inputs": [],
            "selected_canonical_games": [],
            "owner_approval": None,
        }
        if row["id"] in CLARIFICATIONS:
            row["clarification"] = CLARIFICATIONS[row["id"]]
            row["required_inputs"] = {
                "single_game_narrative-018": [
                    "fewest Knicks Q3 points versus worst Q3 margin",
                    "scope",
                ],
                "turning_points-005": [
                    "scope",
                    "all observed versus erased deficits",
                    "tied/regained lead/eventual win",
                ],
                "turning_points-007": ["run boundaries", "damage measure (season scope preserved)"],
                "aliases_typos-005": [
                    "unanswered points versus net window gain",
                    "window",
                    "scope",
                ],
                "aliases_typos-010": [
                    "lead surrendered versus margin decline",
                    "interval",
                    "scope",
                    "loss required",
                ],
            }[row["id"]]
            row["decision_basis"] = [
                "Confirmed owner clarification inputs; no new measure default."
            ]
        if row["id"].startswith("follow_ups-") or row["id"] == "aliases_typos-003":
            n = int(row["id"].rsplit("-", 1)[1])
            row["required_inputs"] = ["game/date"]
            if row["id"].startswith("follow_ups-") and n <= 9:
                row["required_inputs"].append("referenced event/stretch/claim")
                if n == 8:
                    row["required_inputs"].extend(["comparison measure", "comparison scope"])
                if n == 9:
                    row["required_inputs"].append("comparison game/date")
            row["clarification"] = "Please specify " + ", ".join(row["required_inputs"]) + "."
            row["decision_basis"] = [
                "Confirmed unanchored clarification; unverified assistant narrative "
                "is not committed state."
            ]
            row["game_reference_policy"] = {
                "history_messages": 10,
                "canonical_game_identity_required": True,
                "context_statistics_are_evidence": False,
                "missing_game_clarification": "Which game?",
            }
            if row["id"] == "aliases_typos-003":
                row["clarification"] = "Which game?"
                row["decision_basis"].append(
                    "Owner confirmed that game references require an identifiable game "
                    "in the preceding ten messages; this case has no context."
                )
        if row["id"] == "single_game_narrative-006":
            selected = canonical.extreme(lambda game: abs(canonical.margin(game)), False)
            row.update(
                disposition="answer",
                facts=narrative_facts(canonical, selected),
                selected_canonical_games=[g["nba_game_id"] for g in selected],
                decision_basis=[
                    "Confirmed defined-superlative policy: tell descriptive stories "
                    "for ALL tied games."
                ],
            )
        if row["id"] in {"single_game_narrative-020", "turning_points-006"}:
            games = [g for g in canonical.games_against("BOS") if canonical.margin(g) < 0]
            if len(games) != 1:
                raise ValueError("Boston loss is no longer independently unique")
            runs = boston_maxima(canonical, games[0])
            facts = narrative_facts(canonical, games)
            for run in runs:
                facts.append(
                    {
                        "metric": "maximum_unanswered_boston_points",
                        "value": run["points"],
                        "scope": {
                            "game": games[0]["nba_game_id"],
                            "start": run["start_sequence"],
                            "end": run["end_sequence"],
                        },
                        "canonical_evidence_ids": [
                            e["canonical_id"] for e in run["scoring_events"]
                        ],
                    }
                )
            row.update(
                disposition="answer",
                facts=facts,
                boston_unanswered_runs=runs,
                selected_canonical_games=[games[0]["nba_game_id"]],
                decision_basis=[
                    "Confirmed descriptive selection of every maximum unanswered "
                    "Boston run; no causal assertion."
                ],
            )
        refs = sorted({ref for fact in row["facts"] for ref in fact["canonical_evidence_ids"]})
        row["canonical_sources"] = [source_rows[ref] for ref in refs]
        rows.append(row)
    return rows


def identity_dossier(payload: dict, material: dict, alias_source: Path) -> dict:
    players = [p for p in payload["data"]["players"] if p["full_name"] == "Jalen Brunson"]
    if len(players) != 1:
        raise ValueError("Canonical player identity is not unique")
    alias_text = alias_source.read_text()
    if '"jb": "Jalen Brunson"' not in alias_text:
        raise ValueError("Known resolver alias changed")
    documents = [r for records in material.values() for r in records]
    hits = [r["id"] for r in documents if re.search(r"\bjb\b", json.dumps(r["payload"]), re.I)]
    identity_docs = [
        r["id"] for r in documents if r["payload"].get("unit_type") == "player_identity"
    ]
    return {
        "case_id": "aliases_typos-003",
        "status": "EXPECTED_GAME_CLARIFICATION_IDENTITY_HYPOTHESIS_PENDING",
        "canonical_player": players[0],
        "canonical_player_sha256": digest(players[0]),
        "resolver_alias": {
            "alias": "JB",
            "target": "Jalen Brunson",
            "source_sha256": file_hash(alias_source),
            "canonical_source": False,
        },
        "game_anchor": None,
        "immutable_context": [],
        "semantic_targets": [],
        "indexed_document_count": len(documents),
        "indexed_alias_mentions": hits,
        "indexed_player_identity_documents": identity_docs,
        "independent_relevance_judgment": (
            "The canonical player row supports the NBA ID and full name. The curated resolver "
            "recognizes JB, but it is application policy, not independent alias evidence. "
            "The retained corpus has game-scoped boxes, summaries, reports and event chunks. "
            "The immutable question supplies no conversation game, so Which game? is the "
            "expected product response. This absence does not demonstrate failure of identity "
            "source relevance. The candidate player source remains a hypothesis requiring "
            "independent relevance adjudication and actual ingestion/scope/receipt mapping "
            "before any new semantic target can be approved."
        ),
        "expected_disposition": "clarify",
        "clarification": "Which game?",
        "history_messages": 10,
        "demonstrated_identity_incompatibility": False,
        "hard_stop": None,
        "remaining_semantic_requirements": [
            "Independent source relevance adjudication for the unchanged question.",
            "Verified current document/receipt mappings and actual ranked captures.",
            "Content-bound evaluation gold approval; clarification earns no retrieval credit.",
        ],
        "canonical_identity_candidate_exists": True,
        "candidate_canonical_source": f"player:{players[0]['nba_player_id']}",
        "candidate_is_gold": False,
        "rejected_alternatives": [
            "Selecting one arbitrary Brunson box or event supplies an unrequested game.",
            "Mapping an identity row to all Brunson game performances inflates source support.",
            "Calling the application alias registry canonical invents independent evidence.",
            "Treating the identity row as performance evidence does not establish relevance "
            "to the absent referenced game. The existence of the player row alone does not "
            "prove the proposed new semantic target definition.",
        ],
        "content_approval_extended": False,
        "invented_source_mapping": False,
    }


def coverage_review(rows: list[dict], settled: dict, material: dict, payload: dict) -> dict:
    canonical = Canonical(payload)
    known_games = {f"game:{g['nba_game_id']}" for g in canonical.games}
    known_boxes = {
        f"box:{r['nba_game_id']}:{r['nba_player_id']}" for r in canonical.data["player_game_stats"]
    }
    inventory = Counter()
    multi, identities = [], []
    for collection, documents in material.items():
        inventory[collection] = len(documents)
        for doc in documents:
            p = doc["payload"]
            if p.get("game_ids") or p.get("unit_type") == "multigame_aggregate":
                multi.append(doc["id"])
            if p.get("unit_type") == "player_identity":
                identities.append(doc["id"])
    cases = []
    for row in rows:
        if not row["semantic_member"]:
            continue
        existing = settled.get(row["id"])
        targets = existing["canonical_targets"] if existing else []
        if not set(targets) <= known_games | known_boxes:
            raise ValueError("Settled canonical target absent from approved archive")
        candidate_sources = sorted(
            {ref for fact in row["facts"] for ref in fact["canonical_evidence_ids"]}
        )
        cases.append(
            {
                "id": row["id"],
                "question": row["question"],
                "context": row["context"],
                "disposition": row["disposition"],
                "settled_targets": targets,
                "settled_targets_preserved": bool(existing),
                "settled_target_record": existing,
                "candidate_supporting_sources": candidate_sources,
                "candidate_sources_are_gold": False,
                "source_relevance_status": "previously_settled_targets_retained"
                if existing
                else "unresolved",
                "missing_requirements": []
                if existing
                else [
                    "independent source relevance",
                    "verified current runtime document/receipt mapping",
                ],
                "conditional_single_source_recall_bound": min(1, 5 / len(targets))
                if targets
                else None,
                "aggregate_can_remove_slot_bound": bool(len(targets or candidate_sources) > 5),
                "actual_ranked_capture": False,
            }
        )
    if len(cases) != 50 or sum(bool(c["settled_targets"]) for c in cases) != 7:
        raise ValueError("Semantic cohort or settled target count changed")
    return {
        "semantic_case_count": 50,
        "settled_target_sets_retained": 7,
        "independently_complete_new_target_sets": 0,
        "actual_ranked_captures": 0,
        "scorer_unchanged": True,
        "threshold": 0.95,
        "inventory": dict(inventory),
        "existing_multigame_documents": multi,
        "existing_player_identity_documents": identities,
        "feasibility": (
            "The previous 0.943333 bound assumes every ranked document covers one game source "
            "and the broad matching-game relevance proposal. It is not an intrinsic scorer "
            "ceiling or a measurement. The unchanged scorer takes five actual ranked receipts "
            "then unions their independently verified canonical source mappings. A genuine "
            "complete aggregate can cover nine targets in one slot, but none is present in "
            "this retained corpus. New aggregate content, ingestion/schema, filtering, retrieval, "
            "manifest and independent relevance proof are required before claiming closure."
        ),
        "cases": cases,
    }


def audit(evidence_root: Path, handoff: Path, expected_bundle: str) -> dict[str, dict]:
    payload, integrity = verify_baseline(evidence_root, expected_bundle)
    questions_path = ROOT / "apps/api/app/evaluation/questions.jsonl"
    if file_hash(questions_path) != QUESTIONS_SHA256:
        raise ValueError("Immutable questions/context binding changed")
    questions = [
        json.loads(line) for line in questions_path.read_text().splitlines() if line.strip()
    ]
    if len(questions) != 120 or len({q["id"] for q in questions}) != 120:
        raise ValueError("Original 120-case inventory changed")
    package = evidence_root / "release-artifacts/rc-20260930"
    review_path = (
        evidence_root / "docs/release-evidence/reconciliation-20260928/expectation-review.json"
    )
    settled_path = (
        evidence_root
        / "release-artifacts/readiness-20260929/semantic-adjudication"
        / "owner-decisions-consolidated-v1.json"
    )
    material_path = package / "isolated-index-material.json"
    if file_hash(handoff) != HANDOFF_SHA256:
        raise ValueError("Confirmed handoff binding changed")
    rows = review_expectations(payload, questions, read_json(review_path))
    context_decision_path = (
        ROOT / "docs/release-evidence/implementation-20261001/confirmed-context-decision.json"
    )
    context_decision = read_json(context_decision_path)
    if (
        context_decision["clarification"] != "Which game?"
        or context_decision["evaluation_gold_approved"]
        or context_decision["production_launch_approved"]
    ):
        raise ValueError("Unexpected scope of confirmed game-context decision")
    material = read_json(material_path)
    identity = identity_dossier(
        payload, material, ROOT / "apps/api/app/services/query_resolution.py"
    )
    coverage = coverage_review(
        rows, read_json(settled_path)["resolved_semantic_targets"], material, payload
    )
    provider = read_json(package / "provider-smoke-admission-final.json")
    if provider["admission_verified"] or provider["unknown_reservation_released"]:
        raise ValueError("Retained provider stop condition changed")
    register = {
        "schema_version": 1,
        "status": "IMPLEMENTED_REVIEW_CONTEXT_NARRATIVE_AND_DISCOVERY_PENDING_RELEASE_GATES",
        "base_candidate": CANDIDATE,
        "implementation_branch": "codex/release-implementation-20261001",
        "scope": (
            "Offline canonical review, coverage feasibility, ten-message game-context fix, "
            "complete tied game stories, Boston unanswered scoring runs and bounded local "
            "canonical discovery before clarification/admission; "
            "no release quality/promotion claim"
        ),
        "inputs": {
            "handoff_sha256": file_hash(handoff),
            "questions_sha256": file_hash(questions_path),
            "historical_review_sha256": file_hash(review_path),
            "historical_settled_targets_sha256": file_hash(settled_path),
            "current_isolated_index_material_sha256": file_hash(material_path),
            "audit_source_sha256": file_hash(Path(__file__)),
            "canonical_reviewer_sha256": file_hash(Path(__file__).with_name("draft_labels.py")),
            "confirmed_context_decision_sha256": file_hash(context_decision_path),
            "application_source_sha256": {
                relative: file_hash(ROOT / relative)
                for relative in (
                    "apps/api/app/api/analysis.py",
                    "apps/api/app/services/analyst_tools.py",
                    "apps/api/app/services/game_reference.py",
                    "apps/api/app/services/query_resolution.py",
                    "apps/api/app/services/canonical_narrative.py",
                    "apps/api/app/services/analyst_loop.py",
                    "apps/api/app/services/narrative_scope.py",
                    "apps/api/app/services/evidence_contracts.py",
                )
            },
        },
        "baseline_integrity": integrity,
        "case_count": 120,
        "semantic_case_count": 50,
        "dispositions": dict(Counter(row["disposition"] for row in rows)),
        "confirmed_context_decision": context_decision,
        "owner_decisions": [
            "Preserve gates; genuine bounded canonical discovery "
            "with no paid model calls/reservations.",
            "Five undefined measures retain clarification; no global defaults.",
            "Boston loss uses descriptive selection; no unsupported causal claim.",
            "Both Boston cases describe every largest unanswered Boston scoring run.",
            "Defined single-game superlatives tell stories for ALL tied games.",
            "Investigate canonical JB identity relevance; stop semantic closure if it fails.",
            "Use the five approved measure clarification inputs.",
            "Require game anchors for eleven cases and referenced "
            "events/comparison inputs as specified.",
            "Any Knicks point ends a Boston run; canonical order; "
            "quarter breaks/zero-point events do not.",
        ],
        "stages": [
            {"step": 1, "name": "baseline and decision register", "status": "completed"},
            {
                "step": 2,
                "name": "120 expectations / 50 coverage and feasibility",
                "status": "review_completed_source_adjudication_pending",
            },
            {
                "step": 3,
                "name": "supported gold and approved freeze",
                "status": "pending_supported_sources_and_content_bound_approval",
            },
            {
                "step": 4,
                "name": "bounded discovery and guarded orchestration",
                "status": "context_narratives_discovery_implemented_guarded_orchestration_pending",
            },
            {
                "step": 5,
                "name": "120 primary / 120 disabled / distinct 120 shadow",
                "status": "not_admitted",
            },
            {"step": 6, "name": "original load and recovery workloads", "status": "not_admitted"},
            {
                "step": 7,
                "name": "coordinated rollback evidence",
                "status": "dependent_on_verified_runtime",
            },
            {"step": 8, "name": "final bindings / readiness / digest", "status": "blocked"},
        ],
        "semantic_closure": "BLOCKED",
        "semantic_closure_reasons": [
            "43 new target sets still require independent source relevance and current mapping.",
            "All 50 members need release-bound ranked captures and independently verified "
            "current source mappings; local HTTP discovery proof is not a frozen evaluation.",
            "Evaluation gold has no content-bound owner approval or freeze.",
        ],
        "frozen": False,
        "owner_approval": None,
        "paid_admission": {
            "status": "BLOCKED",
            "prior_accounting": provider,
            "fresh_monthly_ledger": None,
            "prior_month_evidence_is_current": False,
            "unknown_reservation_preserved_usd": provider["unknown_reserved_usd"],
            "journal_reset": False,
            "journal_reopened": False,
            "primary_cap": {"requests": 720, "usd": 0.50},
            "shadow_cap": {"requests": "6 * actual fixed selected turns", "usd": 0.50},
            "combined_usd": 1.10,
            "monthly_cutoff_usd": 2,
            "workload_reservations": "Required before evaluation; not yet admitted",
        },
        "runtime_dependencies": (
            "Retained isolated Render profile has no Redis, mock provider, "
            "evidence loop disabled; local-rag omitted."
        ),
        "remote_requests": 0,
        "paid_requests": 0,
        "reservations_created": 0,
        "production_mutations": 0,
        "ranked_receipts_created": 0,
        "affected_prior_proof": (
            "Application context resolution, play-in parsing, tied story selection, measure "
            "clarifications, Boston run computation, local retrieval before clarification "
            "and cancellation cleanup changed. Prior engineering, "
            "evaluation, load and readiness receipts remain historical for their original "
            "source bindings; affected checks require fresh proof. New local HTTP receipts "
            "prove only their stated behavior and do not pass any blocked release gate. "
            "No production configuration or approved corpus changed."
        ),
    }
    return {
        "implementation-register.json": register,
        "expectation-review.json": {
            "status": "canonical_review_pending_source_relevance_and_content_approval",
            "case_count": 120,
            "cases": rows,
            "owner_approval": None,
            "frozen": False,
        },
        "semantic-coverage.json": coverage,
        "identity-incompatibility.json": identity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", default=BUNDLE_SHA256)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        artifacts = audit(args.evidence_root, args.handoff, args.expected_bundle_sha256)
        for name, value in artifacts.items():
            (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        hashes = {name: file_hash(args.output / name) for name in artifacts}
        (args.output / "SHA256SUMS").write_text(
            "".join(f"{value}  {name}\n" for name, value in sorted(hashes.items()))
        )
    except Exception as exc:
        (args.output / "failure.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                    "remote_requests": 0,
                },
                indent=2,
            )
            + "\n"
        )
        raise
    print(
        json.dumps(
            {
                "status": "audit_complete",
                "semantic_closure": "BLOCKED",
                "case_count": 120,
                "semantic_case_count": 50,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
