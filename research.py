#!/usr/bin/env python3
"""research.py — Acme F3 Research module (the manual-topic replacement).

Produces brief.json files automatically, in TWO discovery modes, at 0 Higgsfield
credits. It is the missing front-end of the engine: research finds *what to post*,
the existing core (copywriter.py -> post.py / reel.py) renders it.

  MODE A — topic discovery  (`research.py topics`)
    Sweep PubMed/news/trends (searchapi/firecrawl) -> candidate topics, score by the
    six SOUL §8 weights × engine_state topic_weights (respecting blocked_topics),
    print the per-topic breakdown, pick the top N -> brief.json files.

  MODE B — viral-outlier mining + format cloning  (`research.py outliers` / `inbox`)
    Find posts whose engagement is far above baseline (YouTube via searchapi —
    view velocity), OR take a dropped link (any platform). Extract the pattern
    (apify.py scrape / blotato.py source), then RECONFIGURE: rewrite the hook in the
    Research-Pharmacist voice via copywriter.py, map the format to a template, STRIP the
    original's claims, apply compliance -> a Trending-Hook brief.json.
    CLONE THE STRUCTURE, NEVER THE CONTENT.

Both modes assemble briefs via the Part 1A.2 pillar presets (pillar -> template +
persona + brand), validate against schemas/brief.schema.json, and log discovery to
a local JSON store (discovery_queue + daily_brief). Marvin's call (2026-06-18):
local-JSON-first — a Supabase db.py can replace DiscoveryStore additively later.

The shared tools (searchapi.py/firecrawl.py/apify.py/blotato.py/copywriter.py) are called
as black-box subprocesses and never modified. Every paid call is cached under
output/research/cache/ (24h TTL) so re-runs don't re-spend — apify is the priciest
call, so Mode B fires it once per URL only.

Usage:
  research.py topics  [--candidates A,B] [--select K] [--pillar P] [--dry-run] [--fresh]
  research.py outliers [--query Q] [--num N] [--extract] [--dry-run] [--fresh]
  research.py inbox   URL [--pillar trending] [--persona P3] [--brand labs|health]
  research.py run     [--select 5]     # full day: 5 pillar briefs (topics + outliers)

Add --dry-run to score + select + print WITHOUT calling copywriter.py or writing briefs
(the cheap iteration path). Reads API keys from .env via the shared tools.
"""

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WS = Path(__file__).parent.resolve()
PY = sys.executable or "python3"
CACHE_DIR = WS / "output" / "research" / "cache"
RESEARCH_DIR = WS / "output" / "research"
JOBS_DIR = WS / "output" / "jobs"
SCHEMA_PATH = WS / "schemas" / "brief.schema.json"
CACHE_TTL = 24 * 3600  # seconds


# ── Strategy config (SOUL §7-9, MIGRATION 1A.1/1A.2, CONTENT_ENGINE_GUIDE §2/§5) ──

# Pillar -> default template + the template families it may use + persona default.
# Defaults are picked so copywriter.py can fill the renderable token set directly
# (story-reel-dark tokens === copywriter.py overlay output). Everything renders at 0 credits.
PILLAR_PRESETS = {
    "science":  {"template": "story-reel-dark", "alts": ["carousel-dark", "static-callout-dark"],
                 "persona": "P1", "slot": "08:00", "platforms": ["instagram", "tiktok", "x"]},
    "stack":    {"template": "static-compound-dark", "alts": ["carousel-dark"],
                 "persona": "P1", "slot": "11:00", "platforms": ["instagram", "tiktok"],
                 "product_feature": True},
    "trending": {"template": "story-reel-dark", "alts": ["carousel-dark"],
                 "persona": "P3", "slot": "13:00", "platforms": ["instagram", "tiktok"]},
    "proof":    {"template": "story-reel-dark", "alts": ["static-callout-dark", "carousel-dark"],
                 "persona": "P3", "slot": "16:00", "platforms": ["instagram", "x", "threads"]},
    "founder":  {"template": "story-reel-dark", "alts": ["carousel-dark"],
                 "persona": "P1", "slot": "19:00", "platforms": ["instagram", "x"]},
}

# Templates that produce a multi-slide deck (slides.json) rather than one card.
CAROUSEL_TEMPLATES = {"carousel-dark", "carousel-light"}
CAROUSEL_DEFAULT_SLIDES = 5

# Persona voice hint injected into the copywriter.py topic string (copywriter.py has no persona
# arg and we don't modify it — backward-compatible). MIGRATION 1A.1 / guide §1.
PERSONA_VOICE = {
    "P1": "Audience: The Optimizer — data-dense, mechanism + numbers, ROI/return language.",
    "P2": "Audience: The Health-Forward Affluent Woman — aspirational, premium, outcome/lifestyle-framed.",
    "P3": "Audience: The Curious Newcomer — plain English, curiosity hook, define every term.",
}

# Acme compound universe (PRODUCTS.md). Drives product_tie scoring, brand routing,
# and the class/spec chips on stack (static-compound) briefs.
COMPOUND_CATALOG = {
    "Semaglutide":  {"cls": "GLP-1 ANALOG", "spec": "GLP-1 analog · 5mg lyophilized · ≥99% HPLC purity",
                     "descriptor": "Incretin mimetic for metabolic research", "price": "$149", "live": True, "sku": "semaglutide-5mg"},
    "Tirzepatide":  {"cls": "GIP/GLP-1 ANALOG", "spec": "Dual GIP/GLP-1 agonist · research-grade",
                     "descriptor": "Dual incretin receptor research compound", "price": "—", "live": False},
    "Retatrutide":  {"cls": "TRIPLE AGONIST", "spec": "GLP-1/GIP/glucagon agonist · research-grade",
                     "descriptor": "Triple-agonist metabolic research compound", "price": "—", "live": False},
    "BPC-157":      {"cls": "PENTADECAPEPTIDE", "spec": "Body Protection Compound 157 · 5mg lyophilized · ≥99% HPLC purity",
                     "descriptor": "Tissue-repair signaling research peptide", "price": "$59", "live": True, "sku": "bpc-157-5mg"},
    "TB-500":       {"cls": "THYMOSIN β-4 FRAGMENT", "spec": "Thymosin Beta-4 fragment · research-grade",
                     "descriptor": "Angiogenesis & repair research peptide", "price": "—", "live": False},
    "CJC-1295":     {"cls": "GHRH ANALOG", "spec": "GHRH/GHRP dual-action blend · 10mg lyophilized · ≥99% HPLC purity",
                     "descriptor": "Growth-hormone axis research blend", "price": "$89", "live": True, "sku": "cjc-1295-ipamorelin"},
    "Ipamorelin":   {"cls": "GHRP", "spec": "GHRH/GHRP dual-action blend · 10mg lyophilized · ≥99% HPLC purity",
                     "descriptor": "Selective ghrelin-receptor research peptide", "price": "$89", "live": True, "sku": "cjc-1295-ipamorelin"},
    "NAD+":         {"cls": "PRECURSOR RESEARCH", "spec": "NAD+ precursor research compound",
                     "descriptor": "Mitochondrial NAD+ biology research", "price": "—", "live": False},
    "Epithalon":    {"cls": "TETRAPEPTIDE", "spec": "Pineal tetrapeptide · 20mg lyophilized · ≥99% HPLC purity",
                     "descriptor": "Telomerase & longevity research peptide", "price": "$79", "live": True, "sku": "epithalon-20mg"},
    "Semax":        {"cls": "NEUROPEPTIDE", "spec": "Nootropic neuropeptide · research-grade",
                     "descriptor": "BDNF-modulation research peptide", "price": "—", "live": False},
    "Selank":       {"cls": "NEUROPEPTIDE", "spec": "Anxiolytic neuropeptide · research-grade",
                     "descriptor": "CNS-signaling research peptide", "price": "—", "live": False},
    "GHK-Cu":       {"cls": "COPPER TRIPEPTIDE", "spec": "Copper tripeptide · research-grade",
                     "descriptor": "Skin/collagen & longevity research peptide", "price": "—", "live": False},
}

# Health-brand routing: metabolic/weight/results angles run on Acme Health (may run
# paid); everything else defaults to Labs (RUO, organic-only). MIGRATION 1A / §5.1.
HEALTH_KEYWORDS = re.compile(
    r"\b(metabolic|weight|glp-?1|semaglutide|tirzepatide|retatrutide|appetite|"
    r"glyc|fat\s*loss|body\s*comp|protocol|results|transformation|longevity\s*program)\b",
    re.IGNORECASE)

# SOUL §8 — Mode A topic scoring weights.
SCORE_WEIGHTS = {
    "trending_velocity": 0.25,
    "comment_bait": 0.20,
    "search_volume": 0.20,
    "educational": 0.15,
    "product_tie": 0.10,
    "recency": 0.10,
}

# Devon's Mode B viral-opportunity scoring (CONTENT_ENGINE_GUIDE §5, 1-10 each + bonuses).
MODE_B_FACTORS = ["niche_fit", "persona_fit", "format_adaptability", "buyer_intent"]

# Viral format archetypes (CONTENT_ENGINE_GUIDE §2 P3 + VIRAL_FRAMEWORK). Used to
# classify an extracted post's structure and to map it to a template + reconfigure.
FORMAT_ARCHETYPES = {
    "this_or_that":   {"keywords": ["vs", "versus", "or", "this or that", "which is better"],
                       "template": "story-reel-dark", "recipe": "This-or-That comparison"},
    "myth_bust":      {"keywords": ["myth", "stop", "wrong", "lie", "don't", "actually", "truth"],
                       "template": "story-reel-dark", "recipe": "Myth-bust: 'Stop X / Start Y'"},
    "wish_i_knew":    {"keywords": ["wish i knew", "before i", "i learned", "things i"],
                       "template": "carousel-dark", "recipe": "'Things I wish I knew before X' list"},
    "controversial":  {"keywords": ["unpopular", "controversial", "hot take", "nobody", "overrated"],
                       "template": "story-reel-dark", "recipe": "Controversial take"},
    "study_reaction": {"keywords": ["study", "research", "scientists", "data", "found", "trial"],
                       "template": "story-reel-dark", "recipe": "Reaction-to-study"},
    "list_countdown": {"keywords": ["top", "best", "5 ", "things", "ways", "reasons"],
                       "template": "carousel-dark", "recipe": "List / countdown"},
}

# Mode A sweep seeds + Mode B YouTube niche queries (SOUL §7 / guide §5).
SWEEP_NEWS_QUERY = "peptides longevity BPC-157 GLP-1 NAD+ healthspan research"
OUTLIER_YT_QUERIES = [
    "peptides longevity", "biohacking longevity", "GLP-1 metabolic health",
    "NAD+ anti-aging", "peptide therapy research",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[research] {msg}", file=sys.stderr)


# ── Cached subprocess tool calls (economy lever) ──────────────────────────────

def run_tool(script, args, ttl=CACHE_TTL, fresh=False):
    """Run a shared tool (searchapi/firecrawl/apify/blotato) and parse its stdout
    JSON. Results are cached on the full argv so identical calls never re-spend."""
    argv = [PY, str(WS / script), *[str(a) for a in args]]
    key = hashlib.sha1((" ".join(argv)).encode()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{Path(script).stem}_{key}.json"
    if not fresh and cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < ttl:
        log(f"cache hit  {script} {args[:2]}")
        return json.loads(cache_file.read_text())
    log(f"calling    {script} {' '.join(str(a) for a in args)}")
    r = subprocess.run(argv, capture_output=True, text=True, cwd=WS)
    if r.returncode != 0:
        log(f"WARN {script} exited {r.returncode}: {(r.stderr or r.stdout)[-300:].strip()}")
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"WARN {script} returned non-JSON: {r.stdout[:200]!r}")
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False))
    return data


# ── Parsers for messy real-world signal data ──────────────────────────────────

def parse_count(v):
    """'1.2M' / '34,000' / 1200 -> int."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower().replace(",", "").replace("views", "").strip()
    m = re.match(r"([\d.]+)\s*([kmb]?)", s)
    if not m:
        return 0
    n = float(m.group(1))
    return int(n * {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2), 1))


def age_days(published):
    """Relative ('3 days ago') or ISO date -> age in days (float). Unknown -> 9999."""
    if not published:
        return 9999.0
    s = str(published).strip().lower()
    m = re.search(r"(\d+)\s*(hour|day|week|month|year)s?\s*ago", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return n * {"hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}[unit]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
            return max(0.0, (datetime.now() - dt).total_seconds() / 86400)
        except ValueError:
            continue
    try:  # ISO with timezone
        dt = datetime.fromisoformat(s.replace("z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        return 9999.0


def clamp01(x):
    return max(0.0, min(1.0, x))


# ══════════════════════════════════════════════════════════════════════════════
# MODE A — topic discovery (sweep -> SOUL §8 score -> select)
# ══════════════════════════════════════════════════════════════════════════════

def gather_signals(topic, fresh=False):
    """Two cheap searchapi calls (trends + news) -> the raw signals all six §8
    factors are computed from. Robust to missing/empty responses."""
    sig = {"trends_now": None, "trends_slope": None, "news_count": 0,
           "newest_age": 9999.0, "debate_hits": 0, "snippets": []}

    trends = run_tool("searchapi.py", ["trends", topic], fresh=fresh)
    series = []
    if trends and isinstance(trends.get("interest_over_time"), dict):
        for pt in (trends["interest_over_time"].get("timeline_data") or []):
            vals = pt.get("values") or []
            if vals:
                ev = vals[0].get("extracted_value", vals[0].get("value"))
                try:
                    series.append(float(ev))
                except (TypeError, ValueError):
                    pass
    if series:
        sig["trends_now"] = series[-1]
        recent = sum(series[-4:]) / len(series[-4:])
        prior = sum(series[-8:-4]) / max(1, len(series[-8:-4])) if len(series) >= 8 else recent
        sig["trends_slope"] = recent - prior

    news = run_tool("searchapi.py", ["news", topic, "--num", "10"], fresh=fresh)
    debate_re = re.compile(r"\b(myth|wrong|controvers|debate|warning|vs\.?|risk|danger|"
                           r"shock|backlash|banned|unpopular)\b", re.IGNORECASE)
    for item in (news or {}).get("results", []):
        sig["news_count"] += 1
        sig["newest_age"] = min(sig["newest_age"], age_days(item.get("date")))
        blob = f"{item.get('title','')} {item.get('snippet','')}"
        sig["snippets"].append(blob[:200])
        if debate_re.search(blob):
            sig["debate_hits"] += 1
    return sig


def score_topic(topic, sig, topic_weights):
    """Compute the six SOUL §8 factor sub-scores (0..1) from gathered signals,
    weight them, multiply by the engine_state per-topic weight. Returns a fully
    explainable breakdown dict."""
    catalog_hit = _catalog_match(topic)

    # trending_velocity (0.25): trends slope + recent news flow.
    slope = sig["trends_slope"]
    vel = 0.5 if slope is None else clamp01(0.5 + slope / 40.0)
    vel = clamp01(vel + min(sig["news_count"], 6) * 0.04)

    # comment_bait (0.20): debate signal in headlines + controversy archetype.
    bait = clamp01(0.35 + sig["debate_hits"] * 0.18)

    # search_volume (0.20): current Google Trends interest (0-100).
    sv = 0.4 if sig["trends_now"] is None else clamp01(sig["trends_now"] / 100.0)

    # educational (0.15): known research compound + active news = real evidence to cite.
    edu = clamp01((0.8 if catalog_hit else 0.45) + min(sig["news_count"], 5) * 0.03)

    # product_tie (0.10): direct Acme compound/category.
    tie = 1.0 if catalog_hit else 0.3

    # recency (0.10): freshness of the newest signal (<48h = full credit).
    age = sig["newest_age"]
    rec = 1.0 if age <= 2 else clamp01(math.exp(-(age - 2) / 7.0))

    raw = {"trending_velocity": vel, "comment_bait": bait, "search_volume": sv,
           "educational": edu, "product_tie": tie, "recency": rec}
    weighted = sum(SCORE_WEIGHTS[k] * raw[k] for k in raw)
    tw = topic_weights.get(catalog_hit, 1.0) if catalog_hit else 1.0
    return {"topic": topic, "compound": catalog_hit, "raw": raw,
            "weighted": weighted, "topic_weight": tw, "final": weighted * tw,
            "signals": {"trends_now": sig["trends_now"], "trends_slope": sig["trends_slope"],
                        "news_count": sig["news_count"], "newest_age_days": round(sig["newest_age"], 1),
                        "debate_hits": sig["debate_hits"]}}


def _catalog_match(topic):
    """Return the canonical compound name if the topic references an Acme compound."""
    low = topic.lower()
    for name in COMPOUND_CATALOG:
        if name.lower() in low or name.lower().replace("-", "") in low.replace("-", ""):
            return name
    return None


# Owned-site shop base per brand (SOUL §6: link acmelabs.co OR acmehealth.co, never both).
SHOP_BASE = {"labs": "https://acmelabs.co/shop/", "health": "https://acmehealth.co/shop/"}


def product_link(compound, brand):
    """The canonical product/COA destination for a live SKU, or None.

    A post whose CTA says "VIEW COA" must point somewhere real — the live product page,
    where the independent 3rd-party COA is attached (PRODUCTS.md). Only LIVE SKUs get a
    link; for non-live compounds we return None so we never promise a COA we can't show."""
    info = COMPOUND_CATALOG.get(compound or "", {})
    sku = info.get("sku")
    if not (info.get("live") and sku):
        return None
    return SHOP_BASE.get(brand, SHOP_BASE["labs"]) + sku


def print_breakdown(score):
    tw = score["topic_weight"]
    print(f"\nTOPIC: {score['topic']}"
          f"{f'  [{score['compound']}]' if score['compound'] else ''}  (topic_weight ×{tw:g})")
    for k in SCORE_WEIGHTS:
        w, r = SCORE_WEIGHTS[k], score["raw"][k]
        print(f"  {k:<18} {w:.2f} × {r:.2f} = {w*r:.3f}")
    print(f"  {'── weighted':<18} {score['weighted']:.3f}  × topic_weight {tw:g} = "
          f"FINAL {score['final']:.3f}")
    s = score["signals"]
    print(f"     signals: trends={s['trends_now']} slope={s['trends_slope']} "
          f"news={s['news_count']} newest={s['newest_age_days']}d debate={s['debate_hits']}")


def discover_topics(candidates, engine_state, fresh=False):
    """Score every candidate, drop blocked, print breakdowns, return sorted scores."""
    blocked = [b.lower() for b in engine_state.get("blocked_topics", [])]
    tw = engine_state.get("topic_weights", {})
    scored = []
    for c in candidates:
        if any(b in c.lower() for b in blocked):
            log(f"blocked: {c}")
            continue
        sig = gather_signals(c, fresh=fresh)
        sc = score_topic(c, sig, tw)
        print_breakdown(sc)
        scored.append(sc)
    scored.sort(key=lambda s: s["final"], reverse=True)
    return scored


# ══════════════════════════════════════════════════════════════════════════════
# MODE B — viral-outlier mining + format cloning
# ══════════════════════════════════════════════════════════════════════════════

def find_outliers(query, num=15, fresh=False):
    """Auto-mine YouTube (searchapi) for posts FAR above baseline view velocity for
    the result set. Velocity = views / age_days; outlier ratio = velocity / median.
    (Per-follower normalization needs a field searchapi/apify don't expose — flagged
    in MIGRATION; view-velocity is the cheap, available signal.)"""
    data = run_tool("searchapi.py", ["youtube", query, "--num", str(num)], fresh=fresh)
    vids = []
    for it in (data or {}).get("results", []):
        views = parse_count(it.get("views"))
        age = age_days(it.get("published_at"))
        if views <= 0 or age >= 9999:
            continue
        vids.append({"title": it.get("title"), "url": it.get("link"),
                     "channel": it.get("channel"), "views": views,
                     "age_days": round(age, 1), "velocity": views / max(age, 0.5)})
    if not vids:
        return []
    vels = sorted(v["velocity"] for v in vids)
    median = vels[len(vels) // 2] or 1.0
    for v in vids:
        v["baseline_ratio"] = round(v["velocity"] / median, 2)
        v["is_outlier"] = v["baseline_ratio"] >= 2.0
    vids.sort(key=lambda v: v["baseline_ratio"], reverse=True)
    return vids


def _detect_platform(url):
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "instagram.com" in u:
        return "instagram"
    if "tiktok.com" in u:
        return "tiktok"
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    return "article"


def extract_pattern(url, fresh=False):
    """Extract a viral post's pattern: apify.py scrape for social URLs (the EXTRACTOR),
    blotato.py source for articles/anything else. Returns hook + text + format type.
    Fires the priciest call (apify) at most once per URL thanks to the cache."""
    platform = _detect_platform(url)
    if platform in ("youtube", "instagram", "tiktok", "facebook"):
        data = run_tool("apify.py", ["scrape", url], ttl=7 * CACHE_TTL, fresh=fresh)
        if not data:
            return None
        d = data[0] if isinstance(data, list) else data
        text = (d.get("transcript") or d.get("caption") or d.get("description")
                or d.get("text") or "")
        hook = _first_line(text)
        return {"platform": platform, "url": url, "hook": hook, "text": text[:1500],
                "caption": (d.get("caption") or d.get("description") or "")[:600],
                "views": parse_count(d.get("views")), "likes": parse_count(d.get("likes")),
                "comments": parse_count(d.get("comments_count")),
                "format_type": classify_format(f"{hook} {text[:400]}")}
    data = run_tool("blotato.py", ["source", url], ttl=7 * CACHE_TTL, fresh=fresh)
    if not data:
        return None
    text = data.get("transcript") or data.get("content") or ""
    hook = _first_line(text)
    return {"platform": "article", "url": url, "hook": hook, "text": text[:1500],
            "caption": "", "views": 0, "likes": 0, "comments": 0,
            "format_type": classify_format(f"{hook} {text[:400]}")}


def _first_line(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) > 8:
            return line[:160]
    return (text or "")[:160].strip()


def classify_format(text):
    """Map extracted text to a viral FORMAT archetype (structure only)."""
    low = (text or "").lower()
    best, hits = "study_reaction", 0
    for name, cfg in FORMAT_ARCHETYPES.items():
        n = sum(1 for kw in cfg["keywords"] if kw in low)
        if n > hits:
            best, hits = name, n
    return best


def reconfigure(pattern, acme_topic, persona):
    """CLONE THE STRUCTURE, NEVER THE CONTENT. Build the copywriter.py topic string from the
    viral FORMAT recipe + an Acme-owned topic. The original's claims are NEVER passed
    through — only the structural archetype is reused. copywriter.py then writes the hook in
    the Research-Pharmacist voice and enforces compliance (banned claims, RUO, etc.)."""
    arch = FORMAT_ARCHETYPES.get(pattern["format_type"], FORMAT_ARCHETYPES["study_reaction"])
    # Persona voice is appended once downstream in assemble_brief — don't duplicate it here.
    angle = (f"{acme_topic} — written in the viral '{arch['recipe']}' format "
             f"(clone this STRUCTURE only; ignore any source claims).")
    return {"format_recipe": arch["recipe"], "template": arch["template"],
            "hook_angle": angle, "acme_topic": acme_topic}


def score_outlier(pattern, acme_topic, persona, curated=False):
    """Devon's Mode B scoring (CONTENT_ENGINE_GUIDE §5): niche/persona/format-adaptability/
    buyer-intent on a 1-10 scale, +2 if <24h, +3 if a curated drop-a-link. Prints breakdown."""
    catalog_hit = _catalog_match(acme_topic)
    raw = {
        "niche_fit": 9 if catalog_hit else 6,
        "persona_fit": 8 if persona in ("P3", "P2") else 6,  # trending targets P3/P2
        "format_adaptability": {"this_or_that": 9, "myth_bust": 9, "list_countdown": 8,
                                "wish_i_knew": 8, "controversial": 7,
                                "study_reaction": 8}.get(pattern["format_type"], 6),
        "buyer_intent": 8 if catalog_hit and COMPOUND_CATALOG.get(catalog_hit, {}).get("live") else 5,
    }
    base = sum(raw.values())          # out of 40
    recency_bonus = 2 if (pattern.get("views") and age_days(pattern.get("published_at")) < 1) else 0
    curated_bonus = 3 if curated else 0
    total = base + recency_bonus + curated_bonus
    return {"raw": raw, "base_of_40": base, "recency_bonus": recency_bonus,
            "curated_bonus": curated_bonus, "total": total, "format": pattern["format_type"]}


def print_outlier_score(sc, acme_topic):
    print(f"\nVIRAL OPPORTUNITY: {acme_topic}   (format: {sc['format']})")
    for k in MODE_B_FACTORS:
        print(f"  {k:<20} {sc['raw'][k]}/10")
    print(f"  {'── base':<20} {sc['base_of_40']}/40  +recency {sc['recency_bonus']} "
          f"+curated {sc['curated_bonus']} = TOTAL {sc['total']}")


# ══════════════════════════════════════════════════════════════════════════════
# Brief assembly (both modes -> 1A.2 pillar preset -> validated brief.json)
# ══════════════════════════════════════════════════════════════════════════════

def next_job_id(reserved=None):
    reserved = reserved or set()
    nums = [int(m.group(1)) for p in JOBS_DIR.glob("ACME-*")
            if (m := re.match(r"ACME-(\d+)$", p.name))]
    n = max(nums or [0])
    while True:
        n += 1
        jid = f"ACME-{n:03d}"
        if jid not in reserved:
            return jid


def route_brand(topic, pillar):
    """Labs (RUO, organic) by default; Health for metabolic/results *angles* only.
    A compound/SKU feature (stack pillar) is always a Labs RUO product, even when the
    compound is metabolic (Semaglutide is a live acmelabs.co RUO SKU). MIGRATION 1A."""
    if pillar == "proof" and HEALTH_KEYWORDS.search(topic):
        return "health"
    return "labs"


def run_copy(topic, brand, platform, product_feature, compound, cls, fresh=False, carousel=None):
    """Call copywriter.py (M2) for the renderable overlay tokens + caption (or, with carousel=N,
    an N-slide deck: cp['slides']). Reuses copywriter.py's compliance engine — the single source
    of truth for brand voice + banned claims."""
    args = [topic, "--brand", brand, "--platform", platform]
    if carousel:
        args += ["--carousel", str(carousel)]
    if product_feature:
        args += ["--product-feature"]
        if compound:
            args += ["--compound", compound]
        if cls:
            args += ["--class", cls]
    return run_tool("copywriter.py", args, ttl=CACHE_TTL, fresh=fresh)


def build_reference(*, url=None, platform="", description="", selection_rationale="",
                    cloned_format=None, extracted_hook=None, scoring_breakdown=None):
    """The provenance contract surfaced at approval (F2) and excluded from posts (F1).
    Records the exact source + WHY it was picked, so a produced post is always traceable
    back to the video/topic that inspired it. Mode A carries no url."""
    ref = {"url": url, "platform": platform, "description": description,
           "selection_rationale": selection_rationale, "scoring_breakdown": scoring_breakdown or {}}
    if cloned_format:
        ref["cloned_format"] = cloned_format
    if extracted_hook:
        ref["extracted_hook"] = extracted_hook
    return ref


def assemble_brief(pillar, topic, *, persona=None, brand=None, template=None,
                   carousel=None, provenance=None, reference=None, job_id=None,
                   dry_run=False, fresh=False):
    """Produce one post.py-ready type=image brief.json (+ copy.json + research.json
    sidecars) from a selected topic. Returns the brief dict (and writes it unless dry-run).

    carousel=N (or a carousel-* template) -> a full N-slide deck: copywriter.py --carousel writes
    slides.json and the brief points post.py at it. Otherwise a single branded card."""
    preset = PILLAR_PRESETS[pillar]
    persona = persona or preset["persona"]
    brand = brand or route_brand(topic, pillar)
    template = template or preset["template"]
    product_feature = preset.get("product_feature", False)
    compound = _catalog_match(topic)
    cls = COMPOUND_CATALOG.get(compound, {}).get("cls") if compound else None

    # Carousel intent: an explicit N, or a carousel-* template was chosen.
    want_carousel = bool(carousel) or template in CAROUSEL_TEMPLATES
    if want_carousel and template not in CAROUSEL_TEMPLATES:
        template = "carousel-light" if brand == "health" else "carousel-dark"
    n_slides = carousel or CAROUSEL_DEFAULT_SLIDES

    job_id = job_id or next_job_id()
    brief = {
        "job_id": job_id, "type": "image", "brand": brand, "pillar": pillar,
        "persona": persona, "topic": topic, "platforms": preset["platforms"],
    }
    if compound:
        brief["compound"] = compound
        if cls:
            brief["class"] = cls
    if product_feature:
        brief["product_feature"] = True
    # The CTA's COA/product promise needs a real destination: the live SKU's product page
    # (where the 3rd-party COA lives). The bridge folds this into every caption so "VIEW COA"
    # is fulfilled on every platform (None for non-live compounds → no empty promise).
    link = product_link(compound, brand)
    if link:
        brief["link"] = link
    # Reference travels IN the brief (metadata only) so F2 can surface it and publish can
    # exclude it. It is never passed to copywriter.py, so it cannot leak into the caption.
    if reference:
        brief["reference"] = reference

    if dry_run:
        fmt = f"carousel×{n_slides}" if want_carousel else template
        log(f"DRY-RUN would assemble {job_id}: {pillar}/{persona}/{brand} [{fmt}] <- {topic[:60]!r}")
        return brief

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    bn = "ACME HEALTH" if brand == "health" else "ACME LABS"
    handle = "@acmehealth" if brand == "health" else "@acmelabs"

    # M2 — fill renderable copy via copywriter.py (persona hint folded into the topic).
    copy_topic = f"{topic}\n{PERSONA_VOICE.get(persona, '')}".strip()
    cp = run_copy(copy_topic, brand, "instagram", product_feature, compound, cls,
                  fresh=fresh, carousel=n_slides if want_carousel else None)
    if not isinstance(cp, dict) or not cp:
        log(f"copywriter.py failed for {job_id} — writing brief without tokens (run copywriter.py later)")
        cp = {}

    slides = cp.get("slides") if want_carousel else None
    if want_carousel and slides:
        # Full multi-slide deck: post.py renders one PNG per slide from slides.json.
        (job_dir / "slides.json").write_text(json.dumps(slides, ensure_ascii=False, indent=2))
        brief["image"] = {"template": f"templates/src/{template}.html", "bg_policy": "plain",
                          "carousel": "slides.json",
                          "set": {"BRAND_NAME": bn, "HANDLE": handle}}
    else:
        if want_carousel:
            log(f"carousel copywriter.py returned no slides for {job_id} — single-card fallback")
        tokens = _map_tokens(template, cp, brand, compound, product_feature)
        brief["image"] = {"template": f"templates/src/{template}.html", "bg_policy": "plain",
                          "set": tokens}

    (job_dir / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    if cp:
        (job_dir / "copy.json").write_text(json.dumps(cp, ensure_ascii=False, indent=2))
    _ref = reference or {}
    (job_dir / "research.json").write_text(json.dumps(
        {"job_id": job_id, "discovered_at": now_iso(),
         "reference": _ref,
         # Flat mirrors so legacy readers (e.g. F4 telegram._source) still resolve the source.
         "source_url": _ref.get("url"), "source_platform": _ref.get("platform"),
         "cloned_format": _ref.get("cloned_format"), **(provenance or {})},
        ensure_ascii=False, indent=2))

    ok, errs = validate_brief(brief)
    log(f"{'OK ' if ok else 'INVALID '}{job_id} -> {job_dir}/brief.json"
        + ("" if ok else f"  errors: {errs}"))
    return brief


def _map_tokens(template, cp, brand, compound, product_feature):
    """Map copywriter.py output -> the exact token names the chosen template needs."""
    bn = cp.get("BRAND_NAME") or ("ACME HEALTH" if brand == "health" else "ACME LABS")
    handle = cp.get("HANDLE") or ("@acmehealth" if brand == "health" else "@acmelabs")
    ruo = "RUO · NOT FOR HUMAN CONSUMPTION"
    if template in ("story-reel-dark", "story-reel-light"):
        return {"BRAND_NAME": bn, "EYEBROW": cp.get("EYEBROW", "RESEARCH"),
                "HOOK_LINE_1": cp.get("HOOK_LINE_1", ""), "HOOK_LINE_2_ITALIC": cp.get("HOOK_LINE_2_ITALIC", ""),
                "HOOK_LINE_3": cp.get("HOOK_LINE_3", ""), "SUBTITLE_TEXT": cp.get("SUBTITLE_TEXT", ""),
                "CTA_LABEL": cp.get("CTA_LABEL", "LEARN MORE"), "HANDLE": handle}
    if template in ("static-compound-dark", "static-compound-light"):
        info = COMPOUND_CATALOG.get(compound, {})
        return {"BRAND_NAME": bn, "EYEBROW": cp.get("EYEBROW", "FEATURED COMPOUND"),
                "COMPOUND": compound or "", "CLASS_CHIP": info.get("cls", ""),
                "DESCRIPTOR": info.get("descriptor", ""), "SPEC_LINE": info.get("spec", ""),
                "SPEC_1": info.get("descriptor", ""), "SPEC_2": info.get("spec", ""),
                "SPEC_3": "Lyophilized · shipped cold-chain, worldwide", "PRICE": info.get("price", ""),
                "COA_CHIP": "COA AVAILABLE", "RUO_LINE": ruo, "HANDLE": handle}
    if template in ("static-callout-dark", "static-callout-light"):
        return {"BRAND_NAME": bn, "EYEBROW": cp.get("EYEBROW", "RESEARCH"),
                "STAT": cp.get("HOOK_LINE_2_ITALIC", ""), "STAT_LABEL": cp.get("SUBTITLE_TEXT", ""),
                "SOURCE": "Peer-reviewed research", "TAGLINE": cp.get("HOOK_LINE_3", ""),
                "RUO_LINE": ruo if product_feature else "", "HANDLE": handle}
    # carousel-dark/light: single-card fallback (full slides.json is a copywriter.py follow-up)
    return {"BRAND_NAME": bn, "EYEBROW": cp.get("EYEBROW", "RESEARCH"),
            "HEAD_1": cp.get("HOOK_LINE_1", ""), "HEAD_2_ITALIC": cp.get("HOOK_LINE_2_ITALIC", ""),
            "HEAD_3": cp.get("HOOK_LINE_3", ""), "BODY": cp.get("SUBTITLE_TEXT", ""),
            "SLIDE_NUM": "1", "SLIDE_TOTAL": "1", "SWIPE_LABEL": "SWIPE TO READ →", "HANDLE": handle}


def validate_brief(brief):
    """Validate against schemas/brief.schema.json (jsonschema if installed, else a
    manual required-fields + enum check)."""
    try:
        import jsonschema  # type: ignore
        schema = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(brief, schema)
        return True, []
    except ImportError:
        pass
    except Exception as e:  # jsonschema.ValidationError
        return False, [str(e).splitlines()[0]]
    errs = []
    for f in ("job_id", "type", "brand", "pillar", "persona", "topic"):
        if f not in brief:
            errs.append(f"missing {f}")
    if brief.get("pillar") not in PILLAR_PRESETS:
        errs.append(f"bad pillar {brief.get('pillar')}")
    if brief.get("persona") not in ("P1", "P2", "P3"):
        errs.append(f"bad persona {brief.get('persona')}")
    if brief.get("brand") not in ("labs", "health"):
        errs.append(f"bad brand {brief.get('brand')}")
    if brief.get("type") == "image" and "template" not in brief.get("image", {}):
        errs.append("image.template missing")
    return (not errs), errs


# ── Storage-agnostic discovery log (local-JSON-first; Supabase db.py plugs in later) ──

class DiscoveryStore:
    """Appends discovery_queue + daily_brief rows to per-day JSON files. Mirrors the
    Supabase table shape (CONTENT_ENGINE_GUIDE §6) so a db.py can replace it additively
    at cutover without changing research.py's call sites."""

    def __init__(self, date=None):
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.dir = RESEARCH_DIR / self.date
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dq = self.dir / "discovery_queue.json"
        self.db = self.dir / "daily_brief.json"

    def _append(self, path, row):
        rows = json.loads(path.read_text()) if path.exists() else []
        row = {"id": f"{path.stem}-{len(rows)+1:03d}", **row}
        rows.append(row)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        return row["id"]

    def add_discovery(self, *, source_url="", platform="", caption="", content_type="",
                      format_type="", engagement=None, **extra):
        return self._append(self.dq, {
            "source_url": source_url, "platform": platform, "caption": caption[:300],
            "content_type": content_type, "format_type": format_type,
            "engagement": engagement or {}, "scraped_at": now_iso(), **extra})

    def add_brief(self, *, pillar, persona, source_url="", format_type="", hook_angle="",
                  scoring_breakdown=None, job_id="", brief_path="", reference=None):
        ref = reference or {}
        return self._append(self.db, {
            "pillar": pillar, "persona_target": persona, "source_url": source_url or ref.get("url"),
            "format_type": format_type, "hook_angle": hook_angle[:300],
            "reference_url": ref.get("url"), "reference_description": ref.get("description", ""),
            "selection_rationale": ref.get("selection_rationale", ""), "reference": ref,
            "scoring_breakdown": scoring_breakdown or {}, "job_id": job_id,
            "brief_path": brief_path, "created_at": now_iso()})


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def load_engine_state():
    p = WS / "engine_state.json"
    return json.loads(p.read_text()) if p.exists() else {"topic_weights": {}, "blocked_topics": []}


def cmd_topics(args):
    es = load_engine_state()
    if args.candidates:
        candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    else:
        # Default seed = the highest-weighted Acme compounds (cheap, on-brand).
        tw = es.get("topic_weights", {})
        candidates = sorted(tw, key=tw.get, reverse=True)[:args.select + 2] or list(COMPOUND_CATALOG)[:3]
    log(f"Mode A — scoring {len(candidates)} candidates: {candidates}")
    scored = discover_topics(candidates, es, fresh=args.fresh)
    if not scored:
        log("no candidates survived scoring")
        return
    picks = scored[:args.select]
    print(f"\n=== SELECTED TOP {len(picks)} (Mode A) ===")
    for s in picks:
        print(f"  {s['final']:.3f}  {s['topic']}")
    if args.dry_run:
        log("dry-run: not assembling briefs")
        return
    store = DiscoveryStore()
    reserved = set()
    for s in picks:
        pillar = args.pillar or ("stack" if s["compound"] else "science")
        topic = f"{s['topic']} research"
        jid = next_job_id(reserved)
        reserved.add(jid)
        sig = s["signals"]
        ref = build_reference(
            platform="topic-discovery",
            description=(f"Topic discovery: {s['topic']} — Google Trends {sig['trends_now']}/100, "
                         f"{sig['news_count']} recent articles, newest {sig['newest_age_days']}d"),
            selection_rationale=(f"Top SOUL §8 score {s['final']:.2f} (velocity "
                                 f"{s['raw']['trending_velocity']:.2f}, search {s['raw']['search_volume']:.2f}, "
                                 f"recency {s['raw']['recency']:.2f}); newest signal {sig['newest_age_days']}d ago."),
            scoring_breakdown=s)
        prov = {"discovery_mode": "A_topic", "selected_topic": s["topic"]}
        brief = assemble_brief(pillar, topic, job_id=jid, provenance=prov, reference=ref,
                               carousel=getattr(args, "carousel", None), fresh=args.fresh)
        store.add_discovery(platform="searchapi", content_type="topic",
                            caption=s["topic"], format_type=pillar,
                            engagement=s["signals"])
        store.add_brief(pillar=pillar, persona=brief["persona"], format_type=pillar,
                        hook_angle=topic, scoring_breakdown=s, job_id=jid, reference=ref,
                        brief_path=str(JOBS_DIR / jid / "brief.json"))
    log(f"Mode A wrote {len(picks)} brief(s) + discovery log -> {store.dir}")


def cmd_outliers(args):
    queries = [args.query] if args.query else OUTLIER_YT_QUERIES[:2]
    all_vids = []
    for q in queries:
        all_vids += find_outliers(q, num=args.num, fresh=args.fresh)
    all_vids.sort(key=lambda v: v["baseline_ratio"], reverse=True)
    print(f"\n=== YOUTUBE OUTLIERS (velocity vs set median) ===")
    for v in all_vids[:10]:
        flag = "★ OUTLIER" if v["is_outlier"] else "         "
        print(f"  {flag}  {v['baseline_ratio']:>5.1f}×  {int(v['velocity']):>7,}/d  "
              f"{v['views']:>10,} views  {v['age_days']:>5}d  {(v['title'] or '')[:54]}")
    outliers = [v for v in all_vids if v["is_outlier"]]
    if not outliers:
        log("no outliers >=2× baseline in this set")
        return
    store = DiscoveryStore()
    for v in outliers[:5]:
        store.add_discovery(source_url=v["url"], platform="youtube", caption=v["title"] or "",
                            content_type="outlier", format_type="trending",
                            engagement={"views": v["views"], "velocity": int(v["velocity"]),
                                        "baseline_ratio": v["baseline_ratio"]})
    if not args.extract:
        log(f"logged {len(outliers[:5])} outliers. Re-run with --extract to clone the top one.")
        return
    top = outliers[0]
    log(f"extracting top outlier: {top['url']}")
    _extract_and_brief(top["url"], store, persona="P3", brand="labs", curated=False,
                       outlier_meta=top, carousel=getattr(args, "carousel", None),
                       dry_run=args.dry_run, fresh=args.fresh)


def cmd_inbox(args):
    """Drop-a-link: Marvin/Devon paste a viral URL (any platform) -> reverse-engineer it."""
    store = DiscoveryStore()
    _extract_and_brief(args.url, store, persona=args.persona, brand=args.brand,
                       curated=True, acme_topic=args.topic, pillar=args.pillar,
                       carousel=getattr(args, "carousel", None),
                       dry_run=args.dry_run, fresh=args.fresh)


def _extract_and_brief(url, store, *, persona="P3", brand="labs", curated=False,
                       acme_topic=None, pillar="trending", outlier_meta=None,
                       carousel=None, dry_run=False, fresh=False):
    pattern = extract_pattern(url, fresh=fresh)
    if not pattern:
        log(f"extraction failed for {url}")
        return
    print(f"\nEXTRACTED PATTERN ({pattern['platform']})")
    print(f"  hook:   {pattern['hook']!r}")
    print(f"  format: {pattern['format_type']}  ({FORMAT_ARCHETYPES[pattern['format_type']]['recipe']})")

    # Choose the Acme-owned topic to pour into the cloned format (never the source's).
    topic = acme_topic or _suggest_topic(pattern, persona)
    sc = score_outlier(pattern, topic, persona, curated=curated)
    print_outlier_score(sc, topic)
    recon = reconfigure(pattern, topic, persona)

    # Reference provenance — the exact inspiring post + why we picked it (F2 surfaces it).
    recipe = recon["format_recipe"]
    if outlier_meta:
        desc = (f"{outlier_meta.get('title','')} — {outlier_meta['views']:,} views, "
                f"{int(outlier_meta['velocity']):,}/d, {outlier_meta['baseline_ratio']}× niche baseline "
                f"({pattern['platform']})")
        why = (f"{outlier_meta['baseline_ratio']}× the niche-baseline view velocity on "
               f"{pattern['platform']}; scored {sc['total']}/40 (niche/persona/format/intent); "
               f"cloned the '{recipe}' structure.")
    else:
        desc = f"{pattern['platform']} drop-a-link — hook: {pattern['hook'][:80]!r}"
        why = (f"Curated drop-a-link; scored {sc['total']}/40 (niche/persona/format/intent); "
               f"cloned the '{recipe}' structure.")
    ref = build_reference(url=url, platform=pattern["platform"], description=desc,
                          selection_rationale=why, cloned_format=recipe,
                          extracted_hook=pattern["hook"], scoring_breakdown=sc)
    print(f"  reference: {desc}")
    print(f"  why:       {why}")

    store.add_discovery(source_url=url, platform=pattern["platform"],
                        caption=pattern.get("caption", "")[:300], content_type="outlier",
                        format_type=pattern["format_type"],
                        engagement={"views": pattern["views"], "likes": pattern["likes"],
                                    "comments": pattern["comments"]})
    if dry_run:
        log("dry-run: pattern extracted + scored, not assembling brief")
        return
    prov = {"discovery_mode": "B_outlier"}
    jid = next_job_id()
    brief = assemble_brief("trending", recon["hook_angle"], persona=persona, brand=brand,
                           template=recon["template"], carousel=carousel, job_id=jid,
                           provenance=prov, reference=ref, fresh=fresh)
    # Keep the brief.topic clean/human (the long copywriter.py angle lives in research.json).
    brief_path = JOBS_DIR / jid / "brief.json"
    bj = json.loads(brief_path.read_text())
    bj["topic"] = topic
    brief_path.write_text(json.dumps(bj, ensure_ascii=False, indent=2))
    store.add_brief(pillar="trending", persona=persona, source_url=url,
                    format_type=pattern["format_type"], hook_angle=topic,
                    scoring_breakdown=sc, job_id=jid, brief_path=str(brief_path), reference=ref)
    log(f"Mode B cloned {pattern['format_type']} format -> {jid} (topic: {topic!r})")


def _suggest_topic(pattern, persona):
    """Pick an on-brand Acme topic that fits the extracted format. Prefer a live SKU."""
    text = f"{pattern['hook']} {pattern['text']}".lower()
    for name, info in COMPOUND_CATALOG.items():
        if name.lower() in text:
            return f"{name} {info['descriptor'].lower()}"
    live = [n for n, i in COMPOUND_CATALOG.items() if i.get("live")]
    return f"{live[0]} research" if live else "peptide research"


def main():
    ap = argparse.ArgumentParser(prog="research", description="Acme F3 Research module (0 Higgsfield credits)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("topics", help="MODE A: sweep -> SOUL §8 score -> brief.json")
    pt.add_argument("--candidates", help="Comma-separated topics (default: top engine_state compounds)")
    pt.add_argument("--select", type=int, default=1, help="How many top topics to turn into briefs (default 1)")
    pt.add_argument("--pillar", choices=list(PILLAR_PRESETS), help="Force a pillar (default: stack if compound else science)")
    pt.add_argument("--carousel", nargs="?", type=int, const=CAROUSEL_DEFAULT_SLIDES, metavar="N",
                    help="Assemble full N-slide carousels (carousel-dark, slides.json) instead of single cards. Default N=5.")
    pt.add_argument("--dry-run", action="store_true", help="Score + select + print only; no copywriter.py, no briefs")
    pt.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    pt.set_defaults(func=cmd_topics)

    po = sub.add_parser("outliers", help="MODE B: auto-mine YouTube for above-baseline posts")
    po.add_argument("--query", help="YouTube niche query (default: built-in seed set)")
    po.add_argument("--num", type=int, default=15, help="Results per query (default 15)")
    po.add_argument("--extract", action="store_true", help="Also extract + clone the top outlier")
    po.add_argument("--carousel", nargs="?", type=int, const=CAROUSEL_DEFAULT_SLIDES, metavar="N",
                    help="Clone the outlier into a full N-slide carousel (better for comparison/"
                         "listicle formats) instead of a single card. Default N=5.")
    po.add_argument("--dry-run", action="store_true", help="Extract + score only; no brief")
    po.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    po.set_defaults(func=cmd_outliers)

    pi = sub.add_parser("inbox", help="MODE B drop-a-link: paste any viral URL -> Trending brief")
    pi.add_argument("url", help="Viral post URL (YouTube/TikTok/IG/FB/article)")
    pi.add_argument("--pillar", default="trending", help="Pillar (default trending)")
    pi.add_argument("--persona", default="P3", choices=["P1", "P2", "P3"])
    pi.add_argument("--brand", default="labs", choices=["labs", "health"])
    pi.add_argument("--topic", help="Override the Acme topic to pour into the cloned format")
    pi.add_argument("--carousel", nargs="?", type=int, const=CAROUSEL_DEFAULT_SLIDES, metavar="N",
                    help="Clone the dropped link into a full N-slide carousel instead of a single card. Default N=5.")
    pi.add_argument("--dry-run", action="store_true", help="Extract + score only; no brief")
    pi.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    pi.set_defaults(func=cmd_inbox)

    pr = sub.add_parser("run", help="Full day: assemble briefs across pillars (topics + outliers)")
    pr.add_argument("--select", type=int, default=4, help="Mode A topics to select (default 4; +1 trending from outliers)")
    pr.add_argument("--carousel", nargs="?", type=int, const=CAROUSEL_DEFAULT_SLIDES, metavar="N",
                    help="Make the Mode-A (Science/Stack) briefs full N-slide carousels. Default N=5.")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--fresh", action="store_true")
    pr.set_defaults(func=lambda a: (cmd_topics(argparse.Namespace(
        candidates=None, select=a.select, pillar=None, carousel=a.carousel,
        dry_run=a.dry_run, fresh=a.fresh)),
        cmd_outliers(argparse.Namespace(query=None, num=15, extract=True,
                                        carousel=a.carousel,
                                        dry_run=a.dry_run, fresh=a.fresh))))

    args = ap.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
