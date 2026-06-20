#!/usr/bin/env python3
"""reel_captions.py — F7 RV4: voice the reel + author its synced captions. 0 credits.

TTS voiceover path (Marvin 2026-06-18 — narrated, works sound-on AND sound-off, and we
OWN the script so the captions are exact):

  1. Kokoro TTS of brief.script           -> narration.wav     (hyperframes tts)
  2. mux narration over brief.video        -> voiced.mp4        (b-roll looped to the VO length)
     and point brief.video at the voiced clip (reel.py captions THAT)
  3. Whisper transcribe the narration      -> word timings      (hyperframes transcribe)
  4. RECONCILE the timings to brief.script — ground truth is the script we wrote, so there
     is no mis-hear fight: exact words, real boundaries.
  5. auto BEAT-GROUP (3-5 words/beat, <=2 lines, UNIFORM_CREAM; RUNBOOK §2) -> caption_data.json
  6. reel.py -> captioned.mp4 + branded cover

Usage:
  reel_captions.py <job_dir>                       # full TTS -> captioned reel
  reel_captions.py <job_dir> --voice am_michael --speed 1.0
  reel_captions.py <job_dir> --no-tts              # b-roll already carries the speech: transcribe it as-is
  reel_captions.py <job_dir> --skip-reel           # stop after caption_data.json (no render)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import engine as e

WS = Path(__file__).parent.resolve()
PY = sys.executable or "python3"
HF = ["npx", "--yes", "hyperframes@0.6.64"]
DEFAULT_VOICE = "am_michael"          # calm, authoritative — the Research-Pharmacist register

# Beat-grouping (RUNBOOK §2): conversational 3-5 words/beat, <=2 lines, one beat at a time.
BEAT_MIN, BEAT_MAX = 3, 5
PAUSE_BREAK = 0.4                      # a gap >= this (s) to the next word ends a beat early
SENT_END = re.compile(r"[.!?…]$")


def fail(msg: str) -> "NoReturn":
    sys.exit(f"[reel-captions] ERROR: {msg}")


def _run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


# ── 1. TTS ───────────────────────────────────────────────────────────────────
def tts(script: str, out: Path, voice: str, speed: float) -> None:
    script_file = out.parent / "script.txt"
    script_file.write_text(script)
    cmd = HF + ["tts", str(script_file), "--voice", voice, "--output", str(out)]
    if speed and speed != 1.0:
        cmd += ["--speed", str(speed)]
    r = _run(cmd, cwd=out.parent)
    if r.returncode != 0 or not out.exists():
        fail(f"hyperframes tts failed (need `pip install kokoro-onnx soundfile`):\n{(r.stdout + r.stderr)[-800:]}")
    e.log(f"TTS -> {out.name} (voice={voice})")


# ── 2. mux narration over the b-roll (loop ONLY if the b-roll is shorter than the VO) ──
def mux(broll: Path, narration: Path, out: Path) -> None:
    """Lay the narration over the b-roll, trimmed to the voiceover (-shortest). RV3 now stitches
    several distinct clips (~30s) so the b-roll usually COVERS the VO and plays straight through
    — no visible loop (Marvin 2026-06-19). We only re-enable -stream_loop as a fallback when the
    b-roll is shorter than the narration (e.g. some clips failed); that case is logged."""
    bdur, ndur = _duration(broll), _duration(narration)
    needs_loop = bdur > 0 and ndur > 0 and bdur < ndur - 0.05
    pre = ["-stream_loop", "-1"] if needs_loop else []
    r = _run(["ffmpeg", *pre, "-i", str(broll), "-i", str(narration),
              "-map", "0:v:0", "-map", "1:a:0", "-shortest",
              "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-movflags", "+faststart", "-y", str(out)])
    if r.returncode != 0 or not out.exists():
        fail(f"ffmpeg mux failed:\n{r.stderr[-800:]}")
    if needs_loop:
        e.log(f"b-roll ({bdur}s) shorter than VO ({ndur}s) — looped to fill (consider more/longer clips)")
    e.log(f"muxed narration over b-roll -> {out.name} ({'looped' if needs_loop else 'straight-through'})")


# ── 3. transcribe ────────────────────────────────────────────────────────────
def transcribe(media: Path, model: str = "small.en") -> list[dict]:
    """Whisper word timings. English script -> small.en is correct (skill rule 2)."""
    r = _run(HF + ["transcribe", str(media), "--model", model], cwd=media.parent)
    tj = media.parent / "transcript.json"
    if r.returncode != 0 or not tj.exists():
        fail(f"hyperframes transcribe failed:\n{(r.stdout + r.stderr)[-800:]}")
    words = json.loads(tj.read_text())
    if not isinstance(words, list) or not words:
        fail("transcribe produced no words")
    return words


# ── 4. reconcile Whisper words to the authored script (script = ground truth) ──
def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", (w or "").lower())


def reconcile(whisper: list[dict], script: str) -> list[dict]:
    """Replace Whisper's (possibly mis-heard) text with the EXACT script tokens, keeping
    Whisper's start/end boundaries. We wrote the script and the TTS spoke it, so a simple
    sequential alignment on normalized tokens is robust; unmatched script tokens inherit a
    proportional slice of the surrounding timing."""
    script_tokens = script.split()
    w_words = [{"text": w.get("text", ""), "start": float(w.get("start", 0)),
                "end": float(w.get("end", 0))} for w in whisper]
    # Fast path: same count -> pair 1:1 (exact text + real timing).
    if len(script_tokens) == len(w_words):
        return [{"text": t, "start": w["start"], "end": w["end"]}
                for t, w in zip(script_tokens, w_words)]
    # General path: greedy align by normalized token; carry script text, borrow timing.
    out, wi = [], 0
    for ti, tok in enumerate(script_tokens):
        nt = _norm(tok)
        match = None
        for j in range(wi, min(wi + 3, len(w_words))):   # look a little ahead
            if _norm(w_words[j]["text"]) == nt and nt:
                match = j
                break
        if match is not None:
            w = w_words[match]
            out.append({"text": tok, "start": w["start"], "end": w["end"]})
            wi = match + 1
        else:
            # No clean match: interpolate between neighbours so timings stay monotonic.
            prev_end = out[-1]["end"] if out else (w_words[wi]["start"] if wi < len(w_words) else 0.0)
            nxt = w_words[wi]["start"] if wi < len(w_words) else prev_end + 0.3
            mid = prev_end + (nxt - prev_end) * 0.5
            out.append({"text": tok, "start": round(prev_end, 3), "end": round(max(mid, prev_end + 0.05), 3)})
    return out


# ── 5. auto beat-grouping ────────────────────────────────────────────────────
def beat_group(words: list[dict]) -> list[dict]:
    """Group words into beats (3-5 words, sentence/pause aware), each split across <=2 lines.
    UNIFORM_CREAM is on, so every word is tier 'n' (emphasis tiers are dormant — RUNBOOK §2)."""
    beats, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        ends_sentence = bool(SENT_END.search(w["text"]))
        gap_next = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 99
        last = i == len(words) - 1
        flush = (len(cur) >= BEAT_MAX
                 or (len(cur) >= BEAT_MIN and (ends_sentence or gap_next >= PAUSE_BREAK))
                 or last)
        if flush:
            beats.append(_split_lines(cur))
            cur = []
    return beats


def _split_lines(idxs: list[int]) -> dict:
    """Balance a beat's words across <=2 lines (line1 the first half). 1-3 words stay on one
    line; 4-5 split. All tier 'n'."""
    if len(idxs) <= 3:
        return {"line1": [[i, "n"] for i in idxs], "line2": None}
    half = (len(idxs) + 1) // 2
    return {"line1": [[i, "n"] for i in idxs[:half]],
            "line2": [[i, "n"] for i in idxs[half:]]}


# ── 6. assemble + render ─────────────────────────────────────────────────────
def _duration(media: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(media)])
    try:
        return round(float(r.stdout.strip()), 2)
    except (ValueError, AttributeError):
        return 0.0


def main():
    ap = argparse.ArgumentParser(description="F7 RV4 — TTS voiceover + synced captions (0 credits)")
    ap.add_argument("job_dir")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"Kokoro voice (default {DEFAULT_VOICE})")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--model", default="small.en", help="Whisper model (script is English -> small.en)")
    ap.add_argument("--no-tts", action="store_true", help="b-roll already carries speech — skip TTS+mux, transcribe it as-is")
    ap.add_argument("--skip-reel", action="store_true", help="Stop after caption_data.json (no render)")
    args = ap.parse_args()

    job = Path(args.job_dir).resolve()
    brief = json.loads((job / "brief.json").read_text()) if (job / "brief.json").exists() else fail("no brief.json")
    if brief.get("type") != "reel":
        fail(f"brief type is {brief.get('type')!r}; reel_captions.py only handles type=reel")
    video = brief.get("video")
    if not video:
        fail("brief.video not set — run RV3 (reel_video.py) first")
    broll = (WS / video).resolve()
    if not broll.exists():
        fail(f"b-roll not found: {broll}")
    script = (brief.get("script") or "").strip()

    if args.no_tts:
        media = broll
    else:
        if not script:
            fail("brief.script not set — run RV2 (script.py) first")
        narration = job / "narration.wav"
        tts(script, narration, args.voice, args.speed)
        voiced = job / "voiced.mp4"
        mux(broll, narration, voiced)
        brief["video"] = str(voiced.relative_to(WS))   # reel.py captions the voiced clip
        (job / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        media = voiced

    whisper = transcribe(media, model=args.model)
    words = reconcile(whisper, script) if script else \
        [{"text": w.get("text", ""), "start": float(w.get("start", 0)), "end": float(w.get("end", 0))}
         for w in whisper]
    blocks = beat_group(words)
    caption = {"duration": _duration(media) or (words[-1]["end"] if words else 0),
               "uniform_cream": True, "words": words, "blocks": blocks}
    cap_name = brief.get("caption_data", "caption_data.json")
    (job / cap_name).write_text(json.dumps(caption, ensure_ascii=False, indent=2))
    e.log(f"caption_data -> {cap_name} · {len(words)} words · {len(blocks)} beats · {caption['duration']}s")

    if args.skip_reel:
        print(f"caption_data={job / cap_name}")
        return
    r = _run([PY, str(WS / "reel.py"), str(job)], cwd=WS)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        fail(f"reel.py render failed:\n{(r.stdout + r.stderr)[-800:]}")
    e.log(f"{job.name}: captioned reel + cover rendered")


if __name__ == "__main__":
    main()
