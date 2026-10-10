"""Yggdrasil overlay over upstream Breeze TTS 2's streaming API (`breeze_infer.api`).

Upstream's API exposes only text / instruction / cfg_scale / ref_audio / ref_text
/ seed. This module serves the same `/v1/audio/speech` contract (backward
compatible, same defaults, still streaming) and adds what the model can do but
upstream hides, plus the guard rails upstream lacks:

- per-request sampling (backbone and depth decoder separately), repetition
  penalty and token budget
- dual CFG for Voice Direction (`cfg_scale_ref` + `cfg_scale_ins`; upstream's
  non-streaming `model.generate` path, so `stream=false` only — experimental;
  eager mode only by default: in fast modes it crashed the process with a
  device-side gather assert, so it's a 400 unless BREEZE_DUAL_CFG_FAST=1, which
  runs it with the compiled depth-decoder modules swapped back, see `_dual_cfg_audio`)
- `speed`: pitch-preserving tempo change of the output (ffmpeg rubberband, or
  atempo), streamed through an ffmpeg pipe; the model has no native speed
- `stream` and `response_format` (`pcm` | `wav`, a streaming-friendly WAV header
  when streamed), a memoryless soft limiter, saved voices (`/v1/voices`, their
  encoded reference codes cached, `sha256`/`updated_at` for client caches), a
  voice changer (`/v1/audio/convert`: transcript-driven `revoice`, or
  experimental `acoustic` conversion that keeps the source's words and timing)
  and `/v1/capabilities`
- 400s instead of upstream's 500s/silent garbage: unknown fields, empty text,
  audio-slot tokens in text, out-of-range params, cfg without an instruction,
  undecodable references, text that won't fit the model's frame budget
- `--fast-mode full|graphs|eager` (+ opt-in `full+compile`): upstream's
  CUDA-graph stages for backbone decode, depth decoder and codec (never text
  encoder / prefill, whose frozen buckets break long prompts), defaulting to
  `BREEZE_FAST_MODE`; `scripts/pick-fast-mode.sh` finds the mode that warms up
- a leaner per-frame streaming loop (fewer host syncs, same output) and the
  forced-frame loop acoustic conversion needs: `yggdrasil_breeze_fast`, which
  subclasses upstream's runtime only when upstream's files match the commit it
  mirrors

It imports upstream rather than forking it: upstream's runtime, templates and
streaming response (with its disconnect-safe lock release) are reused as-is.
Run inside the image (docker/entrypoint.sh) with this file's directory on
PYTHONPATH and `/opt/breeze-tts` as the working directory:

    python -m yggdrasil_breeze_api /models/breeze-tts-2 --host 0.0.0.0 --port 8500
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Generator, Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from breeze_infer import api as upstream
from breeze_infer import templates as upstream_templates
from breeze_infer.templates import get_template, prepare_inputs, select_template_name
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import yggdrasil_breeze_fast as fast

API_VERSION = "2026.10.07"
SAMPLE_RATE = 24000
CODEC_FRAME_RATE = 12.5
STREAM_CHUNK_FRAMES = 2  # upstream's eager codec decodes 2 frames (160 ms) per chunk
VOICES_DIR = Path(os.environ.get("BREEZE_VOICES_DIR", "/outputs/voices"))
TAGS_FILE = Path(os.environ.get("BREEZE_TAGS_FILE", Path(__file__).with_name("breeze_tags.json")))
MAX_TEXT_CHARS = 1000  # the vendor's hosted API cap; longer text should be chunked
CHUNK_CHARS = {"recommended": 350, "max": 600}  # where long-form quality holds (C++ port)
REF_SECONDS = {"min": 1.0, "recommended": [3.0, 30.0], "max": 60.0}
DEPTH_MAX_TOP_K = 1024  # DepthDecoderGraph's fixed top-k workspace
SPEED_RANGE = (0.5, 2.0)
SPEED_RECOMMENDED = (0.75, 1.25)
SPEED_ENGINES = ("rubberband", "atempo")
LIMITER_KNEE = 0.89  # ≈ -1 dBFS
# A request that finds the server busy waits this long for it before a 409:
# an aborted stream frees the lock only once its generation step winds down
# (measured ~5 s), and the next request shouldn't bounce off that.
BUSY_WAIT_SECONDS = float(os.environ.get("BREEZE_BUSY_WAIT", "8"))
# Inline direction: `<ins_bos>…<ins_eos>` inside text. These weights don't
# switch style mid-generation (measured: the text before the marker is
# dropped), so the overlay splits the text there and voices each segment
# with that instruction as its top-level one. `raw=true` passes text untouched.
INLINE_INSTRUCTION = re.compile(r"<ins_bos>(.*?)<ins_eos>", re.DOTALL)
INLINE_DEFAULT_CFG = 3.0  # an inline instruction at cfg 1 barely registers
VOICE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")  # fullmatch: `$` would admit a trailing \n
# Demuxers an uploaded clip may use. Anything else (notably HLS/m3u8 playlists,
# which can make ffmpeg read other local files) is refused before it's opened.
FFMPEG_INPUT_GUARD = [
    "-protocol_whitelist", "file,pipe",
    "-format_whitelist", "wav,mp3,flac,ogg,mov,mp4,m4a,aac,matroska,webm,w64,aiff",
]  # fmt: skip
# Fast-mode presets → upstream's per-stage flags. Never the text encoder or
# backbone prefill: those freeze 512-token buckets after warmup, and a longer
# prompt then fails mid-stream after the 200 has gone out.
FAST_MODES = {
    "full": {"fast_backbone_decode": True, "fast_depth_decoder": True, "fast_codec": True},
    "graphs": {"fast_backbone_decode": True, "fast_depth_decoder": False, "fast_codec": True},
    "eager": {"fast_backbone_decode": False, "fast_depth_decoder": False, "fast_codec": False},
    # `full`, plus torch.compile of the backbone decode step before its CUDA graph
    # is captured. Opt-in (BREEZE_FAST_MODE=full+compile) until measured on sm_121.
    "full+compile": {
        "fast_backbone_decode": True, "fast_depth_decoder": True, "fast_codec": True,
    },
}  # fmt: skip
COMPILE_MODES = frozenset({"full+compile"})
# The leaner per-frame loop (yggdrasil_breeze_fast); BREEZE_LEAN_LOOP=0 keeps upstream's.
LEAN_LOOP = os.environ.get("BREEZE_LEAN_LOOP", "1") != "0"
# Dual CFG in fast modes (eager-module swap + streaming-codec decode). Off by default:
# on 2026-10-07 in fast_mode=full it hit a device-side ScatterGatherKernel "index out
# of bounds" assert that killed the process (RestartCount 0→1); the module/dtype swap
# didn't prevent it, so fast modes answer 400. =1 re-enables it (known to crash).
DUAL_CFG_FAST = os.environ.get("BREEZE_DUAL_CFG_FAST", "0") == "1"
KEEP_ACOUSTIC_RECOMMENDED = (0, 2)  # Breeze-TTS-2.cpp: >2 warbles; 1-2 only for singing
# Conservative speaking rates for the frame-budget estimate: slow speech + pauses.
_SLOW_WORDS_PER_SECOND = 1.6
_SLOW_CJK_CHARS_PER_SECOND = 2.5
_CJK = re.compile(r"[㐀-鿿]")

TAGS = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
# `<|AUDIO|>`/`<|audio_eos|>` mark where reference-audio codes go; in user text they
# misalign the prompt (a stray one in ref_text crashed generation after the 200).
# The other control tokens — `[S0]`-`[S9]`, `<ins_bos>`/`<ins_eos>` — pass through on
# purpose: inline `<ins_bos>…<ins_eos>` in text is (experimental) mid-line direction.
CONTROL_TOKENS = re.compile(TAGS["control_token_pattern"])
ENGLISH_BRACKET_EVENT = re.compile(TAGS["english_bracket_event_pattern"])

SAMPLING_FIELDS = (
    "temperature",
    "top_k",
    "top_p",
    "do_sample",
    "depth_temperature",
    "depth_top_k",
    "depth_top_p",
    "repetition_penalty",
    "max_new_tokens",
)
OUTPUT_FIELDS = ("speed", "speed_engine", "response_format", "stream", "limiter")
SPEECH_FIELDS = frozenset(
    {
        "text",
        "instruction",
        "cfg_scale",
        "cfg_scale_ref",
        "cfg_scale_ins",
        "ref_audio",
        "ref_text",
        "voice",
        "seed",
        "raw",
        *OUTPUT_FIELDS,
        *SAMPLING_FIELDS,
    }
)
CONVERT_FIELDS = frozenset(
    {
        "mode",
        "source_audio",
        "source_text",
        "voice",
        "ref_audio",
        "ref_text",
        "instruction",
        "cfg_scale",
        "seed",
        "match_duration",
        "keep_acoustic",
        *OUTPUT_FIELDS,
        *SAMPLING_FIELDS,
    }
) - {"stream"}
VOICE_FIELDS = frozenset({"id", "ref_audio", "ref_text", "instruction", "description", "overwrite"})


# ─── validation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Sampling:
    """Per-request overrides; `None` keeps the server default."""

    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    do_sample: bool | None = None
    depth_temperature: float | None = None
    depth_top_k: int | None = None
    depth_top_p: float | None = None
    repetition_penalty: float | None = None
    max_new_tokens: int | None = None

    def validate(self) -> None:
        for name in ("temperature", "depth_temperature"):
            _check_range(name, getattr(self, name), 0.0, 5.0, low_open=True)
        for name in ("top_p", "depth_top_p"):
            _check_range(name, getattr(self, name), 0.0, 1.0, low_open=True)
        _check_range("top_k", self.top_k, 0, 100_000)
        _check_range("depth_top_k", self.depth_top_k, 0, DEPTH_MAX_TOP_K)
        _check_range("repetition_penalty", self.repetition_penalty, 0.0, 5.0, low_open=True)
        _check_range("max_new_tokens", self.max_new_tokens, 1, upstream.MAX_NEW_TOKENS)


@dataclass(frozen=True)
class Output:
    speed: float
    speed_engine: str
    response_format: str
    limiter: bool

    def validate(self) -> None:
        _check_range("speed", self.speed, *SPEED_RANGE)
        if self.speed_engine not in SPEED_ENGINES:
            raise HTTPException(400, f"speed_engine must be one of {', '.join(SPEED_ENGINES)}")
        if self.response_format not in ("pcm", "wav"):
            raise HTTPException(400, "response_format must be 'pcm' or 'wav'")


def _check_range(
    name: str, value: float | None, low: float, high: float, *, low_open: bool = False
) -> None:
    if value is None:
        return
    if not np.isfinite(value) or value > high or value < low or (low_open and value == low):
        bracket = "(" if low_open else "["
        raise HTTPException(400, f"{name} must be in {bracket}{low}, {high}], got {value}")


async def _reject_unknown_fields(request: Request, allowed: frozenset[str]) -> None:
    """A misspelled field is a 400, not a silently ignored knob."""
    form = await request.form()  # already parsed for the endpoint; cached
    unknown = sorted(set(form.keys()) - allowed)
    if unknown:
        raise HTTPException(
            400, f"unknown field(s): {', '.join(unknown)}; accepted: {', '.join(sorted(allowed))}"
        )


def _clean_text(name: str, value: str | None, *, required: bool = False) -> str:
    """Strip, reject audio-slot tokens, and send English `[event]` tags as `(event)`."""
    value = (value or "").strip()
    if required and not value:
        raise HTTPException(
            400,
            f"{name} is empty. With curl, a value starting with '(', '@' or '<' must be sent "
            f"with --form-string, not -F (-F sends it empty or as a file)",
        )
    tokens = [match[0] for match in CONTROL_TOKENS.finditer(value)]
    if tokens:
        raise HTTPException(
            400,
            f"{name} contains audio-slot tokens {sorted(set(tokens))}; they mark where "
            f"reference-audio codes go and break generation in text, so remove them",
        )
    return ENGLISH_BRACKET_EVENT.sub(r"(\1)", value)


def _check_text_length(text: str) -> None:
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            400,
            f"text is {len(text)} characters; send at most {MAX_TEXT_CHARS} per request "
            f"(~{CHUNK_CHARS['recommended']} keeps long-form quality steady) and stitch",
        )


def _estimated_frames(text: str) -> int:
    """Upper-ish estimate of the frames needed to speak `text` slowly."""
    cjk = len(_CJK.findall(text))
    words = len(_CJK.sub(" ", text).split())
    seconds = words / _SLOW_WORDS_PER_SECOND + cjk / _SLOW_CJK_CHARS_PER_SECOND + 1.0
    return int(seconds * CODEC_FRAME_RATE)


@dataclass(frozen=True)
class Segment:
    text: str
    instruction: str | None
    cfg_scale: float


def _segments(text: str, instruction: str | None, cfg_scale: float, *, raw: bool) -> list[Segment]:
    """Split `text` at inline `<ins_bos>…<ins_eos>` markers into separately voiced segments.

    The first segment keeps the request's instruction and cfg_scale; each
    inline instruction then governs the text after it, at `cfg_scale` (or
    `INLINE_DEFAULT_CFG` when the request left it at 1). A segment with no
    instruction runs at cfg 1, which needs none.
    """
    if raw or "<ins_bos>" not in text and "<ins_eos>" not in text:
        return [Segment(text, instruction, cfg_scale)]
    inline_cfg = cfg_scale if cfg_scale != 1.0 else INLINE_DEFAULT_CFG
    segments: list[Segment] = []
    current_instruction, current_cfg, position = instruction, cfg_scale, 0
    for match in INLINE_INSTRUCTION.finditer(text):
        segments.append(Segment(text[position : match.start()], current_instruction, current_cfg))
        current_instruction = match[1].strip() or None
        current_cfg = inline_cfg if current_instruction else 1.0
        position = match.end()
    segments.append(Segment(text[position:], current_instruction, current_cfg))
    voiced = [replace(seg, text=seg.text.strip()) for seg in segments if seg.text.strip()]
    if any("<ins_bos>" in seg.text or "<ins_eos>" in seg.text for seg in voiced):
        raise HTTPException(
            400,
            "unbalanced inline instruction: write <ins_bos>instruction<ins_eos> before the "
            "text it directs (or send raw=true to pass markers to the model untouched)",
        )
    if not voiced:
        raise HTTPException(400, "text has inline instructions but nothing to say")
    return [
        seg if seg.instruction or seg.cfg_scale == 1.0 else replace(seg, cfg_scale=1.0)
        for seg in voiced
    ]


# ─── audio helpers ───────────────────────────────────────────────────────────


def _ffmpeg(
    args: list[str], stdin: bytes | None = None, *, what: str = "audio", status: int = 400
) -> bytes:
    """Run ffmpeg; a failure is `status` — 400 for a bad upload, 500 for our own output."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status, f"could not process {what}: {result.stderr.decode()[-300:]}")
    return result.stdout


def _rubberband_available() -> bool:
    try:
        listing = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False
        )
    except OSError:
        return False
    return " rubberband " in listing.stdout


RUBBERBAND = _rubberband_available()


def _speed_filter(speed: float, engine: str) -> tuple[str, str]:
    """The ffmpeg filter for a tempo change, and the engine actually used."""
    if engine == "rubberband" and RUBBERBAND:
        return f"rubberband=tempo={speed}:pitchq=quality", "rubberband"
    return f"atempo={speed}", "atempo"  # 0.5-2.0 in one stage, which is SPEED_RANGE


def _ffmpeg_pcm_args(audio_filter: str) -> list[str]:
    return [
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
        "-af", audio_filter, "-f", "s16le", "-flush_packets", "1", "pipe:1",
    ]  # fmt: skip


def _normalize_clip(source: Path, dest: Path, *, what: str) -> float:
    """Any whitelisted audio clip (wav, mp3, m4a/aac, ogg, flac, …) → 24 kHz mono PCM16
    WAV, transcoded by ffmpeg; returns its duration."""
    _ffmpeg(
        ["-y", *FFMPEG_INPUT_GUARD, "-i", str(source),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(dest)],
        what=what,
    )  # fmt: skip
    duration = sf.info(str(dest)).duration
    if duration < REF_SECONDS["min"]:
        raise HTTPException(400, f"{what} is {duration:.2f}s — too short to use")
    if duration > REF_SECONDS["max"]:
        raise HTTPException(
            400,
            f"{what} is {duration:.1f}s; keep it under {REF_SECONDS['max']:.0f}s "
            "(3-30s of clean speech clones best)",
        )
    return duration


def _ref_warning(duration: float) -> str | None:
    low, high = REF_SECONDS["recommended"]
    if low <= duration <= high:
        return None
    return f"reference is {duration:.1f}s; {low:.0f}-{high:.0f}s of clean speech clones best"


def _soft_clip(audio: np.ndarray) -> np.ndarray:
    """Memoryless soft knee above ≈-1 dBFS: safe per streaming chunk, no lookahead."""
    audio = np.asarray(audio, dtype=np.float32)
    over = np.abs(audio) > LIMITER_KNEE
    if not over.any():
        return audio
    audio = audio.copy()
    excess = (np.abs(audio[over]) - LIMITER_KNEE) / (1.0 - LIMITER_KNEE)
    audio[over] = np.sign(audio[over]) * (LIMITER_KNEE + (1.0 - LIMITER_KNEE) * np.tanh(excess))
    return audio


def _wav_header(data_bytes: int | None) -> bytes:
    """A 44-byte PCM WAV header; `None` sizes it 0xFFFFFFFF, as streaming WAV does."""
    size = 0xFFFFFFFF if data_bytes is None else data_bytes
    riff = 0xFFFFFFFF if data_bytes is None else 36 + data_bytes
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff, b"WAVE", b"fmt ", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16,
        b"data", size,
    )  # fmt: skip


PcmGenerator = Generator[bytes, None, None]


def _stretch_stream(pcm: PcmGenerator, audio_filter: str) -> PcmGenerator:
    """Pipe PCM through ffmpeg as it arrives, yielding stretched PCM as ffmpeg emits it.

    A feeder thread writes `pcm` (the model's generator) to ffmpeg's stdin while
    this generator reads stdout. Closing this generator (client disconnect)
    kills ffmpeg, which breaks the feeder's write; the feeder then closes the
    model generator itself, and we wait for it so the model is idle before the
    caller releases the request lock.
    """
    process = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
         *_ffmpeg_pcm_args(audio_filter)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    assert process.stdin and process.stdout and process.stderr
    failure: list[BaseException] = []

    def feed() -> None:
        try:
            with closing(pcm):
                for chunk in pcm:
                    process.stdin.write(chunk)  # type: ignore[union-attr]
        except BrokenPipeError:
            pass  # ffmpeg was killed: we're being closed
        except BaseException as exc:  # noqa: BLE001 - re-raised on the reading side
            failure.append(exc)
        finally:
            with contextlib.suppress(OSError):
                process.stdin.close()  # type: ignore[union-attr]

    feeder = threading.Thread(target=feed, name="breeze-stretch-feed", daemon=True)
    feeder.start()
    try:
        while chunk := process.stdout.read1(STREAM_CHUNK_FRAMES * 1920 * 2):
            yield chunk
        returncode = process.wait()
        feeder.join()
        if failure:
            raise failure[0]
        if returncode != 0:
            raise RuntimeError(f"ffmpeg stretch failed: {process.stderr.read().decode()[-300:]}")
    finally:
        if process.poll() is None:
            process.kill()
        feeder.join()
        process.wait()


# ─── saved voices ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Voice:
    ref_audio: Path
    ref_text: str
    instruction: str | None
    meta: dict[str, Any]


def _voice_dir(voice_id: str) -> Path:
    if not VOICE_ID.fullmatch(voice_id):
        raise HTTPException(
            400, "voice id must be 1-64 chars of lowercase letters, digits, '_' or '-'"
        )
    return VOICES_DIR / voice_id


def _voice_sha256(audio: bytes, ref_text: str) -> str:
    """What a client caches against: the stored clip's bytes, a NUL, the UTF-8 ref_text."""
    return hashlib.sha256(audio + b"\0" + ref_text.encode()).hexdigest()


def _utc(seconds: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _voice_meta(folder: Path) -> dict[str, Any]:
    """voice.json, with `sha256`/`updated_at` filled in for voices saved before they existed."""
    meta_path = folder / "voice.json"
    meta = json.loads(meta_path.read_text())
    clip = folder / "ref.wav"
    if not meta.get("sha256") and clip.is_file():
        meta["sha256"] = _voice_sha256(clip.read_bytes(), meta.get("ref_text") or "")
    if not meta.get("updated_at"):
        meta["updated_at"] = _utc(meta_path.stat().st_mtime)
    return meta


def _load_voice(voice_id: str) -> Voice:
    folder = _voice_dir(voice_id)
    meta_path = folder / "voice.json"
    if not meta_path.is_file():
        raise HTTPException(404, f"no saved voice {voice_id!r}")
    meta = _voice_meta(folder)
    # Voices saved before the audio-slot guard existed are checked on use too.
    _clean_text(f"saved voice {voice_id!r} ref_text", meta["ref_text"], required=True)
    _clean_text(f"saved voice {voice_id!r} instruction", meta.get("instruction"))
    return Voice(folder / "ref.wav", meta["ref_text"], meta.get("instruction") or None, meta)


def _atomic_write(dest: Path, data: bytes) -> None:
    """Write via a temp file in `dest`'s directory, then rename over it (atomic on POSIX)."""
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# Reference audio → codec codes, cached by content hash: a saved voice (or a
# clip re-sent every request) is encoded once. Hooked in through upstream's
# own module-level seam, `templates._encode_prompt_audio`.
_CODES_CACHE: OrderedDict[str, Any] = OrderedDict()
_CODES_CACHE_SIZE = 64
_encode_uncached = getattr(upstream_templates, "_encode_prompt_audio", None)


def _encode_cached(audio_tokenizer: Any, audio_path: str) -> Any:
    key = hashlib.sha256(Path(audio_path).read_bytes()).hexdigest()
    if key in _CODES_CACHE:
        _CODES_CACHE.move_to_end(key)
        return _CODES_CACHE[key]
    assert _encode_uncached is not None
    codes = _encode_uncached(audio_tokenizer, audio_path)
    _CODES_CACHE[key] = codes
    if len(_CODES_CACHE) > _CODES_CACHE_SIZE:
        _CODES_CACHE.popitem(last=False)
    return codes


if _encode_uncached is not None:
    upstream_templates._encode_prompt_audio = _encode_cached


# ─── inference ───────────────────────────────────────────────────────────────


@dataclass
class Prepared:
    inputs: dict[str, Any]
    request_id: str
    seed: int
    prompt_len: int
    dual_cfg: bool


def _apply_sampling(sampling: Sampling) -> Callable[[], None]:
    """Set per-request sampling on the shared model/runtime; return the undo.

    Safe only because the API serves one request at a time (upstream's lock).
    """
    runtime = app.state.runtime
    backbone = app.state.model.generation_config
    depth = app.state.model.depth_decoder.generation_config
    overrides = [
        (backbone, "temperature", sampling.temperature),
        (backbone, "top_k", sampling.top_k),
        (backbone, "top_p", sampling.top_p),
        (backbone, "do_sample", sampling.do_sample),
        (depth, "temperature", sampling.depth_temperature),
        (depth, "top_k", sampling.depth_top_k),
        (depth, "top_p", sampling.depth_top_p),
        (depth, "do_sample", sampling.do_sample),
    ]
    saved = [(target, name, getattr(target, name, None)) for target, name, _ in overrides]
    saved_config = runtime.config
    for target, name, value in overrides:
        if value is not None:
            setattr(target, name, value)
    config_changes = {
        key: value
        for key, value in (
            ("repetition_penalty", sampling.repetition_penalty),
            ("max_new_tokens", sampling.max_new_tokens),
        )
        if value is not None
    }
    if config_changes:
        runtime.config = replace(saved_config, **config_changes)

    def restore() -> None:
        for target, name, value in saved:
            setattr(target, name, value)
        runtime.config = saved_config

    return restore


def _prepare(
    *,
    text: str,
    instruction: str | None,
    cfg_scale: float,
    cfg_scale_ref: float | None,
    cfg_scale_ins: float | None,
    ref_path: Path | None,
    ref_text: str,
    seed: int,
    max_new_tokens: int,
    needed_frames: int | None = None,
) -> Prepared:
    """Build model inputs; `needed_frames` replaces the text-based estimate (acoustic
    conversion knows exactly how many frames it will force)."""
    if not np.isfinite(cfg_scale) or cfg_scale <= 0:
        raise HTTPException(400, "cfg_scale must be greater than 0.")
    request_id = f"api-{uuid.uuid4().hex}"
    request: dict[str, Any] = {"id": request_id, "text": text, "speaker": "S0"}
    if instruction:
        request["instruction"] = instruction
    if ref_path is not None:
        request["ref_audio_path"] = str(ref_path)
        request["ref_text"] = ref_text
    template = get_template(select_template_name(request))

    dual_cfg = cfg_scale_ref is not None or cfg_scale_ins is not None
    if dual_cfg:
        if cfg_scale_ref is None or cfg_scale_ins is None:
            raise HTTPException(400, "cfg_scale_ref and cfg_scale_ins go together")
        if template.build_dual_branches is None:
            raise HTTPException(
                400,
                "dual CFG (cfg_scale_ref/cfg_scale_ins) needs Voice Direction: "
                "a reference (ref_audio+ref_text or voice) and an instruction",
            )
        for name, value in (("cfg_scale_ref", cfg_scale_ref), ("cfg_scale_ins", cfg_scale_ins)):
            _check_range(name, value, 0.0, 20.0)
    elif cfg_scale != 1.0 and template.build_negative_segments is None:
        # Upstream raises a ValueError here → bare 500. Say what's wrong instead.
        raise HTTPException(
            400,
            "cfg_scale != 1 strengthens the instruction, so it needs one; send an "
            "instruction (e.g. 'Speak clearly and naturally.') or leave cfg_scale at 1",
        )

    upstream.set_all_seeds(seed)
    try:
        inputs = prepare_inputs(
            app.state.tokenizer,
            app.state.audio_tokenizer,
            app.state.model,
            [request],
            template,
            guidance_scale=1.0 if dual_cfg else cfg_scale,
            guidance_scale_ref=cfg_scale_ref,
            guidance_scale_ins=cfg_scale_ins,
        )
    except (ValueError, RuntimeError, sf.LibsndfileError) as exc:
        raise HTTPException(400, f"could not prepare request: {exc}") from exc
    prompt_len = int(inputs["input_ids"].shape[1])
    available = min(max_new_tokens, upstream.MAX_SEQ_LEN - prompt_len)
    needed = _estimated_frames(text) if needed_frames is None else needed_frames
    if needed_frames is not None:
        # Exact, not an estimate: the frame loop stops once prefill + step reaches
        # max_seq_len - 1, so one position fewer fits than the header budget says.
        available = min(max_new_tokens, upstream.MAX_SEQ_LEN - 1 - prompt_len)
    if needed > available and needed_frames is not None:
        raise HTTPException(
            400,
            f"source_audio is {needed} codec frames but only {available} fit after a "
            f"{prompt_len}-token prompt (limits: {upstream.MAX_SEQ_LEN} positions, "
            f"max_new_tokens {max_new_tokens}); split the source",
        )
    if needed > available:
        fits = max(int(len(text) * available / needed), 0)
        raise HTTPException(
            400,
            f"text may need ~{needed} audio frames but only {available} fit after a "
            f"{prompt_len}-token prompt (limits: {upstream.MAX_SEQ_LEN} positions, "
            f"max_new_tokens {max_new_tokens}); split it — roughly {fits} characters fit",
        )
    return Prepared(inputs, request_id, seed, prompt_len, dual_cfg)


def _model_audio(prepared: Prepared) -> Iterator[np.ndarray]:
    """Float audio chunks from upstream's streaming runtime (2 codec frames each)."""
    with closing(
        upstream._iter_seeded_audio_chunks(
            app.state.runtime,
            prepared.inputs,
            request_id=prepared.request_id,
            seed=prepared.seed,
        )
    ) as chunks:
        for chunk in chunks:
            yield chunk.audio


@contextlib.contextmanager
def _weights_in_model_dtype() -> Iterator[None]:
    """Run the HF generate path with every weight back in the model dtype.

    Upstream's fast paths recast *shared* modules to fp32 in place: the depth
    decoder graph its `codebooks_head` (built by the first streamed request or
    at warmup), the backbone decode graph the whole `lm_head` (fast modes). HF
    `model.generate` then calls `F.linear(bf16, fp32)` and dies. Model-dtype
    copies stand in for the duration of the call; the original fp32 tensors —
    the exact storage the captured CUDA graphs point at — go back afterwards.
    Safe because requests are serialized by upstream's lock.
    """
    model = app.state.model
    dtype = model.dtype
    targets = [
        param
        for param in model.parameters()
        if param.dtype != dtype and param.dtype.is_floating_point
    ]
    swapped: list[tuple[Any, Any]] = []
    try:
        # Inside the try: a cast that fails part-way (OOM) must still put back the
        # ones already swapped, or the captured graphs' fp32 storage is freed under them.
        for param in targets:
            original = param.data
            param.data = original.to(dtype)
            swapped.append((param, original))
        yield
    finally:
        for param, original in reversed(swapped):
            param.data = original


def _dual_cfg_audio(prepared: Prepared) -> Iterator[np.ndarray]:
    """Upstream's non-streaming HF generate — the only path that runs dual CFG.

    Several times slower than real time (no streaming runtime, no CUDA graphs).
    After the fast-mode graphs exist, two shared-module mutations break it:
    the depth decoder's layers/norm are `torch.compile` wrappers built for the
    graph's shapes (HF runs them uncached, at growing lengths, three branches:
    the device-side gather assert), and some heads are recast to fp32. So it
    runs with the original modules and model-dtype weights swapped in, makes
    codes only (`output_audio=False`), and decodes them through the streaming
    codec — not the full-clip decoder, which the fast codec recompiled.
    Everything is restored in `finally`, also on failure; a device-side
    assert still exits the process (`_CleanErrors`) for docker to restart it.
    """
    model = app.state.model
    runtime = app.state.runtime
    upstream.set_all_seeds(prepared.seed)
    runtime_config = runtime.config
    with torch.inference_mode():
        with fast.eager_modules(model), _weights_in_model_dtype():
            sequences = model.generate(
                **prepared.inputs,
                output_audio=False,
                max_new_tokens=runtime_config.max_new_tokens,
                repetition_penalty=runtime_config.repetition_penalty,
            )
        codes = fast.codes_until_pad(sequences, model.config.codebook_pad_token_id)
        audio = fast.decode_codes(
            runtime, codes, codebook_size=int(model.config.codec_config.codebook_size)
        )
    yield np.asarray(audio, dtype=np.float32).reshape(-1)


def _require_forced_frames() -> None:
    if getattr(app.state.runtime, "supports_forced_frames", False):
        return
    reason = (getattr(app.state, "runtime_overlay", None) or {}).get("reason")
    raise HTTPException(
        501,
        "mode=acoustic needs the overlay's runtime (forced frames), which is not active"
        + (f": {reason}" if reason else ""),
    )


def _codes_on_device(codes: Any, device: Any) -> Any:
    return torch.as_tensor(codes).to(device=device, dtype=torch.long)


def _acoustic_audio(
    prepared: Prepared, source_codes: Any, *, keep_acoustic: int, depth: dict[str, Any]
) -> Iterator[np.ndarray]:
    """Acoustic voice conversion: the source's semantic codes, the target's acoustics.

    Breeze-TTS-2.cpp's recipe (docs/voice-conversion.md): prompt the backbone
    with the target reference and text of about the right length, force each
    frame's codebook 0 to the source's, and let the depth decoder regenerate
    codebooks 1-15 for the target voice, near-greedy. `keep_acoustic=N` copies
    the source's lowest N acoustic codebooks as well (pitch; for singing), which
    needs the eager depth step — with the compiled modules swapped back, as in
    `_dual_cfg_audio`. Runs the overlay's streaming loop with forced frames.
    """
    runtime = app.state.runtime
    model = app.state.model
    _require_forced_frames()
    codes = _codes_on_device(source_codes, runtime.device)
    num_codebooks = int(model.config.num_codebooks)
    codebook_size = int(model.config.codec_config.codebook_size)
    if codes.ndim != 2 or int(codes.shape[1]) != num_codebooks:
        raise HTTPException(500, f"source encoded to codes of shape {tuple(codes.shape)}")
    if bool(((codes < 0) | (codes >= codebook_size)).any()):
        raise HTTPException(500, "source encoded to codes outside the codec's codebook")
    forced = fast.ForcedFrames(codes=codes, depth_params=depth)
    swap: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()
    if keep_acoustic:
        forced.depth_fn = fast.forced_depth_fn(
            model,
            codes,
            keep_acoustic=keep_acoustic,
            params=depth,
            sample=runtime._lean_sample_logits,
            codec_codebook_size=codebook_size,
        )
        swap = fast.eager_modules(model)
    upstream.set_all_seeds(prepared.seed)
    with (
        swap,
        closing(
            runtime.iter_audio_chunks(
                prepared.inputs, request_id=prepared.request_id, seed=prepared.seed, forced=forced
            )
        ) as chunks,
    ):
        for chunk in chunks:
            yield chunk.audio


def _pcm_chunks(prepared: Prepared | list[Prepared], limiter: bool) -> PcmGenerator:
    """PCM for one prepared request, or several voiced back to back (inline direction)."""
    for part in prepared if isinstance(prepared, list) else [prepared]:
        source = _dual_cfg_audio(part) if part.dual_cfg else _model_audio(part)
        with closing(source):
            for audio in source:
                pcm = upstream._pcm16(_soft_clip(audio) if limiter else audio)
                if pcm:
                    yield pcm


# ─── app ─────────────────────────────────────────────────────────────────────


class _CleanErrors:
    """Turn an unexpected exception into a JSON 500 instead of a dropped socket.

    Starlette's own handler re-raises after answering, and uvicorn then drops
    the keep-alive connection. Once a body has started streaming nothing can be
    answered any more: the exception propagates and aborts the chunked body, so
    the client sees an incomplete response rather than a silently short clip.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if "device-side assert" in str(exc):
                # A device-side assert poisons the CUDA context for good: every
                # later request would fail. Exit so docker restarts the container.
                print(f"breeze overlay: fatal CUDA error, exiting: {exc}", flush=True)
                os._exit(70)
            if started:
                raise
            print(f"breeze overlay: unhandled {type(exc).__name__}: {exc}", flush=True)
            response = JSONResponse(
                {"detail": f"internal error: {type(exc).__name__}: {exc}"}, status_code=500
            )
            await response(scope, receive, send)


app = FastAPI(
    title="Breeze TTS 2 API (yggdrasil overlay)",
    version=API_VERSION,
    lifespan=upstream._lifespan,
)
app.add_middleware(_CleanErrors)
app.state.fast_mode = "eager"  # main() sets the real one before the model loads
app.state.runtime_overlay = fast.InstallStatus(reason="not started via main()").as_dict()


@app.get("/health")
def health() -> JSONResponse:
    if not hasattr(app.state, "runtime"):
        return JSONResponse({"status": "loading"}, status_code=503)
    return JSONResponse(
        {
            "status": "ok",
            "sample_rate": app.state.runtime.sample_rate,
            "api_version": API_VERSION,
            "busy": upstream._request_lock.locked(),
            "fast_mode": app.state.fast_mode,
        }
    )


@app.get("/v1/capabilities")
def capabilities() -> JSONResponse:
    model = app.state.model
    backbone = model.generation_config
    depth = model.depth_decoder.generation_config
    runtime_config = app.state.runtime.config
    return JSONResponse(
        {
            "api_version": API_VERSION,
            "audio": {"sample_rate": SAMPLE_RATE, "sample_format": "s16le", "channels": 1},
            "codec_frame_rate": CODEC_FRAME_RATE,
            "fast_mode": {
                "mode": app.state.fast_mode,
                "stages": FAST_MODES.get(app.state.fast_mode),
                "backbone_compiled": app.state.fast_mode in COMPILE_MODES,
                "note": "fast modes replay CUDA graphs: same sampling knobs per request, but a "
                "seeded take may differ from the same seed in eager mode",
            },
            "runtime": {
                **app.state.runtime_overlay,
                "note": "lean_loop: the overlay's per-frame loop (same tokens and audio as "
                "upstream's for a seed, fewer GPU syncs); forced_frames: needed by "
                "/v1/audio/convert mode=acoustic",
            },
            "concurrency": 1,
            "busy_status": 409,
            "languages": ["en", "zh"],
            "limits": {
                "max_text_chars": MAX_TEXT_CHARS,
                "chunk_chars": CHUNK_CHARS,
                "max_new_tokens": upstream.MAX_NEW_TOKENS,
                "max_audio_seconds": upstream.MAX_NEW_TOKENS / CODEC_FRAME_RATE,
                "max_seq_len": upstream.MAX_SEQ_LEN,
                "prompt_budget": "prompt tokens (instruction + ref_text + text + reference "
                "frames at 12.5/s) + max_new_tokens must fit max_seq_len; text estimated to "
                "need more frames than remain is a 400",
                "frame_estimate": {
                    "words_per_second": _SLOW_WORDS_PER_SECOND,
                    "cjk_chars_per_second": _SLOW_CJK_CHARS_PER_SECOND,
                    "padding_seconds": 1.0,
                },
                "reference_seconds": REF_SECONDS,
            },
            "modes": {
                "voice_design": "text + instruction, no reference",
                "voice_clone": "text + reference (ref_audio+ref_text or voice), no instruction",
                "voice_direction": "text + reference + instruction",
                "voice_conversion": {
                    "endpoint": "POST /v1/audio/convert (experimental, buffered)",
                    "revoice": "transcript-driven (re-speaks source_text in the target voice, "
                    "stretched to the source's duration; the source's intonation is not "
                    "preserved)",
                    "acoustic": "keeps the source's words and timing frame by frame (its "
                    "semantic codes) and regenerates the voice from the target reference; no "
                    "transcript needed (source_text, if given, helps difficult material); "
                    "depth sampling defaults to near-greedy (depth_temperature 0.3, "
                    "depth_top_k 1: wider sampling lets the source voice leak back); "
                    "keep_acoustic=N also copies the source's lowest N acoustic codebooks "
                    f"(pitch; recommended {KEEP_ACOUSTIC_RECOMMENDED[0]} for speech, 1-"
                    f"{KEEP_ACOUSTIC_RECOMMENDED[1]} for singing; slower eager path); 501 "
                    "when the overlay runtime is inactive",
                    "available": {
                        "revoice": True,
                        "acoustic": bool(app.state.runtime_overlay.get("forced_frames")),
                    },
                },
                "dual_cfg": {
                    "available": app.state.fast_mode == "eager" or DUAL_CFG_FAST,
                    "note": "stream=false only; several times slower than real time",
                },
            },
            "defaults": {
                "cfg_scale": upstream.DEFAULT_CFG_SCALE,
                "seed": 42,
                "temperature": backbone.temperature,
                "top_k": backbone.top_k,
                "top_p": backbone.top_p,
                "do_sample": backbone.do_sample,
                "depth_temperature": depth.temperature,
                "depth_top_k": depth.top_k,
                "depth_top_p": depth.top_p,
                "repetition_penalty": runtime_config.repetition_penalty,
                "max_new_tokens": runtime_config.max_new_tokens,
                "speed": 1.0,
                "speed_engine": "rubberband" if RUBBERBAND else "atempo",
                "stream": True,
                "response_format": "pcm",
                "limiter": True,
            },
            "ranges": {
                "cfg_scale": "(0, inf); 1-4 typical; != 1 requires an instruction; 2-3 helps "
                "vocal events fire",
                "cfg_scale_ref": "[0, 20]; with cfg_scale_ins; Voice Direction, stream=false",
                "cfg_scale_ins": "[0, 20]; with cfg_scale_ref; Voice Direction, stream=false",
                "keep_acoustic": "0..15, /v1/audio/convert mode=acoustic only; 0 for speech",
                "temperature": "(0, 5]",
                "top_k": "0 (off) or more",
                "top_p": "(0, 1]",
                "depth_top_k": f"0..{DEPTH_MAX_TOP_K}",
                "repetition_penalty": "(0, 5]",
                "max_new_tokens": f"1..{upstream.MAX_NEW_TOKENS} codec frames",
                "speed": {
                    "min": SPEED_RANGE[0],
                    "max": SPEED_RANGE[1],
                    "recommended": list(SPEED_RECOMMENDED),
                },
                "speed_engine": list(SPEED_ENGINES),
            },  # fmt: skip
            "speed": "experimental post-processing: a pitch-preserving tempo change of the "
            "generated audio (ffmpeg rubberband, else atempo); pauses scale with it. The model "
            "has no native speed — for a performance-level pace, say it in `instruction`.",
            "streaming": {
                "default": True,
                "framing": "chunked transfer of raw s16le PCM (or a WAV header with sizes "
                "0xFFFFFFFF, then PCM, for response_format=wav); each model chunk is "
                f"{STREAM_CHUNK_FRAMES} codec frames = {STREAM_CHUNK_FRAMES / CODEC_FRAME_RATE:.2f}"
                " s of audio; with speed != 1 chunks come out of an ffmpeg pipe instead",
                "incremental": "pcm or wav at speed 1 streams chunk by chunk; speed != 1 "
                "streams through an ffmpeg pipe (bursty; measured ~2.3-3 s to first audio)",
                "buffered_only": [
                    "dual CFG (cfg_scale_ref/cfg_scale_ins): non-streaming HF generate, several "
                    "times slower than real time",
                    "/v1/audio/convert",
                    "stream=false",
                ],
                "stream_headers": [
                    "X-Sample-Rate",
                    "X-Sample-Format",
                    "X-Prompt-Tokens",
                    "X-Max-New-Tokens",
                    "X-Speed",
                    "X-Speed-Engine",
                    "X-Reference-Warning",
                ],
                "truncation": "streamed: audio seconds × 12.5 ≥ X-Max-New-Tokens - 2 means the "
                "clip was cut off by the frame budget; buffered: X-Truncated",
                "buffered_headers": [
                    "X-Audio-Duration",
                    "X-Codec-Frames",
                    "X-Truncated",
                    "X-Generation-Seconds",
                    "X-Speed",
                    "X-Speed-Engine",
                ],
                "errors": "a failure before the first byte is a JSON error status; after it, "
                "the chunked body is aborted (clients see an incomplete body, never a short "
                "clip that looks complete)",
                "disconnect": "closing the connection stops generation and frees the server",
            },  # fmt: skip
            "limiter": "memoryless soft clip above ≈-1 dBFS (per sample, so streaming-safe); "
            "send limiter=false for raw model output",
            "voices": {
                "cache_key": "GET /v1/voices[/{id}] carry sha256 = sha256(stored ref.wav bytes "
                "+ NUL + UTF-8 ref_text) and updated_at (changes on overwrite); refetch the "
                "clip when sha256 changes",
            },
            "vocal_events": {
                "syntax": "inline in text where the sound happens: (event) for English, "
                "[事件] for Chinese; English [event] is accepted and sent as (event); don't mix "
                "EN and ZH tag syntax in one request; if a tag is read aloud, reroll the seed",
                "tiers": TAGS["tiers"],
                "events": TAGS["events"],
            },
            "rejected_text": "audio-slot tokens (they break generation): "
            + TAGS["control_token_pattern"],
            "inline_direction": {
                "syntax": "text <ins_bos>instruction<ins_eos> more text",
                "status": "experimental",
                "how": "the overlay splits text at each inline instruction and voices the "
                "segments back to back (same voice and seed), each with its instruction as "
                "the top-level one at cfg_scale (or "
                f"{INLINE_DEFAULT_CFG:g} when cfg_scale is 1); the model itself drops text "
                "before an inline marker. raw=true sends markers to the model untouched",
                "speaker_tokens": "[S0]-[S9] pass through; no measured effect",
            },
        }
    )


async def _resolve_reference(
    voice: str | None, ref_audio: UploadFile | None, ref_text: str, workdir: Path
) -> tuple[Path | None, str, Voice | None, str | None]:
    """The reference clip + transcript to clone from (uploaded or saved), and a warning."""
    ref_text = _clean_text("ref_text", ref_text)
    has_upload = ref_audio is not None and bool(ref_audio.filename)
    if voice:
        if has_upload:
            raise HTTPException(400, "send either voice or ref_audio, not both")
        saved = _load_voice(voice)
        return saved.ref_audio, ref_text or saved.ref_text, saved, None
    if has_upload != bool(ref_text):
        raise HTTPException(
            400, "ref_audio and ref_text must be provided together or both omitted."
        )
    if not has_upload:
        return None, "", None, None
    assert ref_audio is not None
    raw = await _save_upload(ref_audio, workdir)
    normalized = workdir / "ref.wav"
    duration = await run_in_threadpool(_normalize_clip, raw, normalized, what="ref_audio")
    return normalized, ref_text, None, _ref_warning(duration)


async def _save_upload(upload: UploadFile, workdir: Path, stem: str = "upload") -> Path:
    payload = await upload.read()
    if not payload:
        raise HTTPException(400, f"{upload.filename or 'uploaded file'} is empty.")
    suffix = Path(upload.filename or "audio.wav").suffix or ".wav"
    path = workdir / f"{stem}{suffix}"
    path.write_bytes(payload)
    return path


def _budget_headers(prepared: Prepared, max_new_tokens: int) -> dict[str, str | None]:
    """The frame budget, so a streaming client can spot truncation itself.

    A stream has no trailer for `X-Truncated`; instead: received seconds ×
    12.5 ≥ `X-Max-New-Tokens` - 2 means the clip hit the budget and was cut off.
    """
    budget = min(max_new_tokens, upstream.MAX_SEQ_LEN - prepared.prompt_len)
    return {"X-Prompt-Tokens": str(prepared.prompt_len), "X-Max-New-Tokens": str(budget)}


def _audio_headers(extra: dict[str, str | None] | None = None) -> dict[str, str]:
    headers = {
        "X-Sample-Rate": str(SAMPLE_RATE),
        "X-Sample-Format": "s16le",
        "Cache-Control": "no-store",
    }
    headers.update({key: value for key, value in (extra or {}).items() if value is not None})
    return headers


class _LockedRequest:
    """Hold upstream's single-request lock and a scratch dir for one request."""

    def __init__(self) -> None:
        """Use `await _LockedRequest.acquire()`; this assumes the lock is already held."""
        self.workdir = Path(tempfile.mkdtemp(prefix="breeze_req_"))
        self._undo: list[Callable[[], None]] = []
        self._released = False

    @classmethod
    async def acquire(cls) -> _LockedRequest:
        """Take the lock, waiting up to `BUSY_WAIT_SECONDS` for a request winding down."""
        lock = upstream._request_lock
        if not lock.acquire(blocking=False) and not (
            BUSY_WAIT_SECONDS > 0
            and await run_in_threadpool(lock.acquire, timeout=BUSY_WAIT_SECONDS)
        ):
            raise HTTPException(409, "An inference request is already running.")
        return cls()

    def defer(self, undo: Callable[[], None]) -> None:
        self._undo.append(undo)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            for undo in reversed(self._undo):
                undo()
            shutil.rmtree(self.workdir, ignore_errors=True)
        finally:
            upstream._request_lock.release()


def _streaming_response(
    pcm: PcmGenerator, output: Output, held: _LockedRequest, headers: dict[str, str | None]
) -> StreamingResponse:
    speed_engine = None
    if output.speed != 1.0:
        audio_filter, speed_engine = _speed_filter(output.speed, output.speed_engine)
        pcm = _stretch_stream(pcm, audio_filter)

    def body() -> PcmGenerator:
        with closing(pcm):
            if output.response_format == "wav":
                yield _wav_header(None)
            yield from pcm

    return upstream._InferenceStreamingResponse(
        body(),
        held.release,
        media_type="audio/wav" if output.response_format == "wav" else "audio/pcm",
        headers=_audio_headers(
            {**headers, "X-Speed": f"{output.speed:g}", "X-Speed-Engine": speed_engine}
        ),
    )


def _buffered_response(
    pcm_chunks: Iterable[bytes],
    output: Output,
    *,
    prompt_len: int,
    max_new_tokens: int,
    started: float,
    headers: dict[str, str | None],
    speed: float | None = None,
) -> Response:
    pcm = b"".join(pcm_chunks)
    frames = round(len(pcm) / 2 / SAMPLE_RATE * CODEC_FRAME_RATE)
    budget = min(max_new_tokens, upstream.MAX_SEQ_LEN - prompt_len)
    speed = output.speed if speed is None else speed
    speed_engine = None
    if speed != 1.0 and pcm:
        audio_filter, speed_engine = _speed_filter(speed, output.speed_engine)
        pcm = _ffmpeg(_ffmpeg_pcm_args(audio_filter), stdin=pcm, what="speed change", status=500)
    body = _wav_header(len(pcm)) + pcm if output.response_format == "wav" else pcm
    return Response(
        body,
        media_type="audio/wav" if output.response_format == "wav" else "audio/pcm",
        headers=_audio_headers(
            {
                **headers,
                "X-Audio-Duration": f"{len(pcm) / 2 / SAMPLE_RATE:.3f}",
                "X-Codec-Frames": str(frames),
                "X-Truncated": "true" if frames >= budget - 2 else "false",
                "X-Generation-Seconds": f"{time.perf_counter() - started:.2f}",
                "X-Speed": f"{speed:g}",
                "X-Speed-Engine": speed_engine,
            }
        ),
    )


@app.post("/v1/audio/speech")
async def speech(
    request: Request,
    text: str = Form(""),
    instruction: str | None = Form(None),
    cfg_scale: float = Form(upstream.DEFAULT_CFG_SCALE),
    cfg_scale_ref: float | None = Form(None),
    cfg_scale_ins: float | None = Form(None),
    ref_audio: UploadFile | None = File(None),  # noqa: B008 - FastAPI binds each File()
    ref_text: str = Form(""),
    voice: str | None = Form(None),
    seed: int = Form(42),
    raw: bool = Form(False),
    stream: bool | None = Form(None),
    speed: float = Form(1.0),
    speed_engine: str = Form("rubberband"),
    response_format: str = Form("pcm"),
    limiter: bool = Form(True),
    temperature: float | None = Form(None),
    top_k: int | None = Form(None),
    top_p: float | None = Form(None),
    do_sample: bool | None = Form(None),
    depth_temperature: float | None = Form(None),
    depth_top_k: int | None = Form(None),
    depth_top_p: float | None = Form(None),
    repetition_penalty: float | None = Form(None),
    max_new_tokens: int | None = Form(None),
) -> Response:
    await _reject_unknown_fields(request, SPEECH_FIELDS)
    sampling = Sampling(
        temperature, top_k, top_p, do_sample, depth_temperature, depth_top_k, depth_top_p,
        repetition_penalty, max_new_tokens,
    )  # fmt: skip
    sampling.validate()
    output = Output(speed, speed_engine, response_format, limiter)
    output.validate()
    text = _clean_text("text", text, required=True)
    _check_text_length(text)
    instruction = _clean_text("instruction", instruction) or None
    ref_text = _clean_text("ref_text", ref_text)  # before the lock: a bad one is a cheap 400
    dual_cfg = cfg_scale_ref is not None or cfg_scale_ins is not None
    if dual_cfg and app.state.fast_mode != "eager" and not DUAL_CFG_FAST:
        # BREEZE_DUAL_CFG_FAST unset/0 (the default): HF generate after the fast-mode
        # graphs hits a device-side gather assert that kills the process, so refuse it.
        raise HTTPException(
            400,
            f"dual CFG (cfg_scale_ref/cfg_scale_ins) is disabled in fast mode "
            f"{app.state.fast_mode!r} on this server (eager only); use cfg_scale",
        )
    segments = _segments(text, instruction, cfg_scale, raw=raw)
    if dual_cfg and len(segments) > 1:
        raise HTTPException(400, "inline instructions can't combine with dual CFG")
    if dual_cfg and stream:
        raise HTTPException(400, "dual CFG can't stream; send stream=false (or omit stream)")
    streaming = not dual_cfg if stream is None else stream

    held = await _LockedRequest.acquire()
    handed_off = False
    try:
        ref_path, ref_text, saved, warning = await _resolve_reference(
            voice, ref_audio, ref_text, held.workdir
        )
        default_instruction = saved.instruction if saved else None
        if segments[0].instruction is None and default_instruction:
            segments[0] = replace(segments[0], instruction=default_instruction)
        budget = sampling.max_new_tokens or app.state.runtime.config.max_new_tokens
        parts = await run_in_threadpool(
            lambda: [
                _prepare(
                    text=segment.text,
                    instruction=segment.instruction,
                    cfg_scale=segment.cfg_scale,
                    cfg_scale_ref=cfg_scale_ref,
                    cfg_scale_ins=cfg_scale_ins,
                    ref_path=ref_path,
                    ref_text=ref_text,
                    seed=seed,
                    max_new_tokens=budget,
                )
                for segment in segments
            ]
        )
        prepared = max(parts, key=lambda part: part.prompt_len)  # the tightest budget
        held.defer(_apply_sampling(sampling))
        headers = {
            "X-Reference-Warning": warning,
            "X-Inline-Segments": str(len(parts)) if len(parts) > 1 else None,
            **_budget_headers(prepared, budget),
        }
        if streaming:
            response = _streaming_response(_pcm_chunks(parts, limiter), output, held, headers)
            handed_off = True  # the response's cleanup releases the lock now
            return response
        started = time.perf_counter()
        chunks = await run_in_threadpool(lambda: list(_pcm_chunks(parts, limiter)))
        return await run_in_threadpool(
            lambda: _buffered_response(
                chunks,
                output,
                prompt_len=prepared.prompt_len,
                max_new_tokens=budget,
                started=started,
                headers=headers,
            )  # fmt: skip
        )
    finally:
        if not handed_off:
            held.release()


@app.post("/v1/audio/convert")
async def convert(
    request: Request,
    source_audio: UploadFile = File(...),  # noqa: B008 - FastAPI binds each File()
    source_text: str = Form(""),
    mode: str = Form("revoice"),
    voice: str | None = Form(None),
    ref_audio: UploadFile | None = File(None),  # noqa: B008 - FastAPI binds each File()
    ref_text: str = Form(""),
    instruction: str | None = Form(None),
    cfg_scale: float = Form(upstream.DEFAULT_CFG_SCALE),
    seed: int = Form(42),
    match_duration: bool = Form(True),
    keep_acoustic: int = Form(0),
    speed: float = Form(1.0),
    speed_engine: str = Form("rubberband"),
    response_format: str = Form("wav"),
    limiter: bool = Form(True),
    temperature: float | None = Form(None),
    top_k: int | None = Form(None),
    top_p: float | None = Form(None),
    do_sample: bool | None = Form(None),
    depth_temperature: float | None = Form(None),
    depth_top_k: int | None = Form(None),
    depth_top_p: float | None = Form(None),
    repetition_penalty: float | None = Form(None),
    max_new_tokens: int | None = Form(None),
) -> Response:
    """Re-voice a recording in the target voice. Experimental; always buffered.

    `mode=revoice` is transcript-driven: the words come from `source_text`, the
    timing from the source's duration (`match_duration`, unless `speed` is set),
    and the source's intonation is not carried over — describe it in
    `instruction`. `mode=acoustic` keeps the source's words and timing frame by
    frame (its semantic codes) and regenerates the voice (see `_acoustic_audio`);
    `source_text` is optional there and only steadies difficult material.
    """
    await _reject_unknown_fields(request, CONVERT_FIELDS)
    if mode not in ("revoice", "acoustic"):
        raise HTTPException(400, "mode must be 'revoice' or 'acoustic'")
    acoustic = mode == "acoustic"
    sampling = Sampling(
        temperature, top_k, top_p, do_sample, depth_temperature, depth_top_k, depth_top_p,
        repetition_penalty, max_new_tokens,
    )  # fmt: skip
    sampling.validate()
    output = Output(speed, speed_engine, response_format, limiter)
    output.validate()
    if acoustic:
        num_decode = _num_codebooks() - 1
        _check_range("keep_acoustic", keep_acoustic, 0, num_decode)
        source_text = _clean_text("source_text", source_text)
        if source_text:
            _check_text_length(source_text)
    else:
        if keep_acoustic:
            raise HTTPException(400, "keep_acoustic applies to mode=acoustic only")
        try:
            source_text = _clean_text("source_text", source_text, required=True)
        except HTTPException as exc:
            if "empty" not in str(exc.detail):
                raise
            raise HTTPException(
                400,
                "source_text (the exact transcript of source_audio) is required for "
                "mode=revoice: it re-voices from the words, it does not recognize speech "
                "(mode=acoustic needs no transcript)",
            ) from exc
        _check_text_length(source_text)
    instruction = _clean_text("instruction", instruction) or None
    ref_text = _clean_text("ref_text", ref_text)

    held = await _LockedRequest.acquire()
    try:
        source = await _save_upload(source_audio, held.workdir, stem="source")
        source_norm = held.workdir / "source.norm.wav"
        source_seconds = await run_in_threadpool(
            _normalize_clip, source, source_norm, what="source_audio"
        )
        ref_path, ref_text, saved, warning = await _resolve_reference(
            voice, ref_audio, ref_text, held.workdir
        )
        if ref_path is None:
            raise HTTPException(400, "convert needs a target voice: voice, or ref_audio+ref_text")
        instruction = instruction or (saved.instruction if saved else None)
        budget = sampling.max_new_tokens or app.state.runtime.config.max_new_tokens
        headers: dict[str, str | None] = {
            "X-Reference-Warning": warning,
            "X-Source-Duration": f"{source_seconds:.3f}",
            "X-Conversion-Mode": mode,
        }
        if acoustic:
            return await _convert_acoustic(
                held,
                source_norm=source_norm,
                source_seconds=source_seconds,
                source_text=source_text,
                ref_path=ref_path,
                ref_text=ref_text,
                instruction=instruction,
                cfg_scale=cfg_scale,
                seed=seed,
                budget=budget,
                keep_acoustic=keep_acoustic,
                sampling=sampling,
                output=output,
                headers=headers,
            )
        prepared = await run_in_threadpool(
            lambda: _prepare(
                text=source_text,
                instruction=instruction,
                cfg_scale=cfg_scale,
                cfg_scale_ref=None,
                cfg_scale_ins=None,
                ref_path=ref_path,
                ref_text=ref_text,
                seed=seed,
                max_new_tokens=budget,
            )
        )
        held.defer(_apply_sampling(sampling))
        started = time.perf_counter()
        chunks = await run_in_threadpool(lambda: list(_pcm_chunks(prepared, limiter)))
        produced = sum(len(chunk) for chunk in chunks) / 2 / SAMPLE_RATE
        effective_speed = output.speed
        if match_duration and output.speed == 1.0 and produced:  # an explicit speed wins
            effective_speed = min(max(produced / source_seconds, SPEED_RANGE[0]), SPEED_RANGE[1])
        return await run_in_threadpool(
            lambda: _buffered_response(
                chunks,
                output,
                prompt_len=prepared.prompt_len,
                max_new_tokens=budget,
                started=started,
                speed=effective_speed,
                headers={**headers, **_budget_headers(prepared, budget)},
            )  # fmt: skip
        )
    finally:
        held.release()


def _num_codebooks() -> int:
    return int(app.state.model.config.num_codebooks)


async def _convert_acoustic(
    held: _LockedRequest,
    *,
    source_norm: Path,
    source_seconds: float,
    source_text: str,
    ref_path: Path,
    ref_text: str,
    instruction: str | None,
    cfg_scale: float,
    seed: int,
    budget: int,
    keep_acoustic: int,
    sampling: Sampling,
    output: Output,
    headers: dict[str, str | None],
) -> Response:
    """mode=acoustic, under the request lock `held`."""
    _require_forced_frames()  # before the GPU encode
    encode = upstream_templates._encode_prompt_audio  # the cached seam
    source_codes = await run_in_threadpool(encode, app.state.audio_tokenizer, str(source_norm))
    frames = int(source_codes.shape[0])
    text = source_text or fast.filler_text(source_seconds)
    prepared = await run_in_threadpool(
        lambda: _prepare(
            text=text,
            instruction=instruction,
            cfg_scale=cfg_scale,
            cfg_scale_ref=None,
            cfg_scale_ins=None,
            ref_path=ref_path,
            ref_text=ref_text,
            seed=seed,
            max_new_tokens=budget,
            needed_frames=frames,
        )
    )
    held.defer(_apply_sampling(sampling))  # backbone knobs are unused: codebook 0 is forced
    defaults = fast.ACOUSTIC_DEPTH_DEFAULTS
    depth = {
        "temperature": _or(sampling.depth_temperature, defaults["temperature"]),
        "top_k": _or(sampling.depth_top_k, defaults["top_k"]),
        "top_p": _or(sampling.depth_top_p, defaults["top_p"]),
        "do_sample": _or(sampling.do_sample, defaults["do_sample"]),
    }
    started = time.perf_counter()

    def run() -> list[bytes]:
        source = _acoustic_audio(prepared, source_codes, keep_acoustic=keep_acoustic, depth=depth)
        with closing(source):
            return [
                pcm
                for audio in source
                if (pcm := upstream._pcm16(_soft_clip(audio) if output.limiter else audio))
            ]

    chunks = await run_in_threadpool(run)
    return await run_in_threadpool(
        lambda: _buffered_response(
            chunks,
            output,
            prompt_len=prepared.prompt_len,
            max_new_tokens=budget,
            started=started,
            headers={
                **headers,
                **_budget_headers(prepared, budget),
                "X-Source-Frames": str(frames),
                "X-Keep-Acoustic": str(keep_acoustic),
                "X-Source-Text": "given" if source_text else "filler",
            },
        )  # fmt: skip
    )


def _or(value: Any, default: Any) -> Any:
    return default if value is None else value


@app.get("/v1/voices")
def list_voices() -> JSONResponse:
    if not VOICES_DIR.is_dir():
        return JSONResponse({"voices": []})
    voices = [_voice_meta(meta.parent) for meta in sorted(VOICES_DIR.glob("*/voice.json"))]
    return JSONResponse({"voices": voices})


@app.get("/v1/voices/{voice_id}")
def get_voice(voice_id: str) -> JSONResponse:
    return JSONResponse(_load_voice(voice_id).meta)


@app.get("/v1/voices/{voice_id}/audio")
def get_voice_audio(voice_id: str) -> Response:
    saved = _load_voice(voice_id)
    return Response(saved.ref_audio.read_bytes(), media_type="audio/wav")


@app.post("/v1/voices")
async def create_voice(
    request: Request,
    id: str = Form(...),
    ref_audio: UploadFile = File(...),  # noqa: B008 - FastAPI binds each File()
    ref_text: str = Form(""),
    instruction: str | None = Form(None),
    description: str | None = Form(None),
    overwrite: bool = Form(False),
) -> JSONResponse:
    """Save a reference clip + transcript (and an optional default instruction)."""
    await _reject_unknown_fields(request, VOICE_FIELDS)
    folder = _voice_dir(id)
    ref_text = _clean_text("ref_text", ref_text, required=True)
    instruction = _clean_text("instruction", instruction) or None
    if folder.exists() and not overwrite:
        raise HTTPException(409, f"voice {id!r} exists; send overwrite=true to replace it")
    workdir = Path(tempfile.mkdtemp(prefix="breeze_voice_"))
    try:
        raw = await _save_upload(ref_audio, workdir)
        normalized = workdir / "ref.wav"
        duration = await run_in_threadpool(_normalize_clip, raw, normalized, what="ref_audio")
        audio = normalized.read_bytes()
        now = _utc()
        meta = {
            "id": id,
            "ref_text": ref_text,
            "instruction": instruction,
            "description": (description or "").strip() or None,
            "duration_s": round(duration, 3),
            "warning": _ref_warning(duration),
            "sha256": _voice_sha256(audio, ref_text),
            "created_at": now,
            "updated_at": now,
        }
        # Under the request lock, so no request reads a half-swapped clip/transcript pair.
        held = await _LockedRequest.acquire()
        try:
            with contextlib.suppress(OSError, ValueError, KeyError):  # overwrite keeps its birth
                meta["created_at"] = json.loads((folder / "voice.json").read_text())["created_at"]
            folder.mkdir(parents=True, exist_ok=True)
            # Clip first, metadata last: voice.json is what makes a voice exist.
            _atomic_write(folder / "ref.wav", audio)
            _atomic_write(
                folder / "voice.json", json.dumps(meta, ensure_ascii=False, indent=2).encode()
            )
        finally:
            held.release()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return JSONResponse(meta, status_code=201)


@app.delete("/v1/voices/{voice_id}")
async def delete_voice(voice_id: str) -> Response:
    folder = _voice_dir(voice_id)
    if not folder.is_dir():
        raise HTTPException(404, f"no saved voice {voice_id!r}")
    held = await _LockedRequest.acquire()  # not out from under a request using it
    try:
        shutil.rmtree(folder)
    finally:
        held.release()
    return Response(status_code=204)


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
)
async def not_found(request: Request, path: str) -> JSONResponse:
    """A clean 404 for unknown routes. Starlette's default answers without reading the
    body, so uvicorn drops the keep-alive socket mid-upload; draining it first doesn't."""
    await request.body()
    return JSONResponse({"detail": f"no route /{path}"}, status_code=404)


def _fast_mode_from_env() -> str:
    """The default preset: `BREEZE_FAST_MODE` (compose.yml sets it), else eager."""
    mode = os.environ.get("BREEZE_FAST_MODE", "").strip()
    if not mode:
        return "eager"
    if mode not in FAST_MODES:
        print(f"breeze overlay: ignoring unknown fast mode {mode!r}; using eager", flush=True)
        return "eager"
    return mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Breeze TTS 2 (yggdrasil overlay)")
    parser.add_argument("model", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument(
        "--fast-mode",
        choices=sorted(FAST_MODES),
        default=None,
        help="stage preset (default: $BREEZE_FAST_MODE, else eager); "
        "--fast-* flags below override single stages",
    )
    for stage in FAST_MODES["full"]:
        parser.add_argument(
            f"--{stage.replace('_', '-')}", action=argparse.BooleanOptionalAction, default=None
        )
    args = parser.parse_args()
    mode = args.fast_mode or _fast_mode_from_env()
    stages = {
        stage: enabled if getattr(args, stage) is None else getattr(args, stage)
        for stage, enabled in FAST_MODES[mode].items()
    }
    if stages == FAST_MODES[mode]:
        name = mode
    else:
        matched = [n for n, preset in FAST_MODES.items() if preset == stages]
        name = next((n for n in matched if n not in COMPILE_MODES), "custom")
    compile_backbone = name in COMPILE_MODES
    status = fast.install(upstream, lean_loop=LEAN_LOOP, compile_backbone=compile_backbone)
    if compile_backbone and not status.compile_backbone:
        name = "full"  # /health then says so, and pick-fast-mode.sh flags the mismatch
    if status.reason:
        print(f"breeze overlay: upstream runtime kept: {status.reason}", flush=True)
    app.state.runtime_overlay = status.as_dict()
    app.state.fast_mode = name
    print(
        f"breeze overlay: fast mode {app.state.fast_mode} {stages} {status.as_dict()}", flush=True
    )
    upstream._settings = upstream.ApiSettings(
        model=args.model,
        fast_all=None,
        fast_text_encoder=False,  # see FAST_MODES: these two freeze prompt-length buckets
        fast_backbone_prefill=False,
        **stages,
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
