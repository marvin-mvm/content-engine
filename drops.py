#!/usr/bin/env python3
"""
drops.py — manual link-drop queue for the Trending pillar (v2 §3.1 / Stage 1 "manual_save").

ANY member of the engine's Telegram chat can paste a viral social URL OR an article/blog link;
approvals.py's poll loop captures it here at ZERO cost (no scrape happens at drop time). The
morning run (`research.py drops`, wired into produce_daily) then drains the highest-priority pending
drop into a Trending (Pillar 3) brief — v2: "Trending clones the FORMAT of saved posts + niche
scrapers." At CONSUME time research.py routes by URL: social/video → Apify, article/blog → Firecrawl.

Generalised to ALL users (Marvin 2026-06-21), not just Devon — Devon's curated drops simply carry the
same +3 priority. Broadened to accept article/blog URLs too (Marvin 2026-06-22): any real http(s)
link that isn't one of our own/internal hosts (see EXCLUDE_HOSTS) is now a valid drop, so a pasted
article reaches Firecrawl instead of being silently ignored. The queue is persistent ACROSS days
(drops accumulate; the run consumes ~1/day, FIFO) and lives under output/engine/ — gitignored
runtime state, same home as the decision ledger and the daily manifests.

0 Higgsfield credits. The only spend is the extraction at CONSUME time (research.py drops), which is
gated by the daily apify budget — never at capture time.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import engine as e

STORE = e.ENGINE_DIR / "manual_drops.json"

# Social/video hosts whose FORMAT we clone — extract_pattern routes these to Apify. Any OTHER
# http(s) link is now accepted too (an article/blog/news URL → Firecrawl downstream), so a pasted
# article link becomes a real drop instead of being silently ignored (Marvin, 2026-06-22).
SOCIAL_HOSTS = (
    "instagram.com", "tiktok.com", "youtube.com", "youtu.be", "twitter.com", "x.com",
    "reddit.com", "facebook.com", "fb.watch", "threads.net",
)
# Hosts we NEVER treat as a drop: our own shop/SPA, internal Google docs, and link-shorteners /
# localhost noise — so the chat can still talk freely without a stray utility URL becoming a false
# "drop". Everything not in here that isn't a bare domain is fair game for extraction.
EXCLUDE_HOSTS = (
    "acmelabs.co", "acme.co", "docs.google.com", "drive.google.com", "sheets.google.com",
    "google.com/maps", "localhost", "127.0.0.1", "t.me", "telegram.org",
)
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def _platform(url: str) -> str:
    u = url.lower()
    for host, name in (("instagram.com", "instagram"), ("tiktok.com", "tiktok"),
                       ("youtu", "youtube"), ("twitter.com", "x"), ("x.com", "x"),
                       ("reddit.com", "reddit"), ("facebook.com", "facebook"),
                       ("fb.watch", "facebook"), ("threads.net", "threads")):
        if host in u:
            return name
    return "article"   # generic article/blog/website → Firecrawl at consume time


def is_content_url(url: str) -> bool:
    """A droppable link: any real http(s) URL that isn't one of our own/internal/utility hosts.
    Social/video → Apify, everything else → Firecrawl (research.py routes by _detect_platform)."""
    u = (url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return False
    if any(h in u for h in EXCLUDE_HOSTS):
        return False
    # Require a host with a dot (reject bare 'http://foo') so only real web links qualify.
    host = u.split("://", 1)[1].split("/", 1)[0]
    return "." in host


def extract_urls(text: str) -> list[str]:
    """All content URLs in a message body, de-duplicated, order-preserving (trailing
    punctuation trimmed so 'see https://x.com/p/123).' yields a clean URL)."""
    out, seen = [], set()
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?)]}'\"")
        if is_content_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _norm(url: str) -> str:
    return (url or "").split("?")[0].rstrip("/").lower()


def load() -> list:
    d = e.load_json(STORE)
    return d if isinstance(d, list) else []


def save(rows: list) -> None:
    e.ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def enqueue(url: str, who: str = "telegram", *, chat_id=None, message_id=None,
            priority_bonus: int = 3) -> dict | None:
    """Add ONE content URL as a pending drop. Dedups on the normalised URL across any row that
    isn't 'failed' (so a re-paste is ignored, but a previously-failed URL may be retried). Returns
    the new row, or None if it's a duplicate or not a content URL. 0 cost — never scrapes."""
    if not is_content_url(url):
        return None
    rows = load()
    n = _norm(url)
    if any(_norm(r.get("url", "")) == n and r.get("status") != "failed" for r in rows):
        return None
    row = {
        "id": f"drop-{len(rows) + 1:04d}", "url": url, "platform": _platform(url),
        "who": who, "chat_id": chat_id, "message_id": message_id,
        "priority_bonus": priority_bonus, "status": "pending",
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "job_id": None,
    }
    rows.append(row)
    save(rows)
    return row


def pending(limit: int | None = None) -> list:
    """Pending drops, oldest-first (FIFO so nothing starves)."""
    rows = sorted((r for r in load() if r.get("status") == "pending"),
                  key=lambda r: r.get("at", ""))
    return rows[:limit] if limit else rows


def mark(drop_id: str, status: str, job_id: str | None = None) -> None:
    rows = load()
    for r in rows:
        if r.get("id") == drop_id:
            r["status"] = status
            if job_id:
                r["job_id"] = job_id
            r["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            break
    save(rows)


if __name__ == "__main__":          # tiny human inspector
    import argparse
    ap = argparse.ArgumentParser(description="Acme manual link-drop queue (Trending pillar)")
    ap.add_argument("--add", metavar="URL", help="manually enqueue a URL (testing)")
    ap.add_argument("--who", default="cli")
    a = ap.parse_args()
    if a.add:
        row = enqueue(a.add, who=a.who)
        print("queued:" if row else "ignored (dup/non-content):", a.add)
    pend = pending()
    print(f"{len(pend)} pending drop(s):")
    for r in pend:
        print(f"  {r['id']}  {r['platform']:9}  by {r.get('who')}  {r['url']}")
