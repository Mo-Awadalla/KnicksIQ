"""Exercise real git commits, recording evidence without touching the caller's index.

Failure cases: off-by-one limits; counting characters instead of bytes; checking
worktree contents instead of the index; scanning unstaged/unchanged files; rejecting
lockfiles, codegen, vendored files, binary assets, deletions, symlinks or gitlinks;
missing renamed files or unusual filenames; honoring unstaged exclusion changes;
reporting only one offender; failing on an unborn branch or from a subdirectory.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = []
ENV = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=ENV, capture_output=True, check=check
    )


def verify(name, files, blocked=False, after_stage=None, before=None, messages=()):
    with tempfile.TemporaryDirectory(prefix="token-hook-e2e-") as directory:
        repo = Path(directory)
        git(repo, "init", "--quiet", "--template=")
        git(repo, "config", "user.name", "Hook E2E")
        git(repo, "config", "user.email", "hook-e2e@example.invalid")
        git(repo, "config", "commit.gpgsign", "false")
        git(repo, "config", "core.hooksPath", str(ROOT / ".githooks"))
        if (ROOT / ".gitattributes").exists():
            shutil.copyfile(ROOT / ".gitattributes", repo / ".gitattributes")
        if before:
            before(repo)
        for name_in_repo, content in files.items():
            path = repo / name_in_repo
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        git(repo, "add", "--all")
        if after_stage:
            after_stage(repo)
        nested = repo / "nested"
        nested.mkdir(exist_ok=True)
        result = git(nested, "commit", "--quiet", "--allow-empty", "-m", name, check=False)
        output = (result.stdout + result.stderr).decode(errors="replace")
        passed = (result.returncode != 0) == blocked and all(
            message in output for message in messages
        )
        RESULTS.append(
            {
                "scenario": name,
                "expected": "blocked" if blocked else "allowed",
                "exit_code": result.returncode,
                "passed": passed,
                "output": output,
            }
        )
        print(f"{'PASS' if passed else 'FAIL'} {name}")


def seed(repo):
    (repo / "old.py").write_bytes(b"x" * 20001)
    git(repo, "add", "--all")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "seed")


def rename(repo):
    git(repo, "mv", "old.py", "renamed.py")


def delete(repo):
    git(repo, "rm", "--quiet", "old.py")


def non_regular(repo):
    (repo / "link.py").symlink_to("old.py")
    git(repo, "add", "link.py")
    commit = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},submodule")


def unstaged_exclusion(repo):
    with (repo / ".gitattributes").open("a") as stream:
        stream.write("\nlarge.py linguist-generated=true\n")


def main():
    large = b"x" * 20001
    verify(
        "over limit on initial commit",
        {"large.py": large},
        True,
        messages=(
            "large.py",
            "20,001",
            "5,000",
            "Split",
            "git add",
        ),
    )
    verify("exactly 5000 tokens", {"boundary.py": b"x" * 20000})
    verify("UTF-8 bytes rather than characters", {"unicode.md": ("é" * 10001).encode()}, True)
    verify(
        "staged large worktree small",
        {"partial.py": large},
        True,
        after_stage=lambda repo: (repo / "partial.py").write_text("small"),
    )
    verify(
        "staged small worktree large",
        {"partial.py": b"small"},
        after_stage=lambda repo: (repo / "partial.py").write_bytes(large),
    )
    verify(
        "unstaged new file ignored",
        {},
        after_stage=lambda repo: (repo / "untracked.py").write_bytes(large),
    )
    verify("unchanged oversized file ignored", {"small.py": b"small"}, before=seed)
    verify(
        "lockfiles excluded",
        {
            path: large
            for path in (
                "uv.lock",
                "apps/web/pnpm-lock.yaml",
                "package-lock.json",
                "yarn.lock",
                "bun.lock",
                "Cargo.lock",
                "poetry.lock",
                "Pipfile.lock",
                "go.sum",
            )
        },
    )
    verify(
        "generated and vendored paths excluded",
        {
            path: large
            for path in (
                "apps/web/src/routeTree.gen.ts",
                "src/client.generated.py",
                "src/generated/api.py",
                "vendor/dependency.py",
                "node_modules/dependency.js",
                "graphify-out/graph.json",
                "dist/bundle.js",
                "release-artifacts/bundle.json",
                "rag-artifacts/index.json",
            )
        },
    )
    verify(
        "staged generated attribute",
        {
            ".gitattributes": b"custom.py linguist-generated=true\n",
            "custom.py": large,
        },
    )
    verify(
        "staged vendored attribute",
        {
            ".gitattributes": b"custom.py linguist-vendored=true\n",
            "custom.py": large,
        },
    )
    verify(
        "unstaged exclusion cannot bypass limit",
        {"large.py": large},
        True,
        after_stage=unstaged_exclusion,
    )
    verify("binary asset excluded", {"asset.bin": b"\x00" + large})
    verify("symlinks and gitlinks ignored", {}, before=seed, after_stage=non_regular)
    verify("deletion ignored", {}, before=seed, after_stage=delete)
    verify("rename checked", {}, True, before=seed, after_stage=rename, messages=("renamed.py",))
    verify(
        "unusual filenames and every offender",
        {
            "space name.py": large,
            "tab\tname.py": large,
            "line\nname.py": large,
        },
        True,
        messages=("space name.py", "tab\\tname.py", "line\\nname.py"),
    )
    verify(
        "generated word in authored filename still checked",
        {
            "generated_stat_fact.py": large,
        },
        True,
    )
    destination = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "release-artifacts/hooks/e2e.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(RESULTS, indent=2) + "\n")
    print(f"Evidence: {destination}")
    return 0 if all(result["passed"] for result in RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
