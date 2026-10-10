#!/usr/bin/env bash
# Poll the server's /health until it reports ok. /health answers 503 while the
# model loads and warms up; fast modes add CUDA-graph capture (and torch.compile
# for the depth decoder) on top, so the caller picks the timeout.
#
# Fails early if the container stops or restarts: a crash during warmup puts it
# in a restart loop (restart: unless-stopped), which would otherwise only show
# up as a timeout.
#
# Usage: scripts/wait-healthy.sh [timeout-seconds]   (run from the repo root)
# Env:   BREEZE_PORT (default 8500), BREEZE_CONTAINER_NAME (default breeze-tts-2)
set -euo pipefail

TIMEOUT=${1:-300}
PORT=${BREEZE_PORT:-8500}
NAME=${BREEZE_CONTAINER_NAME:-breeze-tts-2}
inspect() { docker inspect -f '{{.State.Status}} {{.RestartCount}}' "$NAME"; }

read -r _ restarts_before < <(inspect)
deadline=$((SECONDS + TIMEOUT))
while ((SECONDS < deadline)); do
  if body=$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" 2>/dev/null) &&
    [[ $body == *'"ok"'* ]]; then
    echo "$body"
    exit 0
  fi
  read -r status restarts < <(inspect)
  if [[ $status != running || $restarts != "$restarts_before" ]]; then
    echo "$NAME died during startup (status=$status, restarts $restarts_before→$restarts)" >&2
    docker logs --tail 30 "$NAME" >&2 || true
    exit 2
  fi
  sleep 5
done
echo "$NAME not healthy after ${TIMEOUT}s; see: docker logs --tail 50 $NAME" >&2
docker logs --tail 30 "$NAME" >&2 || true
exit 1
