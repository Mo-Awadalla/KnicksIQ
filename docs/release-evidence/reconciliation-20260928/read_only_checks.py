"""Production metadata inspection only; SQL read-only transaction and HTTP GETs."""
import asyncio
import json
import ssl
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import yaml
from app.core.config import get_settings
from qdrant_client import QdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

OUT = Path(__file__).resolve().parent


def get(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=20,
        context=ssl.create_default_context(cafile=certifi.where())) as r:
        return json.load(r)


async def main():
    result = {'observed_at': datetime.now(UTC).isoformat(), 'remote_mutations': False}
    cfg = yaml.safe_load((Path.home()/'.render/cli.yaml').read_text())
    auth = {'Authorization': 'Bearer ' + cfg['api']['key']}
    env = {r['envVar']['key']: r['envVar']['value'] for r in get('https://api.render.com/v1/services/srv-d9cgko8js32c73bbvu10/env-vars?limit=100', auth)}
    settings = get_settings()
    # Use previously configured external read-only audit connection, never print credentials.
    if urlsplit(settings.effective_db_url).hostname not in {'127.0.0.1', 'localhost', None}:
        engine = create_async_engine(settings.effective_db_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                assert await conn.scalar(text('SHOW transaction_read_only')) == 'on'
                rows = (await conn.execute(text('SELECT id,version,status,manifest_sha256,validation_passed FROM dataset_releases ORDER BY id'))).mappings().all()
                migrations = (await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars().all()
                result['database'] = {'transaction_read_only': True, 'migrations': list(migrations), 'releases': [dict(r) for r in rows]}
                await conn.rollback()
        except Exception as exc:
            result['database'] = {'status': 'unavailable', 'error_type': type(exc).__name__}
        finally:
            await engine.dispose()
    else:
        result['database'] = {'status': 'external_audit_connection_unavailable'}
    try:
        q = QdrantClient(url=env['QDRANT_URL'], api_key=env.get('QDRANT_API_KEY'), timeout=10)
        aliases = {a.alias_name: a.collection_name for a in q.get_aliases().aliases}
        existing = {c.name for c in q.get_collections().collections}
        old = {name: q.get_collection(name).points_count for name in aliases.values()}
        candidate = {f'{alias}__2025_26_20260928_1': f'{alias}__2025_26_20260928_1' in existing for alias in ['knicks_games','knicks_reports','knicks_box_scores','knicks_possessions']}
        result['qdrant'] = {'aliases': aliases, 'retained_counts': old, 'candidate_collection_exists': candidate,
                            'candidate_verified': False}
        q.close()
    except Exception as exc:
        result['qdrant'] = {'status': 'unavailable', 'error_type': type(exc).__name__}
    result['services'] = {}
    for name, sid in {'api': 'srv-d9cgko8js32c73bbvu10', 'web':'srv-d9cgko8js32c73bbvu1g'}.items():
        service = get(f'https://api.render.com/v1/services/{sid}', auth)
        deps = get(f'https://api.render.com/v1/services/{sid}/deploys?limit=5', auth)
        result['services'][name] = {'auto_deploy': service.get('autoDeploy'), 'live': [{'id': d['deploy']['id'], 'commit': d['deploy'].get('commit', {}).get('id')} for d in deps if d['deploy']['status'] == 'live']}
    result['headers'] = {}
    for name, url in {'api':'https://api.knicksiq.win/health', 'web':'https://www.knicksiq.win'}.items():
        try:
            with urllib.request.urlopen(url, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as r:
                result['headers'][name] = {'status': r.status, **{k:r.headers.get(k) for k in ['Strict-Transport-Security','X-Content-Type-Options','Content-Security-Policy']}}
        except Exception as exc:
            result['headers'][name] = {'error_type':type(exc).__name__}
    (OUT/'read-only-checks.json').write_text(json.dumps(result, indent=2, default=str)+'\n')
    print('Read-only metadata checks saved locally.')


if __name__ == '__main__':
    asyncio.run(main())
