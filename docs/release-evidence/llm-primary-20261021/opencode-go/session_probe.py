import asyncio
from app.services.report_llm import get_llm_adapter
async def main():
    a = get_llm_adapter(response_format_json=True); a.max_tokens = 50
    try:
        await a.generate(system='Return only JSON {"ok":true}.', user="go"); print("NO-SESSION-CALL OK")
    except Exception as e:
        print("NO-SESSION-CALL FAILED", str(e)[:140])
asyncio.run(main())
