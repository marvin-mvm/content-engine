---
name: acme-skit
description: Recreate a multi-character talking-head skit (one actor as several "future selves") as a faithful AI copy with skit.py — Higgsfield Veo 3.1 image-to-video, native synced speech, real reference frames. Use when asked to recreate/clone a creator's talking skit or build an AI multi-character talking video. Config-driven (one .skit.json), credit-GATED (never spends without --go). This is a CAPABILITY path, not a brand path — recreations skip Acme compliance. Recipe + gotchas: docs/SKIT.md.
---

# acme-skit — multi-character talking-skit recreation (Veo 3.1)

Drives **`skit.py`**: one JSON spec (characters + per-shot line/duration/delivery/label) →
faithful talking clips via **Veo 3.1 `veo-3-1-fast`, `--image <real frame>`, native synced
speech** → normalized, top-labelled, concatenated skit. Full spec: **docs/SKIT.md**. Paths
relative to `acme/`.

**Capability test, NOT a brand post.** Recreations deliberately ignore Acme
compliance / research-audience rules (they govern on-brand content, not a copy of someone
else's video). Never publish a recreation as Acme without a separate compliance pass.
Boss wants this creator-skit format — memory `acme-boss-creator-skit-direction`.

## Stages (credit spend isolated + gated)

```bash
python3 skit.py probe    <spec>              # source + 5×5 contact sheet + whisper transcript   (0 cr)
python3 skit.py plan     <spec>              # resolve refs + FREE per-shot cost preview          (0 cr)
python3 skit.py shoot    <spec> --go         # upload refs, submit, poll, download shot_NN.mp4    (SPENDS)
python3 skit.py assemble <spec> [--subtitles]# normalize + labels (+subs) + concat + TG-compress  (0 cr)
```

→ `output/skits/<name>/…/<name>.mp4`. Example spec: `schemas/examples/future_self_demo.skit.json`
(the proven @creatordemo "Choosing Your Future Self" — 11 shots, 56s, ~155 clean credits).

## Hard rules

- **ASK before spending.** Always `plan` first, show Marvin the estimated total, then
  `shoot --go` only on his OK. `shoot` REFUSES without `--go` by design.
- **Verify each character's reference frame on the contact sheet BEFORE `shoot`** — a
  wrong `ref_ts` = whole batch reshot (the creator run wasted ~66 cr this way). Use `probe`.
- **Raw `higgsfield` CLI for generate/cost; the `higgsfield.py` wrapper only for
  upload/credits/job** (wrapper is stale for generate). Auth lapses when cron is paused →
  `higgsfield auth login` (Ultra, info@acmelabs.co).
- **NSFW filter is inconsistent** on muscular/tank-top subjects; flagged clips AUTO-REFUND
  (free) → `shoot` auto-retries (portrait refs + "wholesome/tasteful/fully dressed" cues help).

## Tuning
- **Length:** cut/shorten shots in the spec, then re-`plan` (you pay per generated second —
  trim at the spec, never in post). ~42s ≈ drop 3–4 beats or move 6s shots to 4s.
- **Subtitles:** `assemble --subtitles` burns each shot's line bottom-center.

Recipe, spec schema, and every gotcha: **docs/SKIT.md**. Memory: `acme-higgsfield-skit-recreation`.
