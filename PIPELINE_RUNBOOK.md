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

---

## 0. The chain (where this fits)

```
M1 brief.json → M2 copy.py → M3 visual(CREDITS) → M4 HyperFrames captions → M5 produce.py → M6 QC
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
> `caption_data.json` and the cover from `brief.cover` — no hand-editing. **A6** will wrap
> `reel.py` as the `acme-reel` skill.

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
submit step can hard-gate on the token; nothing can mistake a block for a pass.

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
