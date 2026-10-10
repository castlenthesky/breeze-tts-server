"""HTTP-level tests for the overlay, with upstream's runtime and torch stubbed out.

Run locally (no GPU, no model), from the repo root:
    uv run --no-project --with fastapi --with httpx --with numpy --with soundfile \\
        --with python-multipart --with pytest \\
        pytest tests/test_overlay.py

Tests that need ffmpeg (clip normalization, time-stretch) skip without it; the
breeze-tts-2 container has it (locally, any static ffmpeg on PATH will do).

The torch-level runtime (`yggdrasil_breeze_fast`) has its own tests, which need
real torch and so run in a separate session: see `test_runtime_torch.py`.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import threading
import types
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

RATE = 24000
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


# ─── stubs for upstream breeze_infer and torch ──────────────────────────────


@dataclass(frozen=True)
class FakeConfig:
    max_new_tokens: int = 1500
    repetition_penalty: float = 1.1


@dataclass
class FakeGenConfig:
    temperature: float = 0.9
    top_k: int = 50
    top_p: float = 1.0
    do_sample: bool = True


@dataclass
class FakeRuntime:
    """Yields `seconds` of constant audio in 4 chunks, recording what it saw."""

    config: FakeConfig = field(default_factory=FakeConfig)
    sample_rate: int = RATE
    seconds: float = 0.5
    amplitude: float = 0.25
    fail_after_chunks: int | None = None
    seen: list[dict[str, Any]] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    model: Any = None

    supports_forced_frames: bool = False
    device: str = "cpu"

    def iter_audio_chunks(self, inputs, *, request_id, seed, token_observer=None, forced=None):
        self.seen.append(
            {
                "inputs": inputs,
                "seed": seed,
                "temperature": self.model.generation_config.temperature,
                "depth_top_k": self.model.depth_decoder.generation_config.top_k,
                "max_new_tokens": self.config.max_new_tokens,
                "forced": forced,
            }
        )
        seconds = self.seconds if forced is None else forced.frames / 12.5
        audio = np.full(round(seconds * RATE), self.amplitude, dtype=np.float32)
        try:
            for index, part in enumerate(np.array_split(audio, 4)):
                if self.fail_after_chunks is not None and index == self.fail_after_chunks:
                    raise RuntimeError("model blew up mid-stream")
                yield types.SimpleNamespace(audio=part)
        finally:
            self.closed.append(request_id)


@dataclass(frozen=True)
class FakeTemplate:
    name: str
    build_negative_segments: Any = None
    build_dual_branches: Any = None


TEMPLATES = {
    "tts_plain": FakeTemplate("tts_plain"),
    "tts_instruction": FakeTemplate("tts_instruction", build_negative_segments=True),
    "ref_clone_tata": FakeTemplate("ref_clone_tata"),
    "ref_edit_tata": FakeTemplate("ref_edit_tata", True, True),
}
ENCODED: list[str] = []


def _select_template_name(request):
    ref = bool(request.get("ref_audio_path"))
    ins = bool(request.get("instruction"))
    if ref:
        return "ref_edit_tata" if ins else "ref_clone_tata"
    return "tts_instruction" if ins else "tts_plain"


def _encode_prompt_audio(audio_tokenizer, audio_path):
    ENCODED.append(audio_path)
    return np.zeros((25, 16))


def _prepare_inputs(tokenizer, audio_tokenizer, model, requests, template, **cfg):
    request = requests[0]
    prompt_len = 10
    if request.get("ref_audio_path"):  # like upstream: encode through the module seam
        encode = sys.modules["breeze_infer.templates"]._encode_prompt_audio
        prompt_len += len(encode(None, request["ref_audio_path"]))
    return {
        "input_ids": np.zeros((1, prompt_len)),
        "request": request,
        "template": template.name,
        **cfg,
    }


def _install_stubs() -> None:
    from fastapi.responses import StreamingResponse

    class InferenceStreamingResponse(StreamingResponse):
        """Upstream's contract: close the body generator, then run cleanup."""

        def __init__(self, stream, cleanup, **kwargs):
            super().__init__(stream, **kwargs)
            self._stream = stream
            self._cleanup = cleanup

        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                try:
                    self._stream.close()
                finally:
                    self._cleanup()

    @asynccontextmanager
    async def lifespan(app):
        yield

    api = types.ModuleType("breeze_infer.api")
    api.MAX_NEW_TOKENS = 1500
    api.MAX_SEQ_LEN = 2048
    api.DEFAULT_CFG_SCALE = 1.0
    api._request_lock = threading.Lock()
    api._settings = None
    api.ApiSettings = lambda **kwargs: kwargs
    api.set_all_seeds = lambda seed: None
    api._pcm16 = lambda audio: (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    api._iter_seeded_audio_chunks = lambda runtime, inputs, *, request_id, seed: (
        runtime.iter_audio_chunks(inputs, request_id=request_id, seed=seed)
    )
    api._InferenceStreamingResponse = InferenceStreamingResponse
    api._lifespan = lifespan

    templates = types.ModuleType("breeze_infer.templates")
    templates.get_template = TEMPLATES.__getitem__
    templates.prepare_inputs = _prepare_inputs
    templates.select_template_name = _select_template_name
    templates._encode_prompt_audio = _encode_prompt_audio

    package = types.ModuleType("breeze_infer")
    package.api = api
    package.templates = templates
    sys.modules.update(
        {"breeze_infer": package, "breeze_infer.api": api, "breeze_infer.templates": templates}
    )
    sys.modules.setdefault("torch", types.ModuleType("torch"))


_install_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from fastapi.testclient import TestClient  # noqa: E402

import yggdrasil_breeze_api as overlay  # noqa: E402


@pytest.fixture
def runtime(tmp_path, monkeypatch) -> FakeRuntime:
    model = types.SimpleNamespace(
        generation_config=FakeGenConfig(),
        depth_decoder=types.SimpleNamespace(generation_config=FakeGenConfig()),
        config=types.SimpleNamespace(
            num_codebooks=16,
            codebook_pad_token_id=2050,
            codec_config=types.SimpleNamespace(codebook_size=2048),
        ),
    )
    runtime = FakeRuntime(model=model)
    overlay.app.state.runtime = runtime
    overlay.app.state.model = model
    overlay.app.state.tokenizer = None
    overlay.app.state.audio_tokenizer = None
    monkeypatch.setattr(overlay, "VOICES_DIR", tmp_path / "voices")
    return runtime


@pytest.fixture
def client(runtime) -> TestClient:
    return TestClient(overlay.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _lock_is_free_afterwards():
    yield
    assert not overlay.upstream._request_lock.locked(), "request lock leaked"


def _wav_upload(seconds: float = 4.0, name: str = "ref.wav") -> tuple[str, bytes, str]:
    buffer = io.BytesIO()
    sf.write(buffer, np.full(round(seconds * RATE), 0.2, dtype=np.float32), RATE, format="WAV")
    return (name, buffer.getvalue(), "audio/wav")


def _pcm_seconds(body: bytes) -> float:
    return len(body) / 2 / RATE


# ─── /v1/audio/speech: contract and streaming ────────────────────────────────


def test_plain_request_streams_pcm_like_upstream(client, runtime):
    response = client.post("/v1/audio/speech", data={"text": "Hello"})
    assert response.status_code == 200
    assert response.headers["x-sample-rate"] == "24000"
    assert _pcm_seconds(response.content) == pytest.approx(0.5)
    assert runtime.seen[0]["inputs"]["template"] == "tts_plain"
    assert runtime.closed  # the model generator was closed


def test_streamed_wav_has_an_open_ended_header(client):
    response = client.post("/v1/audio/speech", data={"text": "Hi", "response_format": "wav"})
    assert response.headers["content-type"] == "audio/wav"
    header, pcm = response.content[:44], response.content[44:]
    assert header[:4] == b"RIFF" and header[40:44] == b"\xff\xff\xff\xff"
    assert _pcm_seconds(pcm) == pytest.approx(0.5)
    assert "x-audio-duration" not in response.headers  # streamed: unknown up front


def test_buffered_wav_has_real_sizes_and_metadata(client):
    response = client.post(
        "/v1/audio/speech", data={"text": "Hi", "response_format": "wav", "stream": "false"}
    )
    with sf.SoundFile(io.BytesIO(response.content)) as wav:
        assert wav.frames == RATE // 2
    assert response.headers["x-audio-duration"] == "0.500"
    assert response.headers["x-truncated"] == "false"


def test_client_disconnect_mid_stream_frees_the_server(client, runtime):
    runtime.seconds = 4.0
    with client.stream("POST", "/v1/audio/speech", data={"text": "Long"}) as response:
        next(response.iter_bytes())
    # The autouse fixture asserts the lock is free; the model generator closed too.
    assert runtime.closed
    assert client.post("/v1/audio/speech", data={"text": "Next"}).status_code == 200


def test_mid_stream_failure_aborts_the_body(client, runtime):
    # Over a real socket uvicorn aborts the chunked body (an incomplete-body error
    # client-side); the in-process TestClient just hands back what arrived.
    runtime.fail_after_chunks = 2
    partial = client.post("/v1/audio/speech", data={"text": "Hi"})
    assert _pcm_seconds(partial.content) < 0.5  # never a complete-looking clip
    runtime.fail_after_chunks = None
    assert client.post("/v1/audio/speech", data={"text": "Hi again"}).status_code == 200


def test_limiter_soft_clips_and_can_be_disabled(client, runtime):
    runtime.amplitude = 1.5
    limited = np.frombuffer(client.post("/v1/audio/speech", data={"text": "Hi"}).content, "<i2")
    raw = np.frombuffer(
        client.post("/v1/audio/speech", data={"text": "Hi", "limiter": "false"}).content, "<i2"
    )
    assert 0.89 * 32767 < limited.max() < 32767
    assert raw.max() == 32767  # hard-clipped by the PCM conversion


def test_sampling_overrides_apply_then_restore(client, runtime):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "temperature": "0.5", "depth_top_k": "10", "max_new_tokens": "200"},
    )
    assert response.status_code == 200
    seen = runtime.seen[0]
    assert (seen["temperature"], seen["depth_top_k"], seen["max_new_tokens"]) == (0.5, 10, 200)
    assert runtime.model.generation_config.temperature == 0.9
    assert runtime.model.depth_decoder.generation_config.top_k == 50
    assert runtime.config.max_new_tokens == 1500


# ─── /v1/audio/speech: validation ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("temperature", "0"),
        ("top_p", "1.5"),
        ("depth_top_k", "5000"),
        ("max_new_tokens", "0"),
        ("speed", "-1"),
        ("speed", "3"),
        ("speed_engine", "sox"),
        ("response_format", "mp3"),
    ],
)
def test_out_of_range_fields_are_400(client, field_name, value):
    response = client.post("/v1/audio/speech", data={"text": "Hi", field_name: value})
    assert response.status_code == 400, response.text


def test_unknown_fields_are_400(client):
    response = client.post("/v1/audio/speech", data={"text": "Hi", "sped": "1.2"})
    assert response.status_code == 400
    assert "sped" in response.json()["detail"]


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_text_is_400_with_a_curl_hint(client, text):
    response = client.post("/v1/audio/speech", data={"text": text})
    assert response.status_code == 400
    assert "--form-string" in response.json()["detail"]


@pytest.mark.parametrize("text", ["<|AUDIO|>", "x<|audio_eos|>", "Hi <|AUDIO|> there"])
def test_audio_slot_tokens_are_400(client, text):
    response = client.post("/v1/audio/speech", data={"text": text})
    assert response.status_code == 400
    assert "audio-slot tokens" in response.json()["detail"]


def test_speaker_tokens_pass_through_untouched(client, runtime):
    response = client.post(
        "/v1/audio/speech", data={"text": "[S1] Hi there.", "instruction": "[S0] calm"}
    )
    assert response.status_code == 200
    request = runtime.seen[0]["inputs"]["request"]
    assert (request["text"], request["instruction"]) == ("[S1] Hi there.", "[S0] calm")


def test_inline_instructions_are_voiced_as_segments(client, runtime):
    text = (
        "<ins_bos>Whisper softly.<ins_eos> I have a secret. "
        "<ins_bos>Shout.<ins_eos> Get out of here!"
    )
    response = client.post(
        "/v1/audio/speech", data={"text": "Wait. " + text, "instruction": "Calm.", "seed": "7"}
    )
    assert response.status_code == 200
    assert response.headers["x-inline-segments"] == "3"
    seen = [(call["inputs"]["request"], call["inputs"]["guidance_scale"]) for call in runtime.seen]
    assert [(request["text"], request.get("instruction"), cfg) for request, cfg in seen] == [
        ("Wait.", "Calm.", 1.0),
        ("I have a secret.", "Whisper softly.", overlay.INLINE_DEFAULT_CFG),
        ("Get out of here!", "Shout.", overlay.INLINE_DEFAULT_CFG),
    ]


def test_segment_without_an_instruction_runs_at_cfg_1(client, runtime):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hello. <ins_bos>Angry.<ins_eos> Go.", "cfg_scale": "4"},
    )
    assert response.status_code == 200
    assert [call["inputs"]["guidance_scale"] for call in runtime.seen] == [1.0, 4.0]


def test_raw_sends_inline_markers_untouched(client, runtime):
    text = "I can't believe it. <ins_bos>Furious.<ins_eos> You lied!"
    response = client.post("/v1/audio/speech", data={"text": text, "raw": "true"})
    assert response.status_code == 200
    assert len(runtime.seen) == 1 and runtime.seen[0]["inputs"]["request"]["text"] == text


@pytest.mark.parametrize("text", ["Hi <ins_eos> there", "Hi <ins_bos>shout there"])
def test_unbalanced_inline_markers_are_400(client, text):
    response = client.post("/v1/audio/speech", data={"text": text})
    assert response.status_code == 400
    assert "raw=true" in response.json()["detail"]


def test_unknown_route_with_an_upload_is_a_clean_404(client):
    response = client.post("/v1/audio/nope", files={"source_audio": _wav_upload()})
    assert response.status_code == 404


def test_text_that_only_looks_like_control_tokens_passes(client, runtime):
    response = client.post("/v1/audio/speech", data={"text": "Room [S10] and [s1] and [cough]."})
    assert response.status_code == 200
    # Only bracketed words become tags; [S10]/[s1] are ordinary text to the tokenizer.
    assert runtime.seen[0]["inputs"]["request"]["text"] == "Room [S10] and [s1] and (cough)."


def test_english_bracket_tags_become_parentheses_and_text_is_stripped(client, runtime):
    client.post("/v1/audio/speech", data={"text": "  [sigh] Fine. [笑]  "})
    assert runtime.seen[0]["inputs"]["request"]["text"] == "(sigh) Fine. [笑]"


def test_overlong_text_is_400(client):
    response = client.post("/v1/audio/speech", data={"text": "word " * 300})
    assert response.status_code == 400
    assert "1000" in response.json()["detail"]


def test_text_beyond_the_frame_budget_is_400(client):
    response = client.post("/v1/audio/speech", data={"text": "word " * 60, "max_new_tokens": "100"})
    assert response.status_code == 400
    assert "split it" in response.json()["detail"]


def test_cfg_without_instruction_is_a_400_not_a_500(client):
    response = client.post("/v1/audio/speech", data={"text": "Hi", "cfg_scale": "3"})
    assert response.status_code == 400
    assert "instruction" in response.json()["detail"]


def test_dual_cfg_needs_voice_direction(client):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "instruction": "Sad.", "cfg_scale_ref": "1", "cfg_scale_ins": "3"},
    )
    assert response.status_code == 400
    assert "Voice Direction" in response.json()["detail"]


def test_dual_cfg_is_refused_in_fast_modes_by_default(client, monkeypatch):
    # Default off: in fast_mode=full it hit a device-side gather assert (2026-10-07).
    monkeypatch.setattr(overlay, "DUAL_CFG_FAST", False)
    monkeypatch.setattr(overlay.app.state, "fast_mode", "full")
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "instruction": "Loud.", "cfg_scale_ref": "2", "cfg_scale_ins": "4"},
    )
    assert response.status_code == 400
    assert "eager only" in response.json()["detail"]


def test_dual_cfg_cannot_stream(client):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "cfg_scale_ref": "1", "cfg_scale_ins": "3", "stream": "true"},
    )
    assert response.status_code == 400
    assert "stream" in response.json()["detail"]


def test_busy_server_answers_409_after_waiting_briefly(client, monkeypatch):
    monkeypatch.setattr(overlay, "BUSY_WAIT_SECONDS", 0.2)
    overlay.upstream._request_lock.acquire()
    try:
        assert client.post("/v1/audio/speech", data={"text": "Hi"}).status_code == 409
    finally:
        overlay.upstream._request_lock.release()


def test_a_request_waits_out_a_lock_that_frees_soon(client, monkeypatch):
    monkeypatch.setattr(overlay, "BUSY_WAIT_SECONDS", 5.0)
    overlay.upstream._request_lock.acquire()
    threading.Timer(0.3, overlay.upstream._request_lock.release).start()
    assert client.post("/v1/audio/speech", data={"text": "Hi"}).status_code == 200


def test_unexpected_errors_are_clean_json_500s(client, monkeypatch):
    def explode(**_kwargs):
        raise KeyError("surprise")

    monkeypatch.setattr(overlay, "_prepare", explode)
    response = client.post("/v1/audio/speech", data={"text": "Hi"})
    assert response.status_code == 500
    assert "KeyError" in response.json()["detail"]
    assert client.post("/v1/audio/speech", data={"text": "Hi"}).status_code == 500  # still up


# ─── speed (ffmpeg) ──────────────────────────────────────────────────────────


@needs_ffmpeg
@pytest.mark.parametrize("engine", ["rubberband", "atempo"])
def test_speed_streams_through_ffmpeg(client, runtime, engine):
    runtime.seconds = 2.0
    response = client.post(
        "/v1/audio/speech", data={"text": "Hi", "speed": "2", "speed_engine": engine}
    )
    assert response.status_code == 200
    assert _pcm_seconds(response.content) == pytest.approx(1.0, abs=0.1)
    assert response.headers["x-speed-engine"] in ("rubberband", "atempo")


@needs_ffmpeg
def test_speed_buffered(client, runtime):
    runtime.seconds = 2.0
    response = client.post("/v1/audio/speech", data={"text": "Hi", "speed": "0.5", "stream": "0"})
    assert float(response.headers["x-audio-duration"]) == pytest.approx(4.0, abs=0.1)


@needs_ffmpeg
def test_disconnect_during_a_speed_stream_frees_the_server(client, runtime):
    runtime.seconds = 6.0
    with client.stream(
        "POST", "/v1/audio/speech", data={"text": "Long", "speed": "1.2"}
    ) as response:
        next(response.iter_bytes())
    assert runtime.closed


# ─── references, voices, convert ─────────────────────────────────────────────


@needs_ffmpeg
def test_garbage_reference_audio_is_400(client):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "ref_text": "Words."},
        files={"ref_audio": ("ref.m4a", b"definitely not audio", "audio/mp4")},
    )
    assert response.status_code == 400
    assert "ref_audio" in response.json()["detail"]


@needs_ffmpeg
def test_short_reference_warns(client):
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "ref_text": "Words."},
        files={"ref_audio": _wav_upload(2.0)},
    )
    assert response.status_code == 200
    assert "3-30s" in response.headers["x-reference-warning"]


@needs_ffmpeg
def test_saved_voice_is_used_with_its_default_instruction_and_cached_codes(client, runtime):
    created = client.post(
        "/v1/voices",
        data={"id": "narrator", "ref_text": "Exact words.", "instruction": "Calm."},
        files={"ref_audio": _wav_upload()},
    )
    assert created.status_code == 201, created.text
    assert created.json()["duration_s"] == pytest.approx(4.0, abs=0.01)
    duplicate = client.post(
        "/v1/voices", data={"id": "narrator", "ref_text": "x"}, files={"ref_audio": _wav_upload()}
    )
    assert duplicate.status_code == 409

    ENCODED.clear()
    for _ in range(2):
        response = client.post("/v1/audio/speech", data={"text": "Hi", "voice": "narrator"})
        assert response.status_code == 200
    assert len(ENCODED) == 1  # encoded once, then served from the cache
    request = runtime.seen[-1]["inputs"]["request"]
    assert (request["ref_text"], request["instruction"]) == ("Exact words.", "Calm.")
    assert runtime.seen[-1]["inputs"]["template"] == "ref_edit_tata"

    assert [v["id"] for v in client.get("/v1/voices").json()["voices"]] == ["narrator"]
    assert client.delete("/v1/voices/narrator").status_code == 204
    assert client.get("/v1/voices/narrator").status_code == 404


def test_voice_ids_are_validated(client):
    response = client.post(
        "/v1/voices", data={"id": "Bad Id!", "ref_text": "x"}, files={"ref_audio": _wav_upload()}
    )
    assert response.status_code == 400
    assert client.get("/v1/voices/Bad%20Id").status_code == 400


@needs_ffmpeg
def test_convert_matches_the_source_duration(client, runtime):
    runtime.seconds = 1.0  # stretched by 1.5x: inside the 0.5-2.0 speed range
    response = client.post(
        "/v1/audio/convert",
        data={"source_text": "The words.", "ref_text": "Target words."},
        files={"source_audio": _wav_upload(1.5, "source.wav"), "ref_audio": _wav_upload()},
    )
    assert response.status_code == 200, response.text
    assert float(response.headers["x-audio-duration"]) == pytest.approx(1.5, abs=0.05)
    assert runtime.seen[-1]["inputs"]["request"]["text"] == "The words."


def test_convert_requires_the_source_transcript(client):
    response = client.post(
        "/v1/audio/convert", data={"voice": "x"}, files={"source_audio": _wav_upload()}
    )
    assert response.status_code == 400
    assert "source_text" in response.json()["detail"]


def test_convert_rejects_unknown_modes(client):
    response = client.post(
        "/v1/audio/convert",
        data={"source_text": "Hi", "voice": "x", "mode": "phonetic"},
        files={"source_audio": _wav_upload()},
    )
    assert response.status_code == 400


def test_capabilities_share_the_tag_vocabulary(client):
    capabilities = client.get("/v1/capabilities").json()
    events = capabilities["vocal_events"]["events"]
    assert {"(laugh)", "(sighs)", "[笑]"} <= {event["tag"] for event in events}
    assert set(capabilities["vocal_events"]["tiers"]) == {"documented", "hosted", "experimental"}
    assert capabilities["ranges"]["speed"]["recommended"] == [0.75, 1.25]
    assert capabilities["limits"]["chunk_chars"]["max"] == 600


# ─── review fixes ────────────────────────────────────────────────────────────


@dataclass
class FakeDtype:
    name: str
    is_floating_point: bool = True


BF16, FP32, INT64 = FakeDtype("bf16"), FakeDtype("fp32"), FakeDtype("int64", False)


@dataclass(eq=False)
class FakeTensor:
    dtype: FakeDtype

    def to(self, dtype):
        return FakeTensor(dtype)


@dataclass(eq=False)
class FakeParam:
    data: FakeTensor

    @property
    def dtype(self):
        return self.data.dtype


def test_dual_cfg_runs_recast_weights_in_the_model_dtype_then_restores_them(runtime):
    # Fast paths recast shared modules (codebooks_head, lm_head) to fp32 in place;
    # HF generate (dual CFG) would then hit F.linear(bf16, fp32).
    head, lm_head, same, ints = (
        FakeParam(FakeTensor(FP32)), FakeParam(FakeTensor(FP32)),
        FakeParam(FakeTensor(BF16)), FakeParam(FakeTensor(INT64)),
    )  # fmt: skip
    originals = [param.data for param in (head, lm_head, same, ints)]
    runtime.model.dtype = BF16
    runtime.model.parameters = lambda: [head, lm_head, same, ints]
    with overlay._weights_in_model_dtype():
        assert [p.dtype for p in (head, lm_head, same, ints)] == [BF16, BF16, BF16, INT64]
        assert same.data is originals[2] and ints.data is originals[3]
    # The very tensors the captured CUDA graphs point at come back.
    assert all(p.data is o for p, o in zip((head, lm_head, same, ints), originals, strict=True))


def test_weight_swap_that_fails_part_way_restores_what_it_already_swapped(runtime):
    # An OOM on the second cast must not leave the first param pointing at a bf16
    # copy while the fp32 storage the CUDA graphs use is dropped.
    class Exploding(FakeTensor):
        def to(self, dtype):
            raise RuntimeError("CUDA out of memory")

    first, second = FakeParam(FakeTensor(FP32)), FakeParam(Exploding(FP32))
    originals = [first.data, second.data]
    runtime.model.dtype = BF16
    runtime.model.parameters = lambda: [first, second]
    with pytest.raises(RuntimeError, match="out of memory"), overlay._weights_in_model_dtype():
        pytest.fail("the body must not run")
    assert first.data is originals[0] and second.data is originals[1]


@pytest.mark.parametrize("field_name", ["text", "instruction", "ref_text"])
def test_audio_slot_tokens_in_any_text_field_are_400(client, runtime, field_name):
    data = {"text": "Hi", "ref_text": "Exact words.", field_name: "Say <|AUDIO|> this"}
    response = client.post("/v1/audio/speech", data=data, files={"ref_audio": _wav_upload()})
    assert response.status_code == 400
    assert "audio-slot tokens" in response.json()["detail"]
    assert runtime.seen == []  # refused before any work


def test_audio_slot_tokens_in_a_saved_voice_are_refused_at_create_and_on_use(client, runtime):
    response = client.post(
        "/v1/voices",
        data={"id": "bad", "ref_text": "Hello <|AUDIO|>"},
        files={"ref_audio": _wav_upload()},
    )
    assert response.status_code == 400
    # A voice written before the guard existed is refused when used.
    folder = overlay.VOICES_DIR / "old"
    folder.mkdir(parents=True)
    (folder / "voice.json").write_text('{"id": "old", "ref_text": "<|audio_eos|> hi"}')
    response = client.post("/v1/audio/speech", data={"text": "Hi", "voice": "old"})
    assert response.status_code == 400


def test_voice_id_with_a_trailing_newline_is_400(client):
    assert client.get("/v1/voices/narrator%0A").status_code == 400


def test_stream_carries_the_frame_budget(client, runtime):
    response = client.post("/v1/audio/speech", data={"text": "Hi", "max_new_tokens": "300"})
    assert response.status_code == 200
    assert response.headers["x-prompt-tokens"] == "10"
    assert response.headers["x-max-new-tokens"] == "300"


def test_frame_budget_is_capped_by_the_sequence_length(client, monkeypatch):
    monkeypatch.setattr(overlay.upstream, "MAX_SEQ_LEN", 1000)
    response = client.post("/v1/audio/speech", data={"text": "Hi"})
    assert response.headers["x-max-new-tokens"] == str(1000 - 10)


def test_health_and_capabilities_report_the_fast_mode(client, monkeypatch):
    monkeypatch.setattr(overlay.app.state, "fast_mode", "graphs", raising=False)
    assert client.get("/health").json()["fast_mode"] == "graphs"
    fast = client.get("/v1/capabilities").json()["fast_mode"]
    assert fast["mode"] == "graphs"
    assert fast["stages"]["fast_depth_decoder"] is False


@pytest.mark.parametrize(
    ("argv", "env_mode", "expected"),
    [
        ([], None, ("eager", False, False, False)),
        ([], "full\n", ("full", True, True, True)),
        ([], "bogus", ("eager", False, False, False)),
        (["--fast-mode", "graphs"], "full", ("graphs", True, False, True)),
        (["--fast-mode", "full", "--no-fast-depth-decoder"], None, ("graphs", True, False, True)),
        (["--fast-codec"], None, ("custom", False, False, True)),
    ],
)
def test_fast_mode_resolution(monkeypatch, argv, env_mode, expected):
    monkeypatch.setattr(overlay.app.state, "fast_mode", "eager", raising=False)  # restored after
    if env_mode is None:
        monkeypatch.delenv("BREEZE_FAST_MODE", raising=False)
    else:
        monkeypatch.setenv("BREEZE_FAST_MODE", env_mode)
    monkeypatch.setattr(sys, "argv", ["api", "/models/x", *argv])
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: None))
    overlay.main()
    settings = overlay.upstream._settings
    stages = (
        settings["fast_backbone_decode"],
        settings["fast_depth_decoder"],
        settings["fast_codec"],
    )
    assert (overlay.app.state.fast_mode, *stages) == expected
    # The two bucket-freezing stages are never on.
    assert not settings["fast_text_encoder"]
    assert not settings["fast_backbone_prefill"]
    assert settings["fast_all"] is None


@needs_ffmpeg
def test_hls_playlists_are_not_opened_as_references(client):
    playlist = b"#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n"
    response = client.post(
        "/v1/audio/speech",
        data={"text": "Hi", "ref_text": "Words."},
        files={"ref_audio": ("ref.m3u8", playlist, "application/vnd.apple.mpegurl")},
    )
    assert response.status_code == 400


@needs_ffmpeg
def test_a_failed_stretch_after_generation_is_500(client, monkeypatch):
    monkeypatch.setattr(overlay, "_speed_filter", lambda speed, engine: ("nosuchfilter", "x"))
    response = client.post("/v1/audio/speech", data={"text": "Hi", "speed": "1.2", "stream": "0"})
    assert response.status_code == 500


# ─── dual CFG in fast modes ──────────────────────────────────────────────────


class FakeModule:
    """Just enough nn.Module for the swap: `_modules`, `modules()`, `named_modules()`."""

    def __init__(self, **children):
        self._modules = dict(children)

    def named_modules(self, prefix=""):
        yield prefix, self
        for name, child in self._modules.items():
            yield from child.named_modules(f"{prefix}.{name}" if prefix else name)

    def modules(self):
        return (module for _, module in self.named_modules())


class FakeCompiled(FakeModule):
    """torch._dynamo's OptimizedModule: the original lives on as `_orig_mod`."""

    def __init__(self, original):
        super().__init__(_orig_mod=original)
        self._orig_mod = original


def _fast_mode_model():
    """A model whose depth decoder layers and norm were compiled in place, as
    DepthDecoderGraph(fast=True) does to the shared modules."""
    layers = [FakeModule(), FakeModule()]
    norm = FakeModule()
    depth_model = FakeModule(
        layers=FakeModule(**{str(i): FakeCompiled(layer) for i, layer in enumerate(layers)}),
        norm=FakeCompiled(norm),
    )
    model = FakeModule(depth_decoder=FakeModule(model=depth_model))
    model.dtype = BF16
    model.parameters = lambda: []
    model.config = types.SimpleNamespace(
        codebook_pad_token_id=2050, codec_config=types.SimpleNamespace(codebook_size=2048)
    )
    return model, layers, norm, depth_model


def _depth_children(depth_model):
    return [*depth_model._modules["layers"]._modules.values(), depth_model._modules["norm"]]


def test_eager_modules_swaps_compiled_wrappers_and_restores_them():
    _, layers, norm, depth_model = _fast_mode_model()
    wrappers = _depth_children(depth_model)
    with overlay.fast.eager_modules(depth_model) as swapped:
        assert _depth_children(depth_model) == [*layers, norm]
        assert sorted(swapped) == ["layers.0", "layers.1", "norm"]
    assert _depth_children(depth_model) == wrappers


def test_eager_modules_restores_even_when_the_body_raises():
    _, _, _, depth_model = _fast_mode_model()
    wrappers = _depth_children(depth_model)
    with pytest.raises(RuntimeError), overlay.fast.eager_modules(depth_model):
        raise RuntimeError("CUDA error: device-side assert triggered")
    assert _depth_children(depth_model) == wrappers


def _dual_cfg_setup(runtime, monkeypatch, generate):
    model, layers, norm, depth_model = _fast_mode_model()
    model.generate = generate
    monkeypatch.setattr(overlay.app.state, "model", model)
    monkeypatch.setattr(overlay.torch, "inference_mode", contextlib.nullcontext, raising=False)
    decoded: list[Any] = []

    def decode(runtime_, codes, *, codebook_size):
        decoded.append((runtime_, codes, codebook_size))
        return np.full(RATE // 4, 0.1, dtype=np.float32)

    monkeypatch.setattr(overlay.fast, "codes_until_pad", lambda seqs, pad: ("codes", seqs, pad))
    monkeypatch.setattr(overlay.fast, "decode_codes", decode)
    prepared = overlay.Prepared({"input_ids": "ids"}, "req", 7, 10, True)
    return model, layers, norm, depth_model, decoded, prepared


def test_dual_cfg_runs_eager_modules_and_decodes_through_the_streaming_codec(runtime, monkeypatch):
    seen: dict[str, Any] = {}

    def generate(**kwargs):
        seen["kwargs"] = kwargs
        seen["inside"] = _depth_children(depth_model)
        return "sequences"

    model, layers, norm, depth_model, decoded, prepared = _dual_cfg_setup(
        runtime, monkeypatch, generate
    )
    wrappers = _depth_children(depth_model)
    audio = list(overlay._dual_cfg_audio(prepared))
    assert seen["inside"] == [*layers, norm]  # HF generate saw the original modules
    assert seen["kwargs"]["output_audio"] is False  # codes only
    assert seen["kwargs"]["input_ids"] == "ids"
    assert decoded == [(runtime, ("codes", "sequences", 2050), 2048)]
    assert audio[0].shape == (RATE // 4,)
    assert _depth_children(depth_model) == wrappers  # the graphs' modules are back


def test_dual_cfg_restores_modules_and_weights_when_generate_raises(runtime, monkeypatch):
    head = FakeParam(FakeTensor(FP32))
    original = head.data

    def generate(**kwargs):
        assert head.dtype == BF16
        raise RuntimeError("CUDA error: device-side assert triggered")

    model, _, _, depth_model, decoded, prepared = _dual_cfg_setup(runtime, monkeypatch, generate)
    model.parameters = lambda: [head]
    wrappers = _depth_children(depth_model)
    with pytest.raises(RuntimeError, match="device-side assert"):
        list(overlay._dual_cfg_audio(prepared))
    assert _depth_children(depth_model) == wrappers
    assert head.data is original
    assert decoded == []


@needs_ffmpeg
def test_dual_cfg_is_served_in_fast_modes_when_enabled(client, runtime, monkeypatch):
    monkeypatch.setattr(overlay, "DUAL_CFG_FAST", True)  # BREEZE_DUAL_CFG_FAST=1
    monkeypatch.setattr(overlay.app.state, "fast_mode", "full")

    def dual(part):
        yield np.zeros(RATE // 2)

    monkeypatch.setattr(overlay, "_dual_cfg_audio", dual)
    response = client.post(
        "/v1/audio/speech",
        data={
            "text": "Hi", "instruction": "Loud.", "ref_text": "Words.",
            "cfg_scale_ref": "2", "cfg_scale_ins": "4",
        },
        files={"ref_audio": _wav_upload()},
    )  # fmt: skip
    assert response.status_code == 200, response.text
    assert response.headers["x-audio-duration"] == "0.500"  # buffered


def test_device_side_assert_exits_for_a_docker_restart(client, monkeypatch):
    exits: list[int] = []
    monkeypatch.setattr(overlay.os, "_exit", exits.append)

    def explode(**_kwargs):
        raise RuntimeError("CUDA error: device-side assert triggered")

    monkeypatch.setattr(overlay, "_prepare", explode)
    client.post("/v1/audio/speech", data={"text": "Hi"})
    assert exits == [70]


# ─── acoustic voice conversion ───────────────────────────────────────────────


def _acoustic(client, **data):
    files = {"source_audio": _wav_upload(2.0, "source.wav"), "ref_audio": _wav_upload()}
    return client.post(
        "/v1/audio/convert",
        data={"mode": "acoustic", "ref_text": "Target words.", **data},
        files=files,
    )


@pytest.fixture
def forcing(runtime, monkeypatch):
    runtime.supports_forced_frames = True
    monkeypatch.setattr(overlay, "_codes_on_device", lambda codes, device: np.asarray(codes))
    return runtime


@needs_ffmpeg
def test_acoustic_is_501_without_the_overlay_runtime(client, runtime, monkeypatch):
    monkeypatch.setattr(
        overlay.app.state, "runtime_overlay", {"reason": "upstream differs"}, raising=False
    )
    response = _acoustic(client)
    assert response.status_code == 501
    assert "upstream differs" in response.json()["detail"]


@needs_ffmpeg
def test_acoustic_forces_the_source_codes_with_near_greedy_depth(client, forcing):
    response = _acoustic(client)
    assert response.status_code == 200, response.text
    call = forcing.seen[-1]
    forced = call["forced"]
    assert forced.frames == 25  # the stub encoder's 25 frames of 16 codebooks
    assert forced.depth_params == {"temperature": 0.3, "top_k": 1, "top_p": 1.0, "do_sample": True}
    assert forced.depth_fn is None  # keep_acoustic=0: the depth graph regenerates all 15
    # No transcript: the backbone reads filler of about the clip's length.
    assert call["inputs"]["request"]["text"] == overlay.fast.filler_text(2.0)
    assert call["inputs"]["template"] == "ref_clone_tata"
    assert response.headers["x-conversion-mode"] == "acoustic"
    assert response.headers["x-source-text"] == "filler"
    assert float(response.headers["x-audio-duration"]) == pytest.approx(2.0)  # 25 frames


@needs_ffmpeg
def test_acoustic_uses_the_transcript_and_depth_overrides(client, forcing):
    response = _acoustic(client, source_text="The real words.", depth_temperature="0.6",
                         depth_top_k="20")  # fmt: skip
    assert response.status_code == 200, response.text
    call = forcing.seen[-1]
    assert call["inputs"]["request"]["text"] == "The real words."
    assert call["forced"].depth_params["temperature"] == 0.6
    assert call["forced"].depth_params["top_k"] == 20


@needs_ffmpeg
def test_keep_acoustic_takes_the_eager_depth_path_with_modules_swapped(
    client, forcing, monkeypatch
):
    made: list[dict[str, Any]] = []
    swaps: list[Any] = []

    def depth_fn_factory(model, codes, **kwargs):
        made.append(kwargs)
        return "eager-depth"

    @contextlib.contextmanager
    def swap(model):
        swaps.append(model)
        yield []

    forcing._lean_sample_logits = "sampler"
    monkeypatch.setattr(overlay.fast, "forced_depth_fn", depth_fn_factory)
    monkeypatch.setattr(overlay.fast, "eager_modules", swap)
    response = _acoustic(client, keep_acoustic="2")
    assert response.status_code == 200, response.text
    assert forcing.seen[-1]["forced"].depth_fn == "eager-depth"
    assert made[0]["keep_acoustic"] == 2 and made[0]["sample"] == "sampler"
    assert swaps == [overlay.app.state.model]
    assert response.headers["x-keep-acoustic"] == "2"


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        ({"mode": "acoustic", "keep_acoustic": "16"}, "keep_acoustic"),
        ({"mode": "revoice", "keep_acoustic": "1", "source_text": "Hi"}, "mode=acoustic only"),
        ({"mode": "revoice"}, "mode=acoustic needs no transcript"),
    ],
)
def test_convert_mode_validation(client, data, detail):
    response = client.post(
        "/v1/audio/convert", data={"voice": "x", **data}, files={"source_audio": _wav_upload()}
    )
    assert response.status_code == 400
    assert detail in response.json()["detail"]


@needs_ffmpeg
def test_acoustic_source_longer_than_the_budget_is_400(client, forcing):
    response = _acoustic(client, max_new_tokens="20")  # 25 forced frames
    assert response.status_code == 400
    assert "source_audio is 25 codec frames" in response.json()["detail"]


@needs_ffmpeg
@pytest.mark.parametrize(("max_seq_len", "status"), [(60, 400), (61, 200)])
def test_acoustic_budget_counts_the_position_the_frame_loop_keeps_free(
    client, forcing, monkeypatch, max_seq_len, status
):
    # 35-token prompt (10 + 25 reference frames), 25 forced frames. The loop stops at
    # prefill + step == max_seq_len - 1, so 60 positions hold only 24 of them: a 400,
    # not a clip silently one frame short.
    monkeypatch.setattr(overlay.upstream, "MAX_SEQ_LEN", max_seq_len)
    response = _acoustic(client)
    assert response.status_code == status, response.text


def test_filler_text_scales_with_the_clip():
    short, long = overlay.fast.filler_text(1.0), overlay.fast.filler_text(20.0)
    assert len(short.split()) == 4 and len(long.split()) == 50
    assert long.endswith(".")


# ─── saved voices: cache keys ────────────────────────────────────────────────


@needs_ffmpeg
def test_voice_metadata_carries_a_content_hash_and_update_time(client):
    first = client.post(
        "/v1/voices", data={"id": "v", "ref_text": "Words one."}, files={"ref_audio": _wav_upload()}
    ).json()
    stored = (overlay.VOICES_DIR / "v" / "ref.wav").read_bytes()
    assert first["sha256"] == overlay.hashlib.sha256(stored + b"\0" + b"Words one.").hexdigest()
    assert first["updated_at"] == first["created_at"]
    assert client.get("/v1/voices/v").json()["sha256"] == first["sha256"]
    assert client.get("/v1/voices").json()["voices"][0]["sha256"] == first["sha256"]

    second = client.post(
        "/v1/voices",
        data={"id": "v", "ref_text": "Words two.", "overwrite": "true"},
        files={"ref_audio": _wav_upload()},
    ).json()
    assert second["sha256"] != first["sha256"]  # same clip, new transcript
    assert second["created_at"] == first["created_at"]


def test_voices_saved_before_the_hash_existed_get_one_on_read(client):
    folder = overlay.VOICES_DIR / "legacy"
    folder.mkdir(parents=True)
    (folder / "ref.wav").write_bytes(b"RIFFfake")
    (folder / "voice.json").write_text('{"id": "legacy", "ref_text": "Hi."}')
    meta = client.get("/v1/voices/legacy").json()
    assert meta["sha256"] == overlay.hashlib.sha256(b"RIFFfake\0Hi.").hexdigest()
    assert meta["updated_at"].endswith("Z")


# ─── fast modes: backbone compile, runtime overlay ───────────────────────────


@pytest.mark.parametrize(("installed", "expected"), [(True, "full+compile"), (False, "full")])
def test_full_compile_mode_reports_what_actually_runs(monkeypatch, installed, expected):
    monkeypatch.setattr(overlay.app.state, "fast_mode", "eager", raising=False)
    monkeypatch.setattr(overlay.app.state, "runtime_overlay", {}, raising=False)
    calls: list[dict[str, Any]] = []

    def install(api, **kwargs):
        calls.append(kwargs)
        return overlay.fast.InstallStatus(
            lean_loop=installed, compile_backbone=installed and kwargs["compile_backbone"],
            forced_frames=installed, reason=None if installed else "upstream differs",
        )  # fmt: skip

    monkeypatch.setattr(overlay.fast, "install", install)
    monkeypatch.setattr(sys, "argv", ["api", "/models/x", "--fast-mode", "full+compile"])
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *a, **k: None))
    overlay.main()
    assert calls == [{"lean_loop": overlay.LEAN_LOOP, "compile_backbone": True}]
    assert overlay.app.state.fast_mode == expected
    assert overlay.upstream._settings["fast_depth_decoder"] is True


def test_capabilities_report_the_runtime_overlay(client, monkeypatch):
    status = overlay.fast.InstallStatus(lean_loop=True, forced_frames=True).as_dict()
    monkeypatch.setattr(overlay.app.state, "runtime_overlay", status, raising=False)
    capabilities = client.get("/v1/capabilities").json()
    assert capabilities["runtime"]["lean_loop"] is True
    conversion = capabilities["modes"]["voice_conversion"]
    assert conversion["available"] == {"revoice": True, "acoustic": True}
    assert capabilities["modes"]["dual_cfg"]["available"] is True  # eager


def test_capabilities_report_dual_cfg_unavailable_in_fast_modes_by_default(client, monkeypatch):
    monkeypatch.setattr(overlay, "DUAL_CFG_FAST", False)
    monkeypatch.setattr(overlay.app.state, "fast_mode", "full")
    assert client.get("/v1/capabilities").json()["modes"]["dual_cfg"]["available"] is False
