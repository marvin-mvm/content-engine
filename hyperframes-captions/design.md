# Acme — HyperFrames Design System

**Source of truth for every caption/composition in this project. Use these exact
values. Never substitute fonts or invent colors.**

## Fonts (brand-locked — do not change)

| Role | Font | Weight | Notes |
|------|------|--------|-------|
| Caption body / normal words | **DM Sans** | 600 (SemiBold) | Embedded locally from `fonts/DMSans-upright.woff2`. NOT a Google-Fonts link. |
| Emphasis / keyword highlight | **Cormorant Garamond** | 700 Italic | HyperFrames built-in. Color = accent green `#3D9E6E`. This is the brand's signature editorial emphasis. |
| Mono / labels (if needed) | **DM Mono** | 400 | Eyebrows, counters, handles. |

- **Never** use Inter, Playfair Display, Arial, or any other font. The installed
  caption component (`compositions/components/caption-editorial-emphasis.html`) is
  already rebranded to DM Sans + Cormorant — keep it that way.
- DM Sans is a custom (non-built-in) font: it MUST be loaded via the local
  `@font-face` block (see `compositions/_dmsans-fontface.css`), never a Google link.

## Color palette (STRICT)

| Token | Hex | Use |
|-------|-----|-----|
| Deep Forest | `#1A2E1E` | Primary dark background / contrast scrim |
| Forest | `#2D6A4A` | CTA fills, secondary surfaces |
| Accent Green | `#3D9E6E` | Single point of emphasis — emphasis/italic caption words ONLY |
| Warm Cream | `#F2EDE4` | Caption body text on dark footage |
| Sage Mint | `#C8DDD0` | Light surfaces |

**Never** use gold, yellow, amber, purple, pink, red, orange, or neon. One accent
(green) per frame.

## Caption style (Zone 2 spec)

- Position: lower-middle, ~600–700px from the bottom on 1080×1920 portrait reels.
- Body words: DM Sans 600, `#F2EDE4`, with a soft dark text-shadow for legibility.
- Emphasis words: Cormorant Garamond 700 Italic, `#3D9E6E`, larger size.
- Max 2 lines, one caption group visible at a time.
- Over bright/busy footage, add a Deep Forest contrast scrim (`rgba(10,20,12,0.55)`)
  behind the caption layer — never bake it into the component.

## Format

- **Reels / stories: 1080×1920 (9:16 portrait).** Set composition `data-width="1080"
  data-height="1920"` and move the caption safe-zone accordingly (the shipped
  component defaults to 1920×1080 landscape — adapt dims for portrait).
- Hook in the first 1.5s. Always burn subtitles.

## Compliance

- RUO content (Acme Labs): research framing only. Never "treats/cures", never
  personal-use or weight-loss claims in burned text.
- Captions mirror the spoken transcript — do not invent claims not in the audio.
