"""Container health probe contract.

Production redirects plaintext HTTP to HTTPS, and that redirect stays in force. The
container ``HEALTHCHECK`` runs inside the container and talks to the process's own
loopback port, where no TLS terminator exists, so it must present the scheme header
that a trusted edge (Render) sends for a TLS-terminated request. The app trusts that
header only from its configured forwarded-for addresses, which by default is
loopback, so no public caller gains an HTTPS bypass.

Exit code 0 means the process answered liveness with HTTP 200. Any redirect, error,
timeout, or non-200 answer exits non-zero so the container is reported unhealthy.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

PROBE_PATH = "/health/live"
PROBE_HEADERS = {"X-Forwarded-Proto": "https"}


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        raise urllib.error.HTTPError(
            req.full_url, code, f"unexpected redirect to {newurl}", headers, fp
        )


def probe(port: str | None = None, timeout: float = 2.0) -> int:
    """Return 0 only for a 200 liveness answer from the loopback port."""
    resolved_port = port or os.getenv("PORT", "8000")
    url = f"http://127.0.0.1:{resolved_port}{PROBE_PATH}"
    opener = urllib.request.build_opener(_RejectRedirect)
    request = urllib.request.Request(url, headers=PROBE_HEADERS)
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status == 200:
                return 0
            print(f"health probe returned HTTP {response.status}", file=sys.stderr)
            return 1
    except (OSError, urllib.error.URLError) as exc:
        print(f"health probe failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(probe())
