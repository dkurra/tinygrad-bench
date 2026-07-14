#!/usr/bin/env python3
"""tinygrad-bench CLI — one front door for the whole benchmark.

  bench leaderboard              ranked results across every evaluated model
  bench tasks [--module M] [--difficulty D]   browse the 100 tasks
  bench inspect <instance|random>             full task card (statement, tests, gold stats)
  bench traj <run> <instance>                 replay an agent trajectory step by step
  bench run <litellm-model> [-w N]            setup + smoke + full run + scoring
  bench sanity                                gold=1.0 / empty=0.0 gate over all tasks
  bench score <run>                           (re)score a run's predictions

Run via ./bench (wrapper) or .venv/bin/python cli.py.
"""

import argparse
import json
import random
import statistics
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

ROOT = Path(__file__).resolve().parent
TASKS_FILE = ROOT / "taskgen/tasks/tinygrad_bench/train.jsonl"
console = Console()


def load_tasks() -> list[dict]:
    return [json.loads(l) for l in open(TASKS_FILE)]


def run_dirs() -> list[Path]:
    return sorted(
        p.parent for p in ROOT.glob("results/*/scores.json")
        if not p.parent.name.startswith(("_", "smoke", "sanity"))
    )


RUN_NAMES = {"A_thinking_high": "gemini-3.1-flash-lite (thinking-high)"}


def pretty_run_name(dirname: str) -> str:
    if dirname in RUN_NAMES:
        return RUN_NAMES[dirname]
    return dirname.replace("openrouter_", "").replace("_", "/", 1)


# ---------------------------------------------------------------- leaderboard

def cmd_leaderboard(_args) -> None:
    rows = []
    for d in run_dirs():
        scores = json.loads((d / "scores.json").read_text())
        if not scores:
            continue
        vals = [r["score"] for r in scores.values()]
        n = len(vals)
        submitted = resolved = 0
        preds = json.loads((d / "preds.json").read_text()) if (d / "preds.json").exists() else {}
        submitted = sum(1 for p in preds.values() if (p.get("model_patch") or "").strip())
        resolved = sum(r["resolved"] for r in scores.values())
        rows.append((statistics.mean(vals), n, resolved, submitted, d.name))

    table = Table(title="tinygrad-bench leaderboard", title_style="bold")
    for col, justify in [("rank", "right"), ("model", "left"), ("n", "right"),
                         ("mean score", "right"), ("resolved", "right"),
                         ("submit rate", "right")]:
        table.add_column(col, justify=justify)
    for i, (mean, n, res, sub, name) in enumerate(sorted(rows, reverse=True), 1):
        partial = " [dim](partial)[/dim]" if n < 100 else ""
        table.add_row(str(i), pretty_run_name(name) + partial, str(n), f"{mean:.3f}",
                      f"{res} ({res / n:.0%})", f"{sub / n:.0%}")
    console.print(table)
    console.print("[dim]mean score in [0,1] = (fail-to-pass fixed) x (pass-to-pass kept); "
                  "resolved = strict 1.0[/dim]")


# ---------------------------------------------------------------- tasks / inspect

def cmd_tasks(args) -> None:
    tasks = load_tasks()
    if args.module:
        tasks = [t for t in tasks if t["module"] == args.module]
    if args.difficulty:
        tasks = [t for t in tasks if t["difficulty"] == args.difficulty]
    table = Table(title=f"{len(tasks)} tasks", title_style="bold")
    for col in ["instance_id", "module", "difficulty", "F2P", "P2P", "gold lines", "PR title"]:
        table.add_column(col)
    for t in tasks:
        table.add_row(t["instance_id"], t["module"], t["difficulty"],
                      str(len(t["FAIL_TO_PASS"])), str(len(t["PASS_TO_PASS"])),
                      str(t["code_lines_changed"]), t["pr_title"][:55])
    console.print(table)


def cmd_inspect(args) -> None:
    tasks = {t["instance_id"]: t for t in load_tasks()}
    t = random.choice(list(tasks.values())) if args.instance == "random" else tasks.get(args.instance)
    if not t:
        console.print(f"[red]unknown instance; try one of {list(tasks)[:3]} or 'random'[/red]")
        sys.exit(1)
    meta = (f"module [bold]{t['module']}[/bold] | difficulty [bold]{t['difficulty']}[/bold] | "
            f"gold fix {t['code_lines_changed']} lines | "
            f"{len(t['FAIL_TO_PASS'])} fail-to-pass + {len(t['PASS_TO_PASS'])} pass-to-pass hidden tests\n"
            f"from PR #{t['pr_number']}: {t['pr_title']}\n"
            f"base commit {t['base_commit'][:12]}")
    console.print(Panel(meta, title=t["instance_id"], border_style="cyan"))
    console.print(Panel(Markdown(t["problem_statement"]), title="problem statement (what the agent sees)"))
    console.print(Panel("\n".join(t["FAIL_TO_PASS"][:8]) +
                        ("\n..." if len(t["FAIL_TO_PASS"]) > 8 else ""),
                        title="hidden fail-to-pass tests (agent never sees these)",
                        border_style="yellow"))
    if args.gold:
        console.print(Panel(Syntax(t["patch"][:4000], "diff", theme="ansi_dark"),
                            title="gold patch (spoiler!)", border_style="red"))


# ---------------------------------------------------------------- trajectory replay

def cmd_traj(args) -> None:
    d = ROOT / "results" / args.run
    if not d.exists():
        matches = [p.name for p in run_dirs() if args.run in p.name]
        if len(matches) == 1:
            d = ROOT / "results" / matches[0]
        else:
            console.print(f"[red]unknown run; available: {[p.name for p in run_dirs()]}[/red]")
            sys.exit(1)
    traj_file = d / args.instance / f"{args.instance}.traj.json"
    if not traj_file.exists():
        console.print(f"[red]no trajectory for {args.instance} in {d.name}[/red]")
        sys.exit(1)
    data = json.loads(traj_file.read_text())
    info = data.get("info", {})
    scores = json.loads((d / "scores.json").read_text()) if (d / "scores.json").exists() else {}
    verdict = scores.get(args.instance, {})
    console.print(Panel(
        f"exit: [bold]{info.get('exit_status')}[/bold] | "
        f"score: [bold]{verdict.get('score', '?')}[/bold] ({verdict.get('status', 'unscored')})",
        title=f"{pretty_run_name(d.name)} on {args.instance}", border_style="cyan"))

    step = 0
    for m in data.get("messages", []):
        role, content = m.get("role"), m.get("content")
        if role == "assistant":
            step += 1
            text = content if isinstance(content, str) else ""
            calls = m.get("tool_calls") or []
            cmds = []
            for c in calls:
                try:
                    cmds.append(json.loads(c["function"]["arguments"]).get("command", ""))
                except Exception:  # noqa: BLE001
                    cmds.append(str(c)[:200])
            body = (text.strip()[: args.chars] + "\n" if text and text.strip() else "")
            for cmd in cmds:
                body += f"[bold green]$ {cmd[: args.chars]}[/bold green]\n"
            console.print(Panel(body.rstrip() or "[dim](no content)[/dim]",
                                title=f"step {step}", border_style="blue"))
        elif role == "tool" and not args.quiet:
            text = content if isinstance(content, str) else json.dumps(content)
            console.print(Panel((text or "").strip()[: args.chars], style="dim",
                                title="observation", border_style="dim"))
        elif role == "exit":
            console.print(Panel(str(content)[:500], title="exit", border_style="red"))


# ---------------------------------------------------------------- run / score / sanity

def cmd_run(args) -> None:
    sys.exit(subprocess.run([str(ROOT / "run.sh"), args.model, str(args.workers)]).returncode)


def cmd_score(args) -> None:
    preds = ROOT / "results" / args.run / "preds.json"
    sys.exit(subprocess.run([sys.executable, str(ROOT / "evaluation/score.py"),
                             "--preds", str(preds)]).returncode)


def cmd_sanity(_args) -> None:
    (ROOT / "results/sanity").mkdir(parents=True, exist_ok=True)
    for mode in ("--empty", "--gold"):
        rc = subprocess.run([sys.executable, str(ROOT / "evaluation/score.py"),
                             "--preds", str(ROOT / "results/sanity/preds.json"), mode]).returncode
        if rc:
            sys.exit(rc)


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("leaderboard", help="ranked results table").set_defaults(fn=cmd_leaderboard)

    p = sub.add_parser("tasks", help="browse the 100 tasks")
    p.add_argument("--module"), p.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    p.set_defaults(fn=cmd_tasks)

    p = sub.add_parser("inspect", help="show one task in full")
    p.add_argument("instance", help="instance_id or 'random'")
    p.add_argument("--gold", action="store_true", help="also reveal the gold patch")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("traj", help="replay an agent trajectory")
    p.add_argument("run", help="results/ dir name (or unique substring, e.g. glm)")
    p.add_argument("instance")
    p.add_argument("--quiet", action="store_true", help="hide tool observations")
    p.add_argument("--chars", type=int, default=600, help="truncate blocks to N chars")
    p.set_defaults(fn=cmd_traj)

    p = sub.add_parser("run", help="setup + smoke + full benchmark run for a model")
    p.add_argument("model"), p.add_argument("-w", "--workers", type=int, default=4)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("score", help="(re)score a run")
    p.add_argument("run")
    p.set_defaults(fn=cmd_score)

    sub.add_parser("sanity", help="gold=1.0 / empty=0.0 gate").set_defaults(fn=cmd_sanity)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
