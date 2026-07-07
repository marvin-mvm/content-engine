---
name: acme-blotato
description: "Publish/schedule to TikTok/Twitter/YouTube and more, generate Blotato visuals from templates (backup images). Auth pre-wired. NOT for text extraction — use acme-firecrawl (articles) / acme-apify (social)."
metadata:
  {
    "openclaw":
      {
        "emoji": "🎨",
        "requires": { "bins": ["acme-blotato"] }
      }
  }
---

# acme-blotato

**Before any real publish, read [REFERENCE.md](REFERENCE.md)** — per-platform aspects/formats
(single vs carousel), the IG-rejects-PNG gotcha, FB `pageId` call shape, X thread wiring,
TikTok loop-video recipe, upload hangs, and Blotato visual generation all live there.

## Connected Accounts (live, verified 2026-06-28)

| Platform | Account ID | Handle |
|----------|-----------|--------|
| Instagram | `54946` | @acmelabs |
| Facebook  | `38021` | Acme Labs page (subaccount/pageId `1095787500294673`) |
| X/Twitter | `18688` | @acmelabs |
| TikTok    | `47738` | @acme.labs |
| YouTube   | `37252` | — (Marvin posts YT **manually** via community post) |

> `acme-blotato accounts` is authoritative. Older docs/SOUL say "TikTok 43061" — that was a **view count**, not an ID; the live TikTok account is **47738**.

## Core commands

```bash
acme-blotato accounts                 # verify live connections + IDs

# Publish (omit --schedule to post now; ISO 8601 UTC to schedule)
acme-blotato publish "caption" --account-id 18688 --platform twitter --media-url URL \
  --schedule 2026-05-30T14:00:00Z
# Carousel: repeat --media-url per slide. Text-only: omit --media-url.
acme-blotato publish "caption" --account-id 47738 --platform tiktok \
  --media-url URL1 --media-url URL2 --media-url URL3

acme-blotato schedules                # list pending scheduled posts
acme-blotato post-status POST_ID      # confirm a post published
```

**Output:** `{"id": "POST_ID", "status": "scheduled|published", ...}` — but API-published posts
do **NOT** appear in the Blotato dashboard; verify on the actual profile.

## Hard rules (full detail in REFERENCE.md)

- **Caption tail order (Marvin 2026-06-29):** `…body… → waitlist CTA → RUO disclaimer LAST` —
  enforced by `engine.ensure_waitlist()`; run every caption through it.
- **Can't edit or delete a published post** via Blotato → always `--dry-run` + eyeball payload first.
- Each platform needs its own aspect/format — never reuse one render everywhere.
- **Extraction is NOT this skill:** articles → `acme-firecrawl scrape`, socials → `acme-apify scrape`.
  (`acme-blotato source` is deprecated — capped AI summary, no pipeline path uses it.)
- Blotato visual generation = backup only (Higgsfield is primary); never retry `generate` more than 2×.
