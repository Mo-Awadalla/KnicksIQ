"""Probe the production driver's locality, ownership, and teardown contracts.

Probes run the real driver CLI against fake ``docker``/``uv``/``pnpm`` tools that
record daemon state, child environments, and argv. Assertions cover unix sockets,
container state, whether a pre-existing API was queried, real signals, and the
``verdict.json`` artifact. No remote host is contacted and no global Docker
context is written. These probes are not product, API, or browser evidence.
"""

import argparse
import json
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from production_driver_probe import Probe, check, wait_until

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")


def interrupt(probe: Probe, environment: dict[str, str]) -> list[str]:
    problems: list[str] = []
    process = probe.spawn(environment, probe.free_base())
    started = wait_until(lambda: len(probe.containers()) >= 2, 20)
    check(problems, started, "driver never created two containers")
    if started:
        process.send_signal(signal.SIGTERM)
        time.sleep(0.15)
        try:
            process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        problems.append("driver survived SIGTERM")
    check(problems, process.returncode not in (0, None), "interrupted driver must exit nonzero")
    return problems


def rejected_daemon(probe: Probe, label: str, **extra: str) -> list[str]:
    problems: list[str] = []
    result = probe.run_driver(probe.env(FAKE_PG_READY="1", **extra), probe.free_base(), timeout=25)
    check(problems, not result["timed_out"], f"{label}: driver did not reject in 25s")
    check(problems, result["returncode"] not in (0, None), f"{label}: exit code should be nonzero")
    verdict, extra_problems = probe.verdict()
    problems += extra_problems
    if verdict is not None:
        check(problems, verdict.get("passed") is False, f"{label}: rejected daemon must not pass")
        message = json.dumps(verdict.get("error", {}))
        check(
            problems,
            "loopback" in message or "nonlocal" in message,
            f"{label}: rejection unnamed",
        )
    check(problems, not probe.mutations(), f"{label}: docker mutation ran before rejection")
    check(problems, not probe.containers(), "daemon created containers before rejection")
    return problems


def probe_forbidden_docker_tcp(probe: Probe) -> list[str]:
    return rejected_daemon(probe, "remote-tcp", DOCKER_HOST="tcp://203.0.113.10:2375")


def probe_forbidden_docker_context(probe: Probe) -> list[str]:
    problems = rejected_daemon(
        probe,
        "remote-context",
        DOCKER_CONTEXT="remote-prod",
        FAKE_DOCKER_CONTEXT_ENDPOINT="tcp://198.51.100.7:2376",
    )
    inspected = [
        entry
        for entry in probe.entries()
        if entry["tool"] == "docker" and entry["argv"][:2] == ["context", "inspect"]
    ]
    check(problems, bool(inspected), "selected context never inspected")
    return problems


def probe_occupied_port(probe: Probe) -> list[str]:
    problems: list[str] = []
    port_base = probe.free_base()
    hits: list[str] = []
    probe.old_api(port_base + 2, hits)
    result = probe.run_driver(probe.env(DOCKER_HOST=probe.unix_endpoint()), port_base, timeout=45)
    check(problems, not result["timed_out"], "occupied port not rejected in 45s")
    check(problems, result["returncode"] not in (0, None), "driver exit code should be nonzero")
    verdict, extra = probe.verdict()
    problems += extra
    if verdict is not None:
        check(problems, verdict.get("passed") is False, "occupied API port must not pass")
        message = json.dumps(verdict.get("error", {})).lower()
        check(
            problems,
            "already in use" in message or "occupied" in message,
            f"port not named: {message[:200]}",
        )
    check(problems, not hits, f"driver queried the pre-existing API process: {hits[:2]}")
    check(problems, not probe.mutations(), "containers touched despite occupied port")
    return problems


def probe_owned_api_exit(probe: Probe) -> list[str]:
    problems: list[str] = []
    result = probe.run_driver(
        probe.env(DOCKER_HOST=probe.unix_endpoint(), FAKE_API_MODE="exit", FAKE_API_EXIT_CODE="3"),
        probe.free_base(),
        timeout=45,
    )
    check(problems, not result["timed_out"], "driver waited on a dead owned API")
    check(problems, result["returncode"] not in (0, None), "driver exit code should be nonzero")
    verdict, extra = probe.verdict()
    problems += extra
    if verdict is not None:
        check(problems, verdict.get("passed") is False, "a dead API child must not pass")
        message = json.dumps(verdict.get("error", {}))
        check(problems, "exited with code 3" in message, f"API exit hidden: {message[:200]}")
    left = sorted(probe.containers())
    check(problems, not left, f"owned containers left behind: {left}")
    return problems


def probe_interrupt_cleanup(probe: Probe) -> list[str]:
    problems = interrupt(probe, probe.env(DOCKER_HOST=probe.unix_endpoint(), FAKE_PG_READY="1"))
    verdict, extra = probe.verdict()
    problems += extra
    if verdict is not None:
        check(problems, verdict.get("passed") is False, "interrupted run must not pass")
        error = verdict.get("error", {})
        check(problems, error.get("type") == "Interrupted", f"unexpected error record: {error}")
        check(problems, "SIGTERM" in json.dumps(error), f"signal missing from verdict: {error}")
    survivors = sorted(probe.containers())
    check(problems, not survivors, f"containers survived interruption: {survivors}")
    check(problems, not probe.api_hits(), "API was started before interruption")
    return problems


def probe_cleanup_failure(probe: Probe) -> list[str]:
    problems = interrupt(
        probe,
        probe.env(
            DOCKER_HOST=probe.unix_endpoint(),
            FAKE_PG_READY="1",
            FAKE_DOCKER_STOP_FAIL_SUFFIX="-redis",
        ),
    )
    verdict, extra = probe.verdict()
    problems += extra
    containers = probe.containers()
    if verdict is not None:
        failures = verdict.get("cleanup_failures") or []
        check(problems, verdict.get("passed") is False, "cleanup failure must not pass")
        recorded = any(str(f.get("resource", "")).endswith("-redis") for f in failures)
        check(problems, recorded, f"cleanup failure not recorded: {failures}")
    stopped_early = any(n.endswith("-pg") for n in containers)
    check(problems, not stopped_early, f"teardown stopped early: {sorted(containers)}")
    return problems


def probe_proxy_silence(probe: Probe) -> list[str]:
    problems: list[str] = []
    proxy, accepted = probe.forbidden_proxy()
    endpoint = probe.unix_endpoint()
    result = probe.run_driver(
        probe.env(
            DOCKER_HOST=endpoint,
            HTTP_PROXY=proxy,
            HTTPS_PROXY=proxy,
            ALL_PROXY=proxy,
            SSL_CERT_FILE="/nonexistent/ca.pem",
            REQUESTS_CA_BUNDLE="/nonexistent/ca.pem",
        ),
        probe.free_base(),
        timeout=90,
    )
    check(problems, not result["timed_out"], "scenario exceeded 90s")
    check(
        problems,
        result["returncode"] == 0,
        f"exit {result['returncode']}: {result['stderr'][-400:]}",
    )
    verdict, extra = probe.verdict()
    problems += extra
    if verdict is not None:
        check(
            problems,
            verdict.get("passed") is True,
            f"verdict did not pass: {verdict.get('error')}",
        )
    check(problems, not accepted, f"forbidden proxy received {len(accepted)} connection(s)")
    check(problems, bool(probe.api_hits()), "driver never reached its API")
    entries = probe.entries()
    check(problems, bool(entries), "no child environment recorded")
    for entry in entries:
        values = entry["env"]
        tool = entry["tool"]
        check(problems, values["DOCKER_HOST"] == endpoint, f"{tool} lost the pinned DOCKER_HOST")
        check(problems, values["DOCKER_CONTEXT"] is None, f"{tool} inherited DOCKER_CONTEXT")
        for key in PROXY_KEYS:
            check(problems, values[key] is None, f"{tool} inherited {key}")
    remaining = sorted(probe.containers())
    check(problems, not remaining, f"containers left behind: {remaining}")
    return problems


PROBES = {
    "forbidden-docker-tcp": probe_forbidden_docker_tcp,
    "forbidden-docker-context": probe_forbidden_docker_context,
    "occupied-port": probe_occupied_port,
    "owned-api-exit": probe_owned_api_exit,
    "interrupt-cleanup": probe_interrupt_cleanup,
    "cleanup-failure": probe_cleanup_failure,
    "proxy-silence": probe_proxy_silence,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    failed = False
    with tempfile.TemporaryDirectory(prefix="kiq-driver-probes-") as root:
        for name, run_probe in PROBES.items():
            probe = Probe(name, Path(root) / name)
            started = time.monotonic()
            try:
                problems = run_probe(probe)
            except Exception as exc:
                problems = [f"probe crashed: {type(exc).__name__}: {exc}"]
            finally:
                probe.cleanup()
            elapsed = time.monotonic() - started
            print(f"[{'PASS' if not problems else 'FAIL'}] {name} ({elapsed:.1f}s)")
            for problem in problems:
                print(f"    - {problem}")
            failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
