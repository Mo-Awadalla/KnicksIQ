"""Repeatable, network-denied CLI E2E checks with retained mutation controls."""

import argparse
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
        "import socket,runpy,sys; "
        "socket.socket=lambda *a,**k: "
        "(_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
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
                r for r in altered if r["payload"]["unit_type"] == "multigame_aggregate"
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
