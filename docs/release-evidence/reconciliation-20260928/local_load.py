"""Ten isolated clients, existing rate limits, local PostgreSQL/ASGI only."""
import asyncio
import time
from contextlib import AsyncExitStack
import local_rehearsal as r
from app.core.db import engine
from app.main import create_app
from app.services import analyst_loop
from httpx import ASGITransport, AsyncClient


async def main():
    analyst_loop.get_llm_adapter = r.no_provider
    app = create_app()
    async with AsyncExitStack() as stack:
        clients = [await stack.enter_async_context(AsyncClient(transport=ASGITransport(app, client=(f'127.0.0.{i+2}',1234)),base_url='https://test')) for i in range(10)]
        async def worker(client, route):
            result = []
            for _ in range(5):
                start = time.perf_counter()
                response = await (client.get('/games') if route == 'archive' else client.post('/analysis/query',json={'question':'What were the Knicks wins and losses?','season':'2025-26'}))
                body = response.json()
                valid = response.status_code == 200 and (isinstance(body,list) and bool(body) if route=='archive' else bool(body.get('answer')) and bool(body.get('citations')))
                result.append({'latency_ms':(time.perf_counter()-start)*1000,'status':response.status_code,'valid':valid})
            return result
        archive = sum(await asyncio.gather(*[worker(c,'archive') for c in clients]),[])
        analyst = sum(await asyncio.gather(*[worker(c,'analyst') for c in clients]),[])
    def p95(rows): return sorted(x['latency_ms'] for x in rows)[47]
    metrics = {'concurrency':10,'archive_p95_ms':p95(archive),'analyst_p95_ms':p95(analyst),'error_rate':sum(not x['valid'] for x in archive+analyst)/100}
    r.dump('local-load-distinct-clients.json', {'scope':'local ASGI/PostgreSQL factual path, 10 clients; not primary provider or remote load','metrics':metrics,'archive':archive,'analyst':analyst,'passed':metrics['archive_p95_ms']<1000 and metrics['analyst_p95_ms']<4000 and metrics['error_rate']<.01})
    await engine.dispose()


asyncio.run(main())
