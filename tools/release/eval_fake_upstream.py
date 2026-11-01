"""A loopback OpenAI-compatible wire for proving the approved run's boundary.

An approval may bind a loopback provider origin, which makes the run a local
fake: the driver, the guard, the ledger, the collector and the scorer all execute
for real, every attempt is counted, and the resulting report is blocked as
non-quality evidence. Nothing here answers a question; the returned content is an
empty object, so the analyst loop degrades exactly as it would against a provider
that returned nothing usable.

Run: python tools/release/eval_fake_upstream.py --port 8791 --hits /tmp/hits.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CONTENT = "{}"


class FakeUpstream(BaseHTTPRequestHandler):
    status = 200
    delay = 0.0
    hits_path: Path | None = None
    lock = threading.Lock()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        with self.lock:
            self.server.count += 1  # type: ignore[attr-defined]
            if self.hits_path is not None:
                line = json.dumps(
                    {
                        "path": self.path,
                        "body_sha256": hashlib.sha256(body).hexdigest(),
                        "at": time.time(),
                    },
                    sort_keys=True,
                )
                with self.hits_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        if self.delay:
            time.sleep(self.delay)
        payload = (
            {
                "id": "fake-completion",
                "model": "local-fake",
                "choices": [{"message": {"content": CONTENT, "role": "assistant"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0},
            }
            if self.status == 200
            else {"error": {"message": "fake upstream failure"}}
        )
        encoded = json.dumps(payload).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: Any) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--status", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--hits", type=Path)
    args = parser.parse_args(argv)

    handler = type(
        "BoundFakeUpstream",
        (FakeUpstream,),
        {"status": args.status, "delay": args.delay, "hits_path": args.hits},
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.count = 0  # type: ignore[attr-defined]
    print(
        json.dumps(
            {
                "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                "scope": "local_fake",
                "status": args.status,
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print(json.dumps({"hits": server.count}), file=sys.stderr, flush=True)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
