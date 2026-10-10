#!/usr/bin/env bash
# Find the fastest fast mode that warms up on this GPU, start the server in it,
# and record it as BREEZE_FAST_MODE in .env so a plain `docker compose up -d` or a
# reboot keeps it.
#
#   ⚠ Restarting interrupts any request in flight. Check nobody is mid-run first.
#
# Fast modes (see FAST_MODES in server/yggdrasil_breeze_api.py):
#   full+compile  full, plus a torch.compile'd backbone decode step (opt-in, unmeasured)
#   full          CUDA graphs for backbone decode + codec, torch.compile'd + graphed depth decoder
#   graphs        backbone decode + codec only: pure CUDA graphs, no torch.compile
#   eager         upstream's default; slowest
# It tries full → graphs → eager, falling back when warmup fails (container crash,
# or /health still 503 at the timeout). A mode that comes up but reports another
# fast_mode on /health (full+compile whose compile didn't install says full) is
# treated as a failure too and falls through to the next mode.
#
# Usage (from the repo root):
#   scripts/pick-fast-mode.sh            # full → graphs → eager
#   scripts/pick-fast-mode.sh compile    # full+compile → full → graphs → eager
#   scripts/pick-fast-mode.sh graphs     # start the chain at graphs
#   scripts/pick-fast-mode.sh eager      # force eager
set -euo pipefail

cd "$(dirname "$0")/.."
declare -A TIMEOUT=([full+compile]=1500 [full]=900 [graphs]=600 [eager]=300)

case ${1:-full} in
  eager | 0) modes=(eager) ;;
  full | 1) modes=(full graphs eager) ;;
  compile | full+compile) modes=(full+compile full graphs eager) ;;
  graphs) modes=(graphs eager) ;;
  *) echo "usage: $0 [full|graphs|eager|compile]" >&2; exit 64 ;;
esac

set_env_mode() {
  touch .env
  if grep -q '^BREEZE_FAST_MODE=' .env; then
    sed -i "s/^BREEZE_FAST_MODE=.*/BREEZE_FAST_MODE=$1/" .env
  else
    echo "BREEZE_FAST_MODE=$1" >>.env
  fi
}

# wait-healthy.sh needs the port and container name. Read just those from .env:
# exporting all of it would shadow BREEZE_FAST_MODE, since compose prefers the shell.
env_value() { sed -n "s/^$1=//p" .env 2>/dev/null | tail -1; }
export BREEZE_PORT=${BREEZE_PORT:-$(env_value BREEZE_PORT)}
export BREEZE_CONTAINER_NAME=${BREEZE_CONTAINER_NAME:-$(env_value BREEZE_CONTAINER_NAME)}
[[ -n $BREEZE_PORT ]] || BREEZE_PORT=8500
[[ -n $BREEZE_CONTAINER_NAME ]] || BREEZE_CONTAINER_NAME=breeze-tts-2
unset BREEZE_FAST_MODE

docker compose run --rm weights
for mode in "${modes[@]}"; do
  echo "→ starting breeze-tts-2 in fast mode '$mode' (timeout ${TIMEOUT[$mode]}s)"
  set_env_mode "$mode"
  docker compose up -d --force-recreate breeze-tts-2
  if health=$(scripts/wait-healthy.sh "${TIMEOUT[$mode]}"); then
    echo "$health"
    if [[ $health == *"\"fast_mode\":\"$mode\""* ]]; then
      echo "✓ breeze-tts-2 is up in fast mode: $mode (saved to .env)"
      exit 0
    fi
    echo "✗ healthy, but /health doesn't report fast_mode=$mode" >&2
  else
    echo "✗ fast mode '$mode' failed to warm up" >&2
  fi
done
echo "breeze-tts-2 failed to start in every mode; see docker logs breeze-tts-2" >&2
exit 1
