"""Resolve local runtime receipts independently of the legacy evaluation scorer."""
import asyncio
import hashlib
import json
from pathlib import Path

import local_rehearsal as r
from app.core.db import AsyncSessionLocal, engine
from app.models.report import Report
from sqlalchemy import select

OUT=Path(__file__).resolve().parent


async def main():
    mapping=json.loads((OUT/'runtime-mapping.json').read_text())
    payloads=json.loads((OUT/'local-index-payloads.json').read_text())
    namespace='f5af0efd-b2f7-4f7c-b0fd-09d2e5166c90'
    import uuid
    documents={}
    for collection, points in payloads.items():
        for point in points:
            p=point['payload']; source=p['chunk_id']
            assert point['id']==str(uuid.uuid5(uuid.UUID(namespace),source))
            assert p['data_version']==mapping['version']
            documents[source]={'point_id':point['id'],'collection':collection,'game_id':p['game_id'],
                               'runtime_evidence_id':mapping['version']+':'+source,
                               'payload_sha256':r.digest(p)}
    async with AsyncSessionLocal() as db:
        reports=list((await db.execute(select(Report).where(Report.release_id==mapping['release_id']))).scalars())
        by_source={p['payload']['chunk_id']:p['payload'] for p in payloads['knicks_reports']}
        for report in reports:
            assert by_source[f'report:{report.id}']['semantic_summary']==f'{report.title}. {report.summary}'
    receipts={v['runtime_receipt']: k for k,v in mapping['rows'].items() if v['runtime_receipt']}
    results=[]
    for observation in json.loads((OUT/'production-profile.json').read_text())['observations']:
        for citation in observation['response']['citations']:
            claim=citation['metadata']['claim']; ref=citation['metadata']['evidence_id']
            assert claim['release_id']==mapping['version']
            game_ids=claim['game_ids']; player_id=claim['subject_id'].split(':')[1] if claim['subject_id'].startswith('player:') else None
            source_ids=[f"{mapping['version']}:game:{g}"+(f':player:{player_id}' if player_id else '') for g in game_ids]
            assert all(source in receipts for source in source_ids)
            if ref.startswith('calculation:'):
                expected='calculation:'+hashlib.sha256(json.dumps([mapping['version'],claim['subject_id'],claim['metric_id'],source_ids,claim['value']],sort_keys=True).encode()).hexdigest()
                assert ref==expected
            else:
                assert ref in receipts
            results.append({'mode':observation['mode'],'claim_id':claim['claim_id'],'reference':ref,'canonical_sources':[receipts[s] for s in source_ids],
                            'identity_and_recipe_resolved':True,'quality_grade':'not_scored_rehearsal_not_frozen_evaluation'})
    r.dump('runtime-receipt-checks.json',{'scope':'local rehearsal identity and calculation recipe only, not quality/expected-answer correctness',
          'document_count':len(documents),'report_title_summary_matches':len(reports),'receipts':results})
    r.dump('runtime-document-mapping.json',{'version':mapping['version'],'scope':'isolated local index only; remap remote after staging','documents':documents})
    await engine.dispose()
    print(f'Validated {len(documents)} document identities, {len(reports)} report summaries and {len(results)} rehearsal receipt recipes.')


asyncio.run(main())
