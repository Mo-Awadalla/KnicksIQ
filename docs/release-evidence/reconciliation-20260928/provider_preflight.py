"""Read-only preflight. Never sends completion requests or changes a ledger."""
import asyncio
import json
import ssl
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import certifi
import yaml
from redis.asyncio import Redis

OUT = Path(__file__).resolve().parent


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(
        req, timeout=20, context=ssl.create_default_context(cafile=certifi.where())
    ) as response:
        return json.load(response)


async def main():
    result = {"observed_at": datetime.now(UTC).isoformat(), "completion_requests": 0,
              "additional_provider_spend_usd": 0, "authorized_request_limit": 9,
              "authorized_cost_limit_usd": 0.10, "status": "blocked", "checks": {}}
    try:
        cfg = yaml.safe_load((Path.home() / '.render/cli.yaml').read_text())
        headers = {'Authorization': 'Bearer ' + cfg['api']['key']}
        envrows = get('https://api.render.com/v1/services/srv-d9cgko8js32c73bbvu10/env-vars?limit=100', headers)
        env = {r['envVar']['key']: r['envVar']['value'] for r in envrows}
        safe = ['AI_CHAT_MODEL', 'AI_BASE_URL', 'ANALYSIS_ANSWER_MODE',
                'ANALYSIS_SHADOW_SAMPLE_RATE', 'ANALYST_EVIDENCE_LOOP_ENABLED',
                'OPENROUTER_MONTHLY_CUTOFF_USD', 'OPENROUTER_ALLOWED_MODELS']
        result['configuration'] = {k: env.get(k) for k in safe}
        assert env['AI_CHAT_MODEL'] == 'deepseek/deepseek-v4.1-flash'
        assert float(env['OPENROUTER_MONTHLY_CUTOFF_USD']) == 2
        result['checks']['model_and_cutoff'] = True
        # Existing real monthly accounting must be accessible and reconciled first.
        url = env.get('REDIS_URL')
        if not url:
            raise RuntimeError('monthly_ledger_endpoint_unavailable')
        redis = Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
        try:
            key = f'ai-budget:{datetime.now(UTC):%Y-%m}'
            total = await redis.get(key)
            reservations = await redis.hgetall(key + ':reservations')
            if total is None:
                raise RuntimeError('monthly_ledger_missing')
            outstanding = sum(float(v) for v in reservations.values())
            result['ledger'] = {'charged_including_reservations': float(total),
                               'outstanding_reservation_count': len(reservations),
                               'outstanding_reserved_usd': outstanding}
            if reservations or float(total) + 0.10 > 2:
                raise RuntimeError('monthly_ledger_unreconciled_or_insufficient')
        finally:
            await redis.aclose()
        catalog = get('https://openrouter.ai/api/v1/models')
        models = [m for m in catalog['data'] if m['id'] == env['AI_CHAT_MODEL']]
        if len(models) != 1:
            raise RuntimeError('authorized_model_current_pricing_unavailable')
        result['model_pricing'] = models[0].get('pricing')
        result['stop_reason'] = 'per_provider_token_and_reasoning_cost_bound_not_yet_verified'
    except Exception as exc:
        # Exception messages may contain endpoints/credentials; retain type only.
        result['stop_reason'] = str(exc) if isinstance(exc, (RuntimeError, AssertionError)) else type(exc).__name__
        result['checks']['preflight_complete'] = False
    (OUT / 'provider-preflight.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
