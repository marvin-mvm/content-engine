#!/usr/bin/env python3
"""
Apify CLI for ACME agent.
Auto-detects platform from URL and fires the right Apify actor via REST API.

Supported platforms: YouTube, Instagram (posts + reels), TikTok, Facebook, Threads, X/Twitter

Usage:
  apify.py scrape   URL  [--timeout N] [--raw]
  apify.py analytics URL [--timeout N] [--raw]

scrape    — Extract content, captions, transcript hooks for STEP 1 (commander sends a link).
analytics — Extract view/like/comment metrics for STEP 5 (7-day post review).

Both subcommands auto-detect the platform, start the right actor, poll until done,
and return clean JSON. Reads APIFY_API_KEY from .env or environment.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SCRIPT_DIR = Path(__file__).parent
API_BASE = "https://api.apify.com/v2"
DEFAULT_TIMEOUT = 180  # seconds — social scraping can be slow
MAX_TRANSCRIPT_CHARS = 4000


def parse_srt_to_text(srt):
    """Strip SRT numbering/timestamps and return plain dialogue text."""
    if not srt:
        return ""
    import re
    text = re.sub(r"^\d+\s*$", "", srt, flags=re.MULTILINE)
    text = re.sub(r"\d{2}:\d{2}:\d+[,\.]\d+ --> \d{2}:\d{2}:\d+[,\.]\d+", "", text)
    lines = [l.strip() for l in text.splitlines() if l.strip() and l.strip() != " "]
    seen, result = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            result.append(line)
    return " ".join(result)

# Actor IDs and input builders for each platform.
# scrape_input: for Step 1 (content + transcript + hooks)
# analytics_input: same actor, same data — we just trim different fields
ACTORS = {
    "youtube": {
        "actor": "streamers~youtube-scraper",
        "input": lambda url: {
            "startUrls": [{"url": url}],
            "maxResults": 1,
            "downloadSubtitles": True,
        },
    },
    "instagram": {
        "actor": "apify~instagram-scraper",
        "input": lambda url: {
            "directUrls": [url],
            "resultsType": "posts",
            "resultsLimit": 1,
            "addParentData": False,
        },
    },
    "tiktok": {
        "actor": "clockworks~tiktok-scraper",
        "input": lambda url: {
            "postURLs": [url],
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        },
    },
    "facebook": {
        "actor": "apify~facebook-posts-scraper",
        "input": lambda url: {
            "startUrls": [{"url": url}],
            "maxPosts": 1,
            "maxPostComments": 10,
        },
    },
    # Threads single-post extraction (Marvin 2026-06-21): logical_scrapers/threads-post-scraper
    # takes post URLs via startUrls (confirmed input schema). Meta-gated like IG/FB; this is the
    # Apify path for a dropped Threads link.
    "threads": {
        "actor": "logical_scrapers~threads-post-scraper",
        "input": lambda url: {
            "startUrls": [{"url": url}],
            "proxyConfiguration": {"useApifyProxy": True},
        },
    },
    # X / Twitter single-post extraction (Marvin 2026-06-22): apidojo/tweet-scraper (Tweet
    # Scraper V2, pay-per-result) takes a tweet URL via `startUrls` (plain URL strings) + maxItems.
    # X is a SOCIAL platform → Apify, not Firecrawl (a logged-in JS timeline isn't crawler-clean).
    # Actor slug + input schema to be confirmed on the first live run (same caution as Threads).
    "x": {
        "actor": "apidojo~tweet-scraper",
        "input": lambda url: {
            "startUrls": [url],
            "maxItems": 1,
        },
    },
}


def load_api_key():
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("APIFY_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("APIFY_API_KEY")
    if key:
        return key
    sys.exit("ERROR: APIFY_API_KEY not found in .env or environment")


def detect_platform(url):
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "instagram.com" in url_lower:
        return "instagram"
    if "tiktok.com" in url_lower:
        return "tiktok"
    if "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    if "threads.net" in url_lower or "threads.com" in url_lower:
        return "threads"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "x"
    return None


def api_request(method, path, api_key, payload=None):
    url = f"{API_BASE}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "acme-apify/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: Apify {e.code} on {path}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure: {e}")


def start_run(actor_id, input_data, api_key):
    path = f"/acts/{actor_id}/runs"
    resp = api_request("POST", path, api_key, input_data)
    run = resp.get("data", {})
    return run.get("id"), run.get("defaultDatasetId")


def poll_run(run_id, api_key, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = api_request("GET", f"/actor-runs/{run_id}", api_key)
        run = resp.get("data", {})
        status = run.get("status", "")
        if status == "SUCCEEDED":
            return run
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            sys.exit(f"ERROR: Apify run {run_id} ended with status: {status}")
        time.sleep(5)
    sys.exit(f"ERROR: Apify run {run_id} timed out after {timeout}s (still {status})")


def fetch_dataset(dataset_id, api_key):
    resp = api_request("GET", f"/datasets/{dataset_id}/items?limit=5", api_key)
    return resp if isinstance(resp, list) else resp.get("data", [])


# ── Trim helpers — one per platform ───────────────────────────────────────────

def trim_youtube(item, mode):
    base = {
        "platform": "youtube",
        "url": item.get("url") or item.get("id"),
        "title": item.get("title"),
        "channel": item.get("channelName") or item.get("channel"),
        "published_at": item.get("date") or item.get("publishedAt"),
        "views": item.get("viewCount") or item.get("views"),
        "likes": item.get("likes") or item.get("likeCount"),
        "comments_count": item.get("commentsCount") or item.get("commentCount"),
    }
    if mode == "scrape":
        # transcript may be a list of SRT objects [{srt: "..."}, ...] or a plain string
        raw_transcript = item.get("subtitles") or item.get("transcript") or ""
        if isinstance(raw_transcript, list):
            srt_text = " ".join(
                t.get("srt", "") for t in raw_transcript if isinstance(t, dict) and t.get("language") == "en"
            ) or " ".join(t.get("srt", "") for t in raw_transcript if isinstance(t, dict))
            transcript = parse_srt_to_text(srt_text)[:MAX_TRANSCRIPT_CHARS]
        else:
            transcript = str(raw_transcript)[:MAX_TRANSCRIPT_CHARS]
        base.update({
            "description": (item.get("text") or item.get("description") or "")[:2000],
            "transcript": transcript,
            "tags": item.get("hashtags") or item.get("tags") or [],
            "duration": item.get("duration"),
        })
    return base


def trim_instagram(item, mode):
    base = {
        "platform": "instagram",
        "url": item.get("url") or item.get("shortCode"),
        "type": item.get("type"),
        "published_at": item.get("timestamp"),
        "views": item.get("videoViewCount") or item.get("videoPlayCount"),
        "likes": item.get("likesCount"),
        "comments_count": item.get("commentsCount"),
    }
    if mode == "scrape":
        caption = item.get("caption") or item.get("text") or ""
        base.update({
            "caption": caption[:3000],
            "hashtags": item.get("hashtags") or [],
            "mentions": item.get("mentions") or [],
            "location": item.get("locationName"),
        })
    return base


def trim_tiktok(item, mode):
    stats = item.get("stats") or {}
    author = item.get("authorMeta") or {}
    base = {
        "platform": "tiktok",
        "url": item.get("webVideoUrl") or item.get("videoUrl"),
        "published_at": item.get("createTimeISO") or item.get("createTime"),
        "views": stats.get("playCount") or item.get("playCount"),
        "likes": stats.get("diggCount") or item.get("diggCount"),
        "comments_count": stats.get("commentCount") or item.get("commentCount"),
        "shares": stats.get("shareCount") or item.get("shareCount"),
        "author": author.get("name") or item.get("authorName"),
    }
    if mode == "scrape":
        base.update({
            "description": (item.get("text") or "")[:2000],
            "hashtags": [h.get("name", h) if isinstance(h, dict) else h
                         for h in (item.get("hashtags") or [])],
            "music": (item.get("musicMeta") or {}).get("musicName"),
            "duration": item.get("videoMeta", {}).get("duration") if isinstance(item.get("videoMeta"), dict) else None,
        })
    return base


def trim_facebook(item, mode):
    base = {
        "platform": "facebook",
        "url": item.get("url") or item.get("postUrl"),
        "published_at": item.get("time") or item.get("date"),
        "likes": item.get("likes"),
        "comments_count": item.get("comments") if isinstance(item.get("comments"), int) else len(item.get("comments") or []),
        "shares": item.get("shares"),
    }
    if mode == "scrape":
        base.update({
            "text": (item.get("text") or item.get("postText") or "")[:2000],
            "media": item.get("media") or [],
        })
    return base


def trim_threads(item, mode):
    # logical_scrapers/threads-post-scraper field names vary; pull the common ones tolerantly.
    base = {
        "platform": "threads",
        "url": item.get("url") or item.get("postUrl") or item.get("permalink"),
        "published_at": item.get("publishedAt") or item.get("timestamp") or item.get("date"),
        "likes": item.get("likeCount") or item.get("likes"),
        "comments_count": item.get("replyCount") or item.get("commentsCount") or item.get("replies"),
    }
    if mode == "scrape":
        base.update({
            "text": (item.get("text") or item.get("caption") or item.get("content") or "")[:3000],
        })
    return base


def trim_x(item, mode):
    # apidojo/tweet-scraper field names vary across versions; pull the common ones tolerantly.
    base = {
        "platform": "x",
        "url": item.get("url") or item.get("twitterUrl") or item.get("tweetUrl"),
        "published_at": item.get("createdAt") or item.get("created_at") or item.get("date"),
        "views": item.get("viewCount") or item.get("views"),
        "likes": item.get("likeCount") or item.get("favoriteCount") or item.get("favorite_count"),
        "comments_count": item.get("replyCount") or item.get("reply_count") or item.get("replies"),
        "shares": item.get("retweetCount") or item.get("retweet_count"),
    }
    if mode == "scrape":
        base.update({
            "text": (item.get("text") or item.get("fullText") or item.get("full_text") or "")[:3000],
        })
    return base


TRIMMERS = {
    "youtube": trim_youtube,
    "instagram": trim_instagram,
    "tiktok": trim_tiktok,
    "facebook": trim_facebook,
    "threads": trim_threads,
    "x": trim_x,
}


def run_command(url, mode, timeout, raw, api_key):
    platform = detect_platform(url)
    if not platform:
        sys.exit(
            f"ERROR: Unrecognized URL — supported platforms: YouTube, Instagram, TikTok, Facebook, Threads, X/Twitter.\nURL: {url}"
        )

    cfg = ACTORS[platform]
    actor_id = cfg["actor"]
    input_data = cfg["input"](url)

    print(f"[acme-apify] platform={platform} actor={actor_id} mode={mode}", file=sys.stderr)
    run_id, dataset_id = start_run(actor_id, input_data, api_key)
    print(f"[acme-apify] run_id={run_id} polling...", file=sys.stderr)

    poll_run(run_id, api_key, timeout)

    items = fetch_dataset(dataset_id, api_key)
    if raw:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return

    if not items:
        print(json.dumps({"platform": platform, "url": url, "error": "no data returned by actor"}))
        return

    trimmer = TRIMMERS[platform]
    out = [trimmer(item, mode) for item in items]
    result = out[0] if len(out) == 1 else out
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="apify", description="Apify social scraper for acme")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for cmd_name, help_text in [
        ("scrape", "Extract caption, transcript, and hooks from a social URL (STEP 1)"),
        ("analytics", "Extract view/like/comment metrics from a published post (STEP 5)"),
    ]:
        p = sub.add_parser(cmd_name, help=help_text)
        p.add_argument("url", help="Social media URL")
        p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                       help=f"Max seconds to wait for actor (default {DEFAULT_TIMEOUT})")
        p.add_argument("--raw", action="store_true", help="Return full unfiltered Apify dataset response")

    args = parser.parse_args()
    key = load_api_key()
    run_command(args.url, args.cmd, args.timeout, args.raw, key)


if __name__ == "__main__":
    main()
