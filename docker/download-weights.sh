#!/usr/bin/env bash
# Fetch BreezeBlue/Breeze-TTS-2 into $BREEZE_MODEL_DIR at a pinned revision, once.
# A marker file records the revision; with it present this is a no-op, so it is
# safe as a start-up step. Without it, `hf download` verifies whatever files are
# already there (hashing them) and fetches only what is missing or different.
# The weights are BreezeBlue's Research/Non-Commercial license; see NOTICE.
set -euo pipefail

model=${BREEZE_MODEL_DIR:-/models/breeze-tts-2}
revision=${BREEZE_WEIGHTS_REVISION:-3e28c5151381a722f1d8661b4118c298caa77aa4}
marker=$model/.breeze-weights-revision

if [[ -f $marker && $(<"$marker") == "$revision" ]]; then
  echo "weights present at $model (revision $revision)"
  exit 0
fi

mkdir -p "$model"
echo "downloading BreezeBlue/Breeze-TTS-2@$revision to $model (~7.2 GB)"
HF_HUB_OFFLINE=0 hf download BreezeBlue/Breeze-TTS-2 --revision "$revision" --local-dir "$model"
echo "$revision" >"$marker"
