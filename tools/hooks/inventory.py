"""List existing authored files above the hook limit, including untracked source.

Usage: python3 tools/hooks/inventory.py [evidence.json]
Uses worktree contents and attributes; the pre-commit hook checks the index.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def inventory():
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    os.chdir(root)
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    ).split(b"\0")
    candidates = {}
    for raw in paths:
        if not raw:
            continue
        path = Path(os.fsdecode(raw))
        if path.is_file() and not path.is_symlink():
            size = path.stat().st_size
            if size > 20000:
                candidates[raw] = size
    attrs = subprocess.check_output(
        ["git", "check-attr", "-z", "--stdin", "linguist-generated", "linguist-vendored"],
        input=b"".join(path + b"\0" for path in candidates),
    ).split(b"\0")
    excluded = {
        attrs[index]
        for index in range(0, len(attrs) - 1, 3)
        if attrs[index + 2] in (b"set", b"true")
    }
    oversized = []
    for raw, size in sorted(candidates.items()):
        if raw in excluded:
            continue
        path = Path(os.fsdecode(raw))
        with path.open("rb") as stream:
            if b"\0" in stream.read(8000):
                continue
        oversized.append({"path": str(path), "bytes": size, "tokens": size / 4})
    return {"limit_bytes": 20000, "oversized": oversized}


def main():
    report = inventory()
    for entry in report["oversized"]:
        print(f"{entry['bytes']:>9,} bytes  {entry['path']}")
    print(f"{len(report['oversized'])} authored files exceed 20,000 bytes.")
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n")
    return bool(report["oversized"])


if __name__ == "__main__":
    raise SystemExit(main())
