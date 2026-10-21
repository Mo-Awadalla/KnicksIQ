"""Prove the registry refactor did not change the provider prompt or the Action schema.

The base revision has the orchestrator prompt inline. This script reads that literal from git,
checks that the branch's request_model assigns the new orchestrator_system_prompt() function, and
compares the strings byte for byte. It also imports the base tree in a temporary directory and
compares Action.model_json_schema(), which carries the ToolCall name enum.

    uv run python tools/release/registry_prompt_diff.py --out report.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROVIDER = "apps/api/app/services/analyst_provider.py"
BASE = "codex/production-ready-20261018"


def _request_model(tree: ast.Module) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "request_model"
        ):
            return node
    raise SystemExit("request_model not found")


def _system_assignment(function: ast.AsyncFunctionDef | ast.FunctionDef) -> ast.expr:
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        if not isinstance(node.test, ast.Name) or node.test.id != "review":
            continue
        for statement in node.orelse:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "system"
                for target in statement.targets
            ):
                return statement.value
    raise SystemExit("non-review system assignment not found")


def _evaluate_constants(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _evaluate_constants(node.left) + _evaluate_constants(node.right)
    raise SystemExit(f"base prompt is not a constant expression: {ast.dump(node)[:120]}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base_schema(base: str, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as scratch:
        archive = subprocess.run(
            ["git", "archive", base], cwd=root, check=True, capture_output=True
        )
        subprocess.run(["tar", "-x", "-C", scratch], input=archive.stdout, check=True)
        env = os.environ | {
            "PYTHONPATH": os.pathsep.join(
                [
                    str(Path(scratch) / "apps/api"),
                    str(Path(scratch) / "packages/basketball-core/src"),
                ]
            )
        }
        code = (
            "import json, app; "
            f"assert app.__file__.startswith({scratch!r}), app.__file__; "
            "from app.services.evidence_contracts import Action; "
            "print(json.dumps(Action.model_json_schema()))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=scratch,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    base_sha = subprocess.check_output(["git", "rev-parse", args.base], cwd=root, text=True).strip()
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    base_source = subprocess.check_output(
        ["git", "show", f"{base_sha}:{PROVIDER}"], cwd=root, text=True
    )
    base_prompt = _evaluate_constants(_system_assignment(_request_model(ast.parse(base_source))))

    branch_source = (root / PROVIDER).read_text()
    branch_tree = ast.parse(branch_source)
    assignment = _system_assignment(_request_model(branch_tree))
    assert isinstance(assignment, ast.Call) and isinstance(assignment.func, ast.Name)
    assert assignment.func.id == "orchestrator_system_prompt"
    assert not assignment.args and not assignment.keywords

    sys.path.insert(0, str(root / "apps/api"))
    sys.path.insert(0, str(root / "packages/basketball-core/src"))
    from app.services.analyst_provider import orchestrator_system_prompt
    from app.services.evidence_contracts import Action

    branch_prompt = orchestrator_system_prompt()
    branch_schema = Action.model_json_schema()
    base_schema = _base_schema(base_sha, root)

    if branch_prompt != base_prompt:
        for index, (a, b) in enumerate(zip(base_prompt, branch_prompt, strict=False)):
            if a != b:
                print(f"first difference at character {index}: base={a!r} branch={b!r}")
                break
        print(f"lengths: base={len(base_prompt)} branch={len(branch_prompt)}")
        raise SystemExit("prompt differs from base")
    if branch_schema != base_schema:
        raise SystemExit("Action schema differs from base")

    report = {
        "base": base_sha,
        "head": head_sha,
        "prompt": {
            "equal": True,
            "sha256": _sha(branch_prompt),
            "characters": len(branch_prompt),
        },
        "action_schema": {
            "equal": True,
            "sha256": _sha(json.dumps(branch_schema, sort_keys=True)),
        },
        "tool_names": list(branch_schema["$defs"]["ToolCall"]["properties"]["name"]["enum"]),
        "branch_assignment": "request_model: system = orchestrator_system_prompt()",
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
