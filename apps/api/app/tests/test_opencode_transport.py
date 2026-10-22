"""Real HTTP transport checks for mixed Chat Completions and Responses models."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.services.report_llm import OpenAICompatibleLLMAdapter


@pytest.fixture
def provider_http():
    observed = []
    replies = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(
                {
                    "path": self.path,
                    "body": body,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                }
            )
            payload = json.dumps(replies.pop(0)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", observed, replies
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


async def test_mixed_protocol_models_normalize_usage_and_send_session(provider_http):
    url, observed, replies = provider_http
    adapter = OpenAICompatibleLLMAdapter(
        base_url=url,
        api_key="synthetic-local-provider",
        model="writer",
        reasoning_effort="none",
        model_protocols={"reviewer": "responses"},
        model_prices={"writer": [1, 2], "reviewer": [3, 4]},
    )
    replies.append(
        {
            "model": "writer",
            "choices": [{"message": {"content": '{"answer":"writer"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    )
    assert json.loads(await adapter.generate(system="system", user="user")) == {"answer": "writer"}
    assert observed[0]["path"] == "/v1/chat/completions"
    assert observed[0]["body"]["reasoning_effort"] == "none"
    assert adapter.last_metadata["usage"]["cost"] == pytest.approx(0.0002)
    adapter.model = "reviewer"
    replies.append(
        {
            "model": "reviewer",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"answer":"reviewed"}'}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
    )
    assert json.loads(await adapter.generate(system="system", user="user")) == {
        "answer": "reviewed"
    }
    assert observed[1]["path"] == "/v1/responses"
    assert observed[1]["body"]["reasoning"] == {"effort": "none"}
    assert adapter.last_metadata["usage"]["prompt_tokens"] == 100
    assert adapter.last_metadata["usage"]["cost"] == pytest.approx(0.0005)
    assert (
        observed[0]["headers"]["x-opencode-session"] == observed[1]["headers"]["x-opencode-session"]
    )
    assert observed[0]["headers"]["x-opencode-session"]


async def test_incomplete_responses_retains_cost_but_rejects_output(provider_http):
    url, _observed, replies = provider_http
    adapter = OpenAICompatibleLLMAdapter(
        base_url=url,
        api_key="synthetic-local-provider",
        model="reviewer",
        model_protocols={"reviewer": "responses"},
        model_prices={"reviewer": [3, 4]},
    )
    replies.append(
        {
            "model": "reviewer",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"answer":"partial"}'}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
    )
    with pytest.raises(RuntimeError):
        await adapter.generate(system="system", user="user")
    assert adapter.last_metadata["usage"]["cost"] == pytest.approx(0.0005)
