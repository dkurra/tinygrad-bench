# tinygrad-bench

An automatically-generated, automatically-scored coding-agent benchmark built from
[tinygrad](https://github.com/tinygrad/tinygrad) (11.9k merged PRs). **100
SWE-bench-style tasks** mined from real merged PRs, each execution-verified in Docker to
have genuine fail-to-pass tests, scored in [0, 1], and evaluated with
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) across 5 models
(best: glm-5.2 at 0.351 mean / 34% resolved — comfortably unsaturated).

**GitHub:** https://github.com/dkurra/tinygrad-bench (live version of this submission)

See `REPORT.md` for design, results, and limitations. `chat_logs/` contains the AI-use
transcript.

## Explore with the CLI

After the quickstart's venv exists, `./bench` gives you the whole benchmark in one tool:

```bash
./bench leaderboard                     # ranked results across all evaluated models
./bench tasks --difficulty hard        # browse/filter the 100 tasks
./bench inspect random                 # full task card; --gold reveals the real fix
./bench traj glm tinygrad__tinygrad-16999   # replay an agent run step by step
./bench run openrouter/z-ai/glm-5.2 -w 8    # evaluate a new model end to end
./bench sanity                         # gold=1.0 / empty=0.0 gate
```

## Layout

```
cli.py / bench               the CLI above
run.sh                       one-command setup + run (used by `bench run`)
benchlib.py                  shared container-run + pytest-parsing helpers
environment/Dockerfile.base  single evaluation image (per-task state via startup command)
taskgen/mine_prs.py          local-git PR mining -> candidates.jsonl
taskgen/validate_tasks.py    Docker validation (F2P/P2P/flake) -> verified.jsonl
taskgen/enrich_prs.py        GitHub API: PR bodies + linked issues (needs `gh auth login`)
taskgen/build_dataset.py     stratified selection + LLM-written problem statements
taskgen/tasks/tinygrad_bench/train.jsonl   the final 100-task dataset (ships in repo)
evaluation/tinygrad.yaml     mini-swe-agent run config (offline containers, limits)
evaluation/run_benchmark.sh  run + score any litellm model, one command
evaluation/run_free_tier.py  quota-aware orchestrator for free-tier API keys ($0 path)
evaluation/score.py          patch -> score in [0,1] (also --gold/--empty sanity modes)
evaluation/aggregate.py      results tables (results/summary.md)
results/                     preds, trajectories, scores per model
```

## Quickstart: one command

Prereqs: docker (macOS: `brew install colima docker && colima start`) and
[uv](https://docs.astral.sh/uv/). The 100-task dataset ships in the repo. Then:

```bash
OPENROUTER_API_KEY=sk-or-...  ./run.sh openrouter/z-ai/glm-5.2 8
```

That single command creates the venv, builds the Docker image, saves the key to `.env`,
smoke-tests 2 tasks, runs all 100, scores every patch in [0,1], and writes
`results/summary.md`. Any litellm model id works (`openrouter/...`, `gemini/...`,
`anthropic/...` — pass the matching `*_API_KEY`). Everything is resume-aware: re-running
the same command skips finished instances.

Piecemeal equivalents, if you prefer:

```bash
evaluation/run_benchmark.sh <model> "0:2" 2       # smoke test (2 tasks)
evaluation/run_benchmark.sh <model> "" 8          # full run + scoring
.venv/bin/python evaluation/aggregate.py          # results/summary.md

# sanity gate (~30 min): gold patches must score 1.0, empty patches 0.0
mkdir -p results/sanity
.venv/bin/python evaluation/score.py --preds results/sanity/preds.json --empty
.venv/bin/python evaluation/score.py --preds results/sanity/preds.json --gold
```

On a free-tier key, use `.venv/bin/python evaluation/run_free_tier.py` instead — it
survives daily quota resets.

## Rebuild the dataset from scratch (optional, ~2 h)

```bash
uv pip install --python .venv/bin/python requests litellm
git clone https://github.com/tinygrad/tinygrad .cache/tinygrad
.venv/bin/python taskgen/mine_prs.py                      # 400 candidates, local git only
.venv/bin/python taskgen/validate_tasks.py --workers 4    # Docker-verify each candidate
.venv/bin/python taskgen/enrich_prs.py                    # PR bodies + issues (needs gh)
.venv/bin/python taskgen/build_dataset.py --n 100         # select + generate statements
```
