# Acme Post Templates — wiring tracker

> **Source of the new templates:** `assets/Acme Labs Post Overlay Templates/` (10 standalone
> bundler exports, dropped 2026-06-19). This file tracks **which template is wired into content
> production and how** — the "task list" of wired vs not. Brand hard-rules live in
> [SOUL.md](../SOUL.md); production recipes in [PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md).

## ⛔ Rendering guardrails — READ BEFORE choosing a template (Marvin 2026-06-22)

Learned the hard way on the ACME-052..061 reference batch (overlapping text + every card on the same
broken poll template). Three rules:

1. **Only auto-route to templates the copywriter actually FILLS.** The default copywriter output is
   `EYEBROW / HOOK_LINE_1/2/3 / SUBTITLE_TEXT / CTA_LABEL / caption` (+ `slides` with `--carousel`).
   - ✅ **story-reel** (single card) — filled by default copy. SHORT hooks only.
   - ✅ **carousel** (deck) — filled by `--carousel` copy (`slides.json`). Robust to long copy.
   - ✅ **static-compound** (product spec) — filled from `COMPOUND_CATALOG` (short structured fields). **Most robust.**
   - ⛔ **story-poll-pro** — comparison body is HARDCODED ("BPC-157 vs Semaglutide"); copywriter never
     fills it. **Never auto-select it.** Comparison/poll angles → carousel deck instead.
   - ⚠️ **static-callout** needs a SHORT `STAT` (e.g. "14.9%"); a sentence overflows it (that's why
     `quote` → story-reel). `story-product` needs the full product token set.
   - ✅ **product-use** (`product-use-{light,dark}`, 1080×1350, added 2026-06-24, Marvin-approved) — the
     **PRODUCT-USE / "what it is" card** (NOT an announcement): real SKU photo CENTERED in the middle, text
     BELOW it. Tokens: `BRAND_NAME / EYEBROW / COMPOUND / PRODUCT_IMAGE (product_images.file_uri) /
     DESCRIPTOR / DESCRIPTION / SPEC1 / SPEC2 / RUO_LINE / HANDLE`. Author the token set directly (not
     auto-filled by copywriter). Use REAL photos only — see [[acme-product-card-rules]]. Announcements
     still use `story-product`; photoless compounds (GHK-Cu, NAD+, MOTS-c, Semax) → centered `story-reel`.

2. **Long copy must not collide with fixed layout.** Templates that pin the body at a fixed `top:`
   overlap when a headline wraps. `carousel-{dark,light}` is now a top-anchored **flow** column
   (headline pushes body down); `story-reel-{dark,light}`'s hook zone is **bounded** (`bottom`+`overflow`)
   so it clips instead of colliding. If you add/edit a text-heavy template, use flow, not fixed `top:`.

3. **ALWAYS eyeball the rendered PNG before pushing to review.** `post.py` "rendered" ≠ correct. Open
   the image (or a slide) and check for overlap / boilerplate / wrong-topic sample data. A clean
   `captions.json` says nothing about the picture.

## Theme rule (light vs dark) — when to use
Theme follows **brand**, now enforced for **every** template by `research.retheme()`:
- **Dark** (`#1A2E1E` forest) → **Acme Labs** (RUO / peptides).
- **Light** (`#F2EDE4` cream) → **Acme Health**.

Every family ships both a `-dark` and `-light` variant. `assemble_brief` calls `retheme(template,
brand)` on the final template, so a health-brand post always renders light (previously only carousel
swapped — every other template was stuck dark; that bug is fixed).

## Slot wiring — Devon's §3.2 format rotation (which template on which day)
`research.WEEKLY_FORMATS` encodes Devon's §3.2 grid (Mon–Sun) per pillar; `daily_image_template()`
maps the format-of-the-day → the right template (theme by brand). `assemble_brief` uses it whenever
the caller forces neither a template nor a carousel. Result:

| Pillar | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| Science | carousel | story-reel | reel¹ | carousel | story-reel | carousel | reel¹ |
| Stack | carousel | **story-product** | carousel | **carousel²** | carousel | **story-product** | carousel |
| Trending | reel¹ | carousel | reel¹ | **carousel²** | reel¹ | story-reel | reel¹ |
| Proof | carousel | static-callout | carousel | quote→story-reel | carousel | static-callout | carousel |
| Founder | quote→story-reel | static-callout | quote→story-reel | carousel | static-callout | carousel | quote→story-reel |

¹ reel cells fire only on the pillar's alternating video day (`slot_wants_reel`); otherwise the
image fallback (carousel) is used.
² **comparison/poll formats render as CAROUSEL decks, NOT story-poll-pro** (Marvin 2026-06-22): the
`compare` / `this_or_that` / `poll` formats — and viral this-or-that clones (`FORMAT_ARCHETYPES`) —
all route through `daily_image_template`'s `_CAROUSEL_FORMATS` set to a carousel. **`story-poll-pro`
is NO LONGER auto-selected anywhere** (see the ⛔ note in the status table). **Daily default:** the
engine follows this rotation. Force modes: `produce_daily run --carousel` / `--no-carousel`.

---

## Status table

| Template family | Variants | Native | Kind | Wired? | Driven by |
|---|---|---|---|---|---|
| **Reel · b-roll molecular** | `reel-overlay-broll-{dark,light}` | 1080×1920 | Video underlay + transparent overlay | ✅ **DEFAULT reel** | `research.assemble_reel_brief` → `brief.overlay` → `reel.py` → `produce.py --video-underlay` |
| **Reel · Person on Camera** | `reel-overlay-studio-{dark,light}` | 1080×1920 | Video underlay + transparent overlay | ✅ wired (manual) | same path; for reels with **real talking-head footage** (not auto-generated) |
| **Story · Product** | `story-product-{dark,light}` | 1080×1920 | Static card (token) | ✅ wired | `brief.image` (`post.py`); `_map_tokens` fills from the compound catalog; `alts` of `stack` |
| **Story · Poll** | `story-poll-pro-{dark,light}` | 1080×1920 | Static card (token) | ⛔ **MANUAL ONLY — NOT auto-wired** | `_map_tokens` fills only the hook; the poll's two options + 4 rows are **HARDCODED** ("BPC-157 vs Semaglutide"). The copywriter never generates them, so any auto-selected poll renders SAMPLE data. Removed from all rotations/alts/archetypes 2026-06-22. Re-enable only after autonomous poll-data generation exists; until then set `brief.image.set` by hand. |
| **Carousel · premium** | `carousel-premium-{dark,light}` | 1080×1350 ×10 | React deck (NOT token) | ⚠️ **renders, not auto-engine-wired** | `render_carousel.py` → per-slide PNGs. Per-post data-injection is a follow-up (see below) |
| **Carousel · legacy** | `carousel-{dark,light}` | 1080×1350 | Static card/slides (token) | ✅ kept as engine carousel | `brief.image.carousel` (`post.py --carousel`) — **unchanged** |
| Static callout / compound, story-reel, story-poll (legacy) | `static-*`, `story-reel-*`, `story-poll` | — | Static (token) | ✅ unchanged (legacy) | as before |

> **Legacy kept intact, per request:** the old static-image + carousel path (`carousel-dark/light`,
> `static-*`, `story-reel-*`, `story-poll.html`) is untouched and still the classic posting route.
> The reel default changed from **burned-in captions** to the **overlay** model below.

---

## The reel change — caption in the overlay, never burned into the video

**What changed:** reels used to burn word-synced captions *into* the video (hyperframes karaoke).
Now the video stays **clean** and the caption/brand chrome lives in a **transparent template overlay**
composited over every frame. This is exactly how the templates are designed (`.reel-bg` =
*"put real footage in here, behind everything"*).

**Pipeline (overlay model — default):**
1. `research.assemble_reel_brief` writes `brief.overlay` = `{ template: reel-overlay-broll-*, EYEBROW,
   BRAND_NAME, HOOK_LINE_1/2_ITALIC/3, SUBTITLE_TEXT, CTA_LABEL, HANDLE }` (same token set as
   `story-reel`, so copywriter fills it).
2. `reel_video.py` (RV3) generates the **clean** b-roll into `brief.video` (it already strips any
   text/typography from prompts — caption-free by design).
3. `reel.py` detects `brief.overlay` → calls `produce.py --video-underlay <brief.video>`:
   - `render.py --transparent` renders the template to an **RGBA overlay PNG** (transparent centre
     where the video shows through; only scrims + hook + subtitle + CTA + logo are painted),
   - `ffmpeg` scales the video to cover 1080×1920 and alpha-composites the overlay over every frame,
   - writes `<job>/<job_id>-final.mp4` + `<job>/thumb.png` (composited poster).

**studio vs broll:** the autonomous engine makes **b-roll only** (no talking-head — `reel_video.py`),
so `reel-overlay-broll-*` is the default. `reel-overlay-studio-*` is for **manual founder reels**
with real talking-head footage — set `brief.overlay.template` to it.

**Legacy burned-in captions still available:** a brief with `brief.cover` + `caption_data.json`
(and no `overlay`) takes the old hyperframes path. `reel.py` auto-selects by which keys are present.

**Manual one-off:**
```bash
python3 produce.py templates/src/reel-overlay-broll-dark.html out.mp4 \
  --video-underlay clean_broll.mp4 \
  --set EYEBROW="RESEARCH USE ONLY" --set BRAND_NAME="ACME LABS" \
  --set HOOK_LINE_1="The molecule" --set "HOOK_LINE_2_ITALIC=behind" --set HOOK_LINE_3="recovery" \
  --set "SUBTITLE_TEXT=BPC-157 · pentadecapeptide" --set "CTA_LABEL=READ THE COA" --set HANDLE="@acmelabs"
```

---

## Story templates (static)

Both render at 0 credits via `post.py` from a `type=image` brief. Tokens come from
`research._map_tokens` (catalog-derived for product; brand-standard defaults + copywriter hook for
poll). Override any token per-post via `brief.image.set`.

- **story-product** (31 tokens): product announcement / restock. `COMPOUND`, `SKU`, `DOSE`, `PRICE`,
  `CLASS`, spec rows, COA callout map from `COMPOUND_CATALOG`. `PRODUCT_IMAGE` defaults to a generic
  vial — pass a real SKU photo for a specific product.
- **story-poll-pro** (26 tokens): engagement poll / this-or-that. ⛔ **MANUAL ONLY.** Hook fills from
  copywriter, but the two poll options + 4 icon rows are **HARDCODED to a BPC-157↔Semaglutide compare**
  in `_map_tokens` — the copywriter never emits them. So any *auto-selected* poll ships that sample data
  regardless of topic (this caused the ACME-052..061 mess: 8 single-compound clones all rendered the same
  BPC-157-vs-Sema poll). It is removed from every rotation/alt/archetype; only use it by hand-setting
  `brief.image.set`. *Follow-up to re-enable autonomously:* copywriter must emit `POLL_A_*`/`POLL_B_*`+`ROW*`.

Get the token list for any template: `python3 produce.py <template> --tokens`.

---

## Premium carousel (React deck) — renders, data-injection is a follow-up

`carousel-premium-*` is a **self-contained React/Babel app** (not a `{{TOKEN}}` template): it mounts
a 10-slide deck into `<div id="stack">`. It cannot go through `render.py`/`post.py`, so it has its
own renderer:

```bash
python3 render_carousel.py templates/premium-carousel/carousel-premium-dark.html output/jobs/ACME-010
# → output/jobs/ACME-010/slide-01.png … slide-10.png  (native 1080×1350 each)
```

Slide **copy currently comes from the `SLIDES` data baked into the app JS**
(`assets/templates/carousel-premium/<app>.bin`). To change copy for a post, edit that array.
**Wiring per-post data injection into the engine (so copywriter drives it) is a tracked follow-up.**
Until then the **legacy `carousel-dark/light`** remains the engine's token-driven carousel.

---

## ✅ Done vs ⛔ still needs wiring (the honest checklist)

**✅ COMPLETE & verified (manual AND autonomous engine paths):**
- Reel overlay compositor: `render.py --transparent` + `produce.py --video-underlay` (ffmpeg alpha-composite).
- `reel.py` auto-routes overlay vs legacy; `research.py` emits `brief.overlay`; `brief.overlay` in schema.
- **Autonomous chain wired:** `reel_video.py` (clean b-roll) → `reel_captions.py` (TTS voiceover, then
  **short-circuits past Whisper** for overlay briefs) → `reel.py` overlay → `<job>-final.mp4` + `thumb.png`.
  `publish.py` already posts `<job>-final.mp4`. Reels = caption-in-template on BOTH paths.
- All 4 reel + 2 story templates tokenised, rendering dark+light; `_map_tokens` covers every token.

**✅ ALSO DONE (2026-06-20 round 2):**
- **Story templates are now auto-SELECTED by the engine** on their §3.2 slots (table above) — not just
  manual. `story-product` lands on stack product days. (`story-poll-pro` was auto-selected on
  stack-compare / trending this-or-that days, but that was **reverted 2026-06-22** — those days now
  render carousels; see the ⛔ guardrail below.) Theme is brand-correct via `retheme()`.
- **Theme is correct for every template** (health → light) via `retheme()`.
- **Product image is non-strict:** `story-product` shows a labelled placeholder (the compound name +
  "image pending") when `PRODUCT_IMAGE` is empty or fails to load; a real per-SKU photo (passed via
  `brief.image.set["PRODUCT_IMAGE"]`) auto-hides the placeholder. No photo needed to ship the card.
- **Any video uses the template underlay**, not just "reels": the `reel-overlay-*` overlay model is the
  treatment for ANY video post. `reel-overlay-studio-*` ("video head-shot") is usable for **any** video
  even with no person speaking — it's just a template choice (`brief.overlay.template`), not restricted.
- **Both carousels work:** classic `carousel-dark/light` (token, the engine's carousel on rotation days)
  AND premium `carousel-premium-*` (React deck via `render_carousel.py`).

**⛔ STILL OPEN (smaller, optional):**
1. **Premium carousel copy is baked-in.** It renders (`render_carousel.py`), but per-post slide copy
   lives in the app's `SLIDES` data — a copywriter→data-injection adapter is unbuilt. The classic
   carousel remains the engine's token-driven carousel on rotation days, so the daily pipeline is
   complete without it.
2. **story-poll-pro rich fields** (poll options + the 4 icon rows) still default to a fixed
   BPC-157↔Semaglutide compare; the headline fills from copywriter. Fully bespoke autonomous polls
   would need `copywriter.py` to emit those fields. Override per-poll via `brief.image.set` meanwhile.
3. **Product photos:** drop real per-SKU images in and pass `PRODUCT_IMAGE` (placeholder ships until then).

---

## How the templates were produced (reproducible)
The drop files are bundler exports (markup is a JSON string inside `<script type="__bundler/template">`,
assets base64 in a manifest). `templates/tools/extract_bundle.py` unpacks one into clean HTML +
externalised assets under `assets/templates/<family>/`. The tokenised `templates/src/*` and the
self-contained `templates/premium-carousel/*` were derived from those extracts.
