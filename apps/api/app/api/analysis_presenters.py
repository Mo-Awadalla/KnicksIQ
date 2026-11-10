"""Evidence context and deterministic answer formatting."""

from __future__ import annotations

from typing import Any


def _table_evidence_note(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    examples = ", ".join(
        f"{item['date']} vs {item['opponent']} ({item['score']['NYK']}-"
        f"{item['score'][item['opponent']]})"
        for item in evidence[:3]
    )
    suffix = f"; {len(evidence) - 3} more" if len(evidence) > 3 else ""
    return f"\n\nKey evidence\n- {len(evidence)} available Knicks game(s): {examples}{suffix}."


def _format_answer(
    *,
    direct_answer: str,
    evidence_note: str = "",
    limitation_note: str | None = None,
) -> str:
    sections = [f"Short answer\n{direct_answer.strip()}"]
    if evidence_note:
        sections.append(evidence_note.strip())
    if limitation_note:
        sections.append(f"Limitation\n{limitation_note.strip()}")
    return "\n\n".join(sections)
