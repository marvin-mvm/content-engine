# Acme Production Pipeline — Runbook

> **What this is:** the proven, repeatable recipe for turning an existing video into a
> brand-compliant captioned reel, **plus every mistake we hit and how to avoid it.**
> Brand hard-rules live in [SOUL.md](SOUL.md) and the captions design system in
> [hyperframes-captions/design.md](hyperframes-captions/design.md) — this file does **not**
> duplicate them, it documents the *process*.
>
> **Status:** the **reel caption chain (M4→M5)** is proven (Phase A1, job ACME-007, Nova
> review, 0 Higgsfield credits) and **wrapped into a brief-driven runner** (`reel.py`, Phase A2
> — see §1.0). The **image chain (M5→M6)** is proven across all 5 template families and
> wrapped into `post.py` (Phase A3, 0 credits — see **§9**). The **M3 preflight gate**
> (`preflight.py`, Phase A4) is the hard wall that protects the single A5 credit spend — see **§10**.
>
> **First proofs:** reel → `output/jobs/ACME-007/` (Nova "Metabolic Support Stack" review);
> image → `output/jobs/ACME-008/` (Semaglutide compound feature), plus the A3 QC set in
> `output/a3_qc/` covering every template family.
>
> **NEW templates (2026-06-20):** the post-overlay template families (reel video-underlay, story
> product/poll, premium carousel) and their wiring status live in **[TEMPLATES.md](TEMPLATES.md)**.
> Headline change: **reels now carry the caption in a transparent template OVERLAY composited over
> the clean video (`produce.py --video-underlay`) — never burned in.** Details in TEMPLATES.md.

---

## 0. The chain (where this fits)

```
M1 brief.json → M2 copywriter.py → M3 visual(CREDITS) → M4 HyperFrames captions → M5 produce.py → M6 QC
                                                    └─ this runbook ─────────────┘
```

A1/A3 prove **M4→M6 on assets already owned** so that when M3 finally spends a credit, the
downstream is known-good. Everything below is **0 credits**.

---

## 1. Reel caption recipe (M4 → M5), step by step

All paths relative to `acme/`. Job ID = next `ACME-NNN` (check existing:
`grep -rhoE 'ACME-[0-9]{3}' content/ output/ ./*.md | sort -u`).

### 1.0 Fast path (A2) — brief-driven, one command

Once the beats are authored, the whole chain is **one command**:

```bash
python3 reel.py output/jobs/ACME-NNN          # captions + M5 cover
python3 reel.py output/jobs/ACME-NNN --skip-cover   # captions only
```

The job folder needs three things:
- **`brief.json`** — the M1 contract ([schemas/brief.schema.json](schemas/brief.schema.json); example: [schemas/examples/ACME-007.brief.json](schemas/examples/ACME-007.brief.json)). `brief.video` points at the source mp4; `brief.cover` carries the M5 cover tokens.
- **`caption_data.json`** — the authored beats:
  `{ "duration": <s>, "uniform_cream": true, "words": [{text,start,end}…], "blocks": [{line1:[[idx,"n|i|e"]…], line2:[…]|null}…] }`
- the source video at `brief.video`.

`reel.py` builds an isolated `_build/` copy of the captions project, injects the caption-data
block (between the `ACME-CAPTION-DATA` markers) + rewrites every `data-duration`, lint/validates,
renders `captioned.mp4`, then runs M5 (`produce.py --no-log` → `<job>-final.mp4` + `thumb.png`).
**No HTML editing.** The tracked `hyperframes-captions/` stays a clean, dev-renderable template
(its default data = ACME-007).

**What you still do by hand (the judgment reel.py can't do): transcribe + author
`caption_data.json`.** That's §1.2–§1.3 below; §1.4–1.6 are exactly what `reel.py` automates.

### 1.1 Set up the job + stage the source

```bash
mkdir -p output/jobs/ACME-NNN
cp "<source video>.mp4" hyperframes-captions/ava.mp4   # working copy lives IN the project
```
- Confirm it has an audio stream and note dims/duration:
  `ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,channels -of default=noprint_wrappers=1 <file>`
- 9:16 source (e.g. 720×1280) upscales cleanly to the 1080×1920 composition.

### 1.2 M4a — Transcribe (Whisper, word-level)

```bash
cd hyperframes-captions
npx --yes hyperframes@0.6.64 transcribe ava.mp4 --model small   # → transcript.json
```
- **Model rule (non-negotiable):** never use a `.en` model unless the audio is *explicitly*
  stated English — `.en` models **translate** non-English instead of transcribing. Default to
  `--model small` (auto-detects). First run downloads ~466 MB (cached in `~/.cache/hyperframes/`).
- Read `transcript.json` and **reconcile mishears against the known script** — keep the Whisper
  timings, fix the words. (ACME-007: Whisper heard **"Avera"** → corrected to **"Acme"**.)

### 1.3 M4b — Author the composition

Two files in `hyperframes-captions/`:

- **`index.html`** (root "main" composition) holds: `#bg-video` (muted) + `#bg-audio` +
  `#scrim` + the caption sub-comp embed. Portrait `data-width="1080" data-height="1920"`,
  `data-duration` = video length.
- **`compositions/components/caption-editorial-emphasis.html`** is the **transparent
  captions-only overlay** — it owns the `W[]` transcript array, the `BLOCKS[]` beat layout,
  and the GSAP timeline.

Edit per job:
1. `data-duration` (both files) = source duration (ACME-007 = `15.09`).
2. Replace `W[]` with the reconciled transcript (`{text,start,end}` per word).
3. Hand-build `BLOCKS[]` — the **Claude-judgment** part (§2).
4. Leave fonts/colors/positioning as-is (they're brand-locked, §3).

### 1.4 M4c — Validate, then render

```bash
cd hyperframes-captions
npm run check        # lint + validate + inspect — fix ALL errors; contrast warnings are advisory (§4)
npx --yes hyperframes@0.6.64 render --output ../output/jobs/ACME-NNN/captioned.mp4
```

### 1.5 M5 — Branded cover + embed (produce.py)

```bash
cd ..   # back to acme/
python3 produce.py templates/src/story-reel-dark.html output/jobs/ACME-NNN/ACME-NNN-final.mp4 \
  --video output/jobs/ACME-NNN/captioned.mp4 \
  --no-log \
  --set BRAND_NAME="ACME LABS" --set EYEBROW="RESEARCH USE ONLY" \
  --set HOOK_LINE_1="..." --set "HOOK_LINE_2_ITALIC=..." --set HOOK_LINE_3="..." \
  --set "SUBTITLE_TEXT=..." --set CTA_LABEL="READ THE COA" --set HANDLE="@acmelabs"
mv output/story-reel-dark-*-thumb.png output/jobs/ACME-NNN/thumb.png
```
- `produce.py --video` renders the template as a **branded cover/poster** and embeds it as the
  mp4's `attached_pic` — it does **not** alter the visible video. Also emits a standalone
  `thumb.png` (for Blotato later).
- **Always `--no-log` for test/validation renders** — otherwise it writes a "Generated" row to
  OpenClaw's *live* Content Matrix sheet. (Real posts later: omit `--no-log`.)
- `produce.py --tokens <template>` lists a template's placeholders.

### 1.6 M6 — Visual QC (see §5 checklist)

Extract frames from the rendered mp4 and **look at them** (one per beat + motion-check points):
```bash
for t in 1 2.5 4.7 7.7 9 12.5 14.95; do
  ffmpeg -v error -ss $t -i output/jobs/ACME-NNN/captioned.mp4 -frames:v 1 -y output/jobs/ACME-NNN/render_frames/out_${t}s.png
done
```

---

## 2. Caption authoring judgment (the part automation can't do)

> **CAPTION STYLE = ALL-CREAM UNIFORM** (decided 2026-06-17, Operator). `UNIFORM_CREAM = true`
> in the component → every word DM Sans 600 cream, one size, no green, no hero words. So the
> emphasis-tier judgment below is **dormant** unless green is re-enabled. Green emphasis stays
> on designed templates/covers, not talking-head captions. (Pending SOUL.md amendment at
> cutover — see §8.) You still do beat grouping; you just don't pick emphasis words.

- **Beat grouping:** break on sentence boundaries / 150 ms+ pauses; conversational = 3–5 words;
  max 2 lines; one beat visible at a time. ACME-007 = 37 words → 11 beats.
- **Emphasis tiers** (only if `UNIFORM_CREAM = false`):
  - `n` normal — DM Sans 600, Warm Cream `#F2EDE4`.
  - `i` inline accent — Cormorant Garamond 700 Italic, Accent Green `#3D9E6E` (~same size).
  - `e` hero — large Cormorant italic green (172px), for the 2–3 biggest moments only.
  - One green accent per beat max; pick brand/CTA/verdict words.
- **Captions mirror the spoken audio verbatim** — never invent claims (compliance).
- `BLOCKS[]` format: `{ line1: [[wordIdx, "n|i|e"], ...], line2: [...] | null }`. Block shows
  from its first word's start until the next block's first word; words pop at their own `start`.

---

## 3. Brand-locked composition specifics (don't re-derive)

- **Portrait 1080×1920.** Caption safe-zone: `top:1260 left:70 width:940 height:560`
  (lower-middle, ~600–700px from bottom per design.md). `SAFE_WIDTH = 940`.
- Fonts: **DM Sans** (body, embedded locally via `@font-face` from `fonts/*.woff2` — NOT a
  Google link), **Cormorant Garamond** (emphasis, HyperFrames built-in — declaring the family
  is enough), **DM Mono** (labels). Never substitute.
- Colors: forest `#1A2E1E`/`#2D6A4A`, accent green `#3D9E6E` (emphasis ONLY), cream `#F2EDE4`,
  sage `#C8DDD0`. No gold/yellow/amber/purple/pink/red/orange/neon.
- **Contrast scrim** lives in `index.html` (root), NOT baked into the reusable caption
  component — bottom Deep-Forest gradient.
- **Word legibility** over footage = dark faux-outline (4-way `text-shadow`) + soft drop shadow
  on `.word`, on top of the scrim.
- Motion: normal words **scale-pop** (0.12s); hero words **fade + rise + scale settle** (0.24s,
  `back.out(1.5)`). See §4 for why NOT a horizontal slide.

---

## 4. Gotchas & fixes — the mistakes we hit (READ BEFORE NEXT JOB)

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | `validate` → `TypeError: Illegal invocation` at composition init | A self-lint loop calling `tl.seek()` + `window.getComputedStyle()` synchronously during init | **Don't** add that self-lint. The hard `tl.set({opacity:0, visibility:"hidden"}, beatEnd)` kills already guarantee exits. |
| 2 | 50–70 **WCAG contrast warnings** that won't clear (green words ~1.2:1) | The audit samples **flat background pixels vs text color only** — it **cannot see** `text-shadow`/outline, and green is mid-luminance so it never clears 3:1 over bright video | Treat as **advisory**, not blocking. Real legibility = scrim + dark outline, **verified visually** in rendered frames. Don't darken the scrim to opacity just to satisfy the tool. |
| 3 | Render warning: `bg-video has sparse keyframes … frame freezing` | Source encoded with keyframes seconds apart (ACME-007: only at 0/5/12.75s) | **Verify** the background actually animates (extract frames across a keyframe gap and compare). ACME-007 was fine. If it *does* freeze, re-encode the source first: `ffmpeg -i in.mp4 -c:v libx264 -r 30 -g 30 -keyint_min 30 -movflags +faststart -c:a copy out.mp4`. |
| 4 | Hero emphasis word **clipped at the left frame edge** in a still, and the **final word barely settled** before the video ended | Hero words used a horizontal slide-in from off-frame-left (`x:-420`); a late word is still mid-slide (partly off-frame) when the clip ends | **No horizontal slide for hero words.** Use fade + small rise (`y:22→0`) + scale (`1.12→1`) — never leaves the frame, settles fast even on the last beat. |
| 5 | `produce.py` writes a bogus row to the live Content Matrix | Default behavior logs every render | **`--no-log` on all test/validation renders.** |
| 6 | Captions wouldn't carry audio / video unmuted errors | HyperFrames requires muted `<video>` + a **separate `<audio>`** element (same `src`) | Put both in the **root** `index.html` (video track 0, audio track 1); keep the caption component a transparent overlay. |
| 7 | Sub-composition video quirks | Scaffold shipped `bg-video` *inside* the caption component | Cleaner + more robust to host video/audio/scrim in the **root** and make the component captions-only. |

---

## 5. M6 QC checklist (SOUL §21)

- [ ] Palette only forest / cream / sage / **one** accent green
- [ ] Brand mark present (cover: leaf badge + BRAND_NAME)
- [ ] Fonts correct (DM Sans / Cormorant Garamond italic / DM Mono)
- [ ] **RUO line on Labs product posts** (`For research use only` — cover eyebrow and/or footer; captions mirror it if spoken)
- [ ] Correct format/aspect (9:16, 1080×1920)
- [ ] Captions legible over the actual footage (check the busy/bright frames)
- [ ] No banned claims (`treats/cures/heals/fixes/proven to/guaranteed`); research framing only
- [ ] Hero words land cleanly (no edge clipping, settled before cuts)
- [ ] Background animates (no freeze) end to end

---

## 6. Job folder layout (`output/jobs/ACME-NNN/`)

```
captioned.mp4        # M4 output — captioned reel
ACME-NNN-final.mp4   # M5 output — captioned + embedded branded cover poster
thumb.png            # M5 — standalone branded cover card (Blotato thumbnail)
transcript.json      # Whisper word-level transcript (record)
render_frames/       # QC frames extracted from the rendered mp4 (scratch)
frames/              # source frames used to calibrate the scrim (scratch)
```
`output/` is gitignored — these are regenerable artifacts. The **composition source**
(`hyperframes-captions/index.html` + the component) IS tracked; commit it once the look is
signed off.

---

## 7. Per-job knobs (what changes next time vs what stays)

**Changes per job (all data, no code):** `brief.json` + `caption_data.json` + the source video.
**Stays (the engine/template):** the composition (`hyperframes-captions/`), dims, safe-zone,
fonts, colors, scrim, outline, motion timings — `reel.py` injects per-job data into an isolated
build copy and never edits the tracked template.

> ✅ **A2 done:** `reel.py` drives `words`/`blocks`/`duration`/`uniform_cream` from
> `caption_data.json` and the cover from `brief.cover` — no hand-editing. ✅ **A6 done:**
> wrapped as the `acme-reel` Claude Code skill (`.claude/skills/acme-reel/`).

---

## 8. Style decisions

- ✅ **RESOLVED 2026-06-17 (Operator): captions = ALL-CREAM uniform** (`UNIFORM_CREAM=true`). No
  green, no hero words, consistent the whole video. Cleaner + clears WCAG. ⚠️ This deviates
  from SOUL.md's documented green "signature editorial emphasis" — SOUL.md is frozen during
  the migration, so the formal brand-book amendment is a **cutover-era action** (worth Devon's
  nod since it's the signature). Green emphasis is retained on designed templates/covers.
- Still open (minor, tune anytime): caption alignment (currently **left-aligned editorial**)
  vs centered; exact band height (~66–80%); cover-card copy tone.

---

## 9. Image pipeline (M5 → M6) — the A3 recipe

> **What this is:** the image analogue of §1. Render any of the 5 brand template families
> to a brand-correct PNG (or carousel slide set) at **0 Higgsfield credits**, then visually QC.
> Proven Phase A3 across all families. Brand hard-rules stay in [SOUL.md](SOUL.md) §21.

### 9.0 Fast path — brief-driven, one command (`post.py`)

The image analogue of `reel.py`. A job folder needs one file — `brief.json` with `type:"image"`:

```bash
python3 post.py output/jobs/ACME-NNN          # render from the brief (--no-log)
python3 post.py output/jobs/ACME-NNN --log    # also write the Content Matrix row (real posts)
```

`brief.image` contract (schema: [schemas/brief.schema.json](schemas/brief.schema.json);
examples: [ACME-008.image.brief.json](schemas/examples/ACME-008.image.brief.json) single ·
[ACME-009.carousel.brief.json](schemas/examples/ACME-009.carousel.brief.json) carousel ·
[ACME-010.reuse.brief.json](schemas/examples/ACME-010.reuse.brief.json) reuse-bg):

```json
"image": {
  "template": "templates/src/static-compound-dark.html",
  "bg_policy": "plain | reuse",            // NEVER generate — post.py refuses it (0 credits)
  "source_asset": "asset_cache/foo.png",   // required iff reuse; aspect must match the template
  "carousel": "slides.json",               // optional -> one PNG per slide (plain only)
  "set": { "COMPOUND": "Semaglutide", ... } // tokens; get them via produce.py <tpl> --tokens
}
```

Writes `<job>/<job_id>.png` (single) or `<job>/<job_id>-slide-NN.png` (carousel). `post.py`
runs `produce.py --no-log` by default, so test renders never touch OpenClaw's live sheet.

### 9.1 Manual path (what post.py automates)

```bash
# plain (template-only baked bg — the DEFAULT for most posts):
python3 produce.py templates/src/static-compound-dark.html out.png --no-log \
  --set COMPOUND="Semaglutide" --set CLASS_CHIP="GLP-1 ANALOG" --set RUO_LINE="RUO · NOT FOR HUMAN CONSUMPTION" ...
# reuse (existing local asset under the template — NEVER --bg-prompt, that fires Higgsfield):
python3 produce.py templates/src/story-reel-light.html out.png --no-log \
  --bg-file asset_cache/url_fbaa....png --set ...
# carousel (one PNG per slide):
python3 produce.py templates/src/carousel-dark.html --no-log --carousel slides.json --set BRAND_NAME=... --set HANDLE=...
```
`produce.py <template> --tokens` lists a template's placeholders. Pull facts from
[PRODUCTS.md](PRODUCTS.md); keep RUO framing.

### 9.2 The 5 families + correct aspect (verify the PNG size every time)

| Family | Templates | Native size | Notes |
|---|---|---|---|
| Story-reel | `story-reel-{dark,light}.html` | 1080×1920 (9:16) | hook + subtitle pill + CTA; cover for reels |
| Story-poll | `story-poll.html` | 1080×1920 (9:16) | A/B pills; centre reserved for IG poll sticker |
| Carousel | `carousel-{dark,light}.html` | 1080×1350 (4:5) | multi-slide via `--carousel`; slide-num + swipe label auto |
| Static callout | `static-callout-{dark,light}.html` | 1080×1080 (1:1) | one big DM Mono stat + source citation |
| Static compound | `static-compound-{dark,light}.html` | 1080×1350 (4:5) | product feature; **RUO + class chip + COA chip** |

### 9.3 M6 QC — same §5 checklist, image specifics

Read every PNG (and `python3 -c "from PIL import Image; print(Image.open(p).size)"` the
dimensions) against [SOUL.md](SOUL.md) §21: palette forest/cream/sage + one accent green ·
brand bar + leaf badge present · DM Sans / Cormorant Garamond italic / DM Mono only · **RUO
line + class/COA chips on Labs product posts** · correct aspect · legible · no banned claims.

> **Green stays on designed templates.** The all-cream rule is **captions-only** (§2/§8).
> The green Cormorant-italic emphasis line (`HOOK_LINE_2_ITALIC`, `HEAD_2_ITALIC`,
> `DESCRIPTOR`) is **required and correct** on every template/cover. Do NOT strip it.

### 9.4 Gotchas (READ BEFORE NEXT IMAGE JOB)

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| I1 | Carousel/callout/compound render at **1080×1920 with a white band** below the card | `render.py detect_size` regex `[^;"]` couldn't cross the `;` in `width:Npx; height:Mpx`, so every non-9:16 template fell back to the 1080×1920 default | **Fixed in A3** (`\s*;?\s*` separator). If a new template renders too tall, check `detect_size` matches its `body { width:…; height:… }`. |
| I2 | Reuse-bg looks cluttered / doubled text (e.g. callout `5MG` over a product vial that already says `5MG`) | A **product hero is dynamic, per-SKU content** — it is the post, not a background | **Reuse backgrounds = generic brand b-roll / textures only** (e.g. the light science b-roll `url_fbaa…`, 9:16), with open negative space and no burned-in text or faces. **Never** use a finished product-hero / spokesperson render as a `--bg-file` (decided 2026-06-17, Operator). Match aspect to the template. |
| I3 | `produce.py --carousel` ignores the positional output path | Carousel mode always writes `output/<stem>-<ts>-slide-NN.png` | `post.py` relocates the latest run's slides into the job folder; don't pass an output path in carousel mode. |
| I4 | Reuse + carousel produces no bg | `produce.py --carousel` renders text cards with **no** bg injection | Carousels are plain-only by design; `post.py` rejects `reuse`+`carousel`. |
| I5 | `produce.py --bg-prompt` would **spend a Higgsfield credit** | That flag calls `higgsfield_generate` | A3 is plain/reuse only. `post.py` refuses `bg_policy: generate` outright. The only credit spend in the whole plan is A5. |

### 9.5 Brand decisions resolved in A3 (2026-06-17, Operator)

- ✅ **story-poll now carries the brand bar** — SOUL is the source of truth ("brand bar on
  **every** template, every story"), so the poll template was brought into compliance: a
  top-right leaf badge + `ACME LABS` wordmark and an `@acmelabs · acmelabs.co` footer.
  Text is hardcoded (not a token) so existing renders that don't pass `BRAND_NAME` stay
  correct; tokenize at A6 if a Health poll is ever needed. All 5 families are now brand-bar
  compliant.
- ✅ **Reuse-bg = generic brand b-roll only.** Product/spokesperson heroes are **dynamic,
  per-SKU content** — they are generated as the post itself, never used as a `--bg-file`
  background (see gotcha I2).

---

## 10. Preflight gate (M3) — the hard wall before any Higgsfield spend (A4)

> **What this is:** `preflight.py` — the mandatory pre-submit check that protects the **only**
> credit spend in the plan (A5). It validates the *generation plan*, so it guards **every**
> route (raw `higgsfield image/video`, `ms-dtc`, `product-photoshoot`, `produce.py --bg-prompt`).
> **Standalone** by design (decided 2026-06-17, Operator): it does **not** modify the shared
> OpenClaw scripts, so the live system is untouched. It **never** calls a generator — the only
> network it does is a best-effort, non-fatal `generate list` **read** for the reuse inventory.
> A6 will wrap it as the `acme-preflight` skill.

**The contract:** ANY failed check → **exit 1**, reasons printed to stderr, **stdout stays
empty** (no go-token). All checks pass → **exit 0** + `PREFLIGHT-OK` printed to stdout. So the
submit step can hard-gate on the token; nothing can mistake a block for a pass. ✅ **A6 done:**
wrapped as the `acme-preflight` Claude Code skill (`.claude/skills/acme-preflight/`).

### 10.1 The checks (all must pass — `python3 tests/test_preflight.py` proves block + pass)

1. **bg_policy honored** — `plain`/`reuse` → BLOCK (render free / `--bg-file`, 0 credits); only `generate` proceeds.
2. **Brand Prompt Block prepended verbatim** — IMAGE block for `image`/`dtc`/`product`, VIDEO block for `video`. The submitted prompt must `startswith()` it exactly.
3. **No rendered text in the prompt** — flags `text/caption/headline/…` and any quoted literal in the *creative* part (after `::`); negations ("no text") are allowed. Text is burned in at M4/M5.
4. **Correct route** — person/Nova/UGC/ad content on a raw `image`/`video` route → BLOCK (use `--route dtc`); product photography → `--route product`; medium↔model mismatch (e.g. `seedance_2_0` on an image route) → BLOCK.
5. **Aspect matches template** — 9:16 story · 4:5 carousel/compound · 1:1 callout (or a valid ratio when no template is given).
6. **Video → `--no-wait`** — video jobs never block on `--wait` (SOUL §17).
7. **Reuse check acknowledged** — requires `--reuse-checked`; the gate first prints the `asset_cache/` + completed-jobs inventory (incl. the Metabolic Support Stack job `7d01b600-…`) so the ack is informed.

### 10.2 How to run it (the A5 pre-submit step)

```bash
# 1. Build the prompt so the brand block is verbatim BY CONSTRUCTION:
P="$(python3 preflight.py --print-block image) cold-chain peptide vial on a deep-forest \
surface, soft side lighting, generous negative space, editorial product still"

# 2. Gate the plan. Only submit if it exits 0 / prints PREFLIGHT-OK:
python3 preflight.py --route image --model gpt_image_2 --aspect 9:16 \
  --template templates/src/story-reel-dark.html --bg-policy generate --reuse-checked \
  --prompt "$P"  &&  echo "→ clear to call higgsfield"   # only runs on PASS

# Video b-roll (note --no-wait is mandatory):
V="$(python3 preflight.py --print-block video) clinical lab b-roll, slow dolly across vials"
python3 preflight.py --route video --model seedance_2_0 --aspect 9:16 --no-wait \
  --reuse-checked --prompt "$V"
```

`--print-block image|video` emits the exact block so you never hand-paste it. The gate is
0-credit; **A5 is the only place a real `higgsfield generate` runs, and only after this passes.**

---

## 11. Publishing to Blotato (F1) — `publish.py`, one command (built 2026-06-17)

> **Status:** the publish flow is **proven end-to-end** (ACME-011 BPC-157 carousel → **X live**
> + **TikTok scheduled**, Operator signed off) **and now wrapped into the one-command module
> `publish.py`** with a hard pre-publish compliance gate (§11.5). §11.1–11.3 below document the
> underlying `blotato.py` flow + the platform limits; §11.5 is the runner that drives it.

### 11.1 The flow that works

```
job folder PNGs  →  blotato.py upload <file>  →  public URL  →  blotato.py publish (per platform)
   (local)            (presigned PUT)            (mediaUrls)      X / TikTok, immediate or --schedule
```

1. **Upload each media file** (the bridge — `create_post` needs PUBLIC urls, our renders are local):
   `python3 blotato.py upload output/jobs/ACME-NNN/ACME-NNN-slide-01.png` → prints a public URL.
2. **Publish per platform** with the right treatment + `--dry-run` FIRST to verify the payload:
   ```bash
   # X (Twitter) — single opinion tweet, cover image, 0 hashtags:
   python3 blotato.py publish "<≤280-char opinion>" --account-id 18688 --platform twitter --media-url <coverURL>
   # TikTok — photo carousel, scheduled, public, AI-flagged (defaults applied automatically):
   python3 blotato.py publish "<caption + 3–5 hashtags>" --account-id 43061 --platform tiktok \
     --media-url <s1> --media-url <s2> ... --media-url <s5> --schedule 2026-06-17T20:53:39Z
   ```
   Connected accounts: **TikTok 43061 · X/Twitter 18688 · YouTube 37252** (`@acmelabs`). Instagram
   NOT connected yet (Operator's manual Blotato step). Get current IDs: `blotato.py accounts`.

### 11.2 `blotato.py` changes made in F1 (backward-compatible; OpenClaw still works)

- **`upload FILE`** — new: presigned-URL PUT → prints `publicUrl`. The missing local→public bridge.
- **`--dry-run`** on publish — prints the exact payload, posts nothing. **Use it every time** (it
  caught a real empty-`mediaUrl` bug pre-flight, see P5).
- **Bug fixes:** `scheduleTime` → **`scheduledTime`** (scheduling silently no-op'd before);
  `post-status` arg `id` → **`postSubmissionId`**.
- **TikTok required fields** auto-applied (privacyLevel=PUBLIC_TO_EVERYONE, isAiGenerated=true,
  isYourBrand=true, the rest false) + `--privacy-level` override.
- **`--also TEXT`** (repeatable) → `additionalPosts` (thread; **chains correctly on X**). Currently text-only per follow-up — see P1 to add a per-post image.

### 11.3 Findings & gotchas (READ BEFORE NEXT PUBLISH)

| # | Finding | Detail / fix |
|---|---------|--------------|
| P1 | **X thread follow-ups had no image** | The thread **chains correctly** on X (earlier "doesn't chain" read was WRONG — Operator confirmed the thread posted). The real gap: `blotato.py --also` passes **text only**, so follow-up tweets carried no media. Blotato's `additionalPosts` supports `{text, mediaUrls}` per post → **attach a slide image to each follow-up**. Enhancement: extend `--also` to carry per-post media (e.g. paired `--also-media`). |
| P2 | **YouTube = video uploads only** | Blotato's YouTube needs `title`+`privacyStatus` (video). **No community/image posts** — a still-image carousel cannot go to YouTube. YouTube is for the video pipeline. |
| P3 | **No first-comment field** | Blotato `create_post` has no first-comment param. SOUL wants 20–30 hashtags in the first comment on IG/TikTok → for now **hashtags go in the caption body** (TikTok 3–5; X 0). Revisit if Blotato adds it. |
| P4 | **Can't delete a published post** | Blotato has `delete_schedule` (scheduled only), no delete-published API. A bad live post must be removed **manually on the platform**. → dry-run + visual check before going live. |
| P5 | **Shell arrays are 1-indexed here** | `${U[0]}` was empty → an empty `mediaUrl` + a dropped slide. `--dry-run` caught it. Use explicit per-file vars, not `${arr[0]}`. |
| P6 | **`published`≠fully posted** | A `200/published` from `create_post` confirms only the MAIN post. **Visually verify** the live post (thread/carousel) — the API won't tell you a sub-post failed. |

### 11.4 Still to build

Instagram/Threads/Facebook **Blotato connection** (Operator's manual step — `publish.py` skips them
with a warning until connected); per-post **thread images** on X (`blotato.py --also` is text-only,
finding P1); **post-status tracking**; **Supabase** `published_posts` (F-series — `publish.py`
currently records to `<job>/published_posts.json`). ✅ **Done in F1:** `publish.py` runner +
compliance gate (§11.5), `copywriter.py` per-platform captions (bug #2 — `x/threads/facebook/linkedin`).

### 11.5 `publish.py` — the one-command publisher (F1)

> **What this is:** job folder → upload each media file via `blotato.py` → publish per platform
> with the right treatment + scheduling. **DRY RUN BY DEFAULT** (prints every `blotato.py` call,
> makes **zero** network calls); `--go` actually posts. A hard **compliance gate** runs in *both*
> modes — `--go` cannot bypass it. 0 Higgsfield credits.

```bash
# DRY RUN (default) — prints the exact upload + publish commands, posts nothing:
python3 publish.py output/jobs/ACME-NNN
python3 publish.py output/jobs/ACME-NNN --platforms x,tiktok --when 2026-06-18T16:00:00Z
# UPLOAD-ONLY — real upload of the media to Blotato, posts NOTHING (pre-stage / safe test):
python3 publish.py output/jobs/ACME-NNN --upload-only
# GO LIVE (irreversible — needs Operator's explicit OK; verify each post visually after):
python3 publish.py output/jobs/ACME-NNN --platforms x,tiktok --go
```

> **Runner validated 2026-06-18 (0 public posts):** compliance gate (block+pass), command
> construction + scheduling + platform skips (dry-run), result recording vs the real ACME-011
> Blotato responses (unit), and the **live upload path** end-to-end via `--upload-only` (5 slides
> → real public URLs, HTTP 200, cached). Only the literal `blotato.py publish` call is unexercised
> by the runner — proven separately by the manual ACME-011/012 publishes. **Meta (IG/Threads/FB)
> connection deferred** (accounts under review) — `publish.py` skips them with a warning; X+TikTok
> are the live channels meanwhile.

**Job folder inputs:** `brief.json` (type/brand/platforms) · **`qc.json`** `{"passed": true}`
(the M6 sign-off marker — REQUIRED) · **`captions.json`** (one unique caption per platform —
contract + example: [schemas/examples/ACME-011.captions.json](schemas/examples/ACME-011.captions.json))
· media (`<job>-final.mp4` for reels; `<job_id>.png` / `<job_id>-slide-*.png` for images).

**`captions.json` shape:** keyed by brief platform-name; each value is a **string** (single post)
or an **object** `{text, thread[], title}`. X carries its thread in `thread[]` (→ `blotato.py
--also`); YouTube carries `title`. Authored by `copywriter.py --platform <p>` (one per platform).

**The compliance gate (hard wall — any fail → exit 1, publish nothing):**

| Check | Rule |
|---|---|
| QC-pass flag | `qc.json` present with `passed: true` |
| RUO | **every Labs-brand caption** carries the RUO line (line may sit anywhere in the post/thread) — decided strict 2026-06-17 (Operator): all Labs posts, not just product-features |
| Labs = organic | Labs is never paid/boosted (no paid path exists; guards a future flag) |
| Banned claims (RED) | **`compliance.py`** (single Red/Yellow/Green authority — `compliance.red_hits`) across caption + every thread post: heal/cure/treat/prevent/diagnose/reverse, "burns fat"/"builds muscle"/"regrows hair"/"boosts testosterone"/"repairs tendons", customer-directed "…your skin", testimonials, "for human/personal use", miracle/proven-to/guaranteed (all tenses; negation-aware). copywriter.py scans slides + warns with "say instead"; YELLOW efficacy verbs need research-subject framing |
| Media | each file exists + aspect matches (carousel 4:5 · callout 1:1 · compound 4:5 · reel 9:16) |
| X shape | each X post (main + each thread post) ≤280 chars **and** 0 hashtags (§1A.4) — decided hard-block 2026-06-17 |

**Routing:** X→twitter `18688` · tiktok `43061` · youtube `37252`. Instagram/Threads/Facebook =
**skipped with a warning** (not connected). YouTube = **skipped for image jobs** (video only, P2).
**X carousel → slide-per-tweet THREAD** (each slide = one tweet, image on each — the guide's
treatment); a single-image X job posts up to 4 images in one tweet. TikTok/IG get the **full carousel**.

> **✅ RESOLVED 2026-06-18 — X carousel = slide-per-tweet thread (Devon's guide).** Was: cover image
> only (`media_urls_for` → `all_urls[:1]`, "ACME-011 treatment"), which contradicted the guide
> (CONTENT_ENGINE_GUIDE §3.4 "each carousel slide → a tweet"; SOUL §6). Now a carousel posts as a
> THREAD, one tweet per slide with its own image: (1) `produce_daily.build_x_thread` authors
> `captions.json["x"] = {text, thread[]}` from `slides.json` (hook leads; RUO + COA link on the
> last tweet; every tweet ≤280 / 0 hashtags), (2) `publish.media_urls_for`/`thread_media_for` put
> the cover on the lead tweet and slide *i+1* on thread post *i*, (3) `blotato.py --also-media`
> makes `additionalPosts` carry `{text, mediaUrls}` per post (was text-only — the old F1 gap).
> Proven on ACME-018 (Epithalon) + ACME-019 (BPC-157). Non-carousel X posts are unchanged.

**Records:** successful `--go` runs append to `<job>/published_posts.json` (Supabase is F-series).
Uploaded URLs cache to `<job>/uploaded_urls.json` so re-runs don't re-upload (`--reupload` forces).

---

## 12. Video reel recipe (M3 generation → M4–M6) — A5, the credit-spend path

> **What this is:** the AI b-roll video path the preflight gate (§10) protects — the ONE place
> credits are spent. **Proven A5** (ACME-012, BPC-157 b-roll reel): one real `seedance_2_0`
> generation → 9:16 fix → HyperFrames captions → branded cover → QC. 1 generation = 1+ credits.

### 12.1 The flow
1. Brief (`type=reel`) + a b-roll **creative** prompt — **no people, no text** (text is burned in M4).
2. **Preflight gate (§10)** — `route=video`, VIDEO block verbatim, `--no-wait`, `--reuse-checked`. Submit ONLY on `PREFLIGHT-OK` (the gate command literally guards the spend via its exit code).
3. **Generate:** `python3 higgsfield.py video "$(preflight.py --print-block video) <creative>" --model seedance_2_0 --no-cinematic --no-wait` → returns a job id.
4. **Poll:** `higgsfield generate get <FULL-UUID>` (the 8-char display prefix is NOT a valid id — use the full UUID).
5. **Download** `result_url` → **crop to 9:16** (§12.3).
6. **Author `caption_data.json` to the REAL duration** (`ffprobe` the clip first), then `reel.py <job>` → captioned + cover.
7. **M6 QC** (§5).

### 12.2 Gotchas (the A5 findings — READ BEFORE NEXT VIDEO)
| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| V1 | submit traceback: `'str' object has no attribute 'get'` | `generate create … --json` returns the new job id as a **bare string**, not an object | **FIXED** (`higgsfield.py _handle_job_result` normalizes a string → `{"id": …}`). |
| V2 | re-ran the submit → **DOUBLE SPEND** | after V1's crash, `generate list` doesn't show brand-new **pending** jobs, so it looked like "no spend" → re-run | **Confirm a submit via `generate get <uuid>` / job status, NEVER via `generate list`.** Every `video` call spends — never re-run to "retry" without checking the job first. |
| V3 | seedance returned **16:9** (1280×720), not 9:16 | `seedance_2_0` ignores aspect (both the flag and prompt-baked) | Crop locally for **free** (§12.3), or budget a Higgsfield `reframe` (costs). |
| V4 | generated green leans **teal/cyan** | model interpretation of "green" | Prompt-tune: "warm forest green #3D9E6E, **NOT** teal/cyan." Minor — QC visually. |
| V5 | **narrator says a different number than the on-screen caption** (ACME-041: caption `2.5%` / `1.9%`, the VO said "5%" / "9%") | Kokoro TTS voices a decimal as **separate cardinals** — it reads `2.5%` as "two … five percent", which at speech pace is heard as "five percent". The caption is `brief.script` and is correct; only the **audio** diverged. | **FIXED** — `reel_captions.tts_normalize()` spells numbers/percent/units as words **only in the text handed to Kokoro** (`2.5%` → "two point five percent"); `brief.script` / the caption keep the clean `2.5%`. Verify a remade reel by **transcribing the new `narration.wav`** (`hyperframes transcribe`) — Whisper should read back the exact figure. **Never put a raw decimal in a script without checking the VO.** |

### 12.3 9:16 conversion (free, local)
```bash
ffmpeg -i raw.mp4 -vf "scale=-2:1920,crop=1080:1920" -c:a copy -y raw_916.mp4   # center cover-crop
```
Then point `brief.video` at `raw_916.mp4` and run `reel.py`. (seedance audio is generated ambient —
keep it, or add `-an` to strip.)

---

## 13. Research recipe (F3) — `research.py`, the brief producer (built 2026-06-18)

The front-end that **replaces manual topic-feeding**: it produces `brief.json` files, which then
flow into the proven core (`copywriter.py` → `post.py`/`reel.py`). **0 Higgsfield credits.** Two modes.
Every paid API call is cached under `output/research/cache/` (24h; apify 7d) so re-runs don't
re-spend — apify is the priciest call, so Mode B fires it once per URL.

> **Daily flow (Marvin 2026-06-22):** fresh research → **text draft** (`<job>/draft.md`) → **duplication
> gate** (`dedup.py`: vs the last-7-day approved/produced posts + REJECTED; surgically revises only a
> near-duplicate hook/body/script, **follow-ups pass**; fail-open; `.env ENGINE_DEDUP=0` to disable) →
> templates → TG → schedule approved. **Product rotation** = `products_in_last_days(7)` (pick a SKU
> outside the 7-day window, related to the research). **Sundays** are **bank-first** (`serve_bank_day`)
> — draw from the Source Bank's mined angles before any external sweep; **used angles are removed**
> (archived to `output/research/sources/_used.jsonl`, source pruned when empty).

### 13.1 Mode A — topic discovery (sweep → SOUL §8 score → brief)
```bash
# Cheap dry-run: score candidates + print the §8 breakdown, write NO briefs:
python3 research.py topics --candidates "BPC-157,Semaglutide" --select 1 --dry-run

# Full run: score the top engine_state compounds, assemble the winner into a brief:
python3 research.py topics --select 1
python3 research.py topics --candidates "NAD+,Epithalon,BPC-157" --select 2 --pillar science
```
Scores the **six SOUL §8 factors** (trending-velocity .25 · comment-bait .20 · search-volume .20 ·
educational .15 · product-tie .10 · recency .10) × the per-topic weight in `engine_state.json`,
skips `blocked_topics`, prints every factor. A compound topic defaults to the **stack** pillar
(static-compound, labs RUO); otherwise **science** (story-reel).

### 13.2 Mode B — viral-outlier mining + format cloning
```bash
# Auto-mine YouTube by view-velocity vs the set median (cheap, searchapi):
python3 research.py outliers --query "peptides longevity" --num 15

# …then extract + clone the TOP outlier (fires ONE apify scrape) → trending brief:
python3 research.py outliers --query "peptides longevity" --extract

# Drop-a-link inbox — paste ANY viral URL (YT/TikTok/IG/FB/article) → trending brief:
python3 research.py inbox "https://www.tiktok.com/@x/video/123" --persona P3 --brand labs
python3 research.py inbox "<url>" --topic "BPC-157 tendon repair research"   # force the Acme angle
```
Outlier = **view-velocity (views/age) ≥ 2× the result-set median** — surfaces fresh high-velocity
posts over old high-view ones. Extract → classify the **format archetype** (this-or-that, myth-bust,
list, study-reaction…) → **reconfigure**: pour an Acme-owned topic into that structure, `copywriter.py`
rewrites the hook in the Research-Pharmacist voice + enforces compliance. **Clone the FORMAT, never
the content** — the source's claims are never carried into the brief (kept in `research.json` for
reference only). Scored by Devon's Mode B weights (niche/persona/format-adaptability/buyer-intent /40
+ recency/curated bonuses).

### 13.3 Daily run + outputs
```bash
python3 research.py run --select 4     # 4 Mode-A pillar briefs + 1 trending from outliers (F4 schedules this)
```
Each brief lands in `output/jobs/ACME-NNN/`: **`brief.json`** (post.py-ready, type=image, validated
against `schemas/brief.schema.json`), **`copy.json`** (caption/hashtags/alt for publishing),
**`research.json`** (discovery provenance + scoring breakdown). Discovery rows are logged to
`output/research/<date>/{discovery_queue,daily_brief}.json` (local-JSON-first; a Supabase `db.py`
replaces `DiscoveryStore` additively at cutover). Then: `python3 post.py output/jobs/ACME-NNN` → PNG
→ **M6 visual QC** (§9.3). Add `--fresh` to any command to bypass the cache; `--dry-run` to score
without spending on copywriter.py or writing briefs.

**Reference provenance (in every brief).** Each `brief.json` carries a **`reference`** block — the
exact source that inspired the post + *why* it was picked: `{ url, platform, description,
selection_rationale, cloned_format, extracted_hook, scoring_breakdown }` (Mode A carries no `url`;
mirrored to the `daily_brief` row as `reference_url`/`reference_description`/`selection_rationale`).
It is **metadata only** — `copywriter.py` never sees it, so the source's hook/claims **cannot leak into
the caption** (verified: the ACME-017 source claim "tortures belly fat" stayed in `extracted_hook`,
absent from the Epithalon caption). **F2** surfaces it at approval (*"📎 Reference: <description> —
<url>"*); the **F1** publish gate will assert it never appears in a post (next-step, MIGRATION Part 2).

### 13.4 Full carousels (the save-rate pillars) — `--carousel N`
```bash
python3 research.py topics --candidates "BPC-157" --carousel 5    # 5-slide deck, not a cover card
python3 research.py run --carousel                                # Mode-A (Science/Stack) briefs as carousels
```
Carousels are the backbone of **Science Simplified + Stack of the Day** — the save-rate pillars.
With `--carousel N` (or any `carousel-*` template), `assemble_brief` calls **`copywriter.py --carousel N`**
(Devon's Stage-3 slide copy: each slide = `EYEBROW + HEAD_1/HEAD_2_ITALIC/HEAD_3 + BODY`, slide 1 =
hook, **final slide carries the RUO line for Labs**), writes **`slides.json`** into the job folder,
and the brief points `post.py` at it → one brand-correct PNG per slide (1080×1350). Proven on
**ACME-015** (BPC-157, 5 slides, M6 QC pass). `copywriter.py --carousel` is backward-compatible (new flag;
single-card behaviour unchanged).

> ⚠️ **Gotchas:** (1) per-follower normalization isn't possible — searchapi/apify don't expose the
> author's follower count — so outlier ranking uses view-velocity only. (2) ✅ **Carousels now render
> full decks** via `--carousel` (above); a single card is only the fallback if slide-gen fails. The
> exact compound spec (purity/dose) isn't injected into carousel copy yet — the model paraphrases it
> (minor). (3) IG/FB/TikTok/Reddit are **drop-a-link only** for now (only YouTube auto-mines) — paste
> the URL into `research.py inbox`.

---

## 14. The autonomous loop (F4 + F2) — produce → review → publish (built 2026-06-18)

The daily loop that ties the proven 0-credit core into **produce daily → review in Telegram →
publish on approval**. A scheduler *without* an approval gate would auto-publish — which Marvin
does NOT want — so F4 (scheduling) and F2 (Telegram approval) ship together. **Carousels + static
cards only; video reels are EXCLUDED** (they cost Higgsfield credits + need hand-authored caption
beats). **0 Higgsfield credits.** Pure-Python launchd (no `claude -p`); the only LLM cost is
`copywriter.py` (OpenRouter, pennies). Shared core: **`engine.py`**.

### 14.1 The three steps

```
A) produce_daily.py run --carousel     research.py run --carousel → post.py render → captions.json
                                       (THE BRIDGE: copywriter.py --platform x|tiktok|instagram, RUO on
                                        every Labs caption, X fit ≤280/0-hashtags) → slots + manifest
B) telegram.py push-day --gap 15       image+card as ONE message (card = caption on the photo/album/
                                       reel; sendPhoto / sendMediaGroup) → DEDICATED engine group.
                                       --gap 15 spaces sends (no jumbled order); --resend re-pushes
                                       already-pushed cards. A/R/E reply commands are tap-to-copy.
   approvals.py poll                   getUpdates → APPROVE writes qc.json {"passed":true} + status
C) publish_slot.py                     drain approvals → this slot's APPROVED jobs → publish.py
```

**Why the bridge exists:** `research.py` writes `copy.json` (one caption); `publish.py`'s gate needs
`captions.json` (one UNIQUE caption per platform) **and the RUO line on EVERY Labs caption** — but
`copywriter.py` only auto-appends RUO for `--product-feature` posts. `produce_daily.py` closes that gap so
produced jobs pass the publish gate verbatim. The human's APPROVE in Telegram **writes the `qc.json`
sign-off** that `publish.py` requires — i.e. Telegram review REPLACES the M6 visual-QC step.

### 14.2 Per-job state (engine bookkeeping — never touches `brief.json`)

| File (in the job folder) | Written by | Meaning |
|---|---|---|
| `captions.json` | `produce_daily` | per-platform captions (the F1 publish contract) |
| `status.json` | all three | `produced → pushed → approved → published` (or `rejected/revise/held/failed`) + slot + history |
| `qc.json` `{"passed":true}` | `approvals` on APPROVE | the M6 sign-off `publish.py` demands |
| `output/engine/<date>/manifest.json` | `produce_daily` | the day's jobs + their PT slot |

### 14.3 Safety rails (all under `output/`, gitignored)

- **`output/STOP`** — kill-switch: `touch` halts every step instantly; `rm` resumes.
- **`output/GO_LIVE`** — go-live switch: **absent ⇒ publishing is DRY-RUN (supervised).** `touch` flips
  `publish_slot.py` to live `--go`. Flip only after watching a few supervised days (Blotato publishing
  is irreversible — §11 P4).
- **Spend caps** (`engine.py`, per-day): copy 30 / searchapi 20 / apify 3; override via `.env`
  (`ENGINE_CAP_COPY` …). Inspect: `python3 engine.py`.
- **Never double-post** (SOUL §19): a `published` job is skipped; no approval at a slot → held, nothing posted.
- **Compliance hold** (SOUL §16): `engine_state.compliance_hold=true` stops `publish_slot` until owner clears it.

### 14.4 Dedicated bot (F2 prerequisite — NEVER OpenClaw's)

`telegram.py`/`approvals.py` read **`ENGINE_TELEGRAM_BOT_TOKEN` / `ENGINE_TELEGRAM_CHAT_ID`** — a bot +
private group created via @BotFather, **separate from OpenClaw's frozen `TELEGRAM_BOT_TOKEN`** (Part 4).
Until those keys exist, `telegram.py`/`approvals.py` no-op safely (and run with `--dry-run` to preview a
card without a bot); `approvals.py apply "APPROVE ACME-NNN"` applies a command manually.

### 14.5 Scheduling (launchd, PT) + bring-up

`launchd/` holds 4 reference plists + `install.sh` (machine = `America/Los_Angeles`, so hours are PT):
`produce` 05:30 · `review` 07:00 · `approvals` every 5m · `publish` 08/11/13/16/19.

```bash
cd launchd && ./install.sh install     # generate for this checkout + load (timers start; still dry-run)
./install.sh status                    # what's loaded
./install.sh uninstall                 # unload + remove
```

Recommended order: (1) create the bot + group, add `ENGINE_TELEGRAM_*` to `.env`; (2) `install.sh install`
— publishing stays supervised (dry-run); (3) watch a few days (produce 05:30, push 07:00, APPROVE in
Telegram, publish slots log "WOULD publish"); (4) `touch output/GO_LIVE` to go live.

> **Proven 2026-06-18 (0 public posts):** full dry-run loop on **ACME-015** — bridge → `captions.json`
> (gate blocks on only the missing `qc.json`) → review card → `approvals.py apply APPROVE` (writes
> `qc.json`, status→approved, trust 0→8) → `publish_slot.py --slot 11:00` gate **PASS**, *would* post to
> X (cover tweet) + TikTok (5 slides). Held-without-approval + STOP-flag-halts both verified. No live
> `--go`, no launchd loaded, no `GO_LIVE` — those stay gated behind Marvin's sign-off.

## 15. API-depletion alerts — never degrade silently (`api_alerts.py`, built 2026-06-23)

**Why:** on 2026-06-23 SearchAPI hit its monthly cap (HTTP 429). Every discovery call returned
nothing, the §8 topic scorer went blind (all candidates tied at 0.495), and the daily run quietly
fell back to compound **rotation** → four duplicate-compound posts (ACME-062..065) with no source
links — and **nothing warned us**. This closes the "silent" gap: a depleted external API now pings
Telegram and (for discovery) stops producing duplicates instead of shipping them.

### 15.1 What happens when a tool is out of quota/credits

`api_alerts.py` (stdlib-only, best-effort, never raises). Each tool calls
`api_alerts.note(tool, code=, body=)` from its HTTP/credit **error branch**:

- **Classify** — depletion = HTTP **402/429** or a quota/credit/billing phrase in the error body
  (`used all of`, `insufficient credit`, `quota`, `payment required`, `upgrade your plan`, …).
  Transient/network/5xx errors are **not** treated as depletion.
- **Alert** — sends **one custom Telegram message per tool** to the engine group (same
  `ENGINE_TELEGRAM_*` bot as §14.4), saying WHAT is down + WHAT to do. E.g. SearchAPI →
  *"depleted… I can't run trending/news/YouTube discovery… drop any links you want me to build
  from, or top up SearchApi.io."* Apify → paste post text/links. Firecrawl → paste article text.
  Blotato → publish manually. Higgsfield → top up / fall back to Blotato images.
- **Dedup** — once per **UTC day per tool** via `output/engine/api_alerts.json` (a daily run that
  hammers a dead API sends ONE message, not 18; it re-alerts the next day if still down).

Wired into the error branch of: `searchapi.py`, `firecrawl.py`, `apify.py`, `blotato.py`
(HTTP + in-band `error`), `higgsfield.py` (the `run()` choke point, so out-of-credits on any
generation is caught). Any caller of those tools triggers the right alert at the source.

### 15.2 Discovery refuses to ship duplicates

`research.py` `run_tool` records depleted tools in `DEPLETED_TOOLS`. **Mode A (`topics`) and
`reel-today` refuse to generate** when SearchAPI is depleted — they log and return instead of
emitting blind-rotation repeats. **A daily run that produces ZERO briefs during a SearchAPI outage
is intentional, not a bug** — check the SearchApi.io quota first.

### 15.3 Switches

- `ENGINE_FORCE_DISCOVERY=1` — generate from rotation anyway (override the no-duplicates guard).
- `ENGINE_ALERTS_OFF=1` — disable all depletion alerts.
- `APIALERTS_DRYRUN=1` — print the message to stderr instead of sending (tests).

```bash
# Preview a tool's depletion message without sending (dry-run):
python3 api_alerts.py test searchapi
# Verify the live guard (uses the real API; alerts dry-run; writes NO briefs if depleted):
APIALERTS_DRYRUN=1 python3 research.py topics --select 4 --dry-run
```

> **Proven 2026-06-23 against the live (depleted) SearchAPI:** the 429 fired the exact custom
> message once (deduped across ~18 calls), Mode A logged "SearchAPI depleted — NOT generating
> blind-rotation briefs", and **zero briefs were written**. classify() unit checks: depletion vs
> transient/network all correct.
