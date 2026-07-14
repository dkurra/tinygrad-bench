#!/usr/bin/env python3
"""Mine merged tinygrad PRs into task candidates.

Works entirely from a local clone: tinygrad squash-merges every PR onto
master with a "<title> (#<number>)" subject, so first-parent history
enumerates merged PRs and `git diff` reconstructs each PR's change.

For each candidate we keep:
  - base_commit  (parent of the squash commit = repo state the PR applied to)
  - patch        (the PR's changes restricted to tinygrad/**)
  - test_patch   (the PR's changes restricted to test/**)

A PR qualifies as a candidate when it changes both production code and
tests, within a size band that excludes typo-fixes and mega-refactors.
Semantic correctness (fail-to-pass behavior) is established later by
validate_tasks.py inside Docker; this stage only needs cheap filters.

Usage:
  python taskgen/mine_prs.py --repo .cache/tinygrad --since 2024-07-01 \
      --out taskgen/tasks/candidates.jsonl [--limit 400]
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

PR_SUBJECT_RE = re.compile(r"\(#(\d+)\)$")
# Subjects that indicate changes unlikely to make good tasks.
SKIP_SUBJECT_RE = re.compile(
    r"revert|bump|hotfix ci|\bci\b|typo|readme|docs?:|benchmark|mlperf|viz:|update version",
    re.IGNORECASE,
)

CODE_PREFIX = "tinygrad/"
TEST_PREFIX = "test/"


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True
    ).stdout


def list_merged_prs(repo: str, since: str) -> list[dict]:
    """First-parent master commits that came from a PR squash-merge."""
    out = git(
        repo, "log", "--first-parent", "master", f"--since={since}",
        "--format=%H%x00%ct%x00%s",
    )
    prs = []
    for line in out.splitlines():
        sha, ts, subject = line.split("\x00", 2)
        m = PR_SUBJECT_RE.search(subject)
        if m:
            prs.append(
                {"sha": sha, "timestamp": int(ts), "subject": subject, "pr_number": int(m.group(1))}
            )
    return prs


def changed_files(repo: str, sha: str) -> list[tuple[str, int, int]]:
    """(path, added, deleted) for sha vs its first parent. Binary files get -1 counts."""
    out = git(repo, "diff", "--numstat", "--no-renames", f"{sha}^", sha)
    files = []
    for line in out.splitlines():
        added, deleted, path = line.split("\t", 2)
        files.append(
            (path, int(added) if added != "-" else -1, int(deleted) if deleted != "-" else -1)
        )
    return files


def classify(pr: dict, files: list[tuple[str, int, int]], args) -> dict | None:
    """Apply cheap structural filters; return candidate record or None."""
    if SKIP_SUBJECT_RE.search(pr["subject"]):
        return None

    code_files = [f for f in files if f[0].startswith(CODE_PREFIX) and f[0].endswith(".py")]
    test_files = [f for f in files if f[0].startswith(TEST_PREFIX) and f[0].endswith(".py")]
    if not code_files or not test_files:
        return None
    # Binary or unparseable changes in the parts we score on -> skip.
    if any(a < 0 for _, a, _ in code_files + test_files):
        return None
    # Environment-affecting files make base_commit installs unpredictable.
    if any(f[0] in ("setup.py", "pyproject.toml", "requirements.txt") for f in files):
        return None

    code_lines = sum(a + d for _, a, d in code_files)
    test_added = sum(a for _, a, _ in test_files)
    if not (args.min_code_lines <= code_lines <= args.max_code_lines):
        return None
    if len(code_files) > args.max_code_files:
        return None
    if test_added < 3:  # tests must meaningfully change to yield fail-to-pass cases
        return None

    # Module label (top-level package dir) for stratification later.
    parts = code_files[0][0].split("/")
    module = parts[1] if len(parts) > 2 else "core"

    return {
        "pr_number": pr["pr_number"],
        "subject": pr["subject"],
        "merge_commit": pr["sha"],
        "timestamp": pr["timestamp"],
        "code_files": [f[0] for f in code_files],
        "test_files": [f[0] for f in test_files],
        "code_lines_changed": code_lines,
        "module": module,
    }


def extract_patches(repo: str, cand: dict) -> None:
    sha = cand["merge_commit"]
    cand["base_commit"] = git(repo, "rev-parse", f"{sha}^").strip()
    cand["patch"] = git(repo, "diff", "--no-renames", f"{sha}^", sha, "--", *cand["code_files"])
    cand["test_patch"] = git(repo, "diff", "--no-renames", f"{sha}^", sha, "--", *cand["test_files"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".cache/tinygrad")
    ap.add_argument("--since", default="2024-07-01")
    ap.add_argument("--out", default="taskgen/tasks/candidates.jsonl")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--min-code-lines", type=int, default=2)
    ap.add_argument("--max-code-lines", type=int, default=400)
    ap.add_argument("--max-code-files", type=int, default=8)
    args = ap.parse_args()

    prs = list_merged_prs(args.repo, args.since)
    print(f"{len(prs)} merged PRs on master since {args.since}")

    candidates = []
    for pr in prs:  # newest first
        try:
            files = changed_files(args.repo, pr["sha"])
        except subprocess.CalledProcessError:
            continue  # e.g. root commit
        cand = classify(pr, files, args)
        if cand is None:
            continue
        extract_patches(args.repo, cand)
        if not cand["patch"].strip() or not cand["test_patch"].strip():
            continue
        candidates.append(cand)
        if len(candidates) >= args.limit:
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for c in candidates:
            f.write(json.dumps(c) + "\n")

    by_module: dict[str, int] = {}
    for c in candidates:
        by_module[c["module"]] = by_module.get(c["module"], 0) + 1
    print(f"kept {len(candidates)} candidates -> {out}")
    print("by module:", dict(sorted(by_module.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
