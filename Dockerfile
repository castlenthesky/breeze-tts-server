# Breeze TTS 2 with the yggdrasil API on top. One image: upstream's inference code at a
# pinned commit, the exact Python packages the reference server runs, and server/.
# Multi-arch (x86_64 and aarch64/GB10): torch's cu130 wheels exist for both.
# flash-attention is upstream's optional perf path and is skipped (no sm_121 build).
FROM nvidia/cuda:13.0.3-devel-ubuntu24.04

# breezeblue-ai/breeze-tts, 2026-09-30. yggdrasil_breeze_fast checks these files'
# hashes (UPSTREAM_SHA256) and falls back to upstream's loop if they differ.
ARG BREEZE_COMMIT=58ec70ce5fa4cc361bdebf77ec40d1365da00ab2
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev git ffmpeg libsndfile1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv $VIRTUAL_ENV && pip install --upgrade pip

# torch first, from the cu130 index (it brings its own nvidia-* and triton wheels).
RUN pip install torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu130

# Everything else, exactly as frozen from the reference server, without resolving.
COPY docker/requirements.lock /opt/requirements.lock
RUN pip install --no-deps -r /opt/requirements.lock

RUN git clone https://github.com/breezeblue-ai/breeze-tts /opt/breeze-tts \
    && cd /opt/breeze-tts && git checkout ${BREEZE_COMMIT}

ENV TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas \
    TORCH_CUDA_ARCH_LIST="12.1+PTX" \
    HF_HUB_OFFLINE=1 \
    HF_HOME=/cache/hf \
    PYTHONPATH=/app \
    BREEZE_MODEL_DIR=/models/breeze-tts-2 \
    BREEZE_VOICES_DIR=/outputs/voices \
    PORT=8500

RUN (getent group ${GID} || groupadd -g ${GID} breeze) \
    && if getent passwd ${UID} >/dev/null; then usermod -l breeze -d /home/breeze -m "$(getent passwd ${UID} | cut -d: -f1)"; else useradd -m -u ${UID} -g ${GID} breeze; fi \
    && mkdir -p /cache /outputs /models \
    && chown -R ${UID}:${GID} /opt/breeze-tts /cache /outputs

COPY --chown=${UID}:${GID} server/ /app/
COPY --chown=${UID}:${GID} docker/entrypoint.sh docker/download-weights.sh /usr/local/bin/

USER breeze
# Upstream's modules import from their checkout, so it stays the working directory.
WORKDIR /opt/breeze-tts
EXPOSE 8500
HEALTHCHECK --interval=30s --timeout=5s --start-period=30m \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
ENTRYPOINT ["entrypoint.sh"]
