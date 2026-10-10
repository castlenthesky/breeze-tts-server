"""Tests for `yggdrasil_breeze_fast` with real (CPU) torch and a fake model.

They need real torch, so run them in their own session — `test_overlay.py`
stubs torch out, and whichever loads first wins:

    uv run --no-project --with torch --with numpy --with pytest \\
        pytest tests/test_runtime_torch.py

The parity tests also run upstream's own loop (breeze-tts commit 58ec70c) on
the same fakes and compare frame by frame; point BREEZE_UPSTREAM_SRC at an
upstream checkout to run them (they skip otherwise):

    BREEZE_UPSTREAM_SRC=/path/to/breeze-tts uv run ... pytest ...test_runtime_torch.py
"""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

torch = pytest.importorskip("torch")
if not hasattr(torch, "tensor"):
    pytest.skip("torch is stubbed in this session; run this file alone", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import yggdrasil_breeze_fast as fast  # noqa: E402

Q = 4  # codebooks per frame
CODEBOOK = 8  # codec codebook size; ids 8-10 are reserved, 10 is the pad id
VOCAB = 11  # backbone EOS is id 11 (logits are 12 wide)
HIDDEN = 6
SAMPLES_PER_FRAME = 4


# ─── fakes ───────────────────────────────────────────────────────────────────


def _config(pad: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        vocab_size=VOCAB,
        codebook_pad_token_id=pad,
        num_codebooks=Q,
        codec_config=SimpleNamespace(codebook_size=CODEBOOK, sampling_rate=24000),
        depth_decoder_config=SimpleNamespace(vocab_size=VOCAB),
    )


class FakeModel:
    """Deterministic stand-ins for the text merge, backbone prefill and lm_head."""

    def __init__(self, config: SimpleNamespace) -> None:
        generator = torch.Generator().manual_seed(0)
        self.config = config
        self.w_embed = torch.randn(HIDDEN, generator=generator)
        self.w_out = torch.randn(HIDDEN, VOCAB + 1, generator=generator) * 2
        self.generation_config = SimpleNamespace(
            temperature=0.9, top_k=5, top_p=0.95, do_sample=True
        )
        self.depth_decoder = SimpleNamespace(
            generation_config=SimpleNamespace(temperature=0.8, top_k=4, top_p=1.0, do_sample=True)
        )
        self.backbone_model = self._backbone

    def _merge_input_ids_with_input_values(self, *, input_ids, **_):
        return {"inputs_embeds": torch.sin(input_ids.float()[..., None] * self.w_embed)}

    def _backbone(self, *, inputs_embeds, attention_mask, **_):
        hidden = torch.tanh(inputs_embeds.cumsum(1))
        return SimpleNamespace(last_hidden_state=hidden, past_key_values=int(hidden.shape[1]))

    def lm_head(self, hidden):
        return hidden.float() @ self.w_out


class FakeBackboneGraph:
    """The buffers BackboneGraph exposes, with `run` exactly as upstream's (58ec70c)."""

    def __init__(self, model: FakeModel, batch_size: int) -> None:
        self.model = model
        self.batch_size = batch_size
        self.no_graph = True
        self.debug = False
        self.input_ids_buf = torch.zeros(batch_size, 1, Q, dtype=torch.long)
        self.position_ids = torch.zeros(batch_size, 1, dtype=torch.long)
        self._base_position = torch.zeros(batch_size, dtype=torch.long)
        self.cache_position = torch.zeros(1, dtype=torch.long)
        self._prefill_len = 0
        self.hidden_buf = torch.zeros(batch_size, 1, HIDDEN)
        self.cfg_logits_buf = torch.zeros(1, VOCAB + 1)
        self.guidance_scale = torch.tensor([1.0])
        self.fed: list[torch.Tensor] = []
        self.mask_positions: list[int] = []

    def prefill_kv(self, past_key_values):
        self._prefill_len = int(past_key_values)
        return self._prefill_len

    def set_generation_state(self, attention_mask=None):
        per = attention_mask.sum(dim=1).long()
        self._base_position.copy_(per)
        self.position_ids.copy_(per.unsqueeze(-1))
        self.cache_position[0] = per.max().item()

    def _set_attention_mask(self, position):
        self.mask_positions.append(int(position))

    def _decode_step(self):
        self.fed.append(self.input_ids_buf[0, 0].clone())
        x = self.input_ids_buf.float().sum(-1, keepdim=True)  # [B, 1, 1]
        position = self.position_ids.float()[..., None]
        hidden = torch.sin(x * self.model.w_embed + 0.1 * position)
        self.hidden_buf.copy_(hidden)
        logits = self.model.lm_head(hidden[:, -1, :])
        logits[:, VOCAB] += 0.5 * position[:, 0, 0] - 18.0  # EOS grows likelier
        if self.batch_size >= 2:
            logits = logits[1:] + self.guidance_scale * (logits[:1] - logits[1:])
        self.cfg_logits_buf.copy_(logits[:1])

    def run(self, input_ids, step_idx):
        self.input_ids_buf.copy_(input_ids)
        self.position_ids.copy_((self._base_position + step_idx).unsqueeze(-1))
        self.cache_position[0] = self._prefill_len + step_idx
        self._set_attention_mask(self.cache_position[0].item())
        self._decode_step()
        return self.hidden_buf, self.cfg_logits_buf


class FakeDepthGraph:
    """Samples Q-1 codes with the RNG, from params held in 'graph buffers'."""

    def __init__(self) -> None:
        self.params = {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "do_sample": True}
        self.guidance = 1.0
        self.calls: list[dict[str, Any]] = []

    def set_guidance_scale(self, value):
        self.guidance = value

    def run(self, hidden, token_batch, **params):
        self.calls.append(dict(params))
        if params.get("guidance_scale") is not None:
            self.guidance = params.pop("guidance_scale")
        self.params.update({k: v for k, v in params.items() if v is not None})
        base = hidden.float().sum(-1)[:1] + token_batch[:1].float()
        logits = torch.stack(
            [torch.cos(base * (book + 1) + torch.arange(VOCAB)) * 3 for book in range(Q - 1)]
        )
        logits[:, CODEBOOK:] = float("-inf")
        if not self.params["do_sample"] or self.params["top_k"] == 1:
            return logits.argmax(-1).view(1, Q - 1)
        probs = torch.softmax(logits / self.params["temperature"], dim=-1)
        return torch.multinomial(probs, 1).view(1, Q - 1)


class FakeCodec:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.fail_on_call: int | None = None

    def open_request(self, request_id, reset=True, is_first_decode=None):
        self.events.append(("open", request_id))

    def close_request(self, request_id):
        self.events.append(("close", request_id))

    def decode_request_chunk(self, request_id, codes, reset=False):
        self.events.append(("decode", (tuple(codes.shape), reset)))
        if self.fail_on_call is not None and len(self.events) - 1 == self.fail_on_call:
            raise RuntimeError("codec failed")
        audio = codes.sum(1).float().repeat_interleave(SAMPLES_PER_FRAME, dim=-1)
        return audio.view(1, 1, -1)


@dataclass(frozen=True)
class Chunk:
    audio: np.ndarray
    sample_rate: int
    codec_frames: int
    is_final: bool
    timing: dict = field(default_factory=dict)


def _sample_reference(logits, *, temperature, top_k, top_p, do_sample, **_):
    """A stand-in for upstream's sample_logits (no penalty/suppress: the lean loop
    applies those itself)."""
    logits = logits.clone().float()
    if not do_sample:
        return logits.argmax(-1)
    logits = logits / temperature
    if top_k > 0:
        threshold = torch.topk(logits, min(top_k, logits.size(-1)))[0][..., -1:]
        logits = logits.masked_fill(logits < threshold, float("-inf"))
    return torch.multinomial(torch.softmax(logits, dim=-1), 1).squeeze(-1)


class FakeBase:
    """The parts of FastBreezeStreamingRuntime the subclass relies on (no CFG)."""

    def __init__(self, model: FakeModel, *, max_new_tokens: int = 60, chunk: int = 1) -> None:
        self.model = model
        self.config = SimpleNamespace(
            max_new_tokens=max_new_tokens,
            max_seq_len=512,
            collect_timing=False,
            repetition_penalty=1.1,
        )
        self._fast_backbone_prefill = False
        self._fast_backbone_decode = False
        self._codec_chunk_frames = chunk
        self.device = torch.device("cpu")
        self._backbone_graphs = {1: FakeBackboneGraph(model, 1)}
        self._backbone_graph = None
        self._backbone_prefill_graph = None
        self._depth_decoder_graph = FakeDepthGraph()
        self._codec_runtime = FakeCodec()
        self._frozen_branch_batch_sizes = None
        self._codec_codebook_size = CODEBOOK
        self._reserved_codec_token_ids = tuple(range(CODEBOOK, VOCAB))

    def _ensure_graphs(self, branch_batch_size, guidance_scale, *, depth_bucket_sizes=None):
        self._backbone_graph = self._backbone_graphs[branch_batch_size]

    def _codec(self):
        return self._codec_runtime

    def _build_branch_batch(self, inputs):
        embeds = self.model._merge_input_ids_with_input_values(input_ids=inputs["input_ids"])
        return SimpleNamespace(
            inputs_embeds=embeds["inputs_embeds"],
            attention_mask=inputs["attention_mask"],
            branch_batch_size=1,
            cfg=SimpleNamespace(mode="no_cfg", guidance_scale=1.0),
        )

    def _sampling_params(self, generation_config):
        return {
            name: getattr(generation_config, name)
            for name in ("temperature", "top_k", "top_p", "do_sample")
        }

    def _decode_codec_frames(self, *, frames, request_id, reset, is_final, timing):
        codes = torch.stack(frames).transpose(0, 1).unsqueeze(0)
        audio = self._codec().decode_request_chunk(request_id, codes, reset=reset)
        return Chunk(audio[0, 0].numpy(), 24000, len(frames), is_final, timing)


FAKE_FS = SimpleNamespace(
    select_fast_cfg=lambda inputs: SimpleNamespace(mode="no_cfg", guidance_scale=1.0),
    should_decode_codec_frame=lambda frame, config: (
        not bool((frame == int(config.codebook_pad_token_id)).all())
    ),
    FastStreamingChunk=Chunk,
    BackbonePrefillGraphCache=None,
    BackboneGraph=None,
)


def _runtime(*, pad: int = 10, max_new_tokens: int = 60, chunk: int = 1) -> Any:
    cls = fast.make_runtime_class(
        FakeBase, FAKE_FS, _sample_reference, lean_loop=True, compile_backbone=False
    )
    return cls(FakeModel(_config(pad)), max_new_tokens=max_new_tokens, chunk=chunk)


def _inputs(length: int = 7) -> dict[str, torch.Tensor]:
    return {
        "input_ids": torch.arange(length).view(1, -1) % 5,
        "attention_mask": torch.ones(1, length, dtype=torch.long),
        "text_ids_mask": torch.ones(1, length, dtype=torch.bool),
        "text_ids_len": torch.tensor([length]),
    }


def _source(frames: int = 9) -> torch.Tensor:
    generator = torch.Generator().manual_seed(3)
    return torch.randint(0, CODEBOOK, (frames, Q), generator=generator)


def _run(runtime, **kwargs) -> tuple[list[Any], list[torch.Tensor]]:
    frames: list[torch.Tensor] = []
    chunks = list(
        runtime.iter_audio_chunks(
            _inputs(), request_id="r", seed=11, token_observer=frames.append, **kwargs
        )
    )
    return chunks, frames


# ─── forced frames (acoustic conversion) ─────────────────────────────────────


def test_forced_frames_take_codebook_0_from_the_source():
    runtime = _runtime()
    source = _source(9)
    chunks, frames = _run(runtime, forced=fast.ForcedFrames(codes=source))
    assert len(frames) == 9  # exactly the source's length, no EOS needed
    assert [int(frame[0]) for frame in frames] == source[:, 0].tolist()
    assert sum(chunk.codec_frames for chunk in chunks) == 9
    assert chunks[-1].is_final
    assert ("close", "r") in runtime._codec_runtime.events


def test_forced_frames_regenerate_acoustics_near_greedy_and_feed_back_the_converted_frame():
    runtime = _runtime()
    source = _source(6)
    _, frames = _run(runtime, forced=fast.ForcedFrames(codes=source))
    depth_calls = runtime._depth_decoder_graph.calls
    assert depth_calls[0] == {**fast.ACOUSTIC_DEPTH_DEFAULTS, "guidance_scale": 1.0}
    assert all(call == {} for call in depth_calls[1:])  # set once per request
    # The backbone is fed frame i (converted, not the source's) to predict i+1;
    # the last frame isn't fed (nothing follows it).
    fed = runtime._backbone_graphs[1].fed
    assert [f.tolist() for f in fed] == [f.tolist() for f in frames[:-1]]
    regenerated = zip(frames, source, strict=True)
    assert any(frame[1:].tolist() != row[1:].tolist() for frame, row in regenerated)


def test_forced_frames_ignore_backbone_eos_and_stop_at_the_source_end():
    runtime = _runtime(max_new_tokens=100)
    source = _source(40)  # the fake backbone would have said EOS long before
    _, frames = _run(runtime, forced=fast.ForcedFrames(codes=source))
    assert len(frames) == 40


def test_forced_frames_with_a_depth_fn_use_it_instead_of_the_graph():
    runtime = _runtime()
    source = _source(5)
    seen: list[tuple[int, float]] = []

    def depth_fn(hidden, token_batch, step_idx, guidance):
        seen.append((step_idx, guidance))
        return source[step_idx : step_idx + 1, 1:]

    _, frames = _run(runtime, forced=fast.ForcedFrames(codes=source, depth_fn=depth_fn))
    assert [step for step, _ in seen] == [0, 1, 2, 3, 4]
    assert torch.equal(torch.stack(frames), source)  # depth_fn copied everything
    assert runtime._depth_decoder_graph.calls == []


class FakeDepthModel:
    """`depth_decoder.model(...)`: records the sequences it is shown."""

    def __init__(self) -> None:
        self.embed_tokens = SimpleNamespace(weight=torch.zeros(1, dtype=torch.bfloat16))
        self.sequences: list[list[int]] = []

    def __call__(self, *, input_ids, backbone_last_hidden_state, use_cache):
        assert use_cache is False and backbone_last_hidden_state.dtype == torch.bfloat16
        self.sequences.append(input_ids[0].tolist())
        hidden = input_ids.float()[..., None].expand(-1, -1, HIDDEN)
        return SimpleNamespace(last_hidden_state=hidden.to(torch.bfloat16))


class FakeCodebooksHead:
    """Predicting codebook `b` (cache_position b), the favourite id is `b + 2`."""

    weight = torch.zeros(1, dtype=torch.float32)  # fp32, as the fast path recasts it

    def __call__(self, hidden, cache_position):
        assert hidden.dtype == torch.float32
        logits = torch.zeros(hidden.shape[0], 1, VOCAB)
        logits[:, 0, (int(cache_position[0]) + 2) % VOCAB] = 5.0  # 8-10 reserved: masked
        logits[:, 0, 1] = 1.0
        return logits


def _depth_model_ns(num_codebooks: int = Q) -> SimpleNamespace:
    config = _config()
    config.num_codebooks = num_codebooks
    return SimpleNamespace(
        config=config,
        depth_decoder=SimpleNamespace(model=FakeDepthModel(), codebooks_head=FakeCodebooksHead()),
    )


def test_forced_depth_fn_keeps_the_lowest_acoustic_codebooks_and_conditions_on_them():
    model = _depth_model_ns()
    source = _source(3)
    step = fast.forced_depth_fn(
        model,
        source,
        keep_acoustic=1,
        params={"temperature": 0.3, "top_k": 1, "top_p": 1.0, "do_sample": False},
        sample=_sample_reference,
        codec_codebook_size=CODEBOOK,
    )
    tokens = step(torch.zeros(1, HIDDEN), torch.tensor([5]), 2, 1.0)
    assert tokens.shape == (1, Q - 1)
    assert int(tokens[0, 0]) == int(source[2, 1])  # kept from the source
    # Codebook 2 is predicted with the kept code already in the sequence.
    assert model.depth_decoder.model.sequences[0] == [0, 5, int(source[2, 1])]
    # Then codebooks 2 and 3: favourites 4 and 5.
    assert tokens[0, 1:].tolist() == [4, 5]


def test_forced_depth_fn_masks_reserved_codec_ids():
    model = _depth_model_ns(num_codebooks=9)  # books reach 7/8, whose favourites are reserved
    step = fast.forced_depth_fn(
        model,
        _source(1),
        keep_acoustic=0,
        params={"temperature": 1.0, "top_k": 0, "top_p": 1.0, "do_sample": False},
        sample=_sample_reference,
        codec_codebook_size=CODEBOOK,
    )
    tokens = step(torch.zeros(1, HIDDEN), torch.tensor([0]), 0, 1.0)
    assert bool((tokens < CODEBOOK).all())


# ─── the lean loop on its own ────────────────────────────────────────────────


def test_lean_loop_writes_depth_params_on_the_first_frame_only():
    runtime = _runtime()
    _, frames = _run(runtime)
    calls = runtime._depth_decoder_graph.calls
    assert len(calls) == len(frames) > 1
    assert calls[0] == {
        "temperature": 0.8, "top_k": 4, "top_p": 1.0, "do_sample": True, "guidance_scale": 1.0
    }  # fmt: skip
    assert all(call == {} for call in calls[1:])


def test_lean_loop_never_reads_back_the_backbone_position():
    runtime = _runtime()
    _run(runtime)
    graph = runtime._backbone_graphs[1]
    assert graph.mask_positions == list(range(7, 7 + len(graph.mask_positions)))


def test_pad_frame_check_is_skipped_only_when_the_pad_id_is_suppressed():
    assert _runtime(pad=10)._pad_frame_possible() is False  # 8 <= 10 < 11: suppressed
    assert _runtime(pad=3)._pad_frame_possible() is True


def test_lean_sample_matches_unique_based_penalty_and_list_suppression():
    runtime = _runtime()
    generator = torch.Generator().manual_seed(5)
    logits = torch.randn(1, VOCAB + 1, generator=generator) * 3
    history = torch.tensor([1, 4, 4, 9, 0])
    seen = torch.zeros(VOCAB + 1, dtype=torch.bool)
    seen[history] = True
    params = {"temperature": 0.7, "top_k": 0, "top_p": 1.0, "do_sample": False}
    captured: list[torch.Tensor] = []
    runtime._lean_sample_logits = lambda x, **p: captured.append(x) or x.argmax(-1)
    runtime._lean_sample(logits, seen, params)
    expected = logits.clone()
    unique = history.unique()
    picked = expected[..., unique]
    expected[..., unique] = torch.where(picked > 0, picked / 1.1, picked * 1.1)
    expected[..., list(range(CODEBOOK, VOCAB))] = float("-inf")
    assert torch.equal(captured[0], expected)


# ─── eager_modules / decode_codes with real torch ────────────────────────────


def test_eager_modules_unwraps_real_compiled_modules():
    layers = torch.nn.ModuleList([torch.nn.Linear(2, 2), torch.nn.Linear(2, 2)])
    norm = torch.nn.LayerNorm(2)
    depth = torch.nn.Module()
    depth.layers = torch.nn.ModuleList([torch.compile(layer) for layer in layers])
    depth.norm = torch.compile(norm)
    root = torch.nn.Module()
    root.depth = depth
    wrapped = [*depth.layers, depth.norm]
    with pytest.raises(ValueError), fast.eager_modules(root) as names:
        assert [*depth.layers, depth.norm] == [*layers, norm]
        assert sorted(names) == ["depth.layers.0", "depth.layers.1", "depth.norm"]
        raise ValueError("boom")
    assert [*depth.layers, depth.norm] == wrapped


def test_codes_until_pad_cuts_at_the_first_all_pad_frame():
    sequences = torch.tensor([[[1, 2], [3, 4], [10, 10], [5, 6]]])
    assert fast.codes_until_pad(sequences, 10).tolist() == [[1, 2], [3, 4]]
    assert fast.codes_until_pad(SimpleNamespace(sequences=sequences[:, :2]), 10).shape == (2, 2)


@pytest.mark.parametrize(("chunk", "frames"), [(1, 50), (2, 51)])
def test_decode_codes_feeds_whole_chunks_and_closes(chunk, frames):
    codec = FakeCodec()
    runtime = SimpleNamespace(codec_chunk_frames=chunk, _codec=lambda: codec)
    codes = torch.randint(0, CODEBOOK, (frames, Q))
    audio = fast.decode_codes(runtime, codes, codebook_size=CODEBOOK)
    assert audio.shape == (frames * SAMPLES_PER_FRAME,)
    decodes = [payload for kind, payload in codec.events if kind == "decode"]
    assert [shape[-1] for shape, _ in decodes] == [24, 24, frames - 48]
    assert [reset for _, reset in decodes] == [True, False, False]
    assert codec.events[-1][0] == "close"


def test_decode_codes_closes_on_failure_and_refuses_out_of_range_codes():
    codec = FakeCodec()
    codec.fail_on_call = 2
    runtime = SimpleNamespace(codec_chunk_frames=1, _codec=lambda: codec)
    with pytest.raises(RuntimeError, match="codec failed"):
        fast.decode_codes(runtime, torch.zeros(30, Q, dtype=torch.long), codebook_size=CODEBOOK)
    assert codec.events[-1][0] == "close"
    with pytest.raises(ValueError, match="outside"):
        fast.decode_codes(runtime, torch.full((2, Q), CODEBOOK), codebook_size=CODEBOOK)


# ─── parity with upstream's loop (needs BREEZE_UPSTREAM_SRC) ─────────────────


@pytest.fixture(scope="module")
def upstream_fs():
    src = os.environ.get("BREEZE_UPSTREAM_SRC")
    if not src:
        pytest.skip("set BREEZE_UPSTREAM_SRC to an upstream breeze-tts checkout")
    root = Path(src)
    saved = {name: sys.modules.get(name) for name in list(sys.modules) if name.startswith("models")}
    for name, path in (
        ("models", root / "models"),
        ("models.cudagraph", root / "models/cudagraph"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]  # the package without its __init__ (transformers)
        sys.modules[name] = package
    for module, attr in (
        ("backbone_graph", "BackboneGraph"),
        ("backbone_prefill_graph", "BackbonePrefillGraphCache"),
        ("depth_decoder_graph", "DepthDecoderGraph"),
    ):
        stub = types.ModuleType(f"models.cudagraph.{module}")
        setattr(stub, attr, type(attr, (), {}))
        sys.modules[stub.__name__] = stub
    sampling = importlib.import_module("models.cudagraph.sampling")
    fs = importlib.import_module("models.fast_streaming")
    yield fs, sampling, root
    for name in [name for name in sys.modules if name.startswith("models")]:
        del sys.modules[name]
    sys.modules.update({name: module for name, module in saved.items() if module})


def test_upstream_files_match_the_mirrored_commit(upstream_fs):
    _, _, root = upstream_fs
    for name, expected in fast.UPSTREAM_SHA256.items():
        path = root / (name.replace(".", "/") + ".py")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name


def _upstream_runtime(fs, cls, *, cfg: bool, penalty: float, max_new_tokens: int, pad: int):
    model = FakeModel(_config(pad))
    runtime = object.__new__(cls)
    runtime.model = model
    runtime.audio_tokenizer = None
    runtime.tokenizer = None
    runtime.config = fs.FastStreamingConfig(
        max_new_tokens=max_new_tokens, max_seq_len=512, repetition_penalty=penalty
    )
    runtime._fast_text_encoder = False
    runtime._fast_backbone_prefill = False
    runtime._fast_backbone_decode = False
    runtime._fast_depth_decoder = False
    runtime._fast_codec = True
    runtime._codec_chunk_frames = 1
    runtime.device = torch.device("cpu")
    runtime.dtype = torch.float32
    runtime._backbone_graphs = {1: FakeBackboneGraph(model, 1), 2: FakeBackboneGraph(model, 2)}
    runtime._backbone_graph = None
    runtime._backbone_prefill_graph = None
    runtime._backbone_prefill_graphs = {}
    runtime._depth_decoder_graph = FakeDepthGraph()
    runtime._codec_runtime = FakeCodec()
    runtime._warmup_profile = None
    runtime._warmup_manifest = None
    runtime._frozen_branch_batch_sizes = None
    runtime._codec_codebook_size = CODEBOOK
    runtime._reserved_codec_token_ids = tuple(range(CODEBOOK, VOCAB))
    return runtime


def _cfg_inputs(cfg: bool) -> dict[str, Any]:
    inputs: dict[str, Any] = _inputs(7)
    if cfg:
        inputs.update(
            cfg_scale=3.0,
            cfg_negative_prompt_ids=torch.arange(5).view(1, -1) % 3,
            cfg_negative_prompt_attention_mask=torch.ones(1, 5, dtype=torch.long),
            cfg_negative_text_ids_mask=torch.ones(1, 5, dtype=torch.bool),
            cfg_negative_text_ids_len=torch.tensor([5]),
        )
    return inputs


def _collect(runtime, inputs, seed):
    frames: list[list[int]] = []
    audio = [
        chunk.audio.tolist()
        for chunk in runtime.iter_audio_chunks(
            inputs, request_id="r", seed=seed, token_observer=lambda f: frames.append(f.tolist())
        )
    ]
    return frames, audio, torch.rand(3).tolist()  # the RNG must end in the same state too


@pytest.mark.parametrize("cfg", [False, True])
@pytest.mark.parametrize("penalty", [1.0, 1.1, 1.7])
@pytest.mark.parametrize(("max_new_tokens", "pad"), [(80, 10), (12, 10), (80, 3)])
@pytest.mark.parametrize("seed", [0, 1, 42])
def test_lean_loop_matches_upstream_frame_for_frame(
    upstream_fs, cfg, penalty, max_new_tokens, pad, seed
):
    fs, sampling, _ = upstream_fs
    lean_cls = fast.make_runtime_class(
        fs.FastBreezeStreamingRuntime,
        fs,
        sampling.sample_logits,
        lean_loop=True,
        compile_backbone=False,
    )
    args = {"cfg": cfg, "penalty": penalty, "max_new_tokens": max_new_tokens, "pad": pad}
    stock = _upstream_runtime(fs, fs.FastBreezeStreamingRuntime, **args)
    lean = _upstream_runtime(fs, lean_cls, **args)
    expected = _collect(stock, _cfg_inputs(cfg), seed)
    actual = _collect(lean, _cfg_inputs(cfg), seed)
    assert expected[0], "the fake produced no frames"
    assert actual == expected
    assert len(lean._depth_decoder_graph.calls) == len(expected[0])
    assert all(call == {} for call in lean._depth_decoder_graph.calls[1:])


def test_lean_loop_hits_eos_and_the_limit_like_upstream(upstream_fs):
    fs, sampling, _ = upstream_fs
    lean_cls = fast.make_runtime_class(
        fs.FastBreezeStreamingRuntime, fs, sampling.sample_logits,
        lean_loop=True, compile_backbone=False,
    )  # fmt: skip
    lengths = set()
    for seed in range(12):
        args = {"cfg": False, "penalty": 1.1, "max_new_tokens": 30, "pad": 10}
        stock = _collect(
            _upstream_runtime(fs, fs.FastBreezeStreamingRuntime, **args), _inputs(), seed
        )
        lean = _collect(_upstream_runtime(fs, lean_cls, **args), _inputs(), seed)
        assert lean == stock
        lengths.add(len(stock[0]))
    assert 30 in lengths and min(lengths) < 30  # both endings exercised
