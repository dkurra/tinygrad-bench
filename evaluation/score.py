#!/usr/bin/env python3
"""Score mini-swe-agent predictions against tinygrad-bench tasks.

For each prediction, a fresh offline container reproduces the exact validation
flow: setup at base_commit -> apply the model patch (test-file hunks stripped)
-> apply the gold test patch (which the agent never saw) -> run pytest on the
task's test files.

score = (F2P passed / F2P total) x (P2P passed / P2P total)   in [0, 1]
  - 0 if the patch is empty or does not apply
  - partial credit for partially-working fixes
  - multiplicative penalty for breaking previously-passing tests
resolved = (score == 1.0)  -- SWE-bench-comparable strict metric

Usage:
  python evaluation/score.py --preds results/<model>/preds.json \
      --tasks taskgen/tasks/tinygrad_bench/train.jsonl --workers 4
Writes scores.json next to preds.json.
"""

import argparse
import concurrent.futures
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchlib import PYTEST_CMD, parse_pytest_summary, passed, run_task_container, split_sections

TEST_BUDGET_S = 420

_DIFF_FILE_RE = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)


def strip_test_hunks(patch: str) -> str:
    """Drop per-file diff blocks that touch test/** (agents must not edit tests)."""
    if not patch.strip():
        return patch
    blocks = re.split(r"(?m)^(?=diff --git )", patch)
    kept = []
    for b in blocks:
        m = _DIFF_FILE_RE.match(b)
        if m and m.group(1).startswith("test/"):
            continue
        kept.append(b)
    return "".join(kept)


def score_one(task: dict, model_patch: str) -> dict:
    iid = task["instance_id"]
    base = {"instance_id": iid, "module": task["module"], "difficulty": task["difficulty"]}
    model_patch = strip_test_hunks(model_patch or "")
    if not model_patch.strip():
        return {**base, "score": 0.0, "resolved": False, "status": "empty_patch"}

    files = " ".join(task["test_files"])
    pytest_cmd = PYTEST_CMD.format(budget=TEST_BUDGET_S, files=files)
    script = f"""
git apply --whitespace=nowarn /patches/model.diff || {{ echo ===TGB_APPLY_FAIL===; exit 1; }}
git apply --whitespace=nowarn /patches/test.diff || {{ echo ===TGB_APPLY_FAIL===; exit 1; }}
echo ===TGB_RUN===
{pytest_cmd}
echo ===TGB_DONE===
"""
    rc, out = run_task_container(
        task["base_commit"], script,
        {"model.diff": model_patch, "test.diff": task["test_patch"]},
        timeout=TEST_BUDGET_S + 300,
    )
    sections = split_sections(out)
    if "APPLY_FAIL" in sections:
        return {**base, "score": 0.0, "resolved": False, "status": "patch_apply_failed"}
    if "DONE" not in sections:
        return {**base, "score": 0.0, "resolved": False, "status": f"run_failed rc={rc}"}

    results = parse_pytest_summary(sections.get("RUN", ""))
    ok = passed(results)
    f2p, p2p = set(task["FAIL_TO_PASS"]), set(task["PASS_TO_PASS"])
    f2p_frac = len(f2p & ok) / len(f2p)
    p2p_frac = len(p2p & ok) / len(p2p) if p2p else 1.0
    score = round(f2p_frac * p2p_frac, 4)
    return {
        **base, "score": score, "resolved": score == 1.0, "status": "ok",
        "f2p_passed": len(f2p & ok), "f2p_total": len(f2p),
        "p2p_passed": len(p2p & ok), "p2p_total": len(p2p),
    }


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--preds", required=True)
    ap.add_argument("--tasks", default=str(root / "taskgen/tasks/tinygrad_bench/train.jsonl"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--gold", action="store_true",
                    help="ignore preds and score the gold patches (sanity: all must be 1.0)")
    ap.add_argument("--empty", action="store_true",
                    help="score empty patches (sanity: all must be 0.0)")
    args = ap.parse_args()

    tasks = {t["instance_id"]: t for t in map(json.loads, open(args.tasks))}
    if args.gold or args.empty:
        preds = {iid: {"model_patch": (t["patch"] if args.gold else "")} for iid, t in tasks.items()}
        out_path = Path(args.preds).parent / ("scores_gold.json" if args.gold else "scores_empty.json")
    else:
        preds = json.loads(Path(args.preds).read_text())
        out_path = Path(args.preds).parent / "scores.json"

    existing = json.loads(out_path.read_text()) if out_path.exists() else {}
    todo = [iid for iid in preds if iid in tasks and iid not in existing]
    print(f"scoring {len(todo)} predictions ({len(existing)} cached) -> {out_path}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(score_one, tasks[iid], preds[iid].get("model_patch", "")): iid for iid in todo}
        for fut in concurrent.futures.as_completed(futures):
            iid = futures[fut]
            try:
                existing[iid] = fut.result()
            except Exception as e:  # noqa: BLE001
                existing[iid] = {"instance_id": iid, "score": 0.0, "resolved": False,
                                 "status": f"scorer_exception: {e}"}
            r = existing[iid]
            print(f"  {iid}: {r['score']} ({r['status']})")
            out_path.write_text(json.dumps(existing, indent=2))

    scores = [r["score"] for r in existing.values()]
    if scores:
        print(f"\nmean score: {sum(scores) / len(scores):.4f}  "
              f"resolved: {sum(r['resolved'] for r in existing.values())}/{len(scores)}")


if __name__ == "__main__":
    main()
