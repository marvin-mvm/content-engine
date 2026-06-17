---
name: acme-searchapi
description: "Google News/Web/YouTube/Trends search via SearchAPI.io. Auth pre-wired."
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": { "bins": ["acme-searchapi"] }
      }
  }
---

# acme-searchapi

```bash
acme-searchapi news "query" --num 8              # Google News — default for STEP 1 ideation
acme-searchapi search "query" --num 8            # Google Web search
acme-searchapi youtube "query" --num 5           # YouTube search — titles, channels, views
acme-searchapi trends "query" --geo US           # Google Trends — confirm topic is rising
```

**Options:**
- `--num N` — max results (default 10, max 10)
- `--geo US` / `--gl us` — country code for geo-targeting (default `us`)
- `--hl en` — language code (default `en`)

**Output — news/search:** `{query, results: [{title, source, link, snippet, date}]}`
**Output — youtube:** `{query, results: [{title, channel, link, views, length, published_at}]}`
**Output — trends:** `{query, interest_over_time, related_queries, trending_searches}`

Specific URL → `acme-apify` (social post) or `acme-firecrawl` (article).
