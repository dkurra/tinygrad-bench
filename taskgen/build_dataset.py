#!/usr/bin/env python3
"""Select the final benchmark tasks and generate leakage-aware problem statements.

Selection: stratified across (module, difficulty) by round-robin so no single
subsystem or size class dominates, newest PRs first within each stratum.

Problem statements: written by Gemini from the PR title/body, linked-issue text,
and the gold patches (as context only). The generator is instructed to describe
observable behavior and required API semantics precisely enough that the hidden
fail-to-pass tests are satisfiable, without revealing where the fix goes, the
diff itself, or the test code. AI use here is declared in the report.

Usage:
  GEMINI_API_KEY in env or ../.env
  python taskgen/build_dataset.py --n 100 --spares 10
"""

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import litellm

MODEL = "gemini/gemini-3.1-flash-lite"  # only text model reachable on the free-tier key

SYSTEM = """You write evaluation task prompts for a coding benchmark built from real merged
pull requests of the tinygrad repository (a small deep-learning framework).

Given a PR's title, body, optional linked issues, its code diff, and its test diff, write a
GitHub-issue-style problem statement that a software engineer (or coding agent) will receive
along with a checkout of the repository at the commit just BEFORE this PR was merged. Their
patch is graded by the PR's (hidden) new/updated tests.

Requirements for the problem statement:
- Style: a well-written bug report or feature request from a knowledgeable tinygrad user.
  Plain markdown. No headers echoing these instructions.
- It must contain enough precise information that the hidden tests are satisfiable:
  state observable current behavior vs expected behavior; if the PR introduces or changes a
  public API (function/method/class/argument names, semantics, defaults, error types), spell
  those names and semantics out exactly, since the tests call them.
- Include a minimal repro snippet or concrete example when it helps pin down semantics.
- Do NOT: reveal which files/functions to modify, include or paraphrase the diff hunks,
  mention the tests, test files or test names, or mention that this comes from a PR.
- Length: typically 80-300 words.

Return only the problem statement text."""


def difficulty(t: dict) -> str:
    n = t["code_lines_changed"]
    return "easy" if n <= 25 else ("medium" if n <= 100 else "hard")


def select(tasks: list[dict], n: int) -> list[dict]:
    """Round-robin over (module, difficulty) strata, newest first within each."""
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for t in sorted(tasks, key=lambda t: -t["timestamp"]):
        strata[(t["module"], difficulty(t))].append(t)
    order = sorted(strata, key=lambda k: -len(strata[k]))
    picked: list[dict] = []
    while len(picked) < n and any(strata.values()):
        for key in order:
            if strata[key] and len(picked) < n:
                picked.append(strata[key].pop(0))
    return picked


def truncate(s: str | None, limit: int) -> str:
    s = (s or "").strip()
    return s[:limit] + ("\n[...truncated]" if len(s) > limit else "")


def gen_statement(task: dict, meta: dict) -> str:
    issues = "\n\n".join(
        f"Linked issue #{i['number']}: {i['title']}\n{truncate(i['body'], 3000)}"
        for i in meta.get("issues", [])
    )
    user = f"""PR title: {meta.get('pr_title') or task['subject']}

PR body:
{truncate(meta.get('pr_body'), 3000) or '(empty)'}

{issues or '(no linked issues)'}

Code diff (context only -- never reveal):
{truncate(task['patch'], 12000)}

Test diff (context only -- never reveal; the hidden tests come from here):
{truncate(task['test_patch'], 12000)}"""
    last_err: Exception = RuntimeError("no attempts")
    for attempt in range(6):  # free tier: 15 RPM, occasional 429/503
        try:
            resp = litellm.completion(
                model=MODEL, max_tokens=4000, reasoning_effort="high",
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": user}],
            )
            text = (resp.choices[0].message.content or "").strip()
            if len(text) < 100:
                raise RuntimeError(f"statement too short: {text[:80]!r}")
            return text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(min(10 * 2**attempt, 120))
    raise last_err


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    ap.add_argument("--verified", default=str(root / "tasks/verified.jsonl"))
    ap.add_argument("--enriched", default=str(root / "tasks/enriched.jsonl"))
    ap.add_argument("--out", default=str(root / "tasks/tinygrad_bench/train.jsonl"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--spares", type=int, default=10)
    args = ap.parse_args()

    # Load GEMINI_API_KEY from ../.env if not already in the environment.
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    verified = [json.loads(l) for l in open(args.verified)]
    enriched = {json.loads(l)["pr_number"]: json.loads(l) for l in open(args.enriched)}
    picked = select(verified, args.n + args.spares)
    print(f"selected {len(picked)} of {len(verified)} verified tasks")

    # Statements are quota-bound (free tier) -> cache them for resumability.
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    stmt_cache = Path(args.out).parent / "statements.jsonl"
    statements: dict[int, str] = {}
    if stmt_cache.exists():
        statements = {json.loads(l)["pr_number"]: json.loads(l)["statement"] for l in open(stmt_cache)}

    def build(t: dict) -> dict | None:
        meta = enriched.get(t["pr_number"], {})
        if t["pr_number"] in statements:
            statement = statements[t["pr_number"]]
        else:
            try:
                statement = gen_statement(t, meta)
            except Exception as e:  # noqa: BLE001
                print(f"  statement failed for #{t['pr_number']}: {e}")
                return None
            with stmt_cache.open("a") as sf:
                sf.write(json.dumps({"pr_number": t["pr_number"], "statement": statement}) + "\n")
            time.sleep(4.5)  # stay under 15 requests/min
        return {
            "instance_id": f"tinygrad__tinygrad-{t['pr_number']}",
            "repo": "tinygrad/tinygrad",
            "image_name": "tinygrad-bench:base",
            "base_commit": t["base_commit"],
            "problem_statement": statement,
            "patch": t["patch"],
            "test_patch": t["test_patch"],
            "FAIL_TO_PASS": t["FAIL_TO_PASS"],
            "PASS_TO_PASS": t["PASS_TO_PASS"],
            "test_files": t["test_files"],
            "module": t["module"],
            "difficulty": difficulty(t),
            "code_lines_changed": t["code_lines_changed"],
            "pr_number": t["pr_number"],
            "pr_title": meta.get("pr_title") or t["subject"],
            "statement_source": "issue+pr" if meta.get("issues") else "pr",
        }

    rows = []
    for t in picked:
        row = build(t)
        if row:
            rows.append(row)
            print(f"  ok {row['instance_id']} [{len(rows)}]")

    rows = rows[: args.n]
    with open(args.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    by = defaultdict(int)
    for r in rows:
        by[(r["module"], r["difficulty"])] += 1
    print(f"wrote {len(rows)} tasks -> {args.out}")
    print(dict(sorted(by.items())))


if __name__ == "__main__":
    main()
