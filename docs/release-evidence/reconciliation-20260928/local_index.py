"""Build real local embeddings/collections; never contacts remote Qdrant or providers."""
import asyncio
import json
import os
from pathlib import Path

import local_rehearsal as rehearsal

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, engine
from app.services import qdrant_client as q
from app.services.rag_index import build_rag_artifacts
from qdrant_client import QdrantClient

OUT = Path(__file__).resolve().parent


async def main():
    settings = get_settings()
    settings.rag_qdrant_enabled = True
    settings.rag_qdrant_cloud_inference = False
    settings.rag_embedding_model = 'sentence-transformers/all-MiniLM-L6-v2'
    settings.rag_qdrant_vector_size = 384
    client = QdrantClient(path=str(OUT / 'local-qdrant'))
    q.get_qdrant_client = lambda: client
    async with AsyncSessionLocal() as db:
        manifest = await build_rag_artifacts(db, season='2025-26', out_dir=OUT/'local-index', data_version='2025-26.20260928.1')
    checks = {}
    mapping = json.loads((OUT/'runtime-mapping.json').read_text())
    games = {row['game_id'] for row in mapping['rows'].values() if row['collection'] == 'games'}
    all_points = {}
    for alias, physical in manifest['candidate_aliases'].items():
        points = []; offset = None
        while True:
            batch, offset = client.scroll(physical, limit=512, offset=offset, with_vectors=True)
            points.extend(batch)
            if offset is None: break
        assert points and all(p.payload['data_version'] == manifest['data_version'] and p.payload['game_id'] in games and len(p.vector) == 384 for p in points)
        assert client.count(physical, count_filter=q.build_qdrant_filter({'data_version':'wrong-release'}), exact=True).count == 0
        cases = []
        sample = points[0].payload
        filters = [{'game_ids':[sample['game_id']]}, {'dates':[sample['date']]}, {'team_ids':sample['team_ids']}]
        if sample.get('player_ids'): filters.append({'player_ids':sample['player_ids']})
        if sample.get('start_period'): filters.append({'periods':[sample['start_period']]})
        for selected in filters:
            actual = client.count(physical, count_filter=q.build_qdrant_filter({**selected,'data_version':manifest['data_version']}), exact=True).count
            def match(payload):
                if 'game_ids' in selected: return payload.get('game_id') in selected['game_ids']
                if 'dates' in selected: return payload.get('date') in selected['dates']
                if 'team_ids' in selected: return bool(set(payload.get('team_ids',[])) & set(selected['team_ids']))
                if 'player_ids' in selected: return bool(set(payload.get('player_ids',[])) & set(selected['player_ids']))
                return payload.get('start_period',0) <= selected['periods'][0] <= payload.get('end_period',0)
            expected = sum(match(p.payload) for p in points)
            cases.append({'filter':selected,'actual':actual,'expected':expected,'passed':actual==expected})
            assert actual == expected
        checks[alias] = {'points':len(points),'vector_size':384,'wrong_release_excluded':True,'filters':cases}
        all_points[alias] = [{'id':str(p.id),'payload':p.payload} for p in points]
    rehearsal.dump('local-index-checks.json', {'scope':'embedded local Qdrant, real cached MiniLM vectors; not cloud inference or remote index validation', 'checks':checks,'manifest':manifest})
    rehearsal.dump('local-index-payloads.json', all_points)
    client.close()
    await engine.dispose()
    print('Local index validation passed.')


if __name__ == '__main__': asyncio.run(main())
