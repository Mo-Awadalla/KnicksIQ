"""Local-only release restore, canonical mapping and production-profile rehearsal."""
import asyncio
import hashlib
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DB = 'postgresql+asyncpg://mohamedawadalla@127.0.0.1:55440/reconciliation'
# Override every outbound dependency before importing application configuration.
os.environ.update(DB_URL=DB, TEST_MODE='false', ENVIRONMENT='production',
                  REDIS_URL='', AI_PROVIDER='mock', AI_API_KEY='', OPENROUTER_API_KEY='',
                  QDRANT_URL='', QDRANT_API_KEY='', RAG_QDRANT_ENABLED='false',
                  RAG_QDRANT_CLOUD_INFERENCE='false', RAG_LLM_PLANNER_ENABLED='false',
                  ANALYST_EVIDENCE_LOOP_ENABLED='true', ANALYSIS_ANSWER_MODE='llm_primary',
                  REQUIRE_ACTIVE_RELEASE='true', SENTRY_DSN='', HF_HUB_OFFLINE='1',
                  TRANSFORMERS_OFFLINE='1', RAG_EMBEDDING_DEVICE='cpu')

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, engine
from app.main import create_app
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.report import Report
from app.services import analyst_loop
from app.services.release_bundle import load_release_bundle, read_bundle
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, default=str) + '\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def no_provider():
    raise AssertionError('Provider access forbidden in local production-data rehearsal')


async def main():
    assert get_settings().effective_db_url == DB
    analyst_loop.get_llm_adapter = no_provider
    meta = json.loads((ROOT / 'docs/release-evidence/report-review-20260928/approved-bundle.json').read_text())
    path = ROOT / meta['path']
    assert sha(path) == meta['sha256']
    bundle = read_bundle(path, meta['sha256'])
    approval = json.loads((ROOT / 'docs/release-evidence/report-review-20260928/owner-content-approval.json').read_text())
    assert all(digest({k: v for k, v in row.items() if k not in {'reviewed', 'review_hash'}}) == approval['content_hashes'][row['nba_game_id']] for row in bundle['data']['reports'])
    async with AsyncSessionLocal() as db:
        # Retain and restore the old release locally; never alter a production DB.
        old = (await db.execute(select(DatasetRelease).where(DatasetRelease.version == '2025-26.20260714.1'))).scalar_one()
        old_id, old_version = old.id, old.version
        old_reports = list((await db.execute(select(Report).where(Report.release_id == old_id))).scalars())
        old_hashes = {r.id: r.content_sha256 for r in old_reports}
        assert len(old_reports) == 101
        new = await load_release_bundle(db, path, expected_sha256=meta['sha256'], activate=True)
        again = await load_release_bundle(db, path, expected_sha256=meta['sha256'])
        assert not again.inserted
        release = (await db.execute(select(DatasetRelease).where(DatasetRelease.version == meta['version']))).scalar_one()
        games = list((await db.execute(select(Game).where(Game.release_id == release.id))).scalars())
        players = list((await db.execute(select(Player))).scalars())
        game_by_id = {g.id: g for g in games}
        game_by_nba = {g.nba_game_id: g for g in games}
        player_by_id = {p.id: p for p in players}
        assert len(game_by_nba) == len(games) == 101
        maps = {}
        lookup = {}
        for model, collection in [(Game, 'games'), (PlayerGameStat, 'player_game_stats'),
                                  (TeamGameStat, 'team_game_stats'), (PeriodScore, 'period_scores')]:
            rows = list((await db.execute(select(model).where(model.release_id == release.id))).scalars())
            for row in rows:
                game = row if model is Game else game_by_id[row.game_id]
                key = game.nba_game_id
                prefix = 'game'
                if model is PlayerGameStat:
                    prefix = 'box'
                    key += ':' + str(player_by_id[row.player_id].nba_player_id)
                elif model is TeamGameStat:
                    prefix = 'team_box'
                    key += ':' + row.team_id
                elif model is PeriodScore:
                    prefix = 'period'
                    key += ':' + row.team_id + ':' + str(row.period)
                lookup[f'{prefix}:{key}'] = row
            for raw in bundle['data'][collection]:
                key = raw['nba_game_id']
                prefix = 'game'
                if model is PlayerGameStat:
                    prefix = 'box'; key += ':' + str(raw['nba_player_id'])
                elif model is TeamGameStat:
                    prefix = 'team_box'; key += ':' + raw['team_id']
                elif model is PeriodScore:
                    prefix = 'period'; key += ':' + raw['team_id'] + ':' + str(raw['period'])
                canonical = f'{prefix}:{key}'
                row = lookup[canonical]
                for field, value in raw.items():
                    if field in {'nba_game_id', 'nba_player_id'}:
                        continue
                    actual = getattr(row, field)
                    if isinstance(actual, datetime):
                        assert actual == datetime.fromisoformat(value)
                    else:
                        assert actual == value or str(actual) == str(value), (canonical, field)
                game = row if model is Game else game_by_id[row.game_id]
                receipt = f'{release.version}:game:{game.id}'
                if model is PlayerGameStat:
                    receipt += f':player:{row.player_id}'
                maps[canonical] = {'collection': collection, 'row_sha256': digest(raw),
                                   'database_row_id': row.id, 'game_id': game.id,
                                   'release_id': release.id,
                                   'runtime_receipt': receipt if model in (Game, PlayerGameStat) else None,
                                   'player_id': row.player_id if model is PlayerGameStat else None}
        labels = [json.loads(line) for line in (ROOT / 'docs/release-evidence/evaluation-label-review-20260907/labels.jsonl').read_text().splitlines()]
        references = [ref for label in labels for ref in label['canonical_sources']]
        assert all(maps[ref['canonical_id']]['row_sha256'] == ref['row_sha256'] for ref in references)
        dump('runtime-mapping.json', {'scope': 'isolated local PostgreSQL restore only; remote IDs must be remapped after staging',
             'bundle_sha256': meta['sha256'], 'version': release.version, 'release_id': release.id,
             'verified_source_references': len(references), 'rows': maps,
             'players': {str(p.nba_player_id): {'id': p.id, 'name': p.full_name} for p in players}})
        reports = list((await db.execute(select(Report).where(Report.release_id == release.id))).scalars())
        assert len(reports) == 101 and all(r.reviewed for r in reports)
        dump('restore.json', {'old': {'release_id': old_id, 'version': old_version, 'report_count': len(old_reports)}, 'candidate': new.__dict__, 'repeat': again.__dict__,
                             'approved_report_hashes_match': True, 'source_rows_verified': len(maps),
                             'report_count': len(reports), 'local_only': True})
    app = create_app()
    observations = []
    async with AsyncClient(transport=ASGITransport(app), base_url='https://test') as client:
        for mode in ['llm_primary', 'shadow']:
            get_settings().analysis_answer_mode = mode
            response = await client.post('/analysis/query', json={'question': 'What were the Knicks wins and losses?', 'season': '2025-26', 'turn_id': 'local-rehearsal-turn-' + mode, 'expected_revision': 0})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body['answer'] and body['citations'] and not body['llm_validated']
            assert body['data_version'] == meta['version']
            assert 'strict-transport-security' in response.headers
            observations.append({'mode': mode, 'response': body, 'status': response.status_code})
        # Loopback ASGI concurrency rehearsal, dependency-disabled factual path only.
        semaphore = asyncio.Semaphore(10)
        async def request(url, payload=None):
            async with semaphore:
                start = time.perf_counter()
                response = await (client.post(url, json=payload) if payload else client.get(url))
                return {'latency_ms': (time.perf_counter() - start) * 1000, 'status': response.status_code}
        await request('/games')
        await request('/analysis/query', {'question': 'What were the Knicks wins and losses?', 'season': '2025-26'})
        archive = await asyncio.gather(*[request('/games') for _ in range(50)])
        analyst = await asyncio.gather(*[request('/analysis/query', {'question': 'What were the Knicks wins and losses?', 'season': '2025-26'}) for _ in range(50)])
        def p95(rows):
            return sorted(r['latency_ms'] for r in rows)[int(len(rows)*.95)-1]
        dump('local-load.json', {'scope': 'local ASGI + PostgreSQL, providers/Redis/vectors disabled; not hosted or full primary load evidence',
             'concurrency': 10, 'archive_p95_ms': p95(archive), 'analyst_p95_ms': p95(analyst),
             'error_rate': sum(r['status'] != 200 for r in archive + analyst)/100,
             'archive': archive, 'analyst': analyst})
    dump('production-profile.json', {'environment': 'production', 'test_mode': False,
         'provider_calls': 0, 'observations': observations, 'fixture_scope': 'Redis unavailable, no provider; local candidate content'})
    async with AsyncSessionLocal() as db:
        await db.execute(update(DatasetRelease).where(DatasetRelease.status == 'active').values(status='superseded'))
        await db.execute(update(DatasetRelease).where(DatasetRelease.id == old_id).values(status='active'))
        await db.commit()
        active = (await db.execute(select(DatasetRelease).where(DatasetRelease.status == 'active'))).scalar_one()
        assert active.version == old_version
        restored_reports = list((await db.execute(select(Report).where(Report.release_id == old_id))).scalars())
        assert {r.id: r.content_sha256 for r in restored_reports} == old_hashes
        await load_release_bundle(db, path, expected_sha256=meta['sha256'], activate=True)
        dump('local-rollback.json', {'old_version': old_version, 'candidate_version': meta['version'], 'restored_old_then_candidate': True, 'scope': 'isolated PostgreSQL activation; no services or remote aliases'})
    await engine.dispose()
    print('Local restore, row mapping, production profile and rollback passed.')


if __name__ == '__main__':
    asyncio.run(main())
