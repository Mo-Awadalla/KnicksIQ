# Local Docker staging

This stack runs the release API, web UI, Postgres, and persistent Redis locally.
It uses the approved 101-game archive and deterministic answers. Provider keys
are explicitly blank, model/planner calls are disabled, and no paid verification
is performed. It is a starting point for local verification, not production
release approval or live model-quality evidence.

## Start

Start Docker Desktop, then run the following from the repository root. Set
`KNICKSIQ_STAGING_BUNDLE` below to your existing approved archive file. Its required
SHA-256 is `549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b`;
the initializer rejects any other file.

Create the ignored environment file once, and reuse it across restarts:

```sh
python3 - <<'PY'
from pathlib import Path
import secrets
directory = Path('release-artifacts/local-docker')
directory.mkdir(parents=True, exist_ok=True)
path = directory / 'staging.env'
with path.open('x') as output:
    output.write('KNICKSIQ_STAGING_BUNDLE=/absolute/path/to/reliability-approved-20260928.json.gz\n')
    output.write('KNICKSIQ_STAGING_IP_HASH_SECRET=' + secrets.token_hex(32) + '\n')
path.chmod(0o600)
PY
docker compose --env-file release-artifacts/local-docker/staging.env \
  -f docker-compose.staging.yml up -d --build --wait --wait-timeout 180
```

Open <http://127.0.0.1:18080>. API readiness is at
<http://127.0.0.1:18000/health/ready>. Only these loopback ports are published.
Postgres and Redis have separate persistent volumes on the internal network.
API/web also use a browser network because Docker Desktop does not publish ports
for containers attached only to an internal network.

The one-shot initializer migrates the local database and loads/activates the
approved bundle transactionally. Repeating it preserves the existing release.
The API waits for initialization and Redis health before starting; the web waits
for API readiness. Existing development and hosted services are separate.

## Verify and retain evidence

```sh
python3 tools/release/verify_local_staging.py \
  --output release-artifacts/local-docker/http-initial
docker compose --env-file release-artifacts/local-docker/staging.env \
  -f docker-compose.staging.yml restart redis api
docker compose --env-file release-artifacts/local-docker/staging.env \
  -f docker-compose.staging.yml up -d --wait --wait-timeout 90
python3 tools/release/verify_local_staging.py --phase replay \
  --receipt release-artifacts/local-docker/http-initial/verification.json \
  --output release-artifacts/local-docker/http-restart
```

Use fresh output directories on later runs. The verifier exercises real HTTP
through nginx and the API, archive/game/report data, committed sessions, exact
replay, conflicting requests, and references to a game in prior messages. The
restart phase checks that an earlier answer survives a Redis/API restart.

For browser navigation, two chat turns, reload persistence, screenshots, and a
Playwright trace against the actual containers:

```sh
uv run --no-project --with playwright==1.55.0 playwright install chromium
uv run --no-project --with playwright==1.55.0 python \
  tools/release/verify_local_staging_browser.py \
  --output release-artifacts/local-docker/browser
```

No API responses are mocked. Browser requests to other origins are blocked.
In deterministic mode, supported answers can carry the existing `factual_fallback`
route and `Model or budget unavailable.` warning. The HTTP verifier accepts that
specific expected response shape with citations; it still rejects dependency
failures and uncommitted state. This warning is not evidence of a Redis problem.

Normal chat limits still apply (10 requests/minute, 100/day per client). Avoid
running repeated probes against the same instance in quick succession; wait for
the existing quota window rather than deleting counters. The local monthly budget
ledger is deliberately not initialized, so it cannot imply reconciled spending
headroom. Deterministic answers do not require model reservations.

## Stop or resume

```sh
docker compose --env-file release-artifacts/local-docker/staging.env \
  -f docker-compose.staging.yml stop
docker compose --env-file release-artifacts/local-docker/staging.env \
  -f docker-compose.staging.yml up -d --wait --wait-timeout 90
```

Keep the saved IP hash secret and volumes to retain sessions. Do not use `down -v`
unless you intentionally want to destroy this local archive and Redis state.
This stack does not change Render or prove hosted connectivity, live model
quality, the complete release workload, or production launch readiness.
