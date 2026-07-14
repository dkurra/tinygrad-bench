#!/usr/bin/env python3
"""Aggregate benchmark results across all configs/models in results/.

Reads results/<name>/scores.json (+ trajectories for steps/exit stats) and the
task metadata, prints per-config summaries and breakdowns, and writes
results/summary.md for the report.

Usage: .venv/bin/python evaluation/aggregate.py
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "taskgen/tasks/tinygrad_bench/train.jsonl"


def traj_stats(out_dir: Path, iid: str) -> dict:
    traj = out_dir / iid / f"{iid}.traj.json"
    if not traj.exists():
        return {}
    data = json.loads(traj.read_text())
    info = data.get("info", {}) or {}
    msgs = data.get("messages", []) or []
    return {
        "steps": sum(1 for m in msgs if m.get("role") == "assistant"),
        "exit_status": info.get("exit_status") or "unknown",
        "cost": (info.get("model_stats") or {}).get("cost"),
    }


def fmt_mean(vals: list) -> str:
    vals = [v for v in vals if v is not None]
    return f"{statistics.mean(vals):.3f}" if vals else "-"


def main():
    tasks = {t["instance_id"]: t for t in map(json.loads, open(TASKS))}
    lines = ["# tinygrad-bench results\n"]
    header = ("| config | n | mean score | resolved | apply-fail | mean steps | "
              "easy | medium | hard |")
    lines += [header, "|" + "---|" * 9]

    detail_blocks = []
    for score_file in sorted(ROOT.glob("results/*/scores.json")):
        name = score_file.parent.name
        if name.startswith(("_", "smoke", "sanity")):
            continue
        scores = json.loads(score_file.read_text())
        rows = list(scores.values())
        if not rows:
            continue
        stats = {iid: traj_stats(score_file.parent, iid) for iid in scores}

        by_diff = defaultdict(list)
        by_module = defaultdict(list)
        for r in rows:
            t = tasks.get(r["instance_id"], {})
            by_diff[t.get("difficulty", "?")].append(r["score"])
            by_module[t.get("module", "?")].append(r["score"])

        n = len(rows)
        mean = statistics.mean(r["score"] for r in rows)
        resolved = sum(r["resolved"] for r in rows)
        apply_fail = sum(r["status"] == "patch_apply_failed" for r in rows)
        steps = fmt_mean([s.get("steps") for s in stats.values()])
        lines.append(
            f"| {name} | {n} | {mean:.3f} | {resolved} ({resolved / n:.0%}) | "
            f"{apply_fail} | {steps} | "
            f"{fmt_mean(by_diff.get('easy', []))} | {fmt_mean(by_diff.get('medium', []))} | "
            f"{fmt_mean(by_diff.get('hard', []))} |"
        )

        exits = defaultdict(int)
        for s in stats.values():
            exits[s.get("exit_status", "unknown")] += 1
        mods = ", ".join(f"{m}: {fmt_mean(v)} (n={len(v)})"
                         for m, v in sorted(by_module.items(), key=lambda kv: -len(kv[1])))
        costs = [s.get("cost") for s in stats.values() if s.get("cost")]
        detail_blocks += [
            f"\n## {name}",
            f"- exit statuses: {dict(exits)}",
            f"- by module: {mods}",
            f"- total reported API cost: ${sum(costs):.2f}" if costs else "- cost: n/a",
        ]

    out = "\n".join(lines + detail_blocks) + "\n"
    (ROOT / "results/summary.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
