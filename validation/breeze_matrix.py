#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "imageio-ffmpeg>=0.5",
#   "soundfile>=0.12",
#   "numpy>=1.26",
#   "librosa>=0.10",
#   "soundfile>=0.12",
#   "faster-whisper>=1.1",
#   "nvidia-cublas-cu12==12.8.4.1",
#   "nvidia-cudnn-cu12==9.10.2.21",
# ]
# ///
"""Breeze TTS 2 capability matrix — re-run after every deploy.

    uv run validation/breeze_matrix.py                 # full matrix + ASR
    uv run validation/breeze_matrix.py --no-asr        # skip transcription
    uv run validation/breeze_matrix.py --only tag_ emotion_   # id prefixes
    uv run validation/breeze_matrix.py --only perf_ --no-asr   # 8 streamed cases, steady-state RTF (~3 min)
    uv run validation/breeze_matrix.py --only stream_ design_plain clone_basic direction_angry long_design
                                                       # streaming + the buffered cases it compares against

Requests go out strictly one at a time. Every case records request fields,
HTTP status, latency, response headers, output duration / sample rate, and
objective checks (Whisper WER, tag-read-aloud, duration deltas, RMS, F0).
Writes validation/runs/<UTC stamp>/{results.json,REPORT.md,*.wav} and
copies REPORT.md to validation/LATEST.md.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
REFS = HERE / "refs"
URL = os.environ.get("BREEZE_URL", "http://localhost:8500")
SPEECH = "/v1/audio/speech"
CLONE_VOICE = os.environ.get("BREEZE_CLONE_VOICE", "narrator_m")
# Breeze licence §5(c)/(d): no cloning real people or unlicensed audio. Clone refs are
# therefore synthetic — made here with Voice Design, saved with their exact text.
DESIGNED_REFS = {
    "narrator_m": ("An older male narrator with a deep, warm, gravelly voice, calm and measured.",
                   "Long ago, before the rivers found their courses, the old roads ran straight through the "
                   "mountains, and travellers spoke of lights that walked beside them in the dark.", "101"),
    "young_f": ("A young woman in her twenties, bright and clear, friendly and lightly energetic.",
                "Honestly, I didn't expect the market to be this busy on a Tuesday, but the bread smells "
                "amazing, so I'm not complaining. Let's grab a loaf before it's gone.", "202"),
    "narrator_long": ("An older male narrator with a deep, warm, gravelly voice, calm and measured.",
                      "Long ago, before the rivers found their courses, the old roads ran straight through the "
                      "mountains, and travellers spoke of lights that walked beside them in the dark. Some said "
                      "the lights were lanterns of the lost; others swore they were only fireflies, grown bold "
                      "in the long summer nights.", "104"),
    "child": ("A young child of about eight, high-pitched, curious and excited.",
              "Look, look, there's a frog on the big rock! Can we take him home? I promise I'll feed him "
              "every single day and give him a really good name.", "303"),
}

LINE = "The council met at dawn to decide the fate of the valley below."
TAG_LINE = "Well, {tag} I really think we should be going now."
TAG_LINE_ZH = "我觉得{tag}我们现在真的应该走了。"
TAG_SEEDS = ("42", "7")
NEUTRAL = "Speak naturally and conversationally."
DOCUMENTED = ([("en", f"({t})") for t in ("laugh", "cough", "clears throat", "sigh")]
              + [("zh", f"[{t}]") for t in ("笑", "咳嗽", "清嗓子", "叹气")])
HOSTED34 = [("en", f"({t})") for t in (
    "laughs", "chuckles", "giggles", "crying", "sobs", "whimpers", "groans", "sighs", "gasps",
    "inhales", "exhales", "breathing heavily", "whispers", "shouts", "screams", "humming",
    "stutters", "pause", "clears throat", "coughs", "sniffs", "yawns", "sneezes", "hiccups",
    "gulps", "grunts", "scoffs", "snorts")]
EXPERIMENTAL = [("en", f"({t})") for t in
                ("sneeze", "gasp", "yawn", "whispers", "chuckle", "cry", "breath", "sob")]
# full seeds × {cfg1 plain, cfg3 neutral instruction}: documented + drama + base/3rd-person pairs
CORE = DOCUMENTED + [("en", f"({t})") for t in
                     ("laughs", "sobs", "gasps", "whispers", "shouts", "screams", "sneezes", "coughs", "sighs")]
BRACKET_CONTROL = [("en", f"[{t}]") for t in ("cough", "laugh", "sigh")]
# Control tokens: the user wants them passed through (max control) EXCEPT the two that
# crash the model, which the server must reject.
INJECTIONS = {  # id: (text, expect)
    "s1": ("[S1] The council met at dawn to decide the fate of the valley below.", "2xx"),
    "ins_bos": ("The council met at dawn <ins_bos> to decide the fate of the valley below.", "2xx|4xx"),
    "audio_tok": ("The council met at dawn <|AUDIO|> to decide the fate of the valley below.", "4xx"),
    "audio_eos": ("The council met at dawn <|audio_eos|> to decide the fate of the valley below.", "4xx"),
}
INS = re.compile(r"<ins_bos>.*?<ins_eos>")
# Inline direction (feature): (id, text-with-inline-instructions, switch word, words that must not be heard)
INLINE = [
    ("furious", "I can't believe it. <ins_bos>Speak in a furious, shouting voice.<ins_eos> You lied to me!",
     "you", ["furious", "shouting", "voice"]),
    ("whisper_shout", "<ins_bos>Whisper softly.<ins_eos> I have to tell you something quietly. "
     "<ins_bos>Now shout as loud as you can.<ins_eos> Get out of here right now!",
     "get", ["whisper", "softly", "shout", "loud"]),
]
EMOTIONS = {
    "neutral": "Speak clearly and naturally.",
    "angry": "A hard, clipped voice, simmering with barely controlled fury, biting off each word.",
    "sad": "A weary, grief-stricken voice, slow and quiet, barely holding back tears.",
    "happy": "A bright, cheerful voice, bursting with warmth and excitement, smiling through every word.",
    "whispering": "A soft, breathy whisper, hushed and intimate, barely voiced.",
    "fearful": "A trembling, terrified voice, shaky and fast, as if hiding from something nearby.",
}
MEDIUM = ("The council met at dawn to decide the fate of the valley below. Nobody wanted to speak first, "
          "so the old miller cleared his throat and began. By noon they had argued themselves hoarse, "
          "and still the river kept rising.")
LONG = (
    "Once upon a time, in a village wedged between two sleepy hills, there lived a clockmaker who "
    "could not tell time. Every clock in his shop ticked at its own pace, and the villagers loved them "
    "anyway, because each one seemed to know exactly when you needed a little more of the afternoon. "
    "One winter, the tallest clock stopped altogether, and nobody knew why. The children said it was "
    "sleeping. The baker said it was sulking. The clockmaker said nothing at all, but every night he sat "
    "beside it with a candle and a cup of tea, listening for a heartbeat that never came. Then, on the "
    "first morning of spring, a small bird flew in through the open window, landed on the minute hand, "
    "and began to sing. And the clock, as if it had only been waiting for company, began to tick again."
)


def ensure_refs(cl: httpx.Client) -> None:
    """Design any missing reference voice and save <name>.wav + <name>.txt (exact text)."""
    REFS.mkdir(exist_ok=True)
    for name, (ins, text, seed) in DESIGNED_REFS.items():
        wav = REFS / f"{name}.wav"
        if wav.exists():
            continue
        r = cl.post(SPEECH, data={"text": text, "instruction": ins, "cfg_scale": "3", "seed": seed}, timeout=300)
        r.raise_for_status()
        sr = int(r.headers.get("x-sample-rate", 24000))
        pcm_to_wav(r.content, sr, wav)
        (REFS / f"{name}.txt").write_text(text)
        (REFS / f"{name}.json").write_text(json.dumps({"instruction": ins, "seed": seed, "cfg_scale": 3,
                                                       "duration_s": len(r.content) / 2 / sr}, indent=1))
        print(f"  designed ref {name}: {len(r.content) / 2 / sr:.1f}s")
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    src = REFS / f"{CLONE_VOICE}.wav"
    for ext, codec in (("mp3", ["-c:a", "libmp3lame", "-b:a", "128k"]), ("ogg", ["-c:a", "libvorbis"]),
                       ("m4a", ["-c:a", "aac", "-b:a", "128k"])):
        dst = REFS / f"{CLONE_VOICE}.{ext}"
        if not dst.exists():
            import subprocess
            subprocess.run([ff, "-v", "error", "-y", "-i", str(src), *codec, str(dst)], check=True)


def clone_ref(name: str) -> tuple[Path, str]:
    return REFS / f"{name}.wav", (REFS / f"{name}.txt").read_text().strip()


def long_wav(src: Path, seconds: float) -> bytes:
    """Loop a ref clip into an in-memory WAV of at least `seconds`."""
    if not src.exists():
        return b""
    with wave.open(str(src)) as w:
        sr, pcm = w.getframerate(), w.readframes(w.getnframes())
    reps = int(seconds * sr * 2 // max(len(pcm), 1)) + 1
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm * reps)
    return buf.getvalue()


def build_cases(ref: Path, ref_text: str) -> list[dict]:
    clone = {"ref": ref, "ref_text": ref_text}
    C: list[dict] = []
    add = lambda **k: C.append(k)  # noqa: E731

    # ── endpoints ──
    add(id="ep_health", cat="health", method="GET", path="/health", expect=200)
    add(id="ep_openapi", cat="health", method="GET", path="/openapi.json", expect=200)
    add(id="ep_convert", cat="voice-change", method="POST", path="/v1/audio/convert", expect="2xx|4xx",
        note="exists (not 404)? empty-ish request", files_ref=ref)
    add(id="ep_voices", cat="saved-voices", method="GET", path="/v1/voices", expect=200)
    add(id="ep_capabilities", cat="health", method="GET", path="/v1/capabilities", expect=200)

    # ── design ──
    add(id="design_plain", cat="design", fields={"text": LINE}, expect=200, asr=True)
    add(id="design_instruct", cat="design",
        fields={"text": LINE, "instruction": "An old, gravelly male narrator, slow and deliberate.",
                "cfg_scale": "4"}, expect=200, asr=True)
    add(id="design_zh", cat="design", fields={"text": "今天天氣很好，我們一起去公園散步吧。"},
        expect=200)

    # ── clone ──
    add(id="clone_basic", cat="clone", fields={"text": LINE}, **clone, expect=200, asr=True)
    add(id="clone_no_ref_text", cat="clone", fields={"text": LINE}, ref=ref, ref_text=None,
        expect=400, note="ref_audio without ref_text")

    # ── direction ──
    for k, ins in [("angry", EMOTIONS["angry"]),
                   ("british", "A crisp, upper-class British accent, precise and formal."),
                   ("whisper", EMOTIONS["whispering"])]:
        add(id=f"direction_{k}", cat="direction",
            fields={"text": LINE, "instruction": ins, "cfg_scale": "4"}, **clone, expect=200, asr=True)

    # ── emotion (design, cfg 4, same seed, same text) ──
    for emo, ins in EMOTIONS.items():
        add(id=f"emotion_{emo}", cat="emotion", group="emotion",
            fields={"text": LINE, "instruction": ins, "cfg_scale": "4"}, expect=200, asr=True)

    # ── non-verbal tags ──
    # Every tag is compared with a no-tag control of the same (lang, cfg, seed).
    # cfg1 = plain (no instruction); cfg3 = NEUTRAL instruction (cfg≠1 needs one).
    def tag_fields(line: str, cfg: str, seed: str) -> dict:
        f = {"text": line, "seed": seed}
        return f | ({"instruction": NEUTRAL, "cfg_scale": cfg} if cfg != "1" else {})

    for lang, line in (("en", TAG_LINE), ("zh", TAG_LINE_ZH)):
        for cfg in ("1", "3"):
            for seed in TAG_SEEDS:
                add(id=f"tag_control_{lang}_cfg{cfg}_s{seed}", cat="tag", group="control", lang=lang,
                    fields=tag_fields(re.sub(r" +", " ", line.format(tag="")), cfg, seed),
                    expect=200, asr=True)
    plan: dict[str, dict] = {}
    def tag_case(grp: str, lang: str, t: str, cfg: str, seed: str) -> None:
        slug = re.sub(r"\W+", "_", t.strip("()[]")).strip("_") or t.strip("()[]")
        form = "paren" if t.startswith("(") else "bracket"
        cid = f"tag_{lang}_{form}_{slug}_cfg{cfg}_s{seed}"
        if cid in plan:
            plan[cid]["group"] += f"+{grp}"
            return
        plan[cid] = dict(id=cid, cat="tag", group=grp, lang=lang, tag=t.strip("()[]"), form=form,
                         cfg=cfg, seed=seed, control=f"tag_control_{lang}_cfg{cfg}_s{seed}",
                         fields=tag_fields((TAG_LINE if lang == "en" else TAG_LINE_ZH).format(tag=t),
                                           cfg, seed),
                         expect=200, asr=True)
    for lang, t in CORE:
        for cfg in ("1", "3"):
            for seed in TAG_SEEDS:
                tag_case("documented" if (lang, t) in DOCUMENTED else "core", lang, t, cfg, seed)
    for lang, t in HOSTED34:
        tag_case("hosted34", lang, t, "3", "42")
    for lang, t in EXPERIMENTAL:
        tag_case("experimental", lang, t, "3", "42")
    for lang, t in BRACKET_CONTROL:
        for seed in TAG_SEEDS:
            tag_case("bracket-control", lang, t, "1", seed)
    C.extend(plan.values())

    # ── every designed voice clones; non-WAV uploads of the same ref decode ──
    for name in DESIGNED_REFS:
        if name != CLONE_VOICE:
            p, t = clone_ref(name)
            add(id=f"clone_voice_{name}", cat="clone", fields={"text": LINE}, ref=p, ref_text=t,
                expect=200, asr=True)
    for fmt, mime, note in (("mp3", "audio/mpeg", ""), ("ogg", "audio/ogg", ""),
                            ("m4a", "audio/mp4", "500 on 2026-10-06; should pass once transcoding lands")):
        add(id=f"clone_ref_{fmt}", cat="clone", fields={"text": LINE}, ref=ref.with_suffix(f".{fmt}"),
            ref_text=ref_text, ref_name=f"ref.{fmt}", ref_mime=mime, expect=200, asr=True, note=note)

    # ── long input: silent truncation at the frame limit? ──
    add(id="long_xl_design", cat="long", fields={"text": LONG + " " + LONG}, expect=200, asr=True,
        timeout=900, words=len((LONG + " " + LONG).split()))

    # ── control tokens: pass-through except the crashing <|AUDIO|>/<|audio_eos|> ──
    TOKS = ["[S1]", "<ins_bos>", "<|AUDIO|>", "<|audio_eos|>"]
    for k, (txt, exp) in INJECTIONS.items():
        add(id=f"inject_text_{k}", cat="injection", fields={"text": txt}, expect=exp, asr=True, strip=TOKS)
    add(id="inject_instruction_audio_tok", cat="injection",
        fields={"text": LINE, "instruction": "Speak calmly. <|AUDIO|>", "cfg_scale": "4"},
        expect="4xx", asr=True)
    add(id="inject_clone_ref_text", cat="injection", fields={"text": LINE}, **clone,
        expect="4xx", asr=True, note="<|AUDIO|> in ref_text; baseline dropped the stream mid-body",
        ref_text_suffix=" <|AUDIO|>")

    # ── inline direction (feature): <ins_bos>…<ins_eos> mid-text vs the same text without ──
    for k, txt, sw, banned in INLINE:
        for variant, t in (("inline", txt), ("control", re.sub(r" +", " ", INS.sub("", txt)).strip())):
            for cfg in ("1", "3"):
                for seed in TAG_SEEDS:
                    f = {"text": t, "seed": seed} | ({"instruction": NEUTRAL, "cfg_scale": "3"} if cfg == "3" else {})
                    add(id=f"inline_{k}_{variant}_cfg{cfg}_s{seed}", cat="inline", group=k, expect=200,
                        asr=True, asr_ref=INS.sub(" ", t), split_word=sw, banned=banned, fields=f,
                        control=f"inline_{k}_control_cfg{cfg}_s{seed}" if variant == "inline" else None)
    k, txt, sw, banned = INLINE[0]
    add(id="inline_furious_raw_cfg1_s42", cat="inline", group="raw", expect=200, asr=True,
        asr_ref=INS.sub(" ", txt), split_word=sw, banned=banned, fields={"text": txt, "seed": "42", "raw": "true"},
        control="inline_furious_control_cfg1_s42", note="raw=true skips the split (old behaviour expected)")
    # [S1] mid-text in a clone: anything audible change at the boundary?
    s1 = "The council met at dawn to decide the fate of the valley. [S1] Nobody wanted to speak first."
    for variant, t in (("s1", s1), ("control", s1.replace(" [S1]", ""))):
        for seed in TAG_SEEDS:
            add(id=f"inline_s1clone_{variant}_s{seed}", cat="inline", group="s1clone", **clone, expect=200,
                asr=True, asr_ref=t.replace("[S1]", " "), split_word="nobody", fields={"text": t, "seed": seed},
                control=f"inline_s1clone_control_s{seed}" if variant == "s1" else None)

    # ── speed: the field the brief asks for, plus instruction-driven pace ──
    for s in ("0.7", "1.0", "1.3"):
        add(id=f"speed_field_{s}", cat="speed", group="speed_field",
            fields={"text": LINE, "speed": s}, expect=200, asr=True)
    for k, ins in [("slow", "Speak very slowly, with long deliberate pauses between words."),
                   ("normal", "Speak clearly and naturally."),
                   ("fast", "Speak very fast, rushing through the words.")]:
        add(id=f"speed_instr_{k}", cat="speed", group="speed_instr",
            fields={"text": LINE, "instruction": ins, "cfg_scale": "4"}, expect=200, asr=True)

    # ── seed determinism ──
    add(id="seed_7_a", cat="seed", fields={"text": LINE, "seed": "7"}, expect=200)
    add(id="seed_7_b", cat="seed", fields={"text": LINE, "seed": "7"}, expect=200)
    add(id="seed_8", cat="seed", fields={"text": LINE, "seed": "8"}, expect=200)
    add(id="seed_clone_7_a", cat="seed", fields={"text": LINE, "seed": "7"}, **clone, expect=200)
    add(id="seed_clone_7_b", cat="seed", fields={"text": LINE, "seed": "7"}, **clone, expect=200)

    # ── long text ──
    add(id="long_design", cat="long", fields={"text": LONG}, expect=200, asr=True, timeout=600,
        words=len(LONG.split()))
    add(id="long_clone", cat="long", fields={"text": LONG}, **clone, expect=200, asr=True, timeout=600,
        words=len(LONG.split()))

    # ── streaming: same fields/seed as the buffered design_plain / clone_basic /
    #    direction_angry cases, so the stitched stream can be compared to them ──
    for k, base in [("design", {"text": LINE}),
                    ("clone", {"text": LINE}),
                    ("direction", {"text": LINE, "instruction": EMOTIONS["angry"], "cfg_scale": "4"}),
                    ("long", {"text": LONG})]:
        add(id=f"stream_{k}", cat="stream", kind="stream", fields=base,
            **(clone if k in ("clone", "direction") else {}), expect=200, asr=True,
            compare={"design": "design_plain", "clone": "clone_basic",
                     "direction": "direction_angry", "long": "long_design"}[k], timeout=600)
    # ── RTF / time-to-first-audio grid: mode × length, all streamed ──
    for ln, txt in (("short", LINE), ("medium", MEDIUM)):
        for mode, extra, use_clone in (
                ("design_cfg1", {}, False),
                ("design_cfg4", {"instruction": EMOTIONS["neutral"], "cfg_scale": "4"}, False),
                ("clone", {}, True),
                ("direction_cfg4", {"instruction": EMOTIONS["angry"], "cfg_scale": "4"}, True)):
            add(id=f"stream_rtf_{mode}_{ln}", cat="stream", kind="stream", group="rtf",
                fields={"text": txt, **extra}, **(clone if use_clone else {}), expect=200, timeout=600)
    add(id="stream_nonstream_flag", cat="stream", fields={"text": LINE, "stream": "false"}, expect=200,
        compare="design_plain", note="non-stream option, if/when one exists (unknown fields are ignored today)")
    add(id="stream_abort_recover", cat="stream", kind="abort", fields={"text": LONG}, expect=200)
    add(id="stream_concurrent_409", cat="stream", kind="concurrent", fields={"text": LONG}, expect=200,
        second_expect=409, note="long stream outlasts the server's 8 s lock wait → 409 after ~8 s")
    add(id="stream_lock_wait", cat="stream", kind="concurrent", fields={"text": "Just a moment, please."},
        expect=200, second_expect=200, note="short stream ends inside the 8 s lock wait → second gets 200")

    # ── speed A/B: engine × {0.85, 1.0, 1.15}, buffered so X-* headers come back ──
    for eng in ("rubberband", "atempo"):
        for sp in ("0.85", "1.0", "1.15"):
            add(id=f"speed_{eng}_{sp}", cat="speed", group=f"speed_{eng}", speed=float(sp), engine=eng,
                fields={"text": MEDIUM, "speed": sp, "speed_engine": eng, "stream": "false", "seed": "42"},
                expect=200, asr=True)
    add(id="stream_speed_1.15", cat="stream", kind="stream", fields={"text": MEDIUM, "speed": "1.15"},
        expect=200, asr=True, note="speed≠1 must still stream")

    # ── output format ──
    add(id="fmt_wav_buffered", cat="format", fields={"text": LINE, "response_format": "wav", "stream": "false"},
        expect=200, asr=True, want_wav="sized")
    add(id="fmt_wav_stream", cat="format", kind="stream",
        fields={"text": LINE, "response_format": "wav", "stream": "true"}, expect=200, asr=True, want_wav="open")

    # ── limiter ──
    add(id="limiter_default_angry", cat="limiter",
        fields={"text": LINE, "instruction": EMOTIONS["angry"], "cfg_scale": "4"}, expect=200, peak_max=0.95)
    add(id="limiter_off_angry", cat="limiter",
        fields={"text": LINE, "instruction": EMOTIONS["angry"], "cfg_scale": "4", "limiter": "false"}, expect=200)

    # hotter limiter probe: screaming at cfg 6, limiter on vs off, 2 seeds
    SCREAM = EMOTIONS["angry"] + " SCREAMING AT THE TOP OF YOUR LUNGS, as loud as humanly possible."
    for seed in ("42", "7"):
        for lim in ("true", "false"):
            add(id=f"limiter_scream_{'on' if lim == 'true' else 'off'}_s{seed}", cat="limiter", expect=200,
                fields={"text": "Get out! Get out of my house right now!", "instruction": SCREAM, "cfg_scale": "6",
                        "seed": seed, "limiter": lim})

    # emotion seed-noise check (whispering / angry regressed on one seed)
    for emo in ("whispering", "angry"):
        for seed in ("42", "7", "123"):
            add(id=f"emoseed_{emo}_s{seed}", cat="emotion", expect=200, asr=True,
                fields={"text": LINE, "instruction": EMOTIONS[emo], "cfg_scale": "4", "seed": seed})

    # ── perf subset: fixed 8 streamed cases for before/after RTF (≈3 min, no ASR) ──
    PERF_LONG = MEDIUM + " " + MEDIUM
    for pid, txt, extra, use_clone in (
            ("design_cfg1_short", LINE, {}, False),
            ("design_cfg1_medium", MEDIUM, {}, False),
            ("design_cfg4_medium", MEDIUM, {"instruction": EMOTIONS["neutral"], "cfg_scale": "4"}, False),
            ("clone_short", LINE, {}, True),
            ("clone_medium", MEDIUM, {}, True),
            ("direction_cfg4_medium", MEDIUM, {"instruction": EMOTIONS["angry"], "cfg_scale": "4"}, True),
            ("design_cfg1_long", PERF_LONG, {}, False),
            ("clone_long", PERF_LONG, {}, True)):
        add(id=f"perf_{pid}", cat="perf", kind="stream", group="perf", expect=200, timeout=600,
            fields={"text": txt, "seed": "42", **extra}, **(clone if use_clone else {}))

    # ── dual CFG / sampling ──
    add(id="dualcfg_buffered", cat="direction", **clone, expect=os.environ.get("BREEZE_DUALCFG_EXPECT", "400"),
        asr=True, note="fast_mode=full: dual CFG is eager-only → 400; set BREEZE_DUALCFG_EXPECT=200 on eager",
        fields={"text": LINE, "instruction": EMOTIONS["angry"], "cfg_scale_ref": "2", "cfg_scale_ins": "4",
                "stream": "false"})
    add(id="dualcfg_stream_rejected", cat="error", **clone, expect=400,
        fields={"text": LINE, "instruction": EMOTIONS["angry"], "cfg_scale_ref": "2", "cfg_scale_ins": "4",
                "stream": "true"})
    add(id="sampling_fields", cat="design", expect=200, asr=True,
        fields={"text": LINE, "temperature": "0.7", "top_k": "50", "top_p": "0.9"})

    # ── long-prompt clone: ~14 s ref + ~70 words (frozen-bucket check) ──
    lp, lt = clone_ref("narrator_long")
    words70 = " ".join(LONG.split()[:72])
    add(id="clone_longref_70w", cat="long", kind="stream", ref=lp, ref_text=lt, fields={"text": words70},
        expect=200, asr=True, timeout=600, words=len(words70.split()))

    # ── saved voices CRUD (order matters) ──
    VID = "validator-narrator"
    add(id="voices_delete_pre", cat="saved-voices", method="DELETE", path=f"/v1/voices/{VID}", expect="2xx|4xx")
    add(id="voices_create", cat="saved-voices", method="POST", path="/v1/voices", ref=ref, ref_text=ref_text,
        fields={"id": VID, "description": "validator test voice (voice-designed, licence-safe)"}, expect="2xx")
    add(id="voices_list", cat="saved-voices", method="GET", path="/v1/voices", expect=200, body_has=VID)
    add(id="voices_get", cat="saved-voices", method="GET", path=f"/v1/voices/{VID}", expect=200)
    add(id="voices_get_audio", cat="saved-voices", method="GET", path=f"/v1/voices/{VID}/audio", expect=200)
    add(id="voices_synth", cat="saved-voices", fields={"text": LINE, "voice": VID}, expect=200, asr=True,
        compare="clone_basic")
    add(id="err_voice_and_ref", cat="error", fields={"text": LINE, "voice": VID}, **clone, expect="4xx")
    add(id="voices_delete", cat="saved-voices", method="DELETE", path=f"/v1/voices/{VID}", expect="2xx")
    add(id="err_voice_unknown", cat="error", fields={"text": LINE, "voice": VID}, expect="4xx")

    # ── voice conversion (revoice): young_f's designed line re-spoken as narrator_m ──
    yp, yt = clone_ref("young_f")
    add(id="convert_revoice", cat="voice-change", path="/v1/audio/convert", ref=ref, ref_text=ref_text,
        extra_files={"source_audio": yp}, fields={"source_text": yt, "seed": "42"}, expect=200, asr=True,
        asr_ref=yt, source_dur=True)

    # ── error handling (expect 4xx) ──
    add(id="err_missing_text", cat="error", fields={"instruction": "x"}, expect=422)
    add(id="err_empty_text", cat="error", fields={"text": ""}, expect="4xx")
    add(id="err_whitespace_text", cat="error", fields={"text": "   "}, expect="4xx")
    add(id="err_bad_seed", cat="error", fields={"text": LINE, "seed": "abc"}, expect=422)
    add(id="err_bad_cfg", cat="error", fields={"text": LINE, "cfg_scale": "nan-ish"}, expect=422)
    add(id="err_cfg_no_instruction", cat="error", fields={"text": LINE, "cfg_scale": "2"},
        expect="4xx", note="known: bare 500 on 2026-10-05")
    add(id="err_negative_cfg", cat="error",
        fields={"text": LINE, "cfg_scale": "-5", "instruction": "Speak naturally."}, expect="4xx")
    add(id="err_garbage_ref_audio", cat="error", fields={"text": LINE},
        ref_bytes=b"this is not audio at all" * 10, ref_text="hello", expect="4xx")
    add(id="err_ref_text_only", cat="error", fields={"text": LINE, "ref_text": "hello there"},
        expect="2xx|4xx", note="ref_text without ref_audio")
    add(id="err_bad_speed", cat="error", fields={"text": LINE, "speed": "-1"}, expect="4xx",
        note="only meaningful once speed is a real field")
    add(id="err_speed_high", cat="error", fields={"text": LINE, "speed": "3.0"}, expect="4xx")
    add(id="err_speed_engine", cat="error", fields={"text": LINE, "speed": "1.1", "speed_engine": "sox"},
        expect="4xx")
    add(id="err_unknown_field", cat="error", fields={"text": LINE, "foo": "bar"}, expect="4xx")
    add(id="err_text_over_1000", cat="error", fields={"text": (LONG + " ") * 2}, expect="4xx",
        note=f"{len((LONG + ' ') * 2)} chars")
    add(id="err_bad_response_format", cat="error", fields={"text": LINE, "response_format": "flac"},
        expect="4xx")
    add(id="err_ref_over_60s", cat="error", fields={"text": LINE}, ref_bytes=long_wav(ref, 65),
        ref_text=ref_text, expect="4xx")
    return C


def status_ok(code: int, expect) -> bool:
    if isinstance(expect, str) and expect.isdigit():
        expect = int(expect)
    if isinstance(expect, int):
        return code == expect
    return any(code // 100 == int(p[0]) for p in expect.split("|"))


def pcm_to_wav(pcm: bytes, sr: int, path: Path) -> np.ndarray:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def audio_stats(a: np.ndarray, sr: int) -> dict:
    import librosa
    if a.size == 0:
        return {"duration_s": 0.0}
    rms = float(np.sqrt(np.mean(a**2)) + 1e-12)
    f0, vflag, _ = librosa.pyin(a, fmin=60, fmax=600, sr=sr, frame_length=2048)
    voiced = f0[vflag] if vflag is not None else np.array([])
    # active speech: frames above -40 dB of peak
    fr = librosa.feature.rms(y=a, frame_length=1024, hop_length=256)[0]
    active = float((fr > fr.max() * 0.01).mean()) if fr.size else 0.0
    return {
        "duration_s": round(a.size / sr, 3),
        "rms_dbfs": round(20 * np.log10(rms), 1),
        "peak": round(float(np.abs(a).max()), 3),
        "clipped_samples": int((np.abs(a) >= 0.999).sum()),
        "over_-1dBFS_samples": int((np.abs(a) >= 0.891).sum()),
        "f0_median_hz": round(float(np.median(voiced)), 1) if voiced.size else None,
        "voiced_ratio": round(float(vflag.mean()), 3) if vflag is not None else None,
        "active_ratio": round(active, 3),
        # time-stretch artifact probes: phasing/echo raise flatness and smear the
        # spectral flux; compare a stretched output with its own 1.0 baseline
        "flatness_mean": round(float(librosa.feature.spectral_flatness(y=a).mean()), 4),
        "flux_median": round(float(np.median(librosa.onset.onset_strength(y=a, sr=sr))), 3),
    }


def norm_words(s: str) -> list[str]:
    return re.sub(r"[^\w' ]", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm_words(ref), norm_words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return round(d[len(h)] / max(len(r), 1), 3)


def _form(c: dict) -> tuple[dict, dict | None]:
    fields = dict(c.get("fields", {}))
    if c.get("ref_text"):
        fields["ref_text"] = c["ref_text"]
    files = ({"ref_audio": (c.get("ref_name", "ref.wav"), Path(c["ref"]).read_bytes(),
                            c.get("ref_mime", "audio/wav"))} if c.get("ref") else None)
    return fields, files


def wav_header_info(buf: bytes) -> dict:
    i = buf.find(b"data", 12)
    riff = int.from_bytes(buf[4:8], "little")
    data = int.from_bytes(buf[i + 4:i + 8], "little") if i >= 0 else None
    actual = len(buf) - (i + 8) if i >= 0 else None
    return {"riff_size": riff, "data_size": data, "actual_data": actual,
            "sr": int.from_bytes(buf[24:28], "little"), "channels": int.from_bytes(buf[22:24], "little"),
            "bits": int.from_bytes(buf[34:36], "little"), "open_ended": data == 0xFFFFFFFF}


def strip_wav_header(buf: bytes) -> tuple[bytes, int | None]:
    """If a stream starts with a RIFF header, return (pcm, sample_rate)."""
    if buf[:4] != b"RIFF":
        return buf, None
    sr = int.from_bytes(buf[24:28], "little")
    i = buf.find(b"data", 12)
    return (buf[i + 8:] if i >= 0 else buf[44:]), sr


def run_stream_case(cl: httpx.Client, c: dict, out: Path) -> dict:
    """Read the response as it arrives, timestamping every chunk off the socket."""
    rec = {k: (str(v) if isinstance(v, Path) else v) for k, v in c.items()}
    fields, files = _form(c)
    rec["request"] = {"method": "POST", "path": SPEECH, "fields": fields, "ref_audio": str(c.get("ref") or "")}
    chunks: list[tuple[float, int]] = []
    buf = bytearray()
    t0 = time.monotonic()
    try:
        with cl.stream("POST", SPEECH, data=fields, files=files, timeout=c.get("timeout", 300)) as r:
            t_hdr = time.monotonic() - t0
            rec["status"] = r.status_code
            rec["headers"] = {k: v for k, v in r.headers.items()
                              if k.lower().startswith("x-") or k.lower() in
                              ("content-type", "content-length", "transfer-encoding")}
            for b in r.iter_raw():
                chunks.append((time.monotonic() - t0, len(b)))
                buf.extend(b)
    except httpx.HTTPError as e:
        rec.update(status=rec.get("status"), error=f"{type(e).__name__}: {e}", status_ok=False)
        return rec
    total = time.monotonic() - t0
    rec["latency_s"] = round(total, 2)
    rec["status_ok"] = status_ok(rec["status"], c["expect"])
    if rec["status"] != 200:
        rec["body"] = bytes(buf[:600]).decode("utf-8", "replace")
        return rec
    if buf[:4] == b"RIFF":
        rec["wav_header"] = wav_header_info(bytes(buf))
    pcm, wsr = strip_wav_header(bytes(buf))
    sr = wsr or int(rec["headers"].get("x-sample-rate", 24000))
    rec["container"] = "wav-stream" if wsr else "raw-pcm"
    wav = out / f"{c['id']}.wav"
    a = pcm_to_wav(pcm[: len(pcm) // 2 * 2], sr, wav)
    rec.update(output=str(wav.relative_to(HERE)), sample_rate=sr,
               sha256=hashlib.sha256(pcm).hexdigest()[:16], audio=audio_stats(a, sr))
    dur = rec["audio"]["duration_s"]
    times = [t for t, _ in chunks]
    sizes = [n for _, n in chunks]
    gaps = np.diff(times) if len(times) > 1 else np.array([0.0])
    # when did 10% / 50% / 90% of the bytes land?
    cum = np.cumsum(sizes) / max(sum(sizes), 1)
    at = lambda q: round(times[int(np.searchsorted(cum, q))], 2) if times else None  # noqa: E731
    rec["timeline"] = [[round(t, 4), n] for t, n in chunks]
    rec["stream"] = {
        "headers_s": round(t_hdr, 3), "ttfb_s": round(times[0], 3) if times else None,
        "total_s": round(total, 2), "ttfb_frac": round(times[0] / total, 3) if times else None,
        "bytes_at_10_50_90pct_s": [at(0.1), at(0.5), at(0.9)],
        "chunks": len(sizes), "chunk_bytes_min_med_max": [min(sizes), int(np.median(sizes)), max(sizes)]
        if sizes else None,
        "gap_s_med_max": [round(float(np.median(gaps)), 3), round(float(gaps.max()), 3)],
        "audio_s_per_chunk_med": round(float(np.median(sizes)) / 2 / sr, 3) if sizes else None,
        "rtf": round(total / max(dur, 1e-3), 2),
        "x_realtime": round(dur / max(total, 1e-3), 2),  # audio s per wall s; ≥1 keeps up
        # smallest playback start delay that never stalls: max_i(arrival_i − audio already queued)
        "min_prebuffer_s": round(max(t - (sum(sizes[:i]) / 2 / sr) for i, t in enumerate(times)), 2)
        if times else None,
        "ttfa_vs_audio": "first audio arrived before total gen time" if times and times[0] < 0.5 * total
        else "buffered",
    }
    return rec


def steady_state(timeline: list, sr: int, total: float) -> dict:
    """Throughput excluding one-time startup, and per-frame (80 ms) delivery cadence."""
    if len(timeline) < 3:
        return {}
    t = np.array([x[0] for x in timeline]); n = np.array([x[1] for x in timeline], dtype=float)
    t0 = t[0] + 1.0
    m = t >= t0
    steady = (n[m].sum() / 2 / sr) / max(t[-1] - t0, 1e-3) if m.sum() > 2 and t[-1] - t0 > 0.5 else None
    # arrival time of each successive 80 ms of audio (interpolated on cumulative bytes)
    cum = np.cumsum(n)
    frame = 0.08 * sr * 2
    marks = np.arange(frame, cum[-1], frame)
    arr = t[np.searchsorted(cum, marks)]
    iv = np.diff(arr) * 1000
    iv_s = iv[arr[1:] >= t0] if (arr[1:] >= t0).sum() > 2 else iv
    return {"steady_x_realtime": round(float(steady), 3) if steady else None,
            "frame_interval_ms_med_p95": [round(float(np.median(iv_s)), 1), round(float(np.percentile(iv_s, 95)), 1)]
            if iv_s.size else None,
            "frames_over_80ms_pct": round(float((iv_s > 80).mean() * 100), 1) if iv_s.size else None}


def run_abort_case(cl: httpx.Client, c: dict, out: Path) -> dict:
    """Read one chunk of a long stream, hang up, then see whether the next request gets the lock."""
    rec = {k: v for k, v in c.items()}
    fields, _ = _form(c)
    rec["request"] = {"method": "POST", "path": SPEECH, "fields": fields}
    t0 = time.monotonic()
    first = None
    try:
        with cl.stream("POST", SPEECH, data=fields, timeout=300) as r:
            rec["status"] = r.status_code
            for b in r.iter_raw():
                first = (round(time.monotonic() - t0, 2), len(b))
                break
    except httpx.HTTPError as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["aborted_after"] = first
    t_abort = time.monotonic()
    tries = []
    while time.monotonic() - t_abort < 120:
        t_req = time.monotonic()
        r2 = cl.post(SPEECH, data={"text": "Recovered."}, timeout=120)
        tries.append({"t_after_abort_s": round(time.monotonic() - t_abort, 2), "status": r2.status_code,
                      "latency_s": round(time.monotonic() - t_req, 2), "body": r2.text[:120] if r2.status_code != 200 else ""})
        if r2.status_code != 409:
            break
        time.sleep(2)
    rec["followups"] = tries
    last = tries[-1]["status"] if tries else None
    rec["status_ok"] = rec.get("status") == 200 and last == 200
    first409 = tries[0]["status"] == 409 if tries else None
    rec["checks"] = [
        {"check": "next_request_succeeds_immediately", "pass": not first409 and last == 200,
         "detail": f"{len(tries)} attempt(s): {[(t['status'], t.get('latency_s')) for t in tries]} "
                   f"(status, request latency s — latency on a 200 = lock linger absorbed by the 8 s wait)"},
        {"check": "lock_released_eventually", "pass": last == 200,
         "detail": f"recovered after {tries[-1]['t_after_abort_s']}s" if last == 200
         else "STUCK: still 409 after 120 s"},
    ]
    return rec


def run_concurrent_case(cl: httpx.Client, c: dict, out: Path) -> dict:
    """While one stream is in flight, fire a second request; expect a clean 409."""
    import threading
    rec = {k: v for k, v in c.items()}
    fields, _ = _form(c)
    rec["request"] = {"method": "POST", "path": SPEECH, "fields": fields}
    started, res = threading.Event(), {}

    def streamer():
        try:
            with httpx.Client(base_url=URL, headers={"Connection": "close"}) as c2, \
                 c2.stream("POST", SPEECH, data=fields, timeout=600) as r:
                res["status"] = r.status_code
                n = 0
                for b in r.iter_raw():
                    n += len(b)
                    started.set()
                res["bytes"] = n
        except httpx.HTTPError as e:
            res["error"] = f"{type(e).__name__}: {e}"
        finally:
            started.set()

    th = threading.Thread(target=streamer)
    th.start()
    started.wait(3)  # first chunk, or 3 s into a ~60 s generation — either way mid-flight
    t0 = time.monotonic()
    r2 = cl.post(SPEECH, data={"text": "Am I allowed in?"}, timeout=120)
    rec["second"] = {"status": r2.status_code, "latency_s": round(time.monotonic() - t0, 3),
                     "body": r2.text[:200] if r2.status_code != 200 else f"<{len(r2.content)} bytes audio>"}
    th.join()
    rec["first"] = res
    rec["status"] = res.get("status")
    clean = r2.status_code == 409
    want = c.get("second_expect", 409)
    clean = r2.status_code == want
    rec["status_ok"] = res.get("status") == 200 and clean
    rec["checks"] = [
        {"check": f"concurrent_gets_{want}", "pass": r2.status_code == want,
         "detail": f"{r2.status_code} in {rec['second']['latency_s']}s: {rec['second']['body']}"},
        {"check": "first_stream_unharmed", "pass": res.get("status") == 200 and res.get("bytes", 0) > 0
         and "error" not in res, "detail": json.dumps(res)},
    ]
    return rec


def run_case(cl: httpx.Client, c: dict, out: Path) -> dict:
    rec = {k: (str(v) if isinstance(v, Path) else v) for k, v in c.items() if k != "ref_bytes"}
    method, path = c.get("method", "POST"), c.get("path", SPEECH)
    files = None
    if c.get("ref") or c.get("ref_bytes") or c.get("files_ref"):
        p = c.get("ref") or c.get("files_ref")
        blob = c["ref_bytes"] if c.get("ref_bytes") else Path(p).read_bytes()
        files = {"ref_audio": (c.get("ref_name", "ref.wav"), blob, c.get("ref_mime", "audio/wav"))}
    for k, pth in (c.get("extra_files") or {}).items():
        files = (files or {}) | {k: (Path(pth).name, Path(pth).read_bytes(), "audio/wav")}
    fields = dict(c.get("fields", {}))
    if c.get("ref_text"):
        fields["ref_text"] = c["ref_text"] + c.get("ref_text_suffix", "")
    rec["request"] = {"method": method, "path": path, "fields": fields,
                      "ref_audio": (str(c.get("ref") or c.get("files_ref") or "") or
                                    ("<garbage bytes>" if c.get("ref_bytes") else None))}
    t0 = time.monotonic()
    try:
        if method in ("GET", "DELETE"):
            r = cl.request(method, path, timeout=30)
        else:
            r = cl.post(path, data=fields, files=files, timeout=c.get("timeout", 300))
    except httpx.HTTPError as e:
        rec.update(status=None, error=f"{type(e).__name__}: {e}", latency_s=round(time.monotonic() - t0, 2),
                   status_ok=False)
        return rec
    rec["latency_s"] = round(time.monotonic() - t0, 2)
    rec["status"] = r.status_code
    rec["status_ok"] = status_ok(r.status_code, c["expect"])
    rec["headers"] = {k: v for k, v in r.headers.items()
                      if k.lower().startswith("x-") or k.lower() in ("content-type", "content-length")}
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 300 or "json" in ctype or "text" in ctype:
        rec["body"] = r.text[:600]
        if c.get("body_has"):
            rec["checks_pre"] = [{"check": "body_contains", "pass": c["body_has"] in r.text, "detail": c["body_has"]}]
        if c["id"] == "ep_openapi" and r.status_code == 200:
            spec = r.json()
            rec["body"] = {"paths": sorted(spec.get("paths", {})),
                           "speech_fields": sorted(spec.get("components", {}).get("schemas", {})
                                                   .get("Body_speech_v1_audio_speech_post", {})
                                                   .get("properties", {}))}
        return rec
    sr = int(r.headers.get("x-sample-rate", 24000))
    pcm = r.content
    if pcm[:4] == b"RIFF":
        rec["wav_header"] = wav_header_info(pcm)
        pcm, sr = strip_wav_header(pcm)
        rec["container"] = "wav"
    else:
        rec["container"] = "raw-pcm"
    wav = out / f"{c['id']}.wav"
    a = pcm_to_wav(pcm, sr, wav)
    rec["output"] = str(wav.relative_to(HERE))
    rec["sample_rate"] = sr
    rec["sha256"] = hashlib.sha256(pcm).hexdigest()[:16]
    rec["audio"] = audio_stats(a, sr)
    rec["rtf"] = round(rec["latency_s"] / max(rec["audio"]["duration_s"], 1e-3), 2)
    return rec


def preload_cuda_libs() -> None:
    """Load the pip-installed cuBLAS/cuDNN so CTranslate2 finds them (no system CUDA)."""
    import ctypes
    import nvidia.cublas.lib, nvidia.cudnn.lib  # noqa: E401

    for mod in (nvidia.cublas.lib, nvidia.cudnn.lib):
        for so in sorted(Path(list(mod.__path__)[0]).glob("lib*.so*")):
            if "nvblas" in so.name:
                continue  # hijacks host BLAS and aborts without a config file
            try:
                ctypes.CDLL(str(so), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def transcribe(results: list[dict]) -> None:
    from faster_whisper import WhisperModel
    preload_cuda_libs()
    root = str(Path.home() / "models" / "asr" / "faster-whisper-large-v3")
    try:
        m = WhisperModel("large-v3", device="cuda", compute_type="float16", download_root=root)
    except Exception as e:  # noqa: BLE001
        print(f"  cuda whisper unavailable ({e}); falling back to CPU int8")
        m = WhisperModel("large-v3", device="cpu", compute_type="int8", download_root=root)
    for r in results:
        if not (r.get("asr") and r.get("output")):
            continue
        import librosa
        a, _ = librosa.load(str(HERE / r["output"]), sr=16000, mono=True)
        lang = r.get("lang", "en")
        segs, _ = m.transcribe(a, language=lang, beam_size=5, vad_filter=False,
                               word_timestamps=bool(r.get("split_word")))
        segs = list(segs)
        if r.get("split_word"):
            r["words_ts"] = [(w.word.strip(), round(w.start, 2), round(w.end, 2)) for sg in segs for w in sg.words]
        hyp = ("" if lang == "zh" else " ").join(s.text.strip() for s in segs)
        ref = r.get("asr_ref") or r["request"]["fields"].get("text", "")
        if r.get("tag"):
            ref = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", ref)
        for tok in r.get("strip", []):
            ref = ref.replace(tok, " ")
        if lang == "zh":
            strip = lambda x: re.sub(r"[\s\W]", "", x)  # noqa: E731
            ref, hyp_cmp = " ".join(strip(ref)), " ".join(strip(hyp))
            r["asr_text"], r["wer"] = hyp, wer(ref, hyp_cmp)  # character error rate
        else:
            r["asr_text"], r["wer"] = hyp, wer(ref, hyp)


def similarity(a: dict, b: dict) -> str:
    """Same seed is NOT bit-exact on this server (GPU float noise): same length, corr ≈0.995.
    So 'equivalent' = equal sample count and waveform correlation ≥ 0.98."""
    import soundfile as sf
    x, _ = sf.read(HERE / a["output"]); y, _ = sf.read(HERE / b["output"])
    n = min(len(x), len(y))
    corr = float(np.corrcoef(x[:n], y[:n])[0, 1]) if n > 1 else 0.0
    a["_equiv"] = len(x) == len(y) and corr >= 0.98
    return f"{'bit-identical' if a['sha256'] == b['sha256'] else 'not bit-identical'}, " \
           f"len {len(x)} vs {len(y)}, corr {corr:.4f}"


def analyse(results: list[dict]) -> None:
    by = {r["id"]: r for r in results}
    dur = lambda i: (by.get(i, {}).get("audio") or {}).get("duration_s")  # noqa: E731
    for r in results:
        v = []
        if r.get("wer") is not None:
            v.append(("intelligible", r["wer"] <= 0.2, f"WER {r['wer']}"))
        if r.get("tag"):
            if r.get("lang") == "zh":
                spoken = r["tag"] in r.get("asr_text", "")
            else:
                # stem match so "laughing"/"coughs"/"sighed" count as read aloud — but only on words
                # that aren't already in the sentence ("shouts" must not match "should")
                base = set(norm_words(INS.sub(" ", re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", r["request"]["fields"]["text"]))))
                hyp = [h for h in norm_words(r.get("asr_text", "")) if h not in base]
                spoken = all(any(h.startswith(w[:4]) for h in hyp) for w in norm_words(r["tag"]))
            v.append(("tag_not_read_aloud", not spoken if r.get("asr_text") is not None else None,
                      "tag words found in transcript" if spoken else "tag words absent from transcript"))
            base = dur(r.get("control", "tag_control"))
            if base and dur(r["id"]):
                d = round(dur(r["id"]) - base, 2)
                r["dur_delta_vs_control"] = d
                v.append(("tag_adds_audio", d > 0.3, f"{d:+.2f}s vs no-tag control"))
        if r.get("words") and r.get("audio"):
            exp = r["words"] / 2.6
            got = r["audio"]["duration_s"]
            tail = norm_words(r["request"]["fields"]["text"])[-4:]
            hyp = norm_words(r.get("asr_text") or "")
            v.append(("not_truncated", got >= 0.75 * exp and (not hyp or hyp[-4:] == tail),
                      f"{got}s for {r['words']} words = {r['words'] / max(got, 1e-3):.2f} w/s "
                      f"(expect ≈{exp:.0f}s @2.6 w/s); ASR ends '{' '.join(hyp[-4:])}'"))
        if r.get("cat") == "injection" and r.get("asr_text") is not None:
            hyp = r["asr_text"].lower()
            leaked = [t for t in ("s1", "audio", "bos", "ins") if re.search(rf"\b{t}\b", hyp)
                      and not re.search(rf"\b{t}\b", LINE.lower())]
            v.append(("control_tokens_not_spoken", not leaked,
                      f"heard {leaked}" if leaked else "no token words in transcript"))
        st = r.get("stream")
        if st:
            v.append(("incremental", st["ttfb_s"] is not None and st["ttfb_frac"] < 0.5 and st["chunks"] > 2,
                      f"TTFB {st['ttfb_s']}s of {st['total_s']}s ({st['ttfb_frac']:.0%}), {st['chunks']} chunks, "
                      f"10/50/90% bytes at {st['bytes_at_10_50_90pct_s']}s"))
            v.append(("realtime", st["rtf"] < 1.0, f"RTF {st['rtf']}"))
            if r.get("timeline"):
                ss = steady_state(r["timeline"], r.get("sample_rate", 24000), st["total_s"])
                st.update(ss)
                if ss.get("steady_x_realtime") is not None:
                    v.append(("steady_state_realtime", ss["steady_x_realtime"] >= 1.0,
                              f"steady {ss['steady_x_realtime']}× (from TTFB+1 s), 80 ms-frame interval med/p95 "
                              f"{ss['frame_interval_ms_med_p95']} ms, {ss['frames_over_80ms_pct']}% frames late; "
                              f"min prebuffer {st.get('min_prebuffer_s')} s"))
        cmp = by.get(r.get("compare") or "")
        if cmp and r.get("sha256") and cmp.get("sha256"):
            d = similarity(r, cmp)
            v.append(("matches_buffered_same_seed", r["_equiv"], f"vs {cmp['id']}: {d}"))
        if r.get("split_word") and r.get("words_ts") is not None and r.get("output"):
            import soundfile as sf
            a, sr = sf.read(HERE / r["output"])
            t = next((w[1] for w in r["words_ts"] if norm_words(w[0])[:1] == [r["split_word"]]), None)
            if t is None:
                v.append(("switch_word_found", False, f"'{r['split_word']}' not in ASR words"))
            else:
                # back the split off 50 ms so Whisper's word-start jitter doesn't leak the new word in
                k = max(int((t - 0.05) * sr), 0)
                full = lambda x: x if "rms_dbfs" in x else {**x, "rms_dbfs": None, "voiced_ratio": None,  # noqa: E731
                                                              "f0_median_hz": None}
                pre = full(audio_stats(a[:k].astype(np.float32), sr) if k > 2048 else {"duration_s": k / sr})
                post = full(audio_stats(a[k:].astype(np.float32), sr))
                r["segments"] = {"split_s": t, "pre": pre, "post": post}
                v.append(("segments", True,
                          f"split@{t}s pre: {pre['rms_dbfs']} dBFS, voiced {pre['voiced_ratio']}, F0 {pre['f0_median_hz']} → "
                          f"post: {post['rms_dbfs']} dBFS, voiced {post['voiced_ratio']}, F0 {post['f0_median_hz']}"))
        if r.get("banned") and r.get("asr_text") is not None:
            heard = [b for b in r["banned"] if b in norm_words(r["asr_text"])]
            v.append(("instruction_not_read_aloud", not heard, f"heard {heard}" if heard else "none heard"))
        wh = r.get("wav_header")
        if r.get("want_wav"):
            if not wh:
                v.append(("wav_container", False, f"no RIFF header (container {r.get('container')})"))
            elif r["want_wav"] == "sized":
                ok = wh["data_size"] == wh["actual_data"] and wh["riff_size"] == wh["actual_data"] + 36
                v.append(("wav_sizes_correct", ok, json.dumps(wh)))
            else:
                v.append(("wav_open_ended_header", wh["open_ended"], json.dumps(wh)))
        if r.get("peak_max") and r.get("audio"):
            pk = r["audio"]["peak"]
            off = (by.get("limiter_off_angry", {}).get("audio") or {}).get("peak")
            v.append(("limited", pk <= r["peak_max"], f"peak {pk} (limiter off: {off})"))
        if r.get("source_dur") and r.get("audio"):
            import soundfile as sf
            info = sf.info(str(REFS / "young_f.wav"))
            ratio = r["audio"]["duration_s"] / info.duration
            v.append(("duration_matched", abs(ratio - 1) < 0.1, f"{r['audio']['duration_s']}s vs source "
                      f"{info.duration:.2f}s ({ratio:.2f}×)"))
        v += [(c["check"], c["pass"], c["detail"]) for c in r.pop("checks_pre", [])]
        r["checks"] = r.get("checks", []) if not v and r.get("kind") in ("abort", "concurrent") else \
            [{"check": a, "pass": b, "detail": c} for a, b, c in v]

    # seed determinism
    for a, b in [("seed_7_a", "seed_7_b"), ("seed_clone_7_a", "seed_clone_7_b")]:
        if by.get(a, {}).get("sha256") and by.get(b, {}).get("sha256"):
            d = similarity(by[b], by[a])
            by[b]["checks"].append({"check": "same_seed_equivalent", "pass": by[b]["_equiv"], "detail": d})
    if by.get("seed_8", {}).get("sha256") and by.get("seed_7_a", {}).get("sha256"):
        diff = by["seed_8"]["sha256"] != by["seed_7_a"]["sha256"]
        by["seed_8"]["checks"].append({"check": "diff_seed_differs", "pass": diff, "detail": ""})

    # inline direction: does the post-switch segment move vs the control's post segment?
    for r in results:
        c = by.get(r.get("control") or "")
        if r.get("cat") == "inline" and c and r.get("segments") and c.get("segments"):
            d = lambda seg, k: (r["segments"][seg][k] or 0) - (c["segments"][seg][k] or 0)  # noqa: E731
            if None in (r["segments"]["pre"]["rms_dbfs"], c["segments"]["pre"]["rms_dbfs"]):
                r["checks"].append({"check": "inline_effect_vs_control", "pass": None,
                                    "detail": "switch word at clip start — no pre segment"})
                continue
            d_rms, d_v = d("post", "rms_dbfs"), d("post", "voiced_ratio")
            jump = (r["segments"]["post"]["rms_dbfs"] - r["segments"]["pre"]["rms_dbfs"]) - \
                   (c["segments"]["post"]["rms_dbfs"] - c["segments"]["pre"]["rms_dbfs"])
            r["checks"].append({"check": "inline_effect_vs_control", "pass": abs(jump) >= 3 or abs(d_rms) >= 3,
                                "detail": f"post-switch ΔRMS {d_rms:+.1f} dB, Δvoiced {d_v:+.2f}, "
                                          f"pre→post RMS jump vs control {jump:+.1f} dB (pass = |≥3 dB|)"})

    # speed A/B: duration accuracy vs the same engine's 1.0, and artifact probes
    for eng in ("rubberband", "atempo"):
        base = by.get(f"speed_{eng}_1.0")
        if not (base and base.get("audio")):
            continue
        for sp in ("0.85", "1.15"):
            r = by.get(f"speed_{eng}_{sp}")
            if not (r and r.get("audio")):
                continue
            want = base["audio"]["duration_s"] / float(sp)
            got = r["audio"]["duration_s"]
            err = got / want - 1
            df = r["audio"]["flatness_mean"] - base["audio"]["flatness_mean"]
            dflux = r["audio"]["flux_median"] / max(base["audio"]["flux_median"], 1e-6)
            r["checks"].append({"check": "speed_duration_accurate", "pass": abs(err) < 0.05,
                                "detail": f"{got}s vs expected {want:.2f}s ({err:+.1%}); hdr X-Speed="
                                          f"{r.get('headers', {}).get('x-speed')}"})
            r["checks"].append({"check": "no_stretch_artifacts", "pass": abs(df) < 0.01 and 0.7 < dflux < 1.4,
                                "detail": f"Δflatness {df:+.4f}, flux ratio {dflux:.2f} vs 1.0 (heuristic)"})

    # speed: does duration move in the right direction by a real amount?
    for grp, lo, mid, hi in [("speed_field", "speed_field_0.7", "speed_field_1.0", "speed_field_1.3"),
                             ("speed_instr", "speed_instr_slow", "speed_instr_normal", "speed_instr_fast")]:
        if all(dur(i) for i in (lo, mid, hi)):
            ok = dur(lo) > dur(mid) * 1.1 and dur(hi) < dur(mid) * 0.9
            by[hi]["checks"].append({"check": "speed_changes_duration", "pass": ok,
                                     "detail": f"{dur(lo)}s / {dur(mid)}s / {dur(hi)}s (slow/1.0/fast)"})


def cell(r: dict) -> str:
    a = r.get("audio") or {}
    bits = [f"{a['duration_s']}s" if a else ""]
    if a.get("f0_median_hz"):
        bits.append(f"F0 {a['f0_median_hz']}")
    if a.get("rms_dbfs") is not None:
        bits.append(f"{a['rms_dbfs']} dBFS")
    return " · ".join(b for b in bits if b)


def report(results: list[dict], out: Path, args) -> str:
    L = [f"# Breeze TTS 2 capability matrix — {out.name}", "",
         f"Server `{URL}` · clone voice `{CLONE_VOICE}` · ASR {'off' if args.no_asr else 'faster-whisper large-v3'}", "",
         "| id | status (expect) | latency | audio | checks | ASR / body |",
         "|---|---|---|---|---|---|"]
    for r in results:
        st = f"{r.get('status')} ({r['expect']}) {'✅' if r.get('status_ok') else '❌'}"
        ch = "; ".join(f"{'✅' if c['pass'] else ('❔' if c['pass'] is None else '❌')} {c['check']}: {c['detail']}"
                       for c in r.get("checks", []))
        tail = r.get("asr_text") or r.get("error") or ""
        if not tail and r.get("body") is not None:
            tail = json.dumps(r["body"]) if not isinstance(r["body"], str) else r["body"]
        tail = str(tail).replace("|", "\\|").replace("\n", " ")[:220]
        L.append(f"| {r['id']} | {st} | {r.get('latency_s')}s | {cell(r)} | {ch} | {tail} |")
    perf = [r for r in results if r.get("cat") == "perf" and r.get("stream")]
    if perf:
        L += ["", "## perf subset", "",
              "| id | audio s | TTFA s | audio s/wall s | steady × | 80ms-frame med/p95 ms | late % | prebuffer s |",
              "|---|---|---|---|---|---|---|---|"]
        for r in perf:
            st = r["stream"]
            L.append(f"| {r['id']} | {r['audio']['duration_s']} | {st['ttfb_s']} | {st['x_realtime']} | "
                     f"{st.get('steady_x_realtime')} | {st.get('frame_interval_ms_med_p95')} | "
                     f"{st.get('frames_over_80ms_pct')} | {st.get('min_prebuffer_s')} |")
        xs = [r["stream"].get("steady_x_realtime") for r in perf if r["stream"].get("steady_x_realtime")]
        if xs:
            L.append(f"\n**steady-state median {float(np.median(xs)):.3f}× (min {min(xs):.3f}, max {max(xs):.3f})**")
    return "\n".join(L) + "\n"


def diff_runs(a_dir: Path, b_dir: Path) -> str:
    A = {r["id"]: r for r in json.loads((a_dir / "results.json").read_text())}
    B = {r["id"]: r for r in json.loads((b_dir / "results.json").read_text())}
    L = [f"# Diff {a_dir.name} → {b_dir.name}", "",
         "| id | status | dur s | TTFA s | audio s / wall s | steady × | WER | corr / len |",
         "|---|---|---|---|---|---|---|---|"]
    for cid in [k for k in A if k in B]:
        a, b = A[cid], B[cid]
        f = lambda r, *k: (lambda x: x)(  # noqa: E731
            __import__("functools").reduce(lambda d, kk: (d or {}).get(kk), k, r))
        xa = f(a, "stream", "x_realtime") or (round(f(a, "audio", "duration_s") / a["latency_s"], 2)
                                               if f(a, "audio", "duration_s") and a.get("latency_s") else None)
        xb = f(b, "stream", "x_realtime") or (round(f(b, "audio", "duration_s") / b["latency_s"], 2)
                                               if f(b, "audio", "duration_s") and b.get("latency_s") else None)
        corr = ""
        if a.get("output") and b.get("output"):
            import soundfile as sf
            x, _ = sf.read(HERE / a["output"]); y, _ = sf.read(HERE / b["output"])
            n = min(len(x), len(y))
            corr = f"{np.corrcoef(x[:n], y[:n])[0, 1]:.3f} / {len(x)}→{len(y)}" if n > 1 else ""
        L.append(f"| {cid} | {a.get('status')}→{b.get('status')} | {f(a, 'audio', 'duration_s')}→"
                 f"{f(b, 'audio', 'duration_s')} | {f(a, 'stream', 'ttfb_s')}→{f(b, 'stream', 'ttfb_s')} | "
                 f"{xa}→{xb} | {f(a, 'stream', 'steady_x_realtime')}→{f(b, 'stream', 'steady_x_realtime')} | "
                 f"{a.get('wer')}→{b.get('wer')} | {corr} |")
    out = "\n".join(L) + "\n"
    (b_dir / f"DIFF-vs-{a_dir.name}.md").write_text(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="case-id prefixes to run")
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--rescore", help="re-run ASR/analysis on an existing runs/<stamp> dir")
    ap.add_argument("--diff", nargs=2, metavar=("RUN_A", "RUN_B"),
                    help="compare two runs case-by-case (e.g. eager vs fast)")
    args = ap.parse_args()
    if args.diff:
        print(diff_runs(*(Path(d).resolve() for d in args.diff)))
        return
    if args.rescore:
        out = Path(args.rescore).resolve()
        results = json.loads((out / "results.json").read_text())
        if not args.no_asr:
            transcribe(results)
        analyse(results)
        (out / "results.json").write_text(json.dumps(results, indent=1, default=str))
        (out / "REPORT.md").write_text(md := report(results, out, args))
        shutil.copy(out / "REPORT.md", HERE / "LATEST.md")
        print(md)
        return
    with httpx.Client(base_url=URL, headers={"Connection": "close"}) as cl:
        ensure_refs(cl)
    ref, ref_text = clone_ref(CLONE_VOICE)
    cases = build_cases(ref, ref_text)
    if args.only:
        cases = [c for c in cases if any(c["id"].startswith(p) for p in args.only)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = HERE / "runs" / stamp
    out.mkdir(parents=True)
    results = []
    # Connection: close — after a 500 the server drops the socket, and a reused
    # keep-alive connection surfaces as a spurious ECONNRESET on the next case.
    with httpx.Client(base_url=URL, headers={"Connection": "close"}) as cl:
        for i, c in enumerate(cases, 1):
            r = {"stream": run_stream_case, "abort": run_abort_case,
                 "concurrent": run_concurrent_case}.get(c.get("kind"), run_case)(cl, c, out)
            results.append(r)
            print(f"[{i}/{len(cases)}] {c['id']}: {r.get('status')} {r.get('latency_s')}s "
                  f"{(r.get('audio') or {}).get('duration_s', '')} {r.get('error', '')}", flush=True)
            (out / "results.json").write_text(json.dumps(results, indent=1, default=str))
    if not args.no_asr:
        transcribe(results)
    analyse(results)
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str))
    md = report(results, out, args)
    (out / "REPORT.md").write_text(md)
    shutil.copy(out / "REPORT.md", HERE / "LATEST.md")
    print(md)


if __name__ == "__main__":
    main()
