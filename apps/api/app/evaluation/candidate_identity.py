"""Public, content-bound identity of the executable candidate worktree."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
_EXECUTABLE_SUFFIXES = {
    ".py",
    ".pyi",
    ".pyc",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".sh",
    ".sql",
    ".so",
    ".pyd",
    ".dll",
    ".dylib",
}
_SOURCE_SUFFIXES = _EXECUTABLE_SUFFIXES | {
    ".toml",
    ".lock",
    ".yaml",
    ".yml",
    ".ini",
    ".conf",
    ".html",
    ".css",
    ".scss",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".woff",
    ".woff2",
}
_SOURCE_NAMES = {
    "Dockerfile",
    "Makefile",
    "justfile",
    "package.json",
    "tsconfig.json",
    ".gitignore",
    ".gitattributes",
}
_EXCLUDED = {
    ".git",
    ".audit",
    ".codex",
    ".github",
    "graphify-out",
    "release-artifacts",
    "rag-artifacts",
    "node_modules",
    ".venv",
    ".pnpm-store",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    "__pycache__",
    "docs",
    "tests",
    "test-results",
}


def _relevant(name: str) -> bool:
    path = Path(name)
    if any(part in _EXCLUDED for part in path.parts):
        return False
    lower = path.name.lower()
    if lower.startswith(".env") or lower.endswith((".pem", ".key", ".p12", ".pfx")):
        return False
    if path.suffix.lower() in _EXECUTABLE_SUFFIXES:
        return True
    if lower.startswith(("secret", "credential")):
        return False
    return (
        path.suffix in _SOURCE_SUFFIXES
        or path.name in _SOURCE_NAMES
        or path.name.startswith("Dockerfile.")
        or (lower.startswith("tsconfig") and path.suffix == ".json")
        or (path.parts[:3] == ("apps", "web", "src") and path.suffix == ".json")
        or (path.parts[:3] == ("apps", "web", "public") and path.suffix == ".json")
        or (
            path.parts[:4] == ("apps", "api", "app", "core")
            and "seed" in path.parts
            and path.suffix == ".json"
        )
    )


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("cannot identify candidate Git worktree") from exc


def candidate_identity(root: Path = ROOT) -> dict[str, Any]:
    """Hash relative names, contents and executable modes; never publish file contents."""
    commit = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    tracked = {os.fsdecode(p) for p in _git(root, "ls-files", "-z").split(b"\0") if p}
    untracked = {
        os.fsdecode(p)
        for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        if p
    }
    # Git ignore rules are not an authority on executable modules: an ignored
    # local Python module can still be imported by the candidate.
    for source_root in ("apps", "packages", "tools", "deploy", "migrations"):
        if (root / source_root).is_symlink():
            raise RuntimeError("candidate source contains a symlink directory")
        for base, dirs, files in os.walk(root / source_root):
            if any((Path(base) / name).is_symlink() for name in dirs if name not in _EXCLUDED):
                raise RuntimeError("candidate source contains a symlink directory")
            dirs[:] = [name for name in dirs if name not in _EXCLUDED]
            for filename in files:
                name = (Path(base) / filename).relative_to(root).as_posix()
                if name not in tracked and _relevant(name):
                    untracked.add(name)
    changed = {
        os.fsdecode(p)
        for p in _git(
            root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD"
        ).split(b"\0")
        if p
    }
    entries = []
    for name in sorted(filter(_relevant, tracked | untracked)):
        path = root / name
        if any(
            (root / Path(*Path(name).parts[:index])).is_symlink()
            for index in range(1, len(Path(name).parts) + 1)
        ):
            raise RuntimeError("candidate source contains a symlink")
        if path.is_file():
            kind = "executable" if path.stat().st_mode & 0o111 else "file"
            content = path.read_bytes()
        else:
            kind, content = "deleted", b""
        entries.append([name, kind, hashlib.sha256(content).hexdigest()])
    source_sha256 = hashlib.sha256(
        json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "commit": commit,
        "source_sha256": source_sha256,
        "dirty": any(_relevant(p) for p in changed | untracked),
    }
