---
name: acme-apify
description: "Scrape Instagram/TikTok/Facebook/YouTube/Threads/X(Twitter) posts and pull 7-day analytics. Platform auto-detected. Auth pre-wired."
metadata:
  {
    "openclaw":
      {
        "emoji": "🕷️",
        "requires": { "bins": ["acme-apify"] }
      }
  }
---

# acme-apify

Supported platforms: **YouTube, Instagram, TikTok, Facebook, Threads, X/Twitter** — auto-detected from URL.
Social/video URLs only. Articles/blogs/websites → use `acme-firecrawl`.

```bash
acme-apify scrape "URL"                  # STEP 1 — caption, engagement, transcript (YouTube)
acme-apify analytics "URL"              # STEP 5 — 7-day metrics only
acme-apify scrape "URL" --timeout 300   # increase timeout for slow actors (default 180s)
```

Runs 30–90s (may reach 3 min for YouTube). Returns JSON:
```json
{
  "platform": "youtube|instagram|tiktok|facebook|threads|x",
  "url": "...",
  "published_at": "2026-05-20T10:00:00Z",
  "views": 45000,
  "likes": 3200,
  "comments_count": 120,
  "shares": 80,
  "caption": "...",           // instagram / tiktok / facebook
  "description": "...",       // youtube
  "transcript": "...",        // youtube only — up to 4000 chars, plain text
  "hashtags": ["longevity"],
  "duration": 45              // seconds, where available
}
```

Use `scrape` for STEP 1 when the commander sends a social link.
Use `analytics` for STEP 5 review at day +7 after publish.
