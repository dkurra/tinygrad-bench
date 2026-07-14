#!/usr/bin/env python3
"""Drive the full free-tier benchmark: 3 flash-lite configs x 100 tasks.

The free Gemini tier allows ~15 requests/min and ~1,000-1,500 requests/day, so a
config (~1-2k agent LLM calls) cannot finish in one sitting. This orchestrator:

  1. runs `mini-extra swebench` for each config (resume-aware: existing preds skipped)
  2. after each pass, prunes preds.json entries that failed on API errors
     (rate limit / 5xx) so they are retried -- genuine agent outcomes are kept
  3. when the daily quota is exhausted, sleeps and probes until it resets
  4. when a config has a genuine prediction for every task, scores it

Safe to interrupt and restart at any time. Requires GEMINI_API_KEY in ../.env.

Usage: .venv/bin/python evaluation/run_free_tier.py [--workers 2]
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemini/gemini-3.1-flash-lite"
TASKS = ROOT / "taskgen/tasks/tinygrad_bench/train.jsonl"

CONFIGS = {
    "A_thinking_high": ["-c", "model.model_kwargs.reasoning_effort=high"],
    "B_no_thinking": [],
    "C_budget_10steps": ["-c", "agent.step_limit=10"],
}

# exit statuses that mean "the API failed us", not "the agent failed the task"
RETRYABLE = ("RateLimitError", "InternalServerError", "ServiceUnavailableError",
             "APIConnectionError", "APIError", "Timeout", "BadRequestError",
             "RetryError", "JSONDecodeError")


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def quota_available() -> bool:
    """Tiny probe request; False only on quota/availability errors."""
    import litellm
    try:
        litellm.completion(model=MODEL, max_tokens=10,
                           messages=[{"role": "user", "content": "hi"}])
        return True
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        print(f"  quota probe: {name}: {str(e)[:120]}")
        return name not in ("RateLimitError", "ServiceUnavailableError", "InternalServerError")


def prune_failed(out_dir: Path) -> tuple[int, int]:
    """Remove API-failure entries from preds.json; return (kept, pruned)."""
    preds_path = out_dir / "preds.json"
    if not preds_path.exists():
        return 0, 0
    preds = json.loads(preds_path.read_text())
    pruned = 0
    for iid in list(preds):
        traj = out_dir / iid / f"{iid}.traj.json"
        exit_status = ""
        if traj.exists():
            exit_status = (json.loads(traj.read_text()).get("info", {}) or {}).get("exit_status") or ""
        patch = preds[iid].get("model_patch") or ""
        if any(t in exit_status for t in RETRYABLE) and not patch.strip():
            del preds[iid]
            pruned += 1
    preds_path.write_text(json.dumps(preds, indent=2))
    return len(preds), pruned


def run_config(name: str, extra: list[str], workers: int) -> None:
    out_dir = ROOT / "results" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    n_tasks = sum(1 for _ in open(TASKS))

    while True:
        kept, _ = prune_failed(out_dir)
        if kept >= n_tasks:
            break
        print(f"[{name}] {kept}/{n_tasks} done; launching agent batch...")
        subprocess.run(
            [str(ROOT / ".venv/bin/mini-extra"), "swebench",
             "--subset", str(TASKS.parent), "--split", "train",
             "-c", str(ROOT / "evaluation/tinygrad.yaml"), *extra,
             "-m", MODEL, "-w", str(workers), "-o", str(out_dir)],
            cwd=ROOT, env=os.environ | {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "30"},
        )
        kept, pruned = prune_failed(out_dir)
        print(f"[{name}] pass finished: {kept}/{n_tasks} genuine, {pruned} pruned for retry")
        if kept >= n_tasks:
            break
        while not quota_available():
            print(f"[{name}] quota exhausted; sleeping 30 min ({time.strftime('%H:%M')})")
            time.sleep(1800)

    print(f"[{name}] complete -> scoring")
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "evaluation/score.py"),
         "--preds", str(out_dir / "preds.json"), "--workers", "4"],
        cwd=ROOT, check=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1,
                    help="agent threads (free tier: 1 avoids token-per-minute collisions)")
    ap.add_argument("--configs", nargs="*", default=list(CONFIGS))
    args = ap.parse_args()
    load_env()
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY missing (put it in .env)"
    assert TASKS.exists(), f"{TASKS} not built yet"
    for name in args.configs:
        run_config(name, CONFIGS[name], args.workers)
    print("ALL CONFIGS COMPLETE")


if __name__ == "__main__":
    main()
