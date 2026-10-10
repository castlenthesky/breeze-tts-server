#!/usr/bin/env bash
# Start the server: the yggdrasil API by default, or upstream's plain API with
# BREEZE_UPSTREAM=1 (the rollback path: same image, none of our endpoints).
# Extra arguments pass through, e.g. `--fast-mode graphs` or `--no-fast-codec`.
set -euo pipefail

model=${BREEZE_MODEL_DIR:-/models/breeze-tts-2}
if [[ ! -f $model/config.json ]]; then
  echo "no model at $model; run the weights service first (docker compose up does)" >&2
  exit 1
fi

if [[ ${BREEZE_UPSTREAM:-0} == 1 ]]; then
  exec python -m breeze_infer.api "$model" --host 0.0.0.0 --port "${PORT:-8500}" "$@"
fi
exec python -m yggdrasil_breeze_api "$model" --host 0.0.0.0 --port "${PORT:-8500}" "$@"
