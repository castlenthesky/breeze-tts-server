# breeze-tts-server

A self-hosted [Breeze TTS 2](https://github.com/breezeblue-ai/breeze-tts) server: a
bilingual (English/Chinese) TTS model behind a streaming REST API. It supports Voice Design
(a voice from an instruction), Voice Clone (from a reference clip) and Voice Direction
(clone, then redirect the delivery).

The image runs upstream's inference code at a pinned commit. It doesn't fork or patch
that code. It imports it and wraps it in an extended API (`server/`). That API adds:

- per-request sampling, dual CFG (eager mode), `speed` (pitch-preserving time-stretch),
  `response_format=wav`
- saved voices (`/v1/voices`, with `sha256` and `updated_at` for client caches)
- a voice changer (`/v1/audio/convert`, `mode=revoice` or the experimental `mode=acoustic`)
- `/v1/capabilities`, and 400s where upstream would 500 or return garbage
- CUDA-graph fast modes and a faster streaming loop

`/v1/audio/speech` stays backward compatible with upstream's fields and defaults.

## License

- **This repo's code** is Apache-2.0 (`LICENSE`), as is upstream's inference code.
- **The model weights are not.** `BreezeBlue/Breeze-TTS-2` is under BreezeBlue's
  *Research and Non-Commercial License* (RESONIA, Inc.). That covers the weights,
  derivative models and **audio you generate with them**. Research and non-commercial use
  only. Commercial use needs a separate license from BreezeBlue. The weights aren't in
  this repo. They're downloaded from Hugging Face on first start, which means you accept
  that license. See `NOTICE`.
- Don't clone real people's voices without their consent, or audio you don't have rights to.

## Run it

Requirements: Docker with the NVIDIA Container Toolkit, and an NVIDIA GPU. Eager mode needs
about 12 GB of GPU memory and the fast modes about 16 GB (CUDA 13 driver; x86_64 or aarch64).
You also need about 7.2 GB of disk for the weights.

```bash
git clone https://github.com/castlenthesky/breeze-tts-server && cd breeze-tts-server
cp .env.example .env            # optional; defaults work
docker compose up -d            # builds, downloads weights once, starts on :8500
scripts/wait-healthy.sh 900     # /health is 503 while the model loads and warms up
curl -s localhost:8500/v1/capabilities | head -c 400
```

Make some speech:

```bash
curl -s localhost:8500/v1/audio/speech -F text="Hello there." \
  -F instruction="A warm, calm female narrator." -F cfg_scale=3 \
  -F response_format=wav -F stream=0 -o hello.wav
```

`/v1/capabilities` describes every mode, field, limit and format the running server
supports. Clients should read it rather than hard-code them.

### What runs

| Service | Role |
|---|---|
| `weights` | One-shot. Downloads `BreezeBlue/Breeze-TTS-2` at a pinned revision into `$MODEL_DIR/$BREEZE_MODEL_NAME`, only if it isn't already there. A no-op once a marker file records that revision. |
| `breeze-tts-2` | The API on `:8500`. Starts once `weights` succeeds. |

State on the host:
- `$MODEL_DIR` (default `./models`): the host folder the weights are read from, mounted
  read-only into the server. The model is the `$BREEZE_MODEL_NAME` folder inside it
  (default `breeze-tts-2`).
- `$DATA_DIR/outputs/voices` (default `./data`): saved voices.
- The `breeze-tts-cache` volume: torch/triton compile caches.

### Settings (`.env`)

See `.env.example`. The main ones:

| Variable | Default | |
|---|---|---|
| `BREEZE_FAST_MODE` | `full` | `full`, `graphs`, `eager` or `full+compile` (below) |
| `BREEZE_PORT` | `8500` | host port |
| `MODEL_DIR` | `./models` | host folder holding the model, e.g. a shared `/home/you/models/tts`. Absolute path; compose doesn't expand `~` |
| `BREEZE_MODEL_NAME` | `breeze-tts-2` | the model's folder inside `MODEL_DIR` |
| `DATA_DIR` | `./data` | saved voices (`outputs/voices`) |
| `BREEZE_MEM_LIMIT` | `28g` | container memory limit |
| `BREEZE_UPSTREAM` | `0` | `1` runs upstream's plain API from the same image (rollback) |
| `COMPOSE_FILE` | | `compose.yml:compose.gb10.yml` on a DGX Spark |

### Sharing weights with other stacks

The weights live on the host, never in the image. To keep one copy per machine, point
`MODEL_DIR` at the host's shared models folder:

```bash
echo "MODEL_DIR=$HOME/models/tts" >> .env   # the model then lives at ~/models/tts/breeze-tts-2
```

If the model is already there, the `weights` service checks it against the pinned revision
and downloads nothing. If not, it downloads once into that folder.

### Fast modes

| Mode | What it does |
|---|---|
| `full` | CUDA graphs for backbone decode and codec, plus a torch.compile'd, graphed depth decoder |
| `graphs` | backbone decode and codec only: pure CUDA graphs, no torch.compile |
| `eager` | upstream's default, and the slowest. The only mode where dual CFG runs. |
| `full+compile` | `full`, plus a torch.compile'd backbone decode step. Opt-in and unmeasured. |

Text encoder and prefill are never graphed: their frozen buckets break long prompts.
A seeded take in a fast mode can differ from the same seed in eager mode.

Not every GPU warms up in every mode. `scripts/pick-fast-mode.sh` tries `full`, then
`graphs`, then `eager`. It starts the server in the first one that comes up healthy and
saves that choice to `.env`. Restarting interrupts any request in flight.

### DGX Spark / GB10

```bash
echo 'COMPOSE_FILE=compose.yml:compose.gb10.yml' >> .env
```

`compose.gb10.yml` does three things:
- uses host networking
- pins the server to the GB10's Cortex-X925 big cores (`cpuset 5-9,15-19`). The frame
  loop is launch-latency bound.
- adds the `spark.managed: llama-swap` label

With `full` mode on a GB10, steady-state speed is about 0.91× real time (≈190 ms frame
p95). See `validation/`.

### Rollback to upstream's API

```bash
BREEZE_UPSTREAM=1 docker compose up -d --force-recreate breeze-tts-2
```

This uses the same image and weights. None of this repo's endpoints are available, and
saved voices stay on disk. Set it back to `0` to return.

## Develop

`server/yggdrasil_breeze_api.py` is the HTTP layer. `server/yggdrasil_breeze_fast.py`
subclasses upstream's streaming runtime, copying its frame loop. It installs only while
upstream's files hash to `UPSTREAM_SHA256`. `/v1/capabilities` → `runtime` says whether
it's active.

The HTTP tests stub out upstream and torch, so they need no GPU:

```bash
uv run --group test pytest
```

The runtime tests need real CPU torch and run in a session of their own. Add
`BREEZE_UPSTREAM_SRC=<breeze-tts checkout>` to run the parity tests against upstream's loop:

```bash
uv run --no-project --with torch --with numpy --with pytest pytest tests/test_runtime_torch.py
```

`validation/breeze_matrix.py` measures a live server, covering every feature, with
Whisper WER, tag read-aloud checks and steady-state speed. It writes `validation/runs/<stamp>/`
(git-ignored) and `validation/LATEST.md`:

```bash
BREEZE_URL=http://localhost:8500 uv run validation/breeze_matrix.py --no-asr
```

### Bumping upstream

1. Update `BREEZE_COMMIT` in the `Dockerfile`.
2. Diff upstream's streaming loop against `yggdrasil_breeze_fast.py`.
3. Run the parity tests, then update `UPSTREAM_SHA256`.
4. Rebuild, then re-run the matrix.

If the hashes don't match, the server still runs, on upstream's loop. Its fast paths come
back once the hashes match again.

`server/breeze_tags.json` is the vocal-event vocabulary the server serves. Clients that
keep their own copy should keep it in sync.
