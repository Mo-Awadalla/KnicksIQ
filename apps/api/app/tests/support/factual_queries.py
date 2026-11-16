"""Exercise the same private lookup dispatch as the season conversation."""

from uuid import uuid4

from app.conversation.facts import lookup_result
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolResult


async def lookup(tools: AnalystTools) -> ToolResult:
    return await lookup_result(tools, request_id=str(uuid4()))


def grouped_claims(result: ToolResult) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for claim in result.claims:
        grouped.setdefault(claim.metric_id, []).append(claim.model_dump(mode="json"))
    return grouped


def text(result: ToolResult) -> str:
    return " ".join(
        [
            result.message,
            *result.choices,
            *(claim.statement for claim in result.claims),
            *(item.text for item in result.evidence),
        ]
    )
