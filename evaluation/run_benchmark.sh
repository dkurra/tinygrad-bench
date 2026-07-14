#!/usr/bin/env bash
# Run mini-swe-agent on tinygrad-bench for one model, then score.
#
# Usage: evaluation/run_benchmark.sh <litellm-model-id> [slice] [workers]
#   e.g. evaluation/run_benchmark.sh openrouter/z-ai/glm-5.2 "" 8
#        evaluation/run_benchmark.sh openrouter/deepseek/deepseek-v4-flash "0:3" 2  # smoke
#
# Requires: the provider's API key in .env (OPENROUTER_API_KEY / GEMINI_API_KEY /
#           ANTHROPIC_API_KEY ...), docker running, taskgen/tasks/tinygrad_bench built.
# Resume-aware: rerunning skips instances already in preds.json.
set -euo pipefail
cd "$(dirname "$0")/.."

# load API keys from .env
if [ -f .env ]; then set -a; source .env; set +a; fi

MODEL="${1:?usage: run_benchmark.sh <model> [slice] [workers]}"
SLICE="${2:-}"
WORKERS="${3:-4}"
OUT="results/$(echo "$MODEL" | tr '/' '_')"
mkdir -p "$OUT"

# bash 3.2 (macOS) treats an empty array as unbound under set -u
SLICE_ARGS=(--slice "${SLICE:-:}")

.venv/bin/mini-extra swebench \
  --subset "$(pwd)/taskgen/tasks/tinygrad_bench" \
  --split train \
  -c evaluation/tinygrad.yaml \
  -m "$MODEL" \
  -w "$WORKERS" \
  -o "$OUT" \
  "${SLICE_ARGS[@]}"

.venv/bin/python evaluation/score.py --preds "$OUT/preds.json" --workers 4
