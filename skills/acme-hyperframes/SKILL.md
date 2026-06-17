---
name: acme-hyperframes
description: "Burn brand-correct synced captions/subtitles onto Acme reels with HyperFrames. Use for any video caption/subtitle work. Brand fonts (DM Sans + Cormorant Garamond) and palette are pre-wired in the hyperframes-captions project."
metadata:
  {
    "openclaw":
      {
        "emoji": "🎬",
        "requires": { "bins": ["hyperframes"] }
      }
  }
---

# acme-hyperframes

**This is the tool for video captions/subtitles — NOT `overlay.py`.** `overlay.py`
uses Bebas Neue (off-brand). HyperFrames renders HTML, so the brand fonts (DM Sans
body + Cormorant Garamond italic emphasis) render correctly.

## Project (pre-wired, reuse it — never `init` a fresh one)

```
hyperframes-captions/          ← the Acme brand caption project
  design.md                    ← brand fonts + palette (HyperFrames auto-reads this)
  fonts/DMSans-*.woff2         ← DM Sans embedded locally (NOT a Google link)
  compositions/components/caption-editorial-emphasis.html  ← rebranded: DM Sans + Cormorant green
  index.html                   ← host composition (populate per job)
```

Always `cd hyperframes-captions` first. The brand is already set — do not change
fonts or colors. See `design.md` for the locked values.

## Caption workflow

```bash
cd hyperframes-captions

# 1. Transcribe the source video → word-level timestamps
hyperframes transcribe /path/to/reel.mp4 --model small        # add --language xx if non-English; .en ONLY if confirmed English

# 2. Edit index.html:
#    - set data-width="1080" data-height="1920" (9:16 reels) on #root + the caption host
#    - add the source video as <video id="bg-video" muted playsinline> + separate <audio>
#    - feed the transcript word-groups into the caption-editorial-emphasis sub-composition
#    - mark keyword/emphasis words so they render in Cormorant green (the brand highlight)

# 3. Validate, then render
npm run check                                                  # lint + validate + inspect — fix all errors
hyperframes render --out ../output/<name>-captioned.mp4
```

## Brand rules (enforced — see design.md)

- **Body/normal words:** DM Sans 600, warm cream `#F2EDE4`.
- **Emphasis/keyword words:** Cormorant Garamond 700 Italic, accent green `#3D9E6E`. One emphasis idea per group.
- **Never** Inter, Playfair, Bebas Neue, or any substitute font.
- Reels are **1080×1920 (9:16)**. Captions sit lower-middle (~600–700px from bottom), max 2 lines, one group on screen at a time.
- Over bright footage add a Deep Forest scrim `rgba(10,20,12,0.55)` behind the caption layer.
- Captions mirror the transcript — never invent claims. RUO content stays research-framed.

## Gotchas

- DM Sans is a **custom font** — it loads via the local `@font-face` in the component
  (path `../../fonts/` relative to `compositions/components/`). Cormorant Garamond is
  a HyperFrames built-in — just declare the family.
- Deterministic only: no `Math.random()`, no `Date.now()`, no runtime network fetches.
- Every caption group needs a hard `tl.set({opacity:0, visibility:"hidden"}, group.end)` kill.
- `npm run dev` is a long-running server — never block on it; use render/snapshot for one-shot output.
- For full composition/caption patterns, read the upstream skill at
  `/opt/homebrew/lib/node_modules/hyperframes/dist/skills/hyperframes/` (SKILL.md + references/captions.md).
