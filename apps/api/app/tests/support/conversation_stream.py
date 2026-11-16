"""Loopback-only upstream for real-HTTP conversation proofs.

A plan is an ordered list of calls. Each call has SSE packets or named gates.
Failures covered by the caller include unexpected extra calls, an unreleased
completion gate, split UTF-8 and frames, malformed packets, missing usage,
truncation, and cancellation while the provider is still writing. This fixture
never supplies a production fallback or evidence of real-model quality.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StreamingUpstream:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.gates: dict[str, threading.Event] = {}
        self.active = 0

    def plan(self, calls: list[dict[str, Any]]) -> None:
        with self.lock:
            if self.active:
                raise ValueError("Release active calls before replacing the plan")
            self.calls = calls
            self.requests = []
            self.gates = {
                step["gate"]: threading.Event()
                for call in calls
                for step in call.get("steps", [])
                if "gate" in step
            }

    def claim(self, request: dict[str, Any]) -> dict[str, Any] | None:
        with self.lock:
            index = len(self.requests)
            self.requests.append(request)
            if index >= len(self.calls):
                return None
            self.active += 1
            return self.calls[index]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "requests": list(self.requests),
                "active": self.active,
                "gates": {name: gate.is_set() for name, gate in self.gates.items()},
            }

    def handler(self) -> type[BaseHTTPRequestHandler]:
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                pass

            def respond(self, status: int, body: object) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()

            def read_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 262_144:
                    raise ValueError("Bounded JSON request required")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                return body

            def do_GET(self) -> None:
                if self.path == "/__control__/state":
                    self.respond(200, upstream.snapshot())
                else:
                    self.respond(404, {"error": "Unknown fixture path"})

            def do_POST(self) -> None:
                try:
                    body = self.read_body()
                    if self.path == "/__control__/plan":
                        calls = body.get("calls")
                        if not isinstance(calls, list) or len(calls) > 32:
                            raise ValueError("A bounded calls list is required")
                        upstream.plan(calls)
                        self.respond(200, {"planned": len(calls)})
                    elif self.path == "/__control__/release":
                        name = body.get("gate")
                        if not isinstance(name, str) or name not in upstream.gates:
                            raise ValueError("Unknown gate")
                        gate = upstream.gates[name]
                        gate.set()
                        self.respond(200, {"released": body["gate"]})
                    elif self.path == "/v1/chat/completions":
                        self.stream(body)
                    else:
                        self.respond(404, {"error": "Unknown fixture path"})
                except (ValueError, KeyError, TypeError) as error:
                    self.respond(400, {"error": str(error)})

            def stream(self, body: dict[str, Any]) -> None:
                call = upstream.claim(body)
                if call is None:
                    self.respond(503, {"error": "Unexpected upstream call"})
                    return
                try:
                    status = call.get("status", 200)
                    if status != 200:
                        self.respond(status, {"error": "Scripted upstream failure"})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for step in call.get("steps", []):
                        if "gate" in step:
                            if not upstream.gates[step["gate"]].wait(timeout=45):
                                return
                            continue
                        if "lookup_refs" in step:
                            facts = []
                            for message in body.get("messages", []):
                                if message.get("role") != "tool":
                                    continue
                                try:
                                    result = json.loads(message.get("content", ""))
                                except (ValueError, TypeError):
                                    continue
                                if result.get("status") == "found":
                                    facts.extend(result.get("facts", []))
                            if not facts:
                                raise ValueError("No found lookup facts in upstream request")
                            refs = " ".join(f"[[{fact['ref']}]]" for fact in facts)
                            data = {
                                "choices": [
                                    {"index": 0, "delta": {"content": refs}, "finish_reason": None}
                                ]
                            }
                            payload = f"data: {json.dumps(data)}\n\n".encode()
                        elif "raw" in step:
                            payload = step["raw"].encode()
                        else:
                            data = step["data"]
                            value = (
                                data
                                if isinstance(data, str)
                                else json.dumps(data, ensure_ascii=False)
                            )
                            payload = f"data: {value}\n\n".encode()
                        size = step.get("fragment_bytes", len(payload))
                        if not isinstance(size, int) or size < 1:
                            raise ValueError("Positive fragment size required")
                        for offset in range(0, len(payload), size):
                            fragment = payload[offset : offset + size]
                            self.wfile.write(f"{len(fragment):x}\r\n".encode())
                            self.wfile.write(fragment + b"\r\n")
                            self.wfile.flush()
                    if not call.get("truncate"):
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    self.close_connection = True
                    with upstream.lock:
                        upstream.active -= 1

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    upstream = StreamingUpstream()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), upstream.handler())
    print(f"Conversation upstream ready on {args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        for gate in upstream.gates.values():
            gate.set()
        server.server_close()


if __name__ == "__main__":
    main()
