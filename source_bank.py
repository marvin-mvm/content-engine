"""source_bank.py — Acme Source Bank (RV0): harvest a long source's FULL transcript
ONCE, then mine it many times at 0 extraction cost.

WHY (Marvin, 2026-06-18): one expensive extraction on a long source — a 1-hour
interview/podcast, a long YouTube — contains far more than one post's worth of material.
Mode B used to scrape a source, use a sliver, and discard the rest (apify's trimmed shape
even truncates the transcript to ~4k chars). We bank the FULL extraction once (via the
existing `--raw` flag), propose N distinct content angles from it, then build briefs from
unused angles with ZERO new extraction spend. Feeds BOTH carousels/images (F3) and reels
(F7). The bank is the SINGLE extraction point — Apify (social/video) fires a fresh (paid)
actor run on every call and does NOT cache by URL, and Firecrawl (articles) bills per
scrape, so we never pay for both a `--raw` and a structured scrape of the same source.

DESIGN (local-JSON now; a Supabase `sources` table plugs in later, same additive path as
research.py's DiscoveryStore):

    output/research/sources/<sha-url>.json = {
        url, source_id, platform, scraped_at,
        full_transcript, transcript_chars, caption, engagement,
        reference,                     # the inspiring source's provenance (or null)
        angles: [ {id, angle, pillar, format, used, job_id} ]
    }

This module is a PURE transform + storage layer: it never fires the paid extraction itself
(that stays in research.py's cached run_tool). research.py hands it the already-fetched
`--raw` payload; source_bank parses, banks, proposes angles, and serves unused ones.

CLI (ops / proving):
    python3 source_bank.py list
    python3 source_bank.py show   <url|source_id>
    python3 source_bank.py angles <url|source_id> [--n N] [--brand labs|health]
    python3 source_bank.py bank-struct <url> <structured.json>   # bank from a structured/cache payload (no spend)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the shared, single-source-of-truth engines — NEVER duplicate brand voice or
# compliance, and never modify those files (import their pure helpers only).
from copywriter import call_openrouter, extract_json, load_api_key, DEFAULT_MODEL, BRAND_SYSTEM
from compliance import red_hits, PROMPT_RULES
from apify import parse_srt_to_text

WS = Path(__file__).parent.resolve()
SOURCES_DIR = WS / "output" / "research" / "sources"

VALID_PILLARS = ("science", "stack", "trending", "proof", "founder")
VALID_FORMATS = ("carousel", "reel", "callout")


# ── identity / paths ──────────────────────────────────────────────────────────

def source_id(url: str) -> str:
    """Stable short id for a source URL (the bank filename stem)."""
    return hashlib.sha1((url or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def bank_path(url_or_id: str) -> Path:
    sid = url_or_id if _looks_like_id(url_or_id) else source_id(url_or_id)
    return SOURCES_DIR / f"{sid}.json"


def _looks_like_id(s: str) -> bool:
    return len(s) == 16 and all(c in "0123456789abcdef" for c in s.lower())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── raw → normalized content (handles both `--raw` actor items and structured cache) ──

def _num(v) -> int:
    """Coerce a possibly-string count (e.g. '2.6M', '73,000') to an int."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    mult = 1
    if s and s[-1].lower() in "kmb":
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[s[-1].lower()]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def normalize_payload(payload) -> tuple[str, str, dict]:
    """Extract (full_transcript, caption, engagement) from any extraction-tool payload:
      • apify `--raw` actor payload  — list of raw items, transcript in `subtitles[].srt`
      • Firecrawl scrape (articles)  — page body in `markdown`; two shapes:
            --raw:    {"success": true, "data": {"markdown", "metadata": {...}}}
            trimmed:  {"url", "title", "description", "markdown"}
      • an already-structured payload (apify-trimmed / a research cache, transcript a string)

    The FULL text is parsed with NO truncation — that is the whole point of `--raw`.
    """
    item = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(item, dict):
        return "", "", {}

    # Firecrawl `--raw` nests the page under data{markdown, metadata}; flatten it so the
    # field lookups below see markdown/description/title at the top level (the trimmed
    # Firecrawl shape is already flat). Articles carry no view/like/comment engagement.
    fc = item.get("data")
    if isinstance(fc, dict) and ("markdown" in fc or "metadata" in fc):
        meta = fc.get("metadata") if isinstance(fc.get("metadata"), dict) else {}
        item = {
            "markdown": fc.get("markdown"),
            "description": meta.get("description") or meta.get("og:description"),
            "title": meta.get("title") or meta.get("og:title"),
        }

    # 1. Transcript — raw subtitle cues (FULL, untruncated) win; else a structured string;
    #    else the Firecrawl article body (`markdown`).
    transcript = ""
    subs = item.get("subtitles")
    if isinstance(subs, list) and subs:
        en = [s.get("srt", "") for s in subs if isinstance(s, dict) and s.get("language") == "en"]
        srt = " ".join(en) or " ".join(s.get("srt", "") for s in subs if isinstance(s, dict))
        transcript = parse_srt_to_text(srt)
    if not transcript:
        transcript = item.get("transcript") or item.get("content") or item.get("markdown") or ""

    # 2. Caption / surrounding text (any platform field name).
    caption = (item.get("caption") or item.get("description") or item.get("text")
               or item.get("summary") or item.get("title") or "")

    # 3. Engagement (raw + structured + nested tiktok stats field names).
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    engagement = {
        "views": _num(item.get("views") or item.get("viewCount") or item.get("videoViewCount")
                      or item.get("videoPlayCount") or stats.get("playCount")),
        "likes": _num(item.get("likes") or item.get("likeCount") or item.get("likesCount")
                      or stats.get("diggCount")),
        "comments": _num(item.get("comments_count") or item.get("commentsCount")
                         or item.get("commentCount") or stats.get("commentCount")),
    }
    return str(transcript), str(caption)[:3000], engagement


# ── store ─────────────────────────────────────────────────────────────────────

def load(url_or_id: str) -> dict | None:
    p = bank_path(url_or_id)
    return json.loads(p.read_text()) if p.exists() else None


def save(record: dict) -> Path:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    p = bank_path(record["source_id"])
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return p


def upsert(url: str, platform: str, payload, *, reference: dict | None = None) -> dict:
    """Bank (or refresh) a source from a `--raw`/structured payload. Existing `angles`
    (and their used/job_id state) are PRESERVED across re-scrapes; a richer transcript on a
    re-scrape only replaces a thinner one."""
    full_transcript, caption, engagement = normalize_payload(payload)
    existing = load(url) or {}
    # Never let a re-scrape that returned a shorter transcript clobber a longer banked one.
    if len(full_transcript) < len(existing.get("full_transcript", "")):
        full_transcript = existing["full_transcript"]
    record = {
        "url": url,
        "source_id": source_id(url),
        "platform": platform,
        "scraped_at": now_iso(),
        "full_transcript": full_transcript,
        "transcript_chars": len(full_transcript),
        "caption": caption or existing.get("caption", ""),
        "engagement": engagement or existing.get("engagement", {}),
        "reference": reference if reference is not None else existing.get("reference"),
        "angles": existing.get("angles", []),
    }
    save(record)
    return record


# ── angle proposal (one cheap OpenRouter call; 0 Higgsfield credits) ────────────

_ANGLE_SYSTEM = (
    BRAND_SYSTEM
    + "\n\n" + PROMPT_RULES
    + "\n\nYou are mining ONE long source transcript for a backlog of distinct Acme content "
      "ideas. Each idea is a SEED for a separate post — they must NOT overlap. Stay in the "
      "Research-Pharmacist voice and obey the compliance framework above (never a RED claim). "
      "Do not copy the source's wording or claims; extract the underlying angle and re-pour it "
      "into Acme's research-grade framing."
)


def propose_angles(record: dict, n: int = 6, *, brand: str = "labs",
                   model: str = DEFAULT_MODEL, api_key: str | None = None) -> dict:
    """Read the banked transcript → propose up to N distinct content angles and APPEND the
    new ones to record['angles'] (deduped by angle text, RED claims dropped). Returns the
    updated record (and persists it). One OpenRouter call — no Higgsfield credits."""
    transcript = (record.get("full_transcript") or "").strip()
    if not transcript:
        print("[source-bank] no transcript to mine", file=sys.stderr)
        return record
    api_key = api_key or load_api_key()
    user = (
        f"Brand: Acme {brand.title()}.\n"
        f"Source platform: {record.get('platform')}. Source caption: {record.get('caption','')[:300]}\n\n"
        f"SOURCE TRANSCRIPT (mine this — it is the only thing you may use):\n{transcript[:12000]}\n\n"
        f"Propose {n} DISTINCT Acme content angles drawn from DIFFERENT moments/ideas in the "
        f"transcript. Spread them across pillars and formats. Return ONLY a JSON object:\n"
        '{ "angles": [ { "angle": "<one specific, compliant content angle in plain English>", '
        f'"pillar": "<one of {"|".join(VALID_PILLARS)}>", '
        f'"format": "<one of {"|".join(VALID_FORMATS)}>" }} ] }}\n'
        "reel = a 15-45s spoken b-roll video idea; carousel = a multi-slide explainer; "
        "callout = a single stat/claim card. Make at least a third of them reels."
    )
    resp = call_openrouter(
        [{"role": "system", "content": _ANGLE_SYSTEM}, {"role": "user", "content": user}],
        model, api_key,
    )
    content = resp["choices"][0]["message"]["content"]
    data = extract_json(content)
    proposed = data.get("angles", data) if isinstance(data, dict) else data
    if not isinstance(proposed, list):
        print("[source-bank] model returned no angle list", file=sys.stderr)
        return record

    existing = record.setdefault("angles", [])
    seen = {(_norm(a.get("angle"))) for a in existing}
    added = 0
    for a in proposed:
        if not isinstance(a, dict):
            continue
        text = (a.get("angle") or "").strip()
        if not text or _norm(text) in seen:
            continue
        if red_hits(text):  # never bank a non-compliant seed
            print(f"[source-bank] dropped RED angle: {text[:70]!r}", file=sys.stderr)
            continue
        pillar = a.get("pillar") if a.get("pillar") in VALID_PILLARS else "trending"
        fmt = a.get("format") if a.get("format") in VALID_FORMATS else "carousel"
        existing.append({
            "id": f"ang-{len(existing) + 1:03d}",
            "angle": text, "pillar": pillar, "format": fmt,
            "used": False, "job_id": None,
        })
        seen.add(_norm(text))
        added += 1
    save(record)
    print(f"[source-bank] +{added} angle(s) banked ({len(existing)} total) -> {bank_path(record['source_id']).name}",
          file=sys.stderr)
    return record


def _norm(s) -> str:
    return " ".join((s or "").lower().split())


# ── serve unused angles → briefs ────────────────────────────────────────────────

def unused_angles(record: dict, *, fmt: str | None = None, pillar: str | None = None) -> list[dict]:
    out = []
    for a in record.get("angles", []):
        if a.get("used"):
            continue
        if fmt and a.get("format") != fmt:
            continue
        if pillar and a.get("pillar") != pillar:
            continue
        out.append(a)
    return out


def mark_used(record: dict, angle_id: str, job_id: str) -> dict:
    for a in record.get("angles", []):
        if a.get("id") == angle_id:
            a["used"] = True
            a["job_id"] = job_id
            break
    save(record)
    return record


def all_sources() -> list[dict]:
    if not SOURCES_DIR.exists():
        return []
    out = []
    for p in sorted(SOURCES_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ── CLI (ops / proving) ─────────────────────────────────────────────────────────

def _resolve(url_or_id: str) -> dict:
    rec = load(url_or_id)
    if not rec:
        sys.exit(f"[source-bank] no banked source for {url_or_id!r}")
    return rec


def main():
    ap = argparse.ArgumentParser(prog="source_bank", description="Acme Source Bank (RV0)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List banked sources + their unused-angle counts")

    ps = sub.add_parser("show", help="Show one banked source")
    ps.add_argument("source", help="source URL or 16-char id")

    pa = sub.add_parser("angles", help="Propose N angles from a banked source (1 OpenRouter call)")
    pa.add_argument("source", help="source URL or 16-char id")
    pa.add_argument("--n", type=int, default=6)
    pa.add_argument("--brand", default="labs", choices=["labs", "health"])

    pb = sub.add_parser("bank-struct", help="Bank from a structured/cache payload (no extraction spend)")
    pb.add_argument("url", help="canonical source URL")
    pb.add_argument("payload", help="path to a structured JSON payload (apify cache / blotato source)")
    pb.add_argument("--platform", help="override platform (else inferred from the payload)")

    args = ap.parse_args()

    if args.cmd == "list":
        rows = all_sources()
        if not rows:
            print("(no banked sources yet)")
            return
        for r in rows:
            nu = len(unused_angles(r))
            print(f"  {r['source_id']}  {r['platform']:<9} {r['transcript_chars']:>6}c  "
                  f"{nu} unused/{len(r.get('angles', []))} angles  {r['url'][:60]}")
        return

    if args.cmd == "show":
        print(json.dumps(_resolve(args.source), ensure_ascii=False, indent=2))
        return

    if args.cmd == "angles":
        rec = propose_angles(_resolve(args.source), n=args.n, brand=args.brand)
        for a in rec.get("angles", []):
            flag = "·" if a["used"] else " "
            print(f" {flag}{a['id']}  [{a['format']}/{a['pillar']}]  {a['angle']}")
        return

    if args.cmd == "bank-struct":
        payload = json.loads(Path(args.payload).read_text())
        item = payload[0] if isinstance(payload, list) and payload else payload
        platform = args.platform or (item.get("platform") if isinstance(item, dict) else None) or "article"
        rec = upsert(args.url, platform, payload)
        print(f"[source-bank] banked {rec['source_id']} ({platform}) · "
              f"{rec['transcript_chars']} transcript chars -> {bank_path(rec['source_id'])}")
        return


if __name__ == "__main__":
    main()
