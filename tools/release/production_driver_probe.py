"""Fake docker/uv/pnpm toolchain and the process harness the driver probes share.

The fake binaries record daemon state, child environments and argv into a throwaway
state directory, so a probe asserts on what the real driver did without a real
Docker daemon. ``Probe`` owns that directory, the throwaway unix sockets and the
driver subprocess, and cleans all of it up. Nothing here contacts a remote host and
no global Docker context is written.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools/release/production_e2e.py"
PYTHON = sys.executable

FAKE_BIN = """#!SHEBANG
import json, os, signal, subprocess, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "DOCKER_HOST", "DOCKER_CONTEXT")
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["FAKE_CHILD_ENV"], "a") as log:
    log.write(json.dumps({"tool": tool, "argv": args,
                          "env": {k: os.environ.get(k) for k in KEYS}}) + "\\n")

def serve(port, hits):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if hits:
                with open(hits, "a") as log:
                    log.write(self.path + "\\n")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if tool == "web-server":
    serve(int(args[0]), None)
if tool == "uv":
    if "uvicorn" in args:
        if os.environ.get("FAKE_API_MODE", "serve") == "exit":
            sys.exit(int(os.environ.get("FAKE_API_EXIT_CODE", "3")))
        Path(os.environ["FAKE_API_PID"]).write_text(str(os.getpid()))
        serve(int(args[args.index("--port") + 1]), os.environ["FAKE_API_HITS"])
    sys.exit(0)
if tool != "docker":
    sys.exit(0)

state_path = Path(os.environ["FAKE_DOCKER_STATE"])
try:
    state = json.loads(state_path.read_text())
except (OSError, ValueError):
    state = {"containers": {}}
containers = state.setdefault("containers", {})
command = args[0] if args else ""
if command == "context":
    show = len(args) > 1 and args[1] == "show"
    print(os.environ.get("FAKE_DOCKER_CONTEXT_NAME", "desktop-local") if show else
          json.dumps(os.environ.get("FAKE_DOCKER_CONTEXT_ENDPOINT", "unix:///tmp/fake.sock")))
    sys.exit(0)
if command == "run":
    name = args[args.index("--name") + 1]
    pid = None
    if "-p" in args and args[-1].startswith("nginx"):
        port = args[args.index("-p") + 1].split(":")[-2]
        pid = subprocess.Popen([sys.executable, os.environ["FAKE_WEB_SERVER"], port],
                               start_new_session=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL).pid
    containers[name] = pid
elif command == "exec":
    sys.exit(int(os.environ.get("FAKE_PG_READY", "0")) if "pg_isready" in args else 0)
elif command == "inspect":
    if args[-1] in containers:
        print("true")
        sys.exit(0)
    sys.stderr.write("Error: No such object: " + args[-1] + "\\n")
    sys.exit(1)
elif command == "stop":
    name = args[-1]
    if name in containers:
        fail_suffixes = os.environ.get("FAKE_DOCKER_STOP_FAIL_SUFFIX", "").split(",")
        if any(name.endswith(suffix) for suffix in fail_suffixes if suffix):
            sys.stderr.write("Error: simulated stop failure\\n")
            sys.exit(1)
        pid = containers.pop(name)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
state_path.write_text(json.dumps(state))
sys.exit(0)
"""

SCRUBBED = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "NODE_TLS_REJECT_UNAUTHORIZED",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
}
MUTATIONS = {"run", "exec", "stop", "inspect"}


def check(problems: list[str], condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def install(path: Path, template: str) -> None:
    path.write_text(template.replace("#!SHEBANG", f"#!{PYTHON}", 1))
    path.chmod(0o755)


def free_port(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def terminate(pid) -> None:
    if not pid:
        return
    for kill in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
        try:
            kill()
            return
        except (ProcessLookupError, PermissionError):
            pass


class Probe:
    def __init__(self, name: str, root: Path) -> None:
        self.root = root
        self.bin, self.state, self.out = root / "bin", root / "state", root / "out"
        self.bin.mkdir(parents=True)
        self.state.mkdir()
        for tool in ("docker", "uv", "pnpm"):
            install(self.bin / tool, FAKE_BIN)
        install(root / "web-server", FAKE_BIN)
        self.sockets = []
        self.servers = []
        self.driver = None
        self.sockets_dir = Path(tempfile.mkdtemp(prefix="kd-"))

    def env(self, **extra: str) -> dict[str, str]:
        environment = {k: v for k, v in os.environ.items() if k.upper() not in SCRUBBED}
        environment.update(
            {
                "PATH": f"{self.bin}{os.pathsep}{environment.get('PATH', '')}",
                "FAKE_DOCKER_STATE": str(self.state / "docker-state.json"),
                "FAKE_CHILD_ENV": str(self.state / "events.jsonl"),
                "FAKE_API_HITS": str(self.state / "api-hits.txt"),
                "FAKE_API_PID": str(self.state / "api-pid.txt"),
                "FAKE_WEB_SERVER": str(self.root / "web-server"),
            }
        )
        environment.update(extra)
        return environment

    def unix_endpoint(self) -> str:
        path = self.sockets_dir / f"d{len(self.sockets)}.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        self.sockets.append(listener)
        return f"unix://{path}"

    def _lines(self, path: Path) -> list[str]:
        try:
            return path.read_text().splitlines()
        except OSError:
            return []

    def containers(self) -> dict:
        try:
            state = json.loads((self.state / "docker-state.json").read_text())
        except (OSError, ValueError):
            return {}
        return dict(state.get("containers", {}))

    def entries(self) -> list[dict]:
        lines = self._lines(self.state / "events.jsonl")
        return [json.loads(line) for line in lines if line.strip()]

    def mutations(self) -> list[dict]:
        return [e for e in self.entries() if e["tool"] == "docker" and e["argv"][0] in MUTATIONS]

    def api_hits(self) -> list[str]:
        return self._lines(self.state / "api-hits.txt")

    def spawn(self, environment: dict[str, str], port_base: int):
        self.driver = subprocess.Popen(
            [PYTHON, str(DRIVER), "--port-base", str(port_base), "--output", str(self.out)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return self.driver

    def run_driver(self, environment: dict[str, str], port_base: int, timeout: float) -> dict:
        process = self.spawn(environment, port_base)
        timed_out = False
        try:
            _, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.send_signal(signal.SIGTERM)
            try:
                _, stderr = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                _, stderr = process.communicate()
        return {"returncode": process.returncode, "timed_out": timed_out, "stderr": stderr}

    def verdict(self):
        runs = sorted(p for p in self.out.glob("run-*") if p.is_dir())
        if len(runs) != 1:
            return None, [f"expected one run directory, found {len(runs)}"]
        path = runs[0] / "verdict.json"
        if not path.is_file():
            return None, ["driver wrote no verdict.json"]
        text = path.read_text()
        return json.loads(text), (
            ["verdict artifact leaks an absolute local path"]
            if str(Path.home()) in text or "/Users/" in text
            else []
        )

    def old_api(self, port: int, hits: list[str]) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"stale")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)

    def forbidden_proxy(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        accepted: list[str] = []

        def accept_loop():
            while True:
                try:
                    connection, address = listener.accept()
                except OSError:
                    return
                accepted.append(str(address))
                connection.close()

        threading.Thread(target=accept_loop, daemon=True).start()
        self.sockets.append(listener)
        return f"http://{listener.getsockname()[0]}:{listener.getsockname()[1]}", accepted

    def free_base(self) -> int:
        for base in range(20000, 45000, 7):
            if all(free_port(base + offset) for offset in range(4)):
                return base
        raise RuntimeError("no free four-port block found")

    def cleanup(self) -> None:
        for pid in self.containers().values():
            terminate(pid)
        try:
            terminate(int((self.state / "api-pid.txt").read_text()))
        except (OSError, ValueError):
            pass
        if self.driver is not None and self.driver.poll() is None:
            self.driver.kill()
            self.driver.communicate()
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for listener in self.sockets:
            listener.close()
        for path in self.sockets_dir.iterdir():
            path.unlink()
        self.sockets_dir.rmdir()
