"""Transport/session micro-probe: fixed tiny output, new connection vs keep-alive.

Run after probe.py; writes ping.jsonl. Each combination is repeated so the connection
setup delta is not confused with output-length variance.

    . /tmp/go.env
    uv run --package knicksiq-api python .../w4-latency/ping.py --out .../ping.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=6)
    args = parser.parse_args()
    keepalive = probe.KeepAlive()
    payloads = {
        "deepseek-v4.1-flash": {
            "system": 'Return exactly the json object {"ok":true} and nothing else.',
            "user": '{"ping":1}',
            "protocol": "chat",
            "model": "deepseek-v4.1-flash",
            "max_tokens": 16,
            "reasoning_effort": "none",
        },
        "gpt-6-luna": {
            "system": 'Return exactly the json object {"ok":true} and nothing else.',
            "user": '{"ping":1}',
            "protocol": "responses",
            "model": "gpt-6-luna",
            "max_tokens": 32,
            "reasoning_effort": "none",
        },
    }
    args.out.write_text("")
    for name, payload in payloads.items():
        path, body, protocol = probe.body_for(payload, name, payload["max_tokens"])
        for transport in ("new", "keep"):
            for _ in range(args.reps):
                row = probe.one(
                    keepalive=keepalive if transport == "keep" else None,
                    path=path,
                    payload=body,
                    model=name,
                    protocol=protocol,
                    session=uuid.uuid4().hex,
                )
                row.update(payload="ping", combo=transport, target=name)
                with args.out.open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
