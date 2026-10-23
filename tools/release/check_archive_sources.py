"""Repeatable, network-denied CLI E2E checks with retained mutation controls."""

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-proof", type=Path)
    parser.add_argument("--comparison-proof-sha256")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "tools/release/verify_archive_sources.py"
    policy = ROOT / "apps/api/app/services/query_resolution.py"
    hashes = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (args.bundle, args.units, policy)
    }
    receipts = []
    bootstrap = (
        "import socket,runpy,sys; from pathlib import Path; "
        "socket.socket=lambda *a,**k: "
        "(_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.argv=sys.argv[1:]; sys.path.insert(0,str(Path(sys.argv[0]).resolve().parent)); "
        "runpy.run_path(sys.argv[0],run_name='__main__')"
    )

    def run(name, destination, *, units=None):
        argv = [
            sys.executable,
            "-c",
            bootstrap,
            str(source),
            "--bundle",
            str(args.bundle),
            "--units",
            str(units or args.units),
            "--alias-policy",
            str(policy),
            "--observations",
            str(args.observations),
            "--output",
            str(destination),
        ]
        if args.comparison_proof:
            argv.extend(
                [
                    "--comparison-proof",
                    str(args.comparison_proof),
                    "--comparison-proof-sha256",
                    args.comparison_proof_sha256,
                ]
            )
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        receipts.append(
            {
                "name": name,
                "argv": argv,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        return result

    status = "failed"
    try:
        first, repeat = args.output / "first", args.output / "repeat"
        assert run("full independent source verification", first).returncode == 0
        assert run("exact repeat", repeat).returncode == 0
        outputs = sorted(p.name for p in first.iterdir() if p.is_file())
        assert all((first / p).read_bytes() == (repeat / p).read_bytes() for p in outputs)
        result = json.loads((first / "source-verification.json").read_text())
        if args.comparison_proof:
            data = json.loads(gzip.decompress(args.bundle.read_bytes()))["data"]
            margins = {}
            for game in data["games"]:
                margin = abs(game["home_score"] - game["away_score"])
                margins[margin] = margins.get(margin, 0) + 1
            assert result["source_units"] == 49 + 12 + len(data["games"]) + sum(
                n > 1 for n in margins.values()
            )
            assert result["comparison_units"] == 12
            assert result["game_story_units"] == len(data["games"])
        else:
            assert result["source_units"] == 49
        assert result["opponent_units"] == 29 and result["identity_units"] == 20
        assert result["semantic_relevance_approved"] is False and result["gold_frozen"] is False
        assert result["actual_ranked_unit_receipts"] >= 2
        before = (first / "source-verification.json").read_bytes()
        assert run("refuse overwrite", first).returncode != 0
        assert (first / "source-verification.json").read_bytes() == before
        units = [json.loads(s) for s in args.units.read_text().splitlines()]
        observed_sources = {
            receipt["metadata"].get("source_document_id")
            for path in args.observations.glob("*.json")
            for search in json.loads(path.read_text()).get("capture", {}).get("searches", [])
            for receipt in search["evidence"]
        }
        for name in (
            "wrong-score",
            "inflated-sources",
            "extra-alias",
            "missing-unit",
            "duplicate-unit",
            "unsupported-text",
            "unknown-source-field",
        ):
            altered = json.loads(json.dumps(units))
            aggregate = next(
                r for r in altered if r["payload"].get("aggregate_kind") == "opponent_results"
            )
            # Use an unobserved identity so rejection must come from independent
            # fact verification, rather than a changed retrieval receipt ID.
            identity = next(
                r
                for r in altered
                if r["payload"]["unit_type"] == "player_identity"
                and r["id"] not in observed_sources
            )
            if name == "wrong-score":
                aggregate["payload"]["canonical_rows"][0]["home_score"] += 1
            elif name == "inflated-sources":
                aggregate["payload"]["canonical_sources"].append("game:9999999999")
            elif name == "extra-alias":
                identity["payload"]["aliases"].append("unsupported-alias")
            elif name == "missing-unit":
                altered.pop()
            elif name == "duplicate-unit":
                altered.append(altered[0])
            elif name == "unsupported-text":
                identity["payload"]["text"] += " An unsupported performance claim."
                identity["payload"]["semantic_summary"] = identity["payload"]["text"]
            else:
                identity["payload"]["unsupported_claim"] = "An unsupported performance claim."
            # Re-sign changed payloads so these exercise independent factual
            # checks rather than failing only their outer content digest.
            if name not in {"missing-unit", "duplicate-unit"}:
                for record in altered:
                    content = {
                        k: v for k, v in record["payload"].items() if k != "source_document_id"
                    }
                    identity = (
                        "archive-unit:"
                        + hashlib.sha256(
                            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                    )
                    record["id"] = identity
                    record["payload"]["source_document_id"] = identity
            changed = args.output / f"{name}.jsonl"
            changed.write_text("".join(json.dumps(r) + "\n" for r in altered))
            destination = args.output / name
            assert run(name, destination, units=changed).returncode != 0
            assert (destination / "failure.json").exists()
            assert not (destination / "source-verification.json").exists()
        if args.comparison_proof:
            for name in (
                "wrong-measure",
                "missing-comparison-game",
                "inflated-comparison-sources",
                "wrong-witness",
                "omitted-physical-witness",
                "representative-comparison-id",
                "wrong-provenance",
                "wrong-single-game-id",
                "missing-measure-unit",
                "wrong-story-score",
                "missing-story-game",
                "unsupported-comparison-text",
            ):
                altered = json.loads(json.dumps(units))
                comparison = next(
                    r
                    for r in altered
                    if r["payload"].get("aggregate_kind") == "measure_comparison"
                    and r["payload"]["measure_family"] == "deficit"
                )
                single = next(
                    r for r in altered if r["payload"]["unit_type"] == "game_scoring_comparison"
                )
                story = next(
                    r
                    for r in altered
                    if r["payload"].get("aggregate_kind") == "selected_game_stories"
                )
                payload = comparison["payload"]
                if name == "wrong-measure":
                    payload["comparison_rows"][0]["measures"]["largest_observed_deficit"][
                        "value"
                    ] = 999
                elif name == "missing-comparison-game":
                    payload["comparison_rows"].pop()
                elif name == "inflated-comparison-sources":
                    payload["canonical_sources"].append(
                        "game:" + payload["comparison_rows"][0]["nba_game_id"]
                    )
                elif name == "wrong-witness":
                    next(iter(payload["witness_events"].values()))["points"] = 9
                elif name == "omitted-physical-witness":
                    body = json.loads(payload["text"].split("\n", 1)[1])
                    body["witness_events"] = {}
                    payload["text"] = (
                        payload["text"].split("\n", 1)[0]
                        + "\n"
                        + json.dumps(body, sort_keys=True, separators=(",", ":"))
                    )
                    payload["semantic_summary"] = payload["text"]
                elif name == "representative-comparison-id":
                    payload["game_id"] = payload["game_ids"][0]
                elif name == "wrong-provenance":
                    payload["provenance"]["comparison_sha256"] = "0" * 64
                elif name == "wrong-single-game-id":
                    single["payload"]["game_id"] = 999999
                elif name == "missing-measure-unit":
                    altered.remove(comparison)
                elif name == "wrong-story-score":
                    story["payload"]["story_rows"][0]["home_score"] += 1
                elif name == "missing-story-game":
                    story["payload"]["story_rows"].pop()
                else:
                    payload["text"] += " Unsupported cause: the opponent gave up."
                    payload["semantic_summary"] = payload["text"]
                for record in altered:
                    content = {
                        k: v for k, v in record["payload"].items() if k != "source_document_id"
                    }
                    record["id"] = (
                        "archive-unit:"
                        + hashlib.sha256(
                            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                    )
                    record["payload"]["source_document_id"] = record["id"]
                changed = args.output / f"{name}.jsonl"
                changed.write_text("".join(json.dumps(r) + "\n" for r in altered))
                destination = args.output / name
                assert run(name, destination, units=changed).returncode != 0
                assert (destination / "failure.json").exists()
                assert (
                    json.loads((destination / "failure.json").read_text())["error_type"]
                    == "ValueError"
                )
                assert not (destination / "source-verification.json").exists()
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        status = "passed"
    finally:
        with (args.output / "e2e-result.json").open("x") as artifact:
            json.dump(
                {
                    "status": status,
                    "input_sha256": hashes,
                    "receipts": receipts,
                    "remote_requests": 0,
                },
                artifact,
                indent=2,
            )
    print(status)


if __name__ == "__main__":
    main()
