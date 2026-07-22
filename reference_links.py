#!/usr/bin/env python3
"""
reference_links.py — persistent ledger of social links USED as Mode-B FORMAT references.

This is the "IG links drop for content reference" record (Marvin 2026-06-22): a separate,
permanent log of every link whose FORMAT we have already cloned into an Acme post — so the
engine never reuses the same reference twice. It is DISTINCT from drops.py:

    drops.py            = the pending drop QUEUE (links waiting to be consumed)
    reference_links.py  = the permanent USED-references ledger (links already cloned)

The inbox / drops consume path (research.py) consults is_used() BEFORE scraping (skip a link
we've already mined, unless --force) and calls mark_used() AFTER a brief is assembled. A link can
also be pre-marked used WITHOUT producing anything (record(..., job_id=None)) — e.g. links Marvin
already used elsewhere and never wants picked again.

0 cost — pure local JSON under output/engine/ (same gitignored runtime home as manual_drops.json
and the decision ledger). Never scrapes, never spends.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import engine as e

STORE = e.ENGINE_DIR / "reference_links.json"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(url: str) -> str:
    """Normalise for dedup: lowercase, drop trailing slash + query string (?img_index=N etc.) —
    EXCEPT YouTube's video id, which lives in the query as ?v=. Without that carve-out every
    youtube.com/watch?v=<id> URL collapses to bare '.../watch' and any one used link makes ALL
    future YouTube links falsely read as 'used'. youtu.be/<id> and /shorts/<id> keep their id in
    the path already, so the plain split handles them."""
    u = (url or "").strip()
    low = u.lower()
    if "youtube.com/watch" in low:
        import urllib.parse as _up
        vid = _up.parse_qs(_up.urlparse(u).query).get("v", [""])[0]
        if vid:
            return f"https://www.youtube.com/watch?v={vid}".lower()
    return low.split("?")[0].rstrip("/")


def _platform(url: str) -> str:
    try:
        import drops
        return drops._platform(url)
    except Exception:
        return "instagram" if "instagram.com" in (url or "").lower() else "link"


def load() -> list:
    d = e.load_json(STORE)
    return d if isinstance(d, list) else []


def save(rows: list) -> None:
    e.ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def find(url: str) -> dict | None:
    n = _norm(url)
    for r in load():
        if _norm(r.get("url", "")) == n:
            return r
    return None


def is_used(url: str) -> bool:
    """True if this link (query-string-insensitive) is already recorded as a used reference."""
    r = find(url)
    return bool(r and r.get("status") == "used")


def record(url: str, *, status: str = "used", job_id: str | None = None,
           who: str = "telegram", note: str = "", platform: str | None = None) -> dict:
    """Upsert ONE link into the ledger (matched on the normalised URL). Updates job_id/note/status
    on an existing row; otherwise appends a new one. Returns the row."""
    rows = load()
    n = _norm(url)
    for r in rows:
        if _norm(r.get("url", "")) == n:
            r["status"] = status
            if job_id:
                r["job_id"] = job_id
            if note:
                r["note"] = note
            r["updated_at"] = _ts()
            save(rows)
            return r
    row = {
        "url": url, "platform": platform or _platform(url), "status": status,
        "job_id": job_id, "who": who, "note": note, "recorded_at": _ts(),
    }
    rows.append(row)
    save(rows)
    return row


def mark_used(url: str, job_id: str | None = None, **kw) -> dict:
    """Convenience: record a link as a USED reference (optionally tied to the job it produced)."""
    return record(url, status="used", job_id=job_id, **kw)


def used_urls() -> list[str]:
    return [r["url"] for r in load() if r.get("status") == "used"]


if __name__ == "__main__":          # tiny human inspector / manual recorder
    import argparse
    ap = argparse.ArgumentParser(description="Acme reference-link ledger (used Mode-B references)")
    ap.add_argument("--add", metavar="URL", help="manually record a URL as used")
    ap.add_argument("--job", default=None, help="job_id to attach to --add")
    ap.add_argument("--who", default="cli")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if a.add:
        row = mark_used(a.add, job_id=a.job, who=a.who, note=a.note)
        print("recorded:", row["url"], "->", row.get("job_id"))
    rows = load()
    used = [r for r in rows if r.get("status") == "used"]
    print(f"{len(used)} used reference link(s) of {len(rows)} recorded:")
    for r in rows:
        print(f"  [{r.get('status'):6}] {r.get('platform'):9} {r.get('job_id') or '—':9} {r['url']}")
