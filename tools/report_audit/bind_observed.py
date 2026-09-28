"""Compare an already captured production hash inventory; makes no network calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from audit import digest


def bind_observed(baseline, observed):
    release_id = observed["release"]["id"]
    matches = []
    for saved in observed["report_hashes"]:
        candidates = []
        for report in baseline["data"]["reports"]:
            row = dict(report)
            nba_game_id = row.pop("nba_game_id")
            # Match the existing release loader's exact stored-hash representation.
            row.update(game_id=saved["game_id"], release_id=release_id)
            if digest(row) == saved["content_sha256"]:
                candidates.append(nba_game_id)
        matches.append({**saved, "matched_nba_game_ids": candidates})
    matched_ids = [
        row["matched_nba_game_ids"][0] for row in matches if len(row["matched_nba_game_ids"]) == 1
    ]
    inventory_matches = len(matched_ids) == len(matches) and sorted(matched_ids) == sorted(
        r["nba_game_id"] for r in baseline["data"]["reports"]
    )
    report80_id = next(
        (
            row["matched_nba_game_ids"][0]
            for row in matches
            if row["id"] == 80 and len(row["matched_nba_game_ids"]) == 1
        ),
        None,
    )
    report80 = next(
        (r for r in baseline["data"]["reports"] if r["nba_game_id"] == report80_id), None
    )
    fields = ["title", "summary", "turning_point", "best_stretch", "worst_stretch"]
    public_matches = bool(report80) and all(
        observed["report80"][field] == report80[field] for field in fields
    )
    return {
        "status": "partial_binding_only_no_new_production_reads",
        "active_release": observed["release"],
        "baseline_version_matches": observed["release"]["version"]
        == baseline["manifest"]["version"],
        "stored_hash_inventory_matches": inventory_matches,
        "reports": matches,
        "public_report80_narrative_matches": public_matches,
        "fresh_canonical_rows_verified": False,
        "fresh_full_report_rows_verified": False,
        "limitation": (
            "Stored content_sha256 values are ingestion-time metadata, not freshly recomputed "
            "hashes of current rows. This supports baseline identity but cannot prove no "
            "in-place mutation. Only Report 80 public narrative was separately compared. "
            "The complete local report audit is not a fresh production-row audit."
        ),
        "approval": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("observed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before, live = args.baseline.read_bytes(), args.observed.read_bytes()
    result = bind_observed(json.loads(before), json.loads(live))
    result["source_files"] = {
        str(args.baseline): hashlib.sha256(before).hexdigest(),
        str(args.observed): hashlib.sha256(live).hexdigest(),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "stored_hash_inventory_matches",
                    "public_report80_narrative_matches",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
