# acme-blotato — REFERENCE (lazy-loaded)

> Loaded on demand from SKILL.md. Everything here is proven-in-production detail;
> account IDs live in SKILL.md.

## Per-Platform Format Playbook  *(proven 2026-06-28 — ACME-071i first publish, IG+FB+X+TikTok)*

**A carousel post hits each platform in a DIFFERENT aspect + format. Render the slides per platform, don't reuse one aspect everywhere.** Source slides = `slides.json`; render with `produce.py <template> --carousel slides.json --set BRAND_NAME="ACME LABS" --set HANDLE="@acmelabs"`.

| Platform | Aspect · template | How it posts | Hashtags | Key params / gotchas |
|----------|-------------------|--------------|----------|----------------------|
| **Instagram** | 4:5 1080×1350 · `carousel-{light,dark}.html` | true native **carousel** (repeat `--media-url` per slide) | **MAX 5** (8 → API rejects: *"Instagram allows a maximum of 5 hashtags"*) | acct `54946`; returns `in-progress`→`published` |
| **Facebook** | same slides as IG | **multi-photo ALBUM — NOT a swipe carousel.** Organic FB has no carousel (ads-only); for carousel-feel use a **slideshow video** | few/none | **requires `pageId`** — the CLI has no flag, so call `blotato.mcp_call("blotato_create_post", {"accountId":"38021","platform":"facebook","text":…,"mediaUrls":[…],"pageId":"1095787500294673"})` (flat `pageId`) |
| **X / Twitter** | **SQUARE 1080×1080** · `carousel-light-square.html` | **slide-per-tweet THREAD** — lead via `--media-url`, each next slide via paired `--also "<text>" --also-media "<url>"` | **0** (1 max, e.g. on last tweet) | each tweet ≤280; RUO + waitlist on the LAST tweet; transient *"Failed to fetch media URL: chunk header exceeded 256 bytes"* → **just retry** (failed submit posts nothing). acct `18688` |
| **TikTok** | **VERTICAL 9:16 1080×1920** · `carousel-light-vertical.html` | photo **carousel** (repeat `--media-url` per slide) | 3–5 | auto-applies `isAiGenerated:true` + `PUBLIC_TO_EVERYONE`; settles `in-progress`→`published` (poll `post-status`). acct `47738` |
| **YouTube** | — | **MANUAL** — Marvin posts via YouTube *community post*; do NOT automate | — | acct `37252` |

**Canonical caption tail order (Marvin 2026-06-29): `…body… → waitlist CTA → RUO disclaimer (ALWAYS last)`.** The CTA line `Join the waitlist → acmelabs.co/waitlist` comes FIRST, then `For research use only — not for human consumption.` is the very last line — never the reverse. `engine.ensure_waitlist()` now enforces this automatically (it pulls any existing CTA/RUO line out and re-pins them in order; idempotent; only re-adds RUO if already present). Run every caption through it before publishing. Captions live in `captions.json` per platform (`instagram`, `tiktok` strings; `x` = `{text, thread[]}`).

**Flow:** render per-platform slides → `acme-blotato upload <file>` each → public URL → `--dry-run` to eyeball payload → publish.
- **Uploads transiently HANG on the first call in a fresh shell** — run foreground, one at a time, 45–60s cap + retry. URL prints to stdout (`https://database.blotato.io/storage/.../public_media/...`).
- **Can't edit OR delete a published post** via Blotato → always `--dry-run` + verify first. IG/FB/TikTok captions are editable in-app; **X tweets are not** (no Premium → delete+repost or reply).
- **API-published posts go STRAIGHT to the platform — they do NOT appear in the Blotato dashboard** post list (that view is only for dashboard-scheduled posts). Verify on the actual profile, not the dashboard.

Reusable square/vertical templates: `templates/src/carousel-light-square.html` (X) · `carousel-light-vertical.html` (TikTok). `render.py` auto-detects size from the body `width:Npx;height:Mpx` rule, so a new aspect = a new template, no flag.

## Per-Platform Handling — SINGLE IMAGE vs CAROUSEL  *(proven ACME-049 single + ACME-076i carousel, 2026-06-29)*

A post hits each platform in a **different aspect + format**. Two job shapes:

### A) SINGLE static image (product card / announcement)
| Platform | Aspect | Format | Build |
|----------|--------|--------|-------|
| **Instagram** | 4:5 1080×1350 | single image | **MUST be JPEG** (see gotcha) · acct 54946 |
| **Facebook** | 4:5 (same) | single photo | PNG ok · mcp `blotato_create_post` + flat `pageId` · acct 38021 |
| **X** | **square 1:1** 1080×1080 | single image tweet | pad the 4:5 → square; acct 18688 |
| **TikTok** | **9:16** 1080×1920 | **4s seamless LOOP VIDEO** (not a static) | still→video, every frame identical, no fade/motion; acct 47738 |

### B) CAROUSEL (multi-slide)
| Platform | Aspect · template | Format | Build |
|----------|-------------------|--------|-------|
| **Instagram** | 4:5 `carousel-{light,dark}.html` | native **carousel** (`mediaUrls`=all slides) | **JPEG slides** · ≤5 hashtags |
| **Facebook** | 4:5 (same slides) | multi-photo **album** (not swipe carousel) | mcp + `pageId` |
| **X** | **square** `carousel-{light,dark}-square.html` | slide-per-tweet **THREAD** | lead `mediaUrls`=[sq1]; `additionalPosts`=[{text, mediaUrls:[sq_i]}]; 0–1 hashtags |
| **TikTok** | **9:16** `carousel-{light,dark}-vertical.html` | photo **carousel** (`mediaUrls`=all vertical slides) — **NO video needed** | 3–5 hashtags + `TIKTOK_DEFAULTS` |

**Rendering the aspects:** carousels → re-render with the square/vertical template: `python3 produce.py templates/src/carousel-light-square.html --carousel <job>/slides.json --set BRAND_NAME="ACME LABS" --set HANDLE="@acmelabs" --no-log` (writes `output/<stem>-<ts>-slide-NN.png`; relocate). If the source template **drifted** (single statics whose template was replaced), don't re-render — PIL-pad the existing PNG (square = scale-to-height + side pad; 9:16 = native-width + top/bottom pad) using the **corner pixel color** so bars are seamless.

**TikTok loop video (single static only):** `ffmpeg -y -loop 1 -framerate 30 -t 4 -i still_9x16.png -f lavfi -t 4 -i anullsrc=r=44100:cl=stereo -map 0:v -map 1:a -c:v libx264 -preset slow -crf 14 -pix_fmt yuv420p -r 30 -c:a aac -b:a 128k -shortest -movflags +faststart out.mp4` — 120 identical frames = invisible loop. **Carousels skip this** (TikTok takes a vertical photo carousel directly).

**⚠️ IG rejects PNG** — `"The media could not be fetched from this URI"`; FB takes the same PNG fine. Convert IG media to JPEG (`PIL .convert('RGB').save(...,'JPEG',quality=95)`), re-upload, retry. A failed IG submit posts nothing (safe to retry).

**Captions:** canonical tail order is `…body… → waitlist CTA → RUO disclaimer (last)` — `Join the waitlist → acmelabs.co/waitlist` comes first, `For research use only — not for human consumption.` is the final line (enforced by `engine.ensure_waitlist`). Pre-launch (no COA): strip COA links/claims from descriptions (COA chip on the image is acceptable; the *description* points to the waitlist). IG ≤5 hashtags. X thread: the CTA + RUO ride the LAST tweet (CTA then RUO), 0 hashtags.

**Schedule vs now:** add `scheduledTime` (ISO8601 UTC, e.g. `2026-06-29T21:30:00Z`) to each `blotato_create_post` to schedule; omit to post now. Verify with `blotato.py schedules`. Record live URLs / schedule IDs to the job's `status.json`.

## Visual Generation (Blotato Templates)

Use only on commander request or when Higgsfield is unavailable. Higgsfield is always the primary media engine.

```bash
# Step 1 — discover template IDs
acme-blotato templates                             # list all templates
acme-blotato templates --search "carousel"         # filter: carousel, quote, slideshow, video, infographic
```

```bash
# Step 2 — generate from a template ID (blocks-and-waits, ~2–4 min)
acme-blotato generate TEMPLATE_ID "prompt describing content" --title "Optional title"
```

**Output:** `{"id": "VISUAL_ID", "status": "completed", "url": "https://...", "type": "carousel|image|..."}`
Use the returned `url` as `--media-url` in publish.

Never retry `generate` more than 2×.

**Carousel warning:** Blotato carousel templates sometimes add AI text artifacts on lower slides. Inspect before sending. Use tweet-card template instead if illegible.

## Extract Transcript / Source Content — ⚠️ DEPRECATED

**Do not use `acme-blotato source` for extraction.** The engine routes all "read-the-link" work to
dedicated extractors and Blotato is publish/schedule + backup images only:

- Article / blog / website → **`acme-firecrawl scrape "URL"`** (faithful full markdown)
- Social / video (YouTube, Instagram, TikTok, Facebook, Threads, X/Twitter) → **`acme-apify scrape "URL"`**

The `source` subcommand still exists for ad-hoc manual use, but it returns a capped AI *summary*
(≤3000 chars), not the real page, and is no longer invoked by any pipeline path.
