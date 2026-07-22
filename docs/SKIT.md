# SKIT.md — multi-character talking-skit recreation (Higgsfield Veo 3.1)

> Recipe for recreating a creator's talking-head skit — one actor playing multiple
> "characters" (e.g. present / unoptimized / optimized future selves) — as a faithful
> AI copy. Tool: **`skit.py`** (config-driven). Skill: **`acme-skit`**.
> First proven 2026-07-21 recreating @creatordemo *"Choosing Your Future Self"* (11 shots,
> 56s, 1080×1920, ~155 clean credits). Memory: `acme-higgsfield-skit-recreation`.

**This is a capability path, not a brand path.** Skit recreations are camera/likeness
capability tests — they deliberately **ignore Acme compliance / research-audience rules**
(those govern the on-brand posts, not a faithful copy of someone else's video). Do NOT ship
a recreation as an Acme post without a separate compliance pass.

## Why Veo 3.1 image-to-video (not the talking-avatar)

`higgsfield generate create veo3_1 --image <ref> --model veo-3-1-fast` does **native synced
speech** *and* takes a **real reference frame** as `--image` → faithful face + lip-sync.
~11 cr / 4s (~2.75 cr/s). The `marketing_studio_video` / `influencer` talking-avatar is
25cr/5s **and** only allows licensed stock avatars — building an avatar from an uploaded face
is BLOCKED ("URL must be from an allowed domain"). So Veo is both cheaper and the only
faithful path. The `higgsfield.py` **wrapper is stale** for generate (rejects `--avatar`,
needs unit'd `--timeout`); call the **raw `higgsfield` CLI** for generate/cost, the wrapper
only for `upload` / `credits` / `job`.

## The spec

One JSON file describes the whole skit — copy `schemas/examples/future_self_demo.skit.json`:

```json
{
  "name": "future_self_demo",
  "source_url": "https://www.instagram.com/reel/XXXX/",   // optional; only probe/extract needs it
  "aspect_ratio": "9:16", "model": "veo3_1", "model_variant": "veo-3-1-fast", "quality": "high",
  "base_prompt": "The man from the reference photo talks directly to the camera, casual handheld selfie video, eye-level medium close-up",
  "wardrobe": "wearing a white ribbed tank top with a small black clip-on lav microphone",
  "safety_cues": "wholesome, tasteful, fully dressed",
  "characters": {
    "P": { "ref_ts": 1,  "room": "plain room with a green wall" },     // extract frame @1s from source
    "U": { "ref_image": "output/skits/x/ref_u.png", "room": "wood-slat wall" },  // local png
    "O": { "ref_id": "59f72b4c-…", "room": "wood-slat wall" }          // already-uploaded media id
  },
  "shots": [
    { "char": "P", "line": "No, don't do it.", "dur": 4, "delivery": "holding a syringe, alarmed", "label": "Choosing Your Future Self" }
  ]
}
```

- **characters** — one entry per distinct on-screen self. Each needs exactly one reference:
  `ref_id` (already uploaded) **>** `ref_image` (local png) **>** `ref_ts` (extract from `source.mp4`).
  Keep the SAME `wardrobe` + per-char `room` across all that character's shots for continuity.
- **shots** — ordered; each is `char` + verbatim `line` + `dur` (4/6/8s) + `delivery`
  (emotion/action cue) + optional `label` (top-center on-screen title for that beat).
  `dur` is generation-only; Veo picks pacing — don't try to time speech to the second.

## Stages (credit spend is isolated + gated)

```bash
python3 skit.py probe    <spec>          # download source + 5×5 contact sheet + whisper transcript   (0 cr)
python3 skit.py plan     <spec>          # resolve refs + FREE per-shot `generate cost` preview        (0 cr)
python3 skit.py shoot    <spec> --go     # upload refs, submit Veo shots, poll, download shot_NN.mp4   (SPENDS)
python3 skit.py assemble <spec> [--subtitles]   # normalize + top-labels (+subs) + concat + TG-compress (0 cr)
```

- **`shoot` REFUSES without `--go`** (project rule: ASK before any Higgsfield credit). Always
  run `plan` first and show Marvin the estimated total; only `shoot --go` after his OK.
- Output → `output/skits/<name>/` : `source.mp4`, `contact_sheet.png`, `plan.json`,
  `refs.json`, `jobs.json`, `shot_NN.mp4`, and the final `<name>.mp4` (+ `<name>_tg.mp4` if >49MB).

## Gotchas (each cost real time/credits the first time)

- **VERIFY every character's `ref_ts` on the contact sheet BEFORE `shoot`.** The creator run
  grabbed the silver "optimized" guy at 22s thinking it was "present" → 5 shots reshot,
  ~66 cr wasted. `probe` exists precisely to eyeball the montage first.
- **NSFW filter flags muscular / tank-top subjects INCONSISTENTLY** (same ref passes some
  shots, fails others; one shot took 11 tries). Flagged/failed clips **AUTO-REFUND (free)** →
  `shoot` auto-retries up to `NSFW_RETRIES` (8). Keep refs **portrait** (a tight landscape
  crop triggers non-nsfw "failed"); `safety_cues` ("wholesome, tasteful, fully dressed") help.
- **Concurrency cap = 8** on Ultra → `shoot` retries rate-limited submits every 25s as slots free.
- **`generate cost` is FREE** and duration-driven — that's what `plan` sums.
- **ffmpeg here has NO drawtext/freetype** — labels & subtitles are PIL-rendered PNGs then
  `overlay`-ed (handled in `assemble`). whisper `base` fails (SSL cert on model download);
  only `tiny` is cached (used by `probe`).
- **Auth lapses** when cron is paused → `higgsfield auth login` (browser device-login;
  can't OAuth non-interactively). Account: info@acmelabs.co, **Ultra**. API exposes
  balance+plan only, not the monthly grant (internal note ~3000/mo → ~15–19 skits/mo).

## Tuning length / subtitles

- **Tighten to ~42s:** drop or shorten shots in the spec (fewer beats, or 4s instead of 6s);
  re-`plan` to see the new total, then `shoot`. Don't trim in post — you pay per generated
  second, so cut at the spec.
- **Burn-in subtitles:** `assemble --subtitles` renders each shot's `line` bottom-center.
