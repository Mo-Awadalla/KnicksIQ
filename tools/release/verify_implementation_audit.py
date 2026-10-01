"""E2E specification for the offline implementation audit, written before it.

Runs the CLI in a separate interpreter with all socket creation denied, against
the actual retained release. Writes repeatable artifacts and negative controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipts = []
    environment = {**os.environ, "AI_API_KEY": "", "OPENROUTER_API_KEY": "", "REDIS_URL": ""}
    command = ROOT / "tools/release/implementation_audit.py"
    # Block network even if the implementation accidentally gains a network path.
    bootstrap = (
        "import socket,runpy,sys; "
        "socket.socket=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network forbidden')); "
        "sys.path.insert(0,str(__import__('pathlib').Path(sys.argv[1]).parent)); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )

    def run(name: str, output: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
        argv = [
            sys.executable,
            "-c",
            bootstrap,
            str(command),
            "--evidence-root",
            str(args.evidence_root),
            "--handoff",
            str(args.handoff),
            "--output",
            str(output),
            *(extra or []),
        ]
        result = subprocess.run(argv, env=environment, text=True, capture_output=True, timeout=60)
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
        first, second = args.output / "first", args.output / "repeat"
        assert run("complete retained package", first).returncode == 0
        assert run("repeat into fresh destination", second).returncode == 0
        first_files = sorted(p.name for p in first.iterdir() if p.is_file())
        assert first_files == sorted(p.name for p in second.iterdir() if p.is_file())
        assert all(
            (first / name).read_bytes() == (second / name).read_bytes() for name in first_files
        )
        register = json.loads((first / "implementation-register.json").read_text())
        assert register["case_count"] == 120 and register["semantic_case_count"] == 50
        assert register["semantic_closure"] == "BLOCKED"
        assert register["owner_approval"] is None and register["frozen"] is False
        assert register["remote_requests"] == 0 and register["paid_requests"] == 0
        assert register["baseline_integrity"]["verified_checksum_files"] == 485
        cases = {
            r["id"]: r for r in json.loads((first / "expectation-review.json").read_text())["cases"]
        }
        assert len(cases) == 120
        assert cases["single_game_narrative-006"]["disposition"] == "answer"
        assert len(cases["single_game_narrative-006"]["selected_canonical_games"]) == 6
        for name in ("single_game_narrative-020", "turning_points-006"):
            assert cases[name]["disposition"] == "answer"
            runs = cases[name]["boston_unanswered_runs"]
            assert [(r["points"], r["start_sequence"], r["end_sequence"]) for r in runs] == [
                (12, 128, 146),
                (12, 282, 299),
            ]
        dossier = json.loads((first / "identity-incompatibility.json").read_text())
        assert dossier["canonical_player"]["nba_player_id"] == 1628973
        assert dossier["canonical_player"]["full_name"] == "Jalen Brunson"
        assert dossier["game_anchor"] is None and dossier["semantic_targets"] == []
        coverage = json.loads((first / "semantic-coverage.json").read_text())["cases"]
        assert len(coverage) == 50
        atl = next(c for c in coverage if c["id"] == "aliases_typos-006")
        assert len(atl["settled_targets"]) == 9 and atl["settled_targets_preserved"]
        assert not any(c["actual_ranked_capture"] for c in coverage)
        before = (first / "implementation-register.json").read_bytes()
        assert run("refuse overwrite", first).returncode != 0
        assert (first / "implementation-register.json").read_bytes() == before
        wrong = args.output / "wrong-bundle"
        assert (
            run(
                "reject changed bundle binding", wrong, ["--expected-bundle-sha256", "0" * 64]
            ).returncode
            != 0
        )
        assert json.loads((wrong / "failure.json").read_text())["status"] == "failed"
        assert not (wrong / "expectation-review.json").exists()
        wrong_root = args.output / "wrong-root"
        assert (
            run(
                "reject missing baseline", wrong_root, ["--evidence-root", str(args.output)]
            ).returncode
            != 0
        )
        assert (wrong_root / "failure.json").exists()
        status = "passed"
    finally:
        result = {
            "status": status,
            "scope": "offline CLI E2E; not release-quality evidence",
            "socket_creation_denied": True,
            "receipts": receipts,
            "artifacts": {
                str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(args.output.rglob("*"))
                if p.is_file()
            },
        }
        (args.output / "e2e-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(status)


if __name__ == "__main__":
    main()
