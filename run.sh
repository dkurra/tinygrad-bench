#!/usr/bin/env bash
# One-command setup + benchmark run.
#
#   OPENROUTER_API_KEY=sk-or-...  ./run.sh openrouter/z-ai/glm-5.2
#
# or put the key in .env first (OPENROUTER_API_KEY=... / GEMINI_API_KEY=... /
# ANTHROPIC_API_KEY=...) and just:
#
#   ./run.sh openrouter/deepseek/deepseek-v4-flash
#
# Does, idempotently: python venv -> docker image -> 2-task smoke test ->
# full 100-task run -> scoring -> results/summary.md. Re-running resumes.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${1:?usage: [PROVIDER_API_KEY=...] ./run.sh <litellm-model-id> [workers]
  e.g. OPENROUTER_API_KEY=sk-or-... ./run.sh openrouter/z-ai/glm-5.2 8}"
WORKERS="${2:-4}"

# 1. API keys: persist any *_API_KEY from the environment into .env
touch .env
for var in OPENROUTER_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do
  val="${!var:-}"
  if [ -n "$val" ] && ! grep -q "^$var=" .env; then
    echo "$var=$val" >> .env && echo "saved $var to .env"
  fi
done
grep -q "_API_KEY=" .env || { echo "ERROR: no API key. Prefix the command with e.g. OPENROUTER_API_KEY=sk-or-... or add it to .env"; exit 1; }

# 2. tooling
command -v docker >/dev/null || { echo "ERROR: docker not found (macOS: brew install colima docker && colima start)"; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: docker daemon not running (colima start?)"; exit 1; }
command -v uv >/dev/null || { echo "ERROR: uv not found (https://docs.astral.sh/uv/ or brew install uv)"; exit 1; }

# 3. python env (skipped if present)
[ -x .venv/bin/mini-extra ] || {
  echo "== creating venv + installing deps"
  uv venv --python 3.11 .venv
  uv pip install --python .venv/bin/python -q mini-swe-agent datasets fastapi orjson
}

# 4. evaluation image (skipped if present; first build ~10 min)
docker image inspect tinygrad-bench:base >/dev/null 2>&1 || {
  echo "== building tinygrad-bench:base"
  docker build -f environment/Dockerfile.base -t tinygrad-bench:base environment/
}

# 5. smoke test (2 tasks) unless this model already has predictions
OUT="results/$(echo "$MODEL" | tr '/' '_')"
if [ ! -f "$OUT/preds.json" ]; then
  echo "== smoke test: 2 tasks on $MODEL"
  evaluation/run_benchmark.sh "$MODEL" "0:2" 2
fi

# 6. full run + scoring (resumes past smoke/finished tasks)
echo "== full run: 100 tasks on $MODEL ($WORKERS workers)"
evaluation/run_benchmark.sh "$MODEL" "" "$WORKERS"

# 7. aggregate
.venv/bin/python evaluation/aggregate.py
echo "done -> $OUT/scores.json and results/summary.md"
