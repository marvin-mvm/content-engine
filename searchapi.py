#!/usr/bin/env python3
"""
SearchAPI CLI for ACME agent.
Wraps the SearchAPI.io REST endpoint at https://www.searchapi.io/api/v1/search.

Usage:
  searchapi.py news    QUERY  [--num N] [--gl COUNTRY] [--hl LANG] [--raw]
  searchapi.py search  QUERY  [--num N] [--gl COUNTRY] [--hl LANG] [--raw]
  searchapi.py youtube QUERY  [--num N] [--gl COUNTRY] [--hl LANG] [--raw]
  searchapi.py trends  QUERY  [--geo COUNTRY] [--raw]

Reads SEARCHAPI_API_KEY from .env (same folder as this script) or the
environment. --raw returns the full SearchAPI response; default returns a
trimmed, agent-friendly JSON shape.
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
API_BASE = "https://www.searchapi.io/api/v1/search"


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
            if line.startswith("SEARCHAPI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("SEARCHAPI_API_KEY")
    if key:
        return key
    sys.exit("ERROR: SEARCHAPI_API_KEY not found in .env or environment")


def call_api(params):
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "acme-searchapi/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:                                   # quota/credit exhaustion -> Telegram heads-up
            import api_alerts
            api_alerts.note("searchapi", code=e.code, body=body)
        except Exception:
            pass
        sys.exit(f"ERROR: SearchAPI {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure: {e}")


def trim_news(data, limit):
    out = []
    for item in (data.get("organic_results") or [])[:limit]:
        src = item.get("source")
        out.append({
            "title": item.get("title"),
            "source": src.get("name") if isinstance(src, dict) else src,
            "link": item.get("link"),
            "snippet": item.get("snippet"),
            "date": item.get("date"),
        })
    return {"query": (data.get("search_parameters") or {}).get("q"), "results": out}


def trim_search(data, limit):
    out = []
    for item in (data.get("organic_results") or [])[:limit]:
        out.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet"),
            "displayed_link": item.get("displayed_link"),
            "position": item.get("position"),
        })
    return {
        "query": (data.get("search_parameters") or {}).get("q"),
        "answer_box": data.get("answer_box"),
        "results": out,
    }


def trim_youtube(data, limit):
    out = []
    for item in (data.get("videos") or [])[:limit]:
        out.append({
            "title": item.get("title"),
            "channel": (item.get("channel") or {}).get("title") if isinstance(item.get("channel"), dict) else item.get("channel"),
            "link": item.get("link"),
            "views": item.get("views"),
            "length": item.get("length"),
            "published_at": item.get("published_time") or item.get("published_at"),
            "description": item.get("description"),
            "thumbnail": (item.get("thumbnail") or {}).get("static") if isinstance(item.get("thumbnail"), dict) else item.get("thumbnail"),
        })
    return {"query": (data.get("search_parameters") or {}).get("q"), "results": out}


def trim_trends(data):
    return {
        "query": (data.get("search_parameters") or {}).get("q"),
        "interest_over_time": data.get("interest_over_time"),
        "related_queries": data.get("related_queries"),
        "related_topics": data.get("related_topics"),
        "trending_searches": data.get("trending_searches"),
    }


def main():
    parser = argparse.ArgumentParser(prog="searchapi", description="SearchAPI.io CLI for acme")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, with_locale=True):
        p.add_argument("query", help="Search query")
        p.add_argument("--num", type=int, default=10, help="Max results (default 10)")
        if with_locale:
            p.add_argument("--gl", default="us", help="Country code (default us)")
            p.add_argument("--hl", default="en", help="Language code (default en)")
        p.add_argument("--raw", action="store_true", help="Return full unfiltered SearchAPI response")

    p_news = sub.add_parser("news", help="Google News search")
    common(p_news)

    p_search = sub.add_parser("search", help="Google web search")
    common(p_search)

    p_youtube = sub.add_parser("youtube", help="YouTube search")
    common(p_youtube)

    p_trends = sub.add_parser("trends", help="Google Trends data")
    p_trends.add_argument("query", help="Topic to fetch trend data for")
    p_trends.add_argument("--geo", default="US", help="Country code for trends (default US)")
    p_trends.add_argument("--raw", action="store_true", help="Return full unfiltered SearchAPI response")

    args = parser.parse_args()
    key = load_api_key()

    if args.cmd == "news":
        data = call_api({"engine": "google_news", "q": args.query, "api_key": key,
                         "num": args.num, "gl": args.gl, "hl": args.hl})
        out = data if args.raw else trim_news(data, args.num)
    elif args.cmd == "search":
        data = call_api({"engine": "google", "q": args.query, "api_key": key,
                         "num": args.num, "gl": args.gl, "hl": args.hl})
        out = data if args.raw else trim_search(data, args.num)
    elif args.cmd == "youtube":
        data = call_api({"engine": "youtube", "q": args.query, "api_key": key,
                         "gl": args.gl, "hl": args.hl})
        out = data if args.raw else trim_youtube(data, args.num)
    elif args.cmd == "trends":
        data = call_api({"engine": "google_trends", "q": args.query, "api_key": key,
                         "geo": args.geo, "data_type": "TIMESERIES"})
        out = data if args.raw else trim_trends(data)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
