#!/usr/bin/env python3
"""
test_drops.py — the manual Telegram link-drop queue (drops.py), the all-user Trending feed.

Pure: no network, no credits. Runs against a temp ENGINE_DIR so the real queue is untouched.
Run:  python3 tests/test_drops.py     # exits 0 = pass, 1 = fail
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as e          # noqa: E402
import drops                # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp())
    e.ENGINE_DIR = tmp                       # redirect drops storage off the real queue
    drops.STORE = tmp / "manual_drops.json"
    fails = []

    def check(name, cond):
        print(("ok  " if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    # ── URL extraction: social + article links accepted, own/internal hosts excluded ──
    urls = drops.extract_urls("love this https://www.tiktok.com/@x/video/123! plus https://acmelabs.co/p")
    check("extract picks tiktok, drops own-domain", urls == ["https://www.tiktok.com/@x/video/123"])
    # Articles ARE now valid drops (→ Firecrawl downstream); they used to be silently ignored.
    check("article link now extracted", drops.extract_urls("see https://www.nytimes.com/x")
          == ["https://www.nytimes.com/x"])
    check("own/internal hosts still excluded", drops.extract_urls(
        "https://docs.google.com/d/1 and https://acmelabs.co/shop and https://t.me/c/9") == [])
    check("non-URL text yields nothing", drops.extract_urls("just chatting, no links here") == [])
    check("multiple content urls kept", len(drops.extract_urls(
        "https://instagram.com/reel/a and https://youtu.be/b")) == 2)
    check("generic article gets 'article' platform", drops._platform("https://www.nature.com/articles/x") == "article")

    # ── enqueue + dedup (zero cost) ──
    r1 = drops.enqueue("https://www.instagram.com/reel/abc/", who="dan")
    check("enqueue returns a pending row, +3 priority",
          bool(r1) and r1["platform"] == "instagram" and r1["status"] == "pending"
          and r1["priority_bonus"] == 3 and r1["who"] == "dan")
    check("duplicate (normalised, ignores query) is dropped",
          drops.enqueue("https://www.instagram.com/reel/abc?utm=ig", who="someone") is None)
    check("own/internal URL is not enqueued", drops.enqueue("https://docs.google.com/d/1") is None)
    ra = drops.enqueue("https://www.nytimes.com/x", who="dan")
    check("an article link enqueues as 'article'",
          bool(ra) and ra["platform"] == "article" and ra["status"] == "pending")
    r2 = drops.enqueue("https://x.com/u/status/9", who="marvin")
    check("a different user's X link enqueues", bool(r2) and r2["platform"] == "x" and r2["who"] == "marvin")

    # ── pending is FIFO; mark moves rows out of pending ──
    check("pending FIFO order",
          [r["url"] for r in drops.pending()] == ["https://www.instagram.com/reel/abc/",
                                                  "https://www.nytimes.com/x",
                                                  "https://x.com/u/status/9"])
    check("pending honours limit", len(drops.pending(limit=1)) == 1)
    drops.mark(r1["id"], "consumed", job_id="ACME-999")
    drops.mark(ra["id"], "consumed", job_id="ACME-998")
    check("consumed rows leave the pending queue", [r["id"] for r in drops.pending()] == [r2["id"]])
    check("consumed row keeps its job_id",
          any(r["id"] == r1["id"] and r["status"] == "consumed" and r["job_id"] == "ACME-999"
              for r in drops.load()))

    # ── a failed URL may be retried (re-enqueued), a live one may not ──
    drops.mark(r2["id"], "failed")
    check("failed URL can be re-enqueued", drops.enqueue("https://x.com/u/status/9") is not None)

    print("PASS" if not fails else f"FAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
