---
name: acme-firecrawl
description: "Scrape clean article markdown from any URL. Auth pre-wired."
metadata:
  {
    "openclaw":
      {
        "emoji": "🔥",
        "requires": { "bins": ["acme-firecrawl"] }
      }
  }
---

# acme-firecrawl

Articles, blogs, and web pages only — the **sole** article/website text extractor.
Social/video posts (YouTube, Instagram, TikTok, Facebook, Threads, X/Twitter) → use `acme-apify`.

```bash
acme-firecrawl scrape "URL"                        # extract clean markdown, 8000 char cap
acme-firecrawl scrape "URL" --timeout 60           # increase timeout for slow pages (default 30s)
acme-firecrawl search "query" --num 5              # Google search — titles + URLs + snippets
acme-firecrawl search "query" --num 3 --scrape     # search + scrape full content (slower, more credits)
```

**Output — scrape:** `{url, title, description, markdown}`
**Output — search:** `{query, results: [{title, url, description}]}`
**Output — search + scrape:** `{query, results: [{title, url, description, markdown}]}`

Always `scrape` before drafting copy. Never write from snippets alone — they lose context.
Markdown is capped at 8000 chars; very long articles are truncated with `[…content truncated…]`.
