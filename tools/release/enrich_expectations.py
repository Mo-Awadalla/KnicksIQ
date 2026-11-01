"""Enrich proposed evaluation expectations with canonical subject identity.

Writes a new proposal beside the pinned evidence: team and scoreline facts gain
``subject`` ``team:NYK`` and leader facts gain ``player_name``, each only when
the approved archive rows reproduce it. Values, scopes, evidence ids,
dispositions, approval and freeze fields are preserved byte for byte --
stripping the added fields and re-serialising reproduces the input file exactly
-- and the input review and the original question file are never written. No
owner approval, freeze or semantic target is manufactured.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from expectation_subject import (
    RESOLVERS,
    Archive,
    EnrichmentError,
    RecipeError,
    classify,
    digest,
    metric_key,
)

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/release-evidence/reconciliation-20260928/expectation-review.json"
BUNDLE = ROOT / "release-artifacts/2025-26/reliability-approved-20260928.json.gz"
BUNDLE_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
LABELS = ROOT / "docs/release-evidence/evaluation-label-review-20260907/labels.jsonl"
VOCABULARY = ROOT / "apps/api/app/evaluation/assertion_vocabulary.py"
OUTPUT = ROOT / "release-artifacts/production-completion-20261030"

PROPOSED_NAME = "expectation-review-proposed.json"
REPORT_NAME = "subject-review-report.json"


def relative(path):
    """A portable reference; never an absolute local path."""
    raw = Path(path)
    for candidate in (raw.absolute(), raw.resolve()):
        try:
            return candidate.relative_to(ROOT).as_posix()
        except ValueError:
            continue
    return raw.name


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rendered(document):
    """The repository's pretty-printed document form, byte for byte."""
    return json.dumps(document, indent=2) + "\n"


def counted(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def enrich(review, archive):
    """Add the missing identity fields and record every decision they rest on."""
    proposal = json.loads(json.dumps(review))
    changes, unresolved, observations, families = [], [], [], {}
    for case_index, case in enumerate(proposal["cases"]):
        facts = case["proposed_expectation"]["canonical_facts"]
        for index, fact in enumerate(facts):
            if fact.get("subject"):
                raise EnrichmentError(f"{case['id']} fact {index} already declares a subject")
            family = classify(fact)
            stats = families.setdefault(family, {"facts": 0, "changed": 0, "verified": 0})
            stats["facts"] += 1
            try:
                added, check = RESOLVERS[family](archive, fact)
            except (RecipeError, EnrichmentError) as error:
                unresolved.append(
                    {
                        "case_id": case["id"],
                        "fact_index": index,
                        "metric": fact["metric"],
                        "scope": fact["scope"],
                        "family": family,
                        "reason": str(error),
                    }
                )
                continue
            stats["verified"] += 1
            if added:
                fact.update(added)
                stats["changed"] += 1
                changes.append(
                    {
                        "case_id": case["id"],
                        "case_index": case_index,
                        "fact_index": index,
                        "metric": fact["metric"],
                        "added": added,
                        "check": check,
                    }
                )
            elif check.get("value_check", "matched") != "matched":
                observations.append(
                    {
                        "case_id": case["id"],
                        "fact_index": index,
                        "metric": fact["metric"],
                        "value_check": check["value_check"],
                    }
                )
    return proposal, changes, unresolved, observations, families


def stripped(document, changes):
    """The proposal with exactly the identity fields this run added removed."""
    copy = json.loads(json.dumps(document))
    for change in changes:
        fact = copy["cases"][change["case_index"]]["proposed_expectation"]["canonical_facts"][
            change["fact_index"]
        ]
        for field in change["added"]:
            del fact[field]
    return copy


def preservation(review_bytes, review, proposal, changes):
    """Refuse any change other than the added identity fields."""
    if rendered(stripped(proposal, changes)) != review_bytes.decode():
        raise EnrichmentError("the proposal changes more than the added identity fields")
    cases = proposal["cases"]
    facts = [fact for case in cases for fact in case["proposed_expectation"]["canonical_facts"]]
    semantic = [case for case in cases if case.get("original_semantic_member")]
    if proposal.get("owner_approval") is not None or proposal.get("frozen") is not False:
        raise EnrichmentError("the review being enriched is no longer an unapproved draft")
    if any(case.get("owner_approved") for case in cases):
        raise EnrichmentError("the review being enriched already carries an owner approval")
    preserved = {
        "case_count": len(cases),
        "semantic_case_count": len(semantic),
        "semantic_targets": counted(
            "declared" if case.get("semantic_targets") is not None else "empty" for case in cases
        ),
        "proposed_dispositions": counted(
            case["proposed_expectation"]["disposition"] for case in cases
        ),
        "cases_owner_approved_false": sum(
            1 for case in cases if case.get("owner_approved") is False
        ),
        "owner_approval": proposal.get("owner_approval"),
        "frozen": proposal.get("frozen"),
        "facts": len(facts),
        "added_fields": sorted({field for change in changes for field in change["added"]}),
        "stripped_proposal_equals_input": True,
        "reserialised_input_matches_original_bytes": True,
    }
    declared = {
        "case_count": review.get("case_count"),
        "semantic_case_count": review.get("semantic_case_count"),
        "proposed_dispositions": review.get("proposed_dispositions"),
    }
    for key, value in declared.items():
        if value is not None and preserved[key] != value:
            raise EnrichmentError(f"{key} changed: {preserved[key]!r} against {value!r}")
    return preserved


def expressible_metrics(path):
    """Label metrics the assertion vocabulary can express, read without importing it."""
    path = Path(path)
    if not path.exists():
        return None
    tree = ast.parse(path.read_text())
    metrics = set()
    for node in tree.body:
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
        name = next(
            (target.id for target in targets if isinstance(target, ast.Name)),
            None,
        )
        value = getattr(node, "value", None)
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        if name == "METRIC_ALIASES" and isinstance(value, ast.Dict):
            metrics.update(str(key.value) for key in value.keys if isinstance(key, ast.Constant))
        if name == "DICT_METRICS" and isinstance(value, (ast.Set, ast.Tuple, ast.List)):
            metrics.update(str(item.value) for item in value.elts if isinstance(item, ast.Constant))
    if not metrics:
        raise EnrichmentError(f"{path} declares no metric vocabulary")
    return metrics


CRITERIA = [
    "A team fact keeps subject team:NYK only when its typed value reproduces from the "
    "archive rows the fact itself names as a Knicks-side aggregate.",
    "A player fact keeps its declared portable player_name; no local SQL identifier is "
    "written into a golden label, and the runtime resolves the name through the mapping.",
    "A leader fact takes player_name from its explicit value object only when one "
    "canonical player wins outright and the total reproduces; the value object is kept.",
    "A scoreline fact takes subject team:NYK because the runtime scoreline claim carries "
    "that subject; its value must equal the archive game row exactly.",
    "No owner approval, freeze, disposition or semantic target is created here; the "
    "proposal is ineligible until the owner adjudicates it.",
]


LIMITATIONS = [
    "The verified labels.jsonl input is packaged beside the proposal so its recorded "
    "labels_sha256 can be reproduced without a path-dependent search.",
    "Every added field is one the production CanonicalFact already parses; no value "
    "object, scope, evidence id, disposition or approval field was rewritten.",
]


def not_expressible(metrics, facts):
    if metrics is None:
        return None
    grouped = {}
    for case_id, fact in facts:
        key = metric_key(fact["metric"])
        if key in metrics:
            continue
        entry = grouped.setdefault(key, {"metric": key, "facts": 0, "case_ids": []})
        entry["facts"] += 1
        if case_id not in entry["case_ids"]:
            entry["case_ids"].append(case_id)
    return [grouped[key] for key in sorted(grouped)]


def build_report(context):
    review, proposal = context["review"], context["proposal"]
    changes, unresolved = context["changes"], context["unresolved"]
    facts = [
        (case["id"], fact)
        for case in proposal["cases"]
        for fact in case["proposed_expectation"]["canonical_facts"]
    ]
    return {
        "schema_version": 1,
        "kind": "expectation_subject_identity_review",
        "status": "proposal_pending_owner_adjudication",
        "generated_by": "tools/release/enrich_expectations.py",
        "invocation": context["invocation"],
        "environment": context["environment"],
        "binding": {
            "review_file": context["references"]["review"],
            "review_sha256": context["hashes"]["review"],
            "review_content_sha256": digest(review),
            "bundle_file": context["references"]["bundle"],
            "bundle_sha256": context["bundle_sha256"],
            "bundle_sha256_expected": context["bundle_sha256_expected"],
            "bundle_version": context["archive"].manifest.get("version"),
            "bundle_data_sha256": context["archive"].data_sha256,
            "bundle_manifest_content_sha256": context["archive"].manifest.get("content_sha256"),
            "labels_file": context["references"]["labels"],
            "labels_sha256": context["hashes"]["labels"],
            "labels_sha256_expected": review.get("labels_sha256"),
            "proposed_file": context["references"]["proposed"],
            "proposed_sha256": context["hashes"]["proposed"],
            "proposal_content_sha256": digest(proposal),
            "stripped_proposal_content_sha256": digest(stripped(proposal, changes)),
            "field_changes_sha256": digest(changes),
            "unresolved_sha256": digest(unresolved),
        },
        "proposal": {
            "status": "pending_owner_adjudication",
            "eligible_for_gold_labels": False,
            "requires_owner_adjudication": True,
            "owner_approved": 0,
            "owner_approval": None,
            "frozen": False,
            "semantic_targets_decided": 0,
            "evaluator_assertion_code_changed": False,
            "original_review_rewritten": False,
            "original_questions_rewritten": False,
        },
        "preserved": context["preserved"],
        "enrichment": {
            "facts_total": len(facts),
            "facts_changed": len(changes),
            "facts_verified_unchanged": len(facts) - len(changes),
            "facts_unresolved": len(unresolved),
            "families": context["families"],
        },
        "resolutions": {
            "team_subject": "team:NYK on Knicks aggregates whose value reproduces",
            "player_identity": "declared player_name confirmed against the roster and rows",
            "leader_identity": "unique canonical leader name extracted from the value object",
            "game_subject": "team:NYK on scorelines per the runtime claim contract",
        },
        "changes": changes,
        "unresolved": unresolved,
        "observations": context["observations"],
        "unexpressible_metrics": not_expressible(context["expressible"], facts),
        "criteria": CRITERIA,
        "limitations": LIMITATIONS,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--bundle-sha256", default=BUNDLE_SHA256)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--vocabulary", type=Path, default=VOCABULARY)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    bundle_raw = args.bundle.read_bytes()
    bundle_sha256 = hashlib.sha256(bundle_raw).hexdigest()
    if bundle_sha256 != args.bundle_sha256:
        raise SystemExit(
            f"bundle sha256 {bundle_sha256} does not match {args.bundle_sha256}; refusing"
        )
    labels_raw = args.labels.read_bytes()
    labels_sha256 = hashlib.sha256(labels_raw).hexdigest()
    review_bytes = args.review.read_bytes()
    review = json.loads(review_bytes)
    if labels_sha256 != review.get("labels_sha256"):
        raise SystemExit(
            f"labels sha256 {labels_sha256} does not match the review's "
            f"{review.get('labels_sha256')}"
        )
    archive = Archive(json.loads(gzip.decompress(bundle_raw)))
    if archive.data_sha256 != archive.manifest.get("content_sha256"):
        raise SystemExit("bundle data does not match its manifest content digest")
    proposal, changes, unresolved, observations, families = enrich(review, archive)
    preserved = preservation(review_bytes, review, proposal, changes)
    expressible = expressible_metrics(args.vocabulary)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    labels_snapshot = args.output_dir / "labels.jsonl"
    if labels_snapshot.exists() and labels_snapshot.read_bytes() != labels_raw:
        raise SystemExit("output directory already holds a different labels.jsonl")
    if not labels_snapshot.exists():
        labels_snapshot.write_bytes(labels_raw)
    proposed_path = args.output_dir / PROPOSED_NAME
    proposed_path.write_text(rendered(proposal))
    document = build_report(
        {
            "review": review,
            "proposal": proposal,
            "changes": changes,
            "unresolved": unresolved,
            "observations": observations,
            "families": families,
            "preserved": preserved,
            "archive": archive,
            "expressible": expressible,
            "invocation": ["python", relative(Path(__file__))]
            + list(sys.argv[1:] if argv is None else argv),
            "environment": {
                "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
                "interpreter": relative(sys.executable),
            },
            "references": {
                "review": relative(args.review),
                "bundle": relative(args.bundle),
                "labels": relative(args.labels),
                "proposed": relative(proposed_path),
            },
            "hashes": {
                "review": file_sha256(args.review),
                "labels": labels_sha256,
                "proposed": file_sha256(proposed_path),
            },
            "bundle_sha256": bundle_sha256,
            "bundle_sha256_expected": args.bundle_sha256,
        }
    )
    report_path = args.output_dir / REPORT_NAME
    report_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "proposed": str(proposed_path),
                "report": str(report_path),
                "facts_changed": len(changes),
                "facts_unresolved": len(unresolved),
                "preserved": preserved,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
