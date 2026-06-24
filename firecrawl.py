#!/usr/bin/env python3
"""
Firecrawl CLI for ACME agent.
Uses the Firecrawl v2 REST API directly (no CLI install required).

Usage:
  firecrawl.py scrape URL  [--timeout N] [--raw]
  firecrawl.py search QUERY [--num N] [--scrape] [--raw]

Reads FIRECRAWL_API_KEY from .env (same folder as this script) or the
environment. --raw returns the full API response; default returns a
trimmed, agent-friendly shape.

scrape: Extract clean markdown from a single URL.
search: Discover pages by query. Add --scrape to also return the full
        markdown content for each result (much slower, uses more credits).
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_BASE = "https://api.firecrawl.dev/v2"
MAX_MARKDOWN_CHARS = 8000  # trim very long articles so context stays manageable


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def load_api_key():
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("FIRECRAWL_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("FIRECRAWL_API_KEY")
    if key:
        return key
    sys.exit("ERROR: FIRECRAWL_API_KEY not found in .env or environment")


def post_json(endpoint, payload, api_key):
    url = f"{API_BASE}{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "acme-firecrawl/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:                                   # quota/credit exhaustion -> Telegram heads-up
            import api_alerts
            api_alerts.note("firecrawl", code=e.code, body=body)
        except Exception:
            pass
        sys.exit(f"ERROR: Firecrawl {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure: {e}")


def trim_markdown(md):
    if md and len(md) > MAX_MARKDOWN_CHARS:
        return md[:MAX_MARKDOWN_CHARS] + "\n\n[…content truncated at 8000 chars…]"
    return md


def cmd_scrape(url, timeout, raw, api_key):
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": timeout * 1000,  # API takes ms
    }
    data = post_json("/scrape", payload, api_key)
    if raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data.get("success"):
        sys.exit(f"ERROR: Firecrawl scrape failed: {data}")
    d = data.get("data") or {}
    meta = d.get("metadata") or {}
    out = {
        "url": url,
        "title": meta.get("title") or meta.get("og:title"),
        "description": meta.get("description") or meta.get("og:description"),
        "markdown": trim_markdown(d.get("markdown")),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_search(query, num, include_content, raw, api_key):
    payload = {"query": query, "limit": num}
    if include_content:
        payload["scrapeOptions"] = {"formats": ["markdown"], "onlyMainContent": True}
    data = post_json("/search", payload, api_key)
    if raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data.get("success"):
        sys.exit(f"ERROR: Firecrawl search failed: {data}")
    results = []
    raw_data = data.get("data") or {}
    items = raw_data if isinstance(raw_data, list) else (raw_data.get("web") or [])
    for item in items:
        r = {
            "title": item.get("title"),
            "url": item.get("url"),
            "description": item.get("description"),
        }
        if include_content:
            r["markdown"] = trim_markdown(item.get("markdown"))
        results.append(r)
    print(json.dumps({"query": query, "results": results}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="firecrawl", description="Firecrawl REST CLI for acme")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scrape = sub.add_parser("scrape", help="Extract clean markdown from a single URL")
    p_scrape.add_argument("url", help="URL to scrape")
    p_scrape.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds (default 30)")
    p_scrape.add_argument("--raw", action="store_true", help="Return full unfiltered Firecrawl response")

    p_search = sub.add_parser("search", help="Search and optionally scrape results")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--num", type=int, default=5, help="Max results (default 5)")
    p_search.add_argument("--scrape", action="store_true", dest="include_content",
                          help="Also return full markdown for each result (slower, more credits)")
    p_search.add_argument("--raw", action="store_true", help="Return full unfiltered Firecrawl response")

    args = parser.parse_args()
    key = load_api_key()

    if args.cmd == "scrape":
        cmd_scrape(args.url, args.timeout, args.raw, key)
    elif args.cmd == "search":
        cmd_search(args.query, args.num, args.include_content, args.raw, key)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
