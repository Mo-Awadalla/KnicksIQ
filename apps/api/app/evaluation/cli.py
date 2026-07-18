"""Run the analyst evaluation set against an API endpoint."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from app.evaluation.harness import EvaluationCase, QueryObservation, evaluate


def _load_cases(path: Path) -> list[EvaluationCase]:
    return [
        EvaluationCase.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _query(base_url: str, case: EvaluationCase, timeout: float) -> tuple[dict[str, Any], float]:
    payload = json.dumps(
        {"question": case.question, "season": "2025-26", "context": list(case.context)}
    ).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/analysis/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read())
    return body, (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-unlabeled",
        action="store_true",
        help="Run candidate questions before archive evidence and facts are reviewed.",
    )
    args = parser.parse_args()
    cases = _load_cases(args.dataset)
    unlabeled = [
        case.id
        for case, raw in zip(
            cases,
            (
                json.loads(line)
                for line in args.dataset.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ),
            strict=True,
        )
        if raw.get("label_status") != "reviewed"
    ]
    if unlabeled and not args.allow_unlabeled:
        raise SystemExit(
            f"{len(unlabeled)} cases are not archive-reviewed; "
            "label them or pass --allow-unlabeled for a dry run"
        )
    observations = []
    for case in cases:
        response, latency_ms = _query(args.base_url, case, args.timeout)
        observations.append(QueryObservation(case, response, latency_ms))
    report = evaluate(observations).as_dict()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
