#!/usr/bin/env python3
"""Validate task candidates by executing them in the evaluation container.

For each candidate, one fresh offline container runs three pytest passes over
the PR's changed test files:

  A: base_commit + test_patch            (pre-fix behavior)
  B: base_commit + test_patch + patch    (post-fix behavior)
  C: repeat of B                         (flake detector)

A candidate is verified iff:
  FAIL_TO_PASS := passed(B) & passed(C) - passed(A)  is non-empty
  PASS_TO_PASS := passed(A) & passed(B) & passed(C)
and the pytest passes finish inside the time budget.

Output: verified.jsonl (candidates + F2P/P2P + timing) and rejects.jsonl
(candidate id + reason) for the report's validation-funnel numbers.

Usage:
  python taskgen/validate_tasks.py [--candidates ...] [--workers 4] [--limit N]
"""

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchlib import PYTEST_CMD, parse_pytest_summary, passed, run_task_container, split_sections

TEST_BUDGET_S = 420  # per pytest pass, inside the container


def validate_one(cand: dict) -> dict:
    files = " ".join(cand["test_files"])
    pytest_cmd = PYTEST_CMD.format(budget=TEST_BUDGET_S, files=files)
    script = f"""
git apply --whitespace=nowarn /patches/test.diff || {{ echo ===TGB_APPLY_FAIL===; exit 1; }}
echo ===TGB_RUN_A===
{pytest_cmd}
git apply --whitespace=nowarn /patches/code.diff || {{ echo ===TGB_APPLY_FAIL===; exit 1; }}
echo ===TGB_RUN_B===
{pytest_cmd}
echo ===TGB_RUN_C===
{pytest_cmd}
echo ===TGB_DONE===
"""
    start = time.monotonic()
    rc, out = run_task_container(
        cand["base_commit"], script,
        {"test.diff": cand["test_patch"], "code.diff": cand["patch"]},
        timeout=3 * TEST_BUDGET_S + 300,
    )
    wall_s = round(time.monotonic() - start, 1)
    sections = split_sections(out)

    def reject(reason: str) -> dict:
        return {"pr_number": cand["pr_number"], "verified": False, "reason": reason, "wall_s": wall_s}

    if "TIMEOUT" in sections:
        return reject("container_timeout")
    if "APPLY_FAIL" in sections:
        return reject("patch_apply_failed")
    if "DONE" not in sections:
        return reject(f"setup_or_run_failed rc={rc}: {out[-400:]}")

    res_a = parse_pytest_summary(sections.get("RUN_A", ""))
    res_b = parse_pytest_summary(sections.get("RUN_B", ""))
    res_c = parse_pytest_summary(sections.get("RUN_C", ""))
    stable_pass = passed(res_b) & passed(res_c)
    f2p = sorted(stable_pass - passed(res_a))
    p2p = sorted(passed(res_a) & stable_pass)

    if not f2p:
        return reject("no_fail_to_pass_tests")
    flaky = (passed(res_b) ^ passed(res_c))
    return {
        **cand,
        "verified": True,
        "FAIL_TO_PASS": f2p,
        "PASS_TO_PASS": p2p,
        "n_flaky_dropped": len(flaky),
        "wall_s": wall_s,
    }


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent
    ap.add_argument("--candidates", default=str(root / "tasks/candidates.jsonl"))
    ap.add_argument("--verified-out", default=str(root / "tasks/verified.jsonl"))
    ap.add_argument("--rejects-out", default=str(root / "tasks/rejects.jsonl"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only process first N candidates")
    args = ap.parse_args()

    candidates = [json.loads(l) for l in open(args.candidates)]
    if args.limit:
        candidates = candidates[: args.limit]

    # Resume support: skip PRs already decided.
    done: set[int] = set()
    for path in (args.verified_out, args.rejects_out):
        if Path(path).exists():
            done |= {json.loads(l)["pr_number"] for l in open(path)}
    todo = [c for c in candidates if c["pr_number"] not in done]
    print(f"{len(todo)} candidates to validate ({len(done)} already done)")

    n_ok = n_rej = 0
    with open(args.verified_out, "a") as vf, open(args.rejects_out, "a") as rf:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(validate_one, c): c for c in todo}
            for fut in concurrent.futures.as_completed(futures):
                cand = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:  # noqa: BLE001 - record and move on
                    result = {"pr_number": cand["pr_number"], "verified": False,
                              "reason": f"exception: {e}"}
                if result["verified"]:
                    n_ok += 1
                    vf.write(json.dumps(result) + "\n")
                    vf.flush()
                    print(f"  OK  #{result['pr_number']} f2p={len(result['FAIL_TO_PASS'])} "
                          f"p2p={len(result['PASS_TO_PASS'])} {result['wall_s']}s "
                          f"[{n_ok} ok / {n_rej} rej]")
                else:
                    n_rej += 1
                    rf.write(json.dumps(result) + "\n")
                    rf.flush()
                    print(f"  rej #{result['pr_number']}: {result['reason'][:100]}")

    print(f"done: {n_ok} verified, {n_rej} rejected")


if __name__ == "__main__":
    main()
