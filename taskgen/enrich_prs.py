#!/usr/bin/env python3
"""Fetch PR bodies and linked-issue text for verified tasks via the GitHub API.

Only verified candidates are enriched (a few hundred requests, well within
authenticated rate limits). Requires `gh auth login`.

Usage: python taskgen/enrich_prs.py [--verified taskgen/tasks/verified.jsonl]
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ISSUE_RE = re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)


def gh_api(path: str) -> dict | None:
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    ap.add_argument("--verified", default=str(root / "tasks/verified.jsonl"))
    ap.add_argument("--out", default=str(root / "tasks/enriched.jsonl"))
    args = ap.parse_args()

    done = set()
    if Path(args.out).exists():
        done = {json.loads(l)["pr_number"] for l in open(args.out)}

    tasks = [json.loads(l) for l in open(args.verified)]
    with open(args.out, "a") as f:
        for i, t in enumerate(tasks):
            n = t["pr_number"]
            if n in done:
                continue
            pr = gh_api(f"repos/tinygrad/tinygrad/pulls/{n}")
            rec = {"pr_number": n, "pr_title": None, "pr_body": None, "issues": []}
            if pr:
                rec["pr_title"] = pr.get("title")
                rec["pr_body"] = pr.get("body")
                for m in ISSUE_RE.finditer(pr.get("body") or ""):
                    issue = gh_api(f"repos/tinygrad/tinygrad/issues/{m.group(1)}")
                    if issue and "pull_request" not in issue:
                        rec["issues"].append(
                            {"number": issue["number"], "title": issue["title"], "body": issue["body"]}
                        )
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if (i + 1) % 25 == 0:
                print(f"{i + 1}/{len(tasks)}")
    print("done")


if __name__ == "__main__":
    main()
