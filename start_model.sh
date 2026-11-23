#!/bin/sh
set -eu
cd "$(dirname "$0")"
export HF_HOME="${HF_HOME:-$PWD/data/model-cache}"
mkdir -p "$HF_HOME/hub"
exec .venv/bin/python -m mlx_lm.server --model "$PWD/data/model" --host 127.0.0.1 --port 8766 --decode-concurrency 2 --prompt-concurrency 1 --prefill-step-size 512 --prompt-cache-size 2 --prompt-cache-bytes 512MB
