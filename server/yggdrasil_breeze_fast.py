"""Torch-level pieces of the yggdrasil Breeze overlay (no HTTP here).

`yggdrasil_breeze_api` imports this; it runs inside the breeze-tts-2 container
next to upstream's `models` package and never edits it. What it adds:

- `eager_modules`: puts the original modules back where upstream's fast depth
  decoder installed `torch.compile` wrappers in the SHARED model, for code
  (HF `generate`, the acoustic converter) that runs those modules at shapes
  the wrappers were never compiled for.
- `codes_until_pad` / `decode_codes`: HF `generate(output_audio=False)` codes →
  audio through the streaming codec runtime instead of the full-clip decoder
  that the fast codec mutates.
- `make_runtime_class`: a `FastBreezeStreamingRuntime` subclass with
  * a leaner per-frame loop (same tokens and audio, fewer host syncs — see
    `_LEAN_LOOP_NOTES`),
  * forced frames for acoustic voice conversion (`ForcedFrames`),
  * an opt-in `torch.compile` of the backbone decode step before its CUDA graph
    is captured.
  It is copied from upstream commit 58ec70c, so `install` only swaps it in when
  the upstream files it mirrors hash the same (`UPSTREAM_SHA256`).

Nothing here touches torch at import time: the HTTP tests import this module
with torch stubbed out.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch

# The upstream files the lean loop mirrors (breeze-tts commit 58ec70c). Any
# other content → the stock runtime stays in place (and acoustic conversion is 501).
UPSTREAM_SHA256 = {
    "models.fast_streaming": "7748cc11fef2a5f54ae82fefc96325673d71b8cb9b1bdd7bb92275c4c100a825",
    "models.cudagraph.backbone_graph": (
        "942b07eb2c16a31f362e10ecc23e9d1c131fc8cc3116550650010d2ec83fd024"
    ),
    "models.cudagraph.depth_decoder_graph": (
        "407bb07d0cd610f9c11748655450ad7708f8bab811d2129382925bf729b88acc"
    ),
    "models.cudagraph.sampling": "3dcaa35fd106c730bc630a998d3a6ed3329beb55e8df03d76d3f857346a86623",
}

# Per frame, upstream's loop (fast_streaming.py:849-945) syncs the host with the
# GPU up to six times; the lean loop keeps only the EOS read and the codec's
# audio copy, with identical tokens and audio for the same seed:
_LEAN_LOOP_NOTES = (
    "EOS is read once per token (upstream reads it again at the top of the next step)",
    "the terminal-pad-frame check is skipped when the backbone can't emit the pad id "
    "(it is one of the suppressed reserved codec ids), else kept as one read",
    "depth sampling params are written to the depth graph on a request's first frame "
    "only (they can't change mid-request)",
    "repetition penalty via a seen-token mask instead of token_history.unique()",
    "suppressed ids indexed with a device tensor, not a Python list per step",
    "the backbone decode step takes its KV position from the host, not cache_position.item()",
)


# ─── compiled-module swap ────────────────────────────────────────────────────


@contextlib.contextmanager
def eager_modules(root: Any) -> Iterator[list[str]]:
    """Temporarily replace every `torch.compile` wrapper under `root` by its original.

    Upstream's fast depth decoder replaces `depth_decoder.model.layers[i]` and
    `.norm` in the shared model with `torch.compile(..., fullgraph=True)`
    wrappers (`OptimizedModule`, which keeps the original as `_orig_mod`).
    Running them at other shapes (HF generate: no cache, growing sequences,
    three CFG branches) is what hit the device-side gather assert. The captured
    CUDA graphs keep their own kernels, so swapping the module objects back
    for the duration doesn't disturb them. Restored in `finally`, even when
    the body raises. Duck-typed on `.modules()` / `._modules` so it tests
    without torch. Yields the dotted names it swapped.
    """
    swapped: list[tuple[dict[str, Any], str, Any]] = []
    names: list[str] = []
    for parent_name, parent in _named_modules(root):
        children = getattr(parent, "_modules", None) or {}
        for name, child in list(children.items()):
            if child is not None and getattr(child, "_orig_mod", None) is not None:
                swapped.append((children, name, child))
                names.append(f"{parent_name}.{name}" if parent_name else name)
    for children, name, child in swapped:
        children[name] = child._orig_mod
    try:
        yield names
    finally:
        for children, name, child in reversed(swapped):
            children[name] = child


def _named_modules(root: Any) -> Iterator[tuple[str, Any]]:
    named = getattr(root, "named_modules", None)
    if callable(named):
        yield from named()
    else:
        yield from (("", module) for module in root.modules())


# ─── codes → audio through the streaming codec ───────────────────────────────


def codes_until_pad(sequences: Any, pad_token_id: int) -> torch.Tensor:
    """HF `generate(output_audio=False)` output → one sample's codes `[frames, codebooks]`.

    Cut at the first all-pad frame (HF stores the EOS row as all-pad), as
    `generate(output_audio=True)` does before decoding.
    """
    sequences = getattr(sequences, "sequences", sequences)
    if sequences.ndim != 3:
        raise RuntimeError(f"generate produced no audio frames (shape {tuple(sequences.shape)})")
    codes = sequences[0]
    is_pad = (codes == int(pad_token_id)).all(dim=-1)
    pads = is_pad.nonzero()
    end = int(pads.min()) if pads.numel() else int(codes.shape[0])
    return codes[:end]


def decode_codes(
    runtime: Any, codes: torch.Tensor, *, codebook_size: int, piece_frames: int = 24
) -> np.ndarray:
    """Decode `[frames, codebooks]` codes through the runtime's streaming codec.

    The same codec path (and, in fast modes, the same CUDA graph) that
    streaming uses, fed `piece_frames` at a time — never the full-clip decoder,
    whose modules the fast codec recompiled for its own shapes. Serialized by
    the caller's request lock, like streaming.
    """
    if codes.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    bad = (codes < 0) | (codes >= codebook_size)
    if bool(bad.any()):
        frame, book = (int(i) for i in bad.nonzero()[0].tolist())
        raise ValueError(
            f"generated codec token {int(codes[frame, book])} at frame {frame}, codebook "
            f"{book} is outside [0, {codebook_size - 1}]"
        )
    codec = runtime._codec()
    step = max(int(runtime.codec_chunk_frames), 1)
    piece = max(step, piece_frames // step * step)  # whole chunks: only the last may tail
    request_id = f"decode-{uuid.uuid4().hex}"
    codec.open_request(request_id, reset=True, is_first_decode=True)
    audio: list[np.ndarray] = []
    try:
        for index, start in enumerate(range(0, int(codes.shape[0]), piece)):
            chunk = codes[start : start + piece].to(torch.long).transpose(0, 1).unsqueeze(0)
            out = codec.decode_request_chunk(request_id, chunk.contiguous(), reset=index == 0)
            audio.append(_audio_np(out))
    finally:
        codec.close_request(request_id)
    return np.concatenate(audio) if audio else np.zeros(0, dtype=np.float32)


def _audio_np(audio: torch.Tensor) -> np.ndarray:
    while audio.dim() > 1:
        audio = audio[0]
    return audio.detach().float().cpu().numpy()


# ─── acoustic voice conversion ───────────────────────────────────────────────

ACOUSTIC_DEPTH_DEFAULTS = {"temperature": 0.3, "top_k": 1, "top_p": 1.0, "do_sample": True}
_FILLER = (
    "The",
    "morning",
    "light",
    "came",
    "slowly",
    "over",
    "the",
    "hills,",
    "and",
    "the",
    "town",
    "woke",
    "one",
    "window",
    "at",
    "a",
    "time.",
    "People",
    "walked",
    "to",
    "work",
    "along",
    "the",
    "river,",
    "talking",
    "about",
    "the",
    "weather",
    "and",
    "the",
    "week",
    "ahead.",
)


def filler_text(seconds: float, words_per_second: float = 2.5) -> str:
    """Text roughly as long as `seconds` of speech: what it says doesn't matter.

    The backbone needs a prompt of about the right length or its state goes
    degenerate and the forced codes come out mumbled (Breeze-TTS-2.cpp's
    measurements: wrong-but-right-length text scores like the real transcript).
    """
    count = max(4, round(seconds * words_per_second))
    words = [_FILLER[index % len(_FILLER)] for index in range(count)]
    return " ".join(words).rstrip(",") + ("" if words[-1].endswith(".") else ".")


@dataclass
class ForcedFrames:
    """Drive the streaming loop from a source's codes instead of sampling the backbone.

    Frame `i`'s codebook 0 (semantic) is the source's; the depth decoder
    regenerates codebooks 1-15 for the target voice, with `depth_params`
    (near-greedy by default). `depth_fn`, when set, replaces the depth graph
    (the eager path that can force the lowest `keep_acoustic` acoustic
    codebooks from the source too). The converted frame, not the source's, is
    what feeds the backbone's next step.
    """

    codes: torch.Tensor  # [frames, codebooks] long, on the runtime's device
    depth_params: dict[str, Any] = field(default_factory=lambda: dict(ACOUSTIC_DEPTH_DEFAULTS))
    depth_fn: Callable[[torch.Tensor, torch.Tensor, int, float], torch.Tensor] | None = None

    @property
    def frames(self) -> int:
        return int(self.codes.shape[0])


def forced_depth_fn(
    model: Any,
    codes: torch.Tensor,
    *,
    keep_acoustic: int,
    params: dict[str, Any],
    sample: Callable[..., torch.Tensor],
    codec_codebook_size: int,
) -> Callable[[torch.Tensor, torch.Tensor, int, float], torch.Tensor]:
    """An eager depth decoder step that copies the lowest `keep_acoustic` acoustic
    codebooks from the source frame and samples the rest for the target.

    The kept codebooks condition the ones generated after them (they are in the
    depth decoder's input sequence), which the captured depth graph can't do.
    Runs the shared depth decoder at shapes its fast-mode compile wrappers
    weren't built for, so the caller wraps it in `eager_modules`. Uncached
    (sequence of 2-16): a few ms per frame, fine for a non-streaming endpoint.
    """
    depth = model.depth_decoder
    num_decode = int(model.config.num_codebooks) - 1
    vocab = int(model.config.depth_decoder_config.vocab_size)
    keep = max(0, min(int(keep_acoustic), num_decode))

    def step(hidden: torch.Tensor, token_batch: torch.Tensor, step_idx: int, guidance: float):
        batch = int(hidden.shape[0])
        device = hidden.device
        dtype = depth.model.embed_tokens.weight.dtype
        hidden = hidden.to(dtype)
        sequence = torch.zeros(batch, 2, dtype=torch.long, device=device)
        sequence[:, 1] = token_batch.to(torch.long)
        kept = codes[step_idx, 1 : 1 + keep]
        head = depth.codebooks_head
        for book in range(num_decode):
            if book < keep:
                token = kept[book : book + 1]
            else:
                hidden_states = depth.model(
                    input_ids=sequence, backbone_last_hidden_state=hidden, use_cache=False
                ).last_hidden_state
                position = torch.tensor([sequence.shape[1] - 1], device=device)
                logits = head(
                    hidden_states[:, -1:, :].to(head.weight.dtype), cache_position=position
                )[:, 0, :].float()
                if batch >= 2:  # [cond, uncond], as the depth graph pairs them
                    logits = logits[1:2] + guidance * (logits[:1] - logits[1:2])
                if codec_codebook_size < vocab:
                    logits[..., codec_codebook_size:vocab] = float("-inf")
                token = sample(logits, **params).view(1)
            sequence = torch.cat([sequence, token.view(1, 1).expand(batch, 1)], dim=1)
        return sequence[:1, 2:]

    return step


# ─── the runtime subclass ────────────────────────────────────────────────────


@dataclass
class InstallStatus:
    lean_loop: bool = False
    compile_backbone: bool = False
    forced_frames: bool = False
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "lean_loop": self.lean_loop,
            "compile_backbone": self.compile_backbone,
            "forced_frames": self.forced_frames,
            "reason": self.reason,
        }


def upstream_mismatches() -> list[str]:
    """The mirrored upstream modules whose source differs from what the subclass copies."""
    mismatched = []
    for name, expected in UPSTREAM_SHA256.items():
        module = sys.modules.get(name) or importlib.import_module(name)
        actual = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        if actual != expected:
            mismatched.append(f"{name} ({actual[:12]})")
    return mismatched


def install(api_module: Any, *, lean_loop: bool, compile_backbone: bool) -> InstallStatus:
    """Swap the subclass into upstream's API module before its lifespan builds the runtime.

    `breeze_infer.api._load_app` looks `FastBreezeStreamingRuntime` up in its own
    module globals at start-up, so rebinding that name is the seam (upstream's
    files are untouched).
    """
    try:
        fs = importlib.import_module("models.fast_streaming")
        sampling = importlib.import_module("models.cudagraph.sampling")
        mismatched = upstream_mismatches()
    except (ImportError, OSError, AttributeError, TypeError) as exc:
        return InstallStatus(reason=f"upstream runtime not importable: {exc}")
    if mismatched:
        return InstallStatus(
            reason="upstream differs from commit 58ec70c, which the overlay's runtime mirrors: "
            + ", ".join(mismatched)
        )
    api_module.FastBreezeStreamingRuntime = make_runtime_class(
        fs.FastBreezeStreamingRuntime,
        fs,
        sampling.sample_logits,
        lean_loop=lean_loop,
        compile_backbone=compile_backbone,
    )
    return InstallStatus(lean_loop=lean_loop, compile_backbone=compile_backbone, forced_frames=True)


def make_runtime_class(
    base: type,
    fs: Any,
    sample_logits: Callable[..., torch.Tensor],
    *,
    lean_loop: bool,
    compile_backbone: bool,
) -> type:
    """Build the subclass over `base` (upstream's runtime class), `fs` (its module).

    A factory so tests can hand in real upstream (parity) or fakes.
    """

    class YggdrasilStreamingRuntime(base):  # type: ignore[misc, valid-type]
        LEAN_LOOP = lean_loop
        COMPILE_BACKBONE = compile_backbone
        supports_forced_frames = True
        _lean_sample_logits = staticmethod(sample_logits)  # upstream's, for forced_depth_fn

        # ── opt-in backbone compile ──

        def _ensure_graphs(self, branch_batch_size, guidance_scale, *, depth_bucket_sizes=None):
            frozen = self._frozen_branch_batch_sizes
            if (
                self.COMPILE_BACKBONE
                and self._fast_backbone_decode
                and branch_batch_size not in self._backbone_graphs
                and (frozen is None or branch_batch_size in frozen)
            ):
                graph = fs.BackboneGraph(
                    backbone_model=self.model.backbone_model,
                    lm_head=self.model.lm_head,
                    embed_tokens=self.model.backbone_model.embed_tokens,
                    config=self.model.config,
                    device=str(self.device),
                    dtype=self.dtype,
                    max_seq_len=self.config.max_seq_len,
                    guidance_scale=guidance_scale,
                    batch_size=branch_batch_size,
                )
                # Compile only this graph's decode step (an instance attribute; the
                # shared backbone modules stay eager for prefill and HF generate),
                # then capture the compiled kernels, as upstream does for the depth
                # decoder. Fixed shapes: one token, static cache, fixed mask buffer.
                graph._decode_step = torch.compile(
                    graph._decode_step, mode="default", fullgraph=False, dynamic=False
                )
                print(f"breeze overlay: compiling backbone decode (batch {branch_batch_size})")
                graph.capture()
                self._backbone_graphs[branch_batch_size] = graph
            super()._ensure_graphs(
                branch_batch_size, guidance_scale, depth_bucket_sizes=depth_bucket_sizes
            )

        # ── per-frame helpers ──

        def _lean_suppress_index(self) -> torch.Tensor | None:
            cached = getattr(self, "_ygg_suppress_index", None)
            if cached is None and self._reserved_codec_token_ids:
                cached = torch.tensor(
                    self._reserved_codec_token_ids, dtype=torch.long, device=self.device
                )
                self._ygg_suppress_index = cached
            return cached

        def _pad_frame_possible(self) -> bool:
            """Can a frame be all `codebook_pad_token_id`? Its codebook 0 is the backbone
            token, which never takes a suppressed reserved id (that logit is -inf)."""
            pad = int(self.model.config.codebook_pad_token_id)
            return not self._codec_codebook_size <= pad < int(self.model.config.vocab_size)

        def _lean_sample(self, logits, seen, params):
            """upstream sample_logits, minus its two host syncs (same result)."""
            logits = logits.clone().float()
            penalty = self.config.repetition_penalty
            if seen is not None and penalty != 1.0:
                penalized = torch.where(logits > 0, logits / penalty, logits * penalty)
                logits = torch.where(seen, penalized, logits)
            suppress = self._lean_suppress_index()
            if suppress is not None:
                logits[..., suppress] = float("-inf")
            return self._lean_sample_logits(logits, **params)

        @staticmethod
        def _lean_backbone_step(graph, input_ids, step_idx: int):
            """BackboneGraph.run without reading back the position it just wrote."""
            graph.input_ids_buf.copy_(input_ids)
            graph.position_ids.copy_((graph._base_position + step_idx).unsqueeze(-1))
            position = int(graph._prefill_len) + step_idx
            graph.cache_position[0] = position
            graph._set_attention_mask(position)
            if graph.no_graph:
                graph._decode_step()
            else:
                graph.graph.replay()
                if graph.debug:
                    graph.lm_head(graph.hidden_buf[:, -1, :].float())
            return graph.hidden_buf, graph.cfg_logits_buf

        # ── the loop ──

        def iter_audio_chunks(
            self,
            inputs,
            *,
            request_id=None,
            seed=None,
            token_observer=None,
            forced: ForcedFrames | None = None,
        ):
            if forced is None and not self.LEAN_LOOP:
                return base.iter_audio_chunks(
                    self, inputs, request_id=request_id, seed=seed, token_observer=token_observer
                )
            return self._lean_chunks(
                inputs,
                request_id=request_id,
                seed=seed,
                token_observer=token_observer,
                forced=forced,
            )

        @torch.inference_mode()
        def _lean_chunks(self, inputs, *, request_id, seed, token_observer, forced):
            """Upstream's `iter_audio_chunks` (58ec70c), trimmed of host syncs and with
            optional forced frames. Keep it diffable against upstream."""
            cfg = fs.select_fast_cfg(inputs)
            branch_batch_size = 2 if cfg.mode == "single_cfg" else 1
            self._ensure_graphs(branch_batch_size, cfg.guidance_scale)
            assert self._backbone_graph is not None
            assert self._depth_decoder_graph is not None

            codec = self._codec()
            branch = self._build_branch_batch(inputs)
            request_id = request_id or f"local-{uuid.uuid4().hex}"
            codec.open_request(request_id, reset=True, is_first_decode=True)

            backbone_params = self._sampling_params(self.model.generation_config)
            depth_params = (
                dict(forced.depth_params)
                if forced is not None
                else self._sampling_params(self.model.depth_decoder.generation_config)
            )
            eos_id = int(self.model.config.vocab_size)
            pad_possible = self._pad_frame_possible()
            steps = self.config.max_new_tokens
            if forced is not None:
                steps = min(steps, forced.frames)
            chunk_buffer: list[torch.Tensor] = []
            chunk_index = 0
            total_frames = 0
            seen: torch.Tensor | None = None
            if seed is not None:
                torch.manual_seed(seed)
                torch.cuda.manual_seed_all(seed)
            first_decode = True
            t_start = time.perf_counter()
            t_chunk = t_start
            prefill_start_event = None
            prefill_end_event = None
            if self.config.collect_timing:
                prefill_start_event = torch.cuda.Event(enable_timing=True)
                prefill_end_event = torch.cuda.Event(enable_timing=True)
                prefill_start_event.record()

            try:
                attention_mask = branch.attention_mask
                if self._fast_backbone_prefill:
                    if self._backbone_prefill_graph is None:
                        self._backbone_prefill_graph = fs.BackbonePrefillGraphCache(
                            self._backbone_graph, token_granularity=32
                        )
                    prefill_output = self._backbone_prefill_graph(
                        branch.inputs_embeds, attention_mask
                    )
                    hidden = prefill_output.hidden_states
                    logits = prefill_output.logits
                    prefill_len = prefill_output.prefill_len
                    generation_attention_mask = prefill_output.attention_mask
                else:
                    position_ids = attention_mask.long().cumsum(-1) - 1
                    position_ids.masked_fill_(attention_mask == 0, 1)
                    backbone_out = self.model.backbone_model(
                        inputs_embeds=branch.inputs_embeds,
                        attention_mask=attention_mask,
                        position_ids=position_ids,
                        past_key_values=None,
                        cache_position=None,
                        use_cache=True,
                    )
                    hidden = backbone_out.last_hidden_state
                    logits = self.model.lm_head(hidden[:, -1, :].float()).float()
                    prefill_len = self._backbone_graph.prefill_kv(backbone_out.past_key_values)
                    generation_attention_mask = attention_mask

                if forced is not None:
                    token = forced.codes[0:1, 0]
                else:
                    if branch.branch_batch_size == 2:
                        cond_logits = logits[:1]
                        uncond_logits = logits[1:]
                        logits = uncond_logits + branch.cfg.guidance_scale * (
                            cond_logits - uncond_logits
                        )
                    else:
                        logits = logits[:1]
                    token = self._lean_sample(logits, None, backbone_params).view(1)
                self._backbone_graph.set_generation_state(generation_attention_mask)
                if prefill_end_event is not None:
                    prefill_end_event.record()
                if forced is None and int(token.item()) == eos_id:
                    return  # upstream breaks at the top of step 0: no frames

                for step_idx in range(steps):
                    if prefill_len + step_idx >= self.config.max_seq_len - 1:
                        break

                    if branch.branch_batch_size == 2:
                        token_batch = token.repeat(2)
                        depth_hidden = hidden[:, -1, :]
                    else:
                        token_batch = token
                        depth_hidden = hidden[:1, -1, :]

                    if forced is not None and forced.depth_fn is not None:
                        depth_tokens = forced.depth_fn(
                            depth_hidden, token_batch, step_idx, branch.cfg.guidance_scale
                        )
                    else:
                        # Params live in per-bucket graph buffers and can't change
                        # mid-request: write them on the first frame only.
                        params = (
                            {**depth_params, "guidance_scale": branch.cfg.guidance_scale}
                            if step_idx == 0
                            else {}
                        )
                        depth_tokens = self._depth_decoder_graph.run(
                            depth_hidden, token_batch, **params
                        )
                    frame = torch.cat([token.view(1), depth_tokens[0]], dim=0)
                    if token_observer is not None:
                        token_observer(frame)
                    if not pad_possible or fs.should_decode_codec_frame(frame, self.model.config):
                        chunk_buffer.append(frame.detach())

                    reached_limit = step_idx == self.config.max_new_tokens - 1
                    last = reached_limit or (forced is not None and step_idx == steps - 1)
                    chunk_ready = len(chunk_buffer) >= self._codec_chunk_frames
                    if chunk_ready or last:
                        if chunk_buffer:
                            decode_started = time.perf_counter()
                            frames = chunk_buffer
                            chunk_buffer = []
                            total_frames += len(frames)
                            timing: dict[str, float | int | bool] = {
                                "chunk_index": chunk_index,
                                "codec_frames": len(frames),
                                "decode_launch_ms": (decode_started - t_chunk) * 1000.0,
                                "total_frames": total_frames,
                                "is_final": last,
                            }
                            chunk = self._decode_codec_frames(
                                frames=frames,
                                request_id=request_id,
                                reset=first_decode,
                                is_final=last,
                                timing=timing,
                            )
                            if chunk_index == 0:
                                first_timing = {
                                    **chunk.timing,
                                    "ttfa_internal_ms": (time.perf_counter() - t_start) * 1000.0,
                                }
                                if (
                                    prefill_start_event is not None
                                    and prefill_end_event is not None
                                ):
                                    first_timing["prefill_gpu_ms"] = (
                                        prefill_start_event.elapsed_time(prefill_end_event)
                                    )
                                chunk = fs.FastStreamingChunk(
                                    audio=chunk.audio,
                                    sample_rate=chunk.sample_rate,
                                    codec_frames=chunk.codec_frames,
                                    is_final=chunk.is_final,
                                    timing=first_timing,
                                )
                            yield chunk
                            first_decode = False
                            chunk_index += 1
                            t_chunk = time.perf_counter()
                        if last:
                            break

                    frame_for_backbone = frame.view(1, 1, -1)
                    if branch.branch_batch_size == 2:
                        frame_for_backbone = frame_for_backbone.repeat(2, 1, 1)

                    hidden, logits = self._lean_backbone_step(
                        self._backbone_graph, frame_for_backbone, step_idx
                    )
                    if forced is not None:
                        token = forced.codes[step_idx + 1 : step_idx + 2, 0]
                        continue
                    logits = logits.float()
                    if seen is None:
                        seen = torch.zeros(logits.shape[-1], dtype=torch.bool, device=logits.device)
                    seen.index_fill_(0, token.view(1), True)  # == token_history[: step + 1]
                    token = self._lean_sample(logits, seen, backbone_params).view(1)
                    if int(token.item()) == eos_id:
                        break

                if chunk_buffer:
                    frames = chunk_buffer
                    total_frames += len(frames)
                    yield self._decode_codec_frames(
                        frames=frames,
                        request_id=request_id,
                        reset=first_decode,
                        is_final=True,
                        timing={
                            "chunk_index": chunk_index,
                            "codec_frames": len(frames),
                            "decode_launch_ms": (time.perf_counter() - t_chunk) * 1000.0,
                            "total_frames": total_frames,
                            "is_final": True,
                        },
                    )
            finally:
                codec.close_request(request_id)

    YggdrasilStreamingRuntime.__name__ = "YggdrasilStreamingRuntime"
    return YggdrasilStreamingRuntime
