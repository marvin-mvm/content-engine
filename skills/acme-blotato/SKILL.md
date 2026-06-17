---
name: acme-blotato
description: "Publish to TikTok/Twitter/YouTube and more, generate Blotato visuals from templates, extract transcripts. Auth pre-wired."
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

## Connected Accounts

| Platform | Account ID |
|----------|-----------|
| TikTok   | `43061`   |
| Twitter  | `18688`   |
| YouTube  | `37252`   |

Instagram not connected. Full platform list: `instagram, tiktok, linkedin, twitter, facebook, youtube, threads, bluesky, pinterest`

```bash
acme-blotato accounts                 # verify live connections + IDs
```

## Publish a Post

```bash
# Single media — post immediately
acme-blotato publish "caption text" --account-id 43061 --platform tiktok --media-url URL

# Single media — scheduled
acme-blotato publish "caption text" --account-id 18688 --platform twitter --media-url URL \
  --schedule 2026-05-30T14:00:00Z

# Carousel — repeat --media-url for each slide
acme-blotato publish "caption text" --account-id 43061 --platform tiktok \
  --media-url URL1 --media-url URL2 --media-url URL3

# No media (text-only)
acme-blotato publish "caption text" --account-id 18688 --platform twitter
```

**Schedule format:** ISO 8601 UTC — `2026-05-30T14:00:00Z`. Omit `--schedule` to post immediately.

**Output:** `{"id": "POST_ID", "status": "scheduled|published", "platform": "tiktok", "scheduled_for": "..."}`

**Carousel warning:** Blotato carousel templates sometimes add AI text artifacts on lower slides. Inspect before sending. Use tweet-card template instead if illegible.

```bash
acme-blotato schedules                # list all pending scheduled posts
acme-blotato post-status POST_ID      # check if a post was published successfully
```

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

Never retry `generate` more than 2x.

## Extract Transcript / Source Content

```bash
acme-blotato source "https://youtube.com/watch?v=..."     # auto-detect: youtube, tiktok, article
acme-blotato source "https://example.com/article"         # extract article content
acme-blotato source "text or summary" --type text         # raw text extraction
```

Auto-detects type from URL. Blocks-and-waits (~30–120s). Useful for repurposing competitor content.

**Output:** `{"id": "SOURCE_ID", "type": "youtube", "summary": "...", "transcript": "...", "title": "..."}`
