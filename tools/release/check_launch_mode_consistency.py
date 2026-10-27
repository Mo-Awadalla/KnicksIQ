#!/usr/bin/env python3
"""Check that the launch mode and model host are stated once and not contradicted.

Render is the deployed declaration. The release checklist's intended-launch section is the
authoritative document. The analyst implementation document must link there and must not assert a
different mode or an obsolete tool count.

Exits 1 on any mismatch. Writes the observations to stdout and, with --json-out, to a file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KEYS = (
    "ANALYSIS_ANSWER_MODE",
    "ANALYST_EVIDENCE_LOOP_ENABLED",
    "ANALYSIS_SHADOW_SAMPLE_RATE",
    "OPENROUTER_MONTHLY_CUTOFF_USD",
    # The model host is part of the launch: a stale provider or model in either document is the
    # same class of drift as a stale answer mode.
    "AI_PROVIDER",
    "AI_CHAT_MODEL",
    "ANALYST_REVIEW_MODEL",
)
TOOLS = (
    "get_player_stats",
    "get_team_stats",
    "compare_windows",
    "discover_facts",
    "search_archive",
    "get_evidence",
    "get_game_flow",
    "get_team_splits",
    "get_period_scoring",
)
CHECKLIST_HEADING = "## Intended launch configuration"
CHECKLIST_LINK = "release-checklist.md#intended-launch-configuration"


def render_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"\s*-\s*key:\s*(\w+)\s*$", line)
        if not match or match.group(1) not in KEYS:
            continue
        for follow in lines[index + 1 : index + 5]:
            value = re.match(r"\s*value:\s*(.+?)\s*$", follow)
            if value:
                values[match.group(1)] = value.group(1).strip().strip("'\"")
                break
    return values


def checklist_values(text: str) -> dict[str, str]:
    if CHECKLIST_HEADING not in text:
        return {}
    section = text.split(CHECKLIST_HEADING, 1)[1].split("\n## ", 1)[0]
    values: dict[str, str] = {}
    for key in KEYS:
        match = re.search(rf"{key}\s*=\s*([A-Za-z0-9_.-]+)", section)
        if match:
            values[key] = match.group(1)
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    root: Path = args.root

    render = render_values((root / "render.yaml").read_text())
    checklist = checklist_values((root / "docs/release-checklist.md").read_text())
    analyst = (root / "docs/analyst-evidence-loop.md").read_text()

    mismatches: list[str] = []
    for key in KEYS:
        if key not in render:
            mismatches.append(f"render.yaml does not declare {key}")
        if key not in checklist:
            mismatches.append(f"release-checklist.md does not declare {key}")
        if key in render and key in checklist and render[key] != checklist[key]:
            mismatches.append(f"{key}: render.yaml={render[key]!r} checklist={checklist[key]!r}")

    doc_modes = re.findall(r"ANALYSIS_ANSWER_MODE\s*=\s*([A-Za-z_]+)", analyst)
    expected_mode = render.get("ANALYSIS_ANSWER_MODE", "")
    for mode in doc_modes:
        if mode != expected_mode:
            mismatches.append(
                f"analyst-evidence-loop.md asserts ANALYSIS_ANSWER_MODE={mode}, "
                f"render.yaml declares {expected_mode}"
            )
    if expected_mode and expected_mode not in doc_modes:
        mismatches.append("analyst-evidence-loop.md does not name the launch answer mode")

    if CHECKLIST_LINK not in analyst:
        mismatches.append("analyst-evidence-loop.md does not link the authoritative launch section")
    if "six controlled tools" in analyst:
        mismatches.append("analyst-evidence-loop.md still claims six controlled tools")
    missing_tools = [name for name in TOOLS if name not in analyst]
    if missing_tools:
        mismatches.append("analyst-evidence-loop.md omits tools: " + ", ".join(missing_tools))

    observation = {
        "render_yaml": render,
        "release_checklist": checklist,
        "analyst_doc": {
            "answer_mode_assertions": doc_modes,
            "links_authoritative_section": CHECKLIST_LINK in analyst,
            "tools_named": [name for name in TOOLS if name in analyst],
        },
        "mismatches": mismatches,
        "status": "fail" if mismatches else "pass",
    }
    text = json.dumps(observation, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
