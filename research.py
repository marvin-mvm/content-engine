#!/usr/bin/env python3
"""research.py — Acme F3 Research module (the manual-topic replacement).

Produces brief.json files automatically, in TWO discovery modes, at 0 Higgsfield
credits. It is the missing front-end of the engine: research finds *what to post*,
the existing core (copywriter.py -> post.py / reel.py) renders it.

  MODE A — topic discovery  (`research.py topics`)
    Sweep PubMed/news/trends (searchapi) -> candidate topics, score by the
    six SOUL §8 weights × engine_state topic_weights (respecting blocked_topics),
    print the per-topic breakdown, pick the top N -> brief.json files.

  MODE B — viral-outlier mining + format cloning  (`research.py outliers` / `inbox`)
    Find posts whose engagement is far above baseline (YouTube via searchapi —
    view velocity), OR take a dropped link (any platform). Extract the pattern
    (apify.py scrape for social/video, firecrawl.py scrape for articles/blogs/sites),
    then RECONFIGURE: rewrite the hook in the
    Research-Pharmacist voice via copywriter.py, map the format to a template, STRIP the
    original's claims, apply compliance -> a Trending-Hook brief.json.
    CLONE THE STRUCTURE, NEVER THE CONTENT.

Both modes assemble briefs via the Part 1A.2 pillar presets (pillar -> template +
persona + brand), validate against schemas/brief.schema.json, and log discovery to
a local JSON store (discovery_queue + daily_brief). Marvin's call (2026-06-18):
local-JSON-first — a Supabase db.py can replace DiscoveryStore additively later.

The shared tools (searchapi.py/firecrawl.py/apify.py/copywriter.py) are called as
black-box subprocesses and never modified. EXTRACTION routing ("read inside a link"):
article/blog/website -> firecrawl.py scrape; social/video (YouTube, Instagram, TikTok,
Facebook, Threads, X/Twitter) -> apify.py scrape. Blotato is publish/schedule + backup image
generation ONLY — never text extraction. Every paid call is cached under
output/research/cache/ (apify/firecrawl banked at a 7-day TTL) so re-runs don't re-spend;
Mode B fires the paid scrape once per URL only.

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
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import engine as eng  # shared core — content cadence (alternating-day video) lives here

import source_bank  # RV0 — full-transcript harvest & angle reuse (0 extraction cost)
import engine as eng  # decision-ledger feedback: skip topics a human previously REJECTED
try:
    import product_images  # real SKU photos → PRODUCT_IMAGE token / Higgsfield reference
except Exception:           # never let a missing asset tree break a produce run
    product_images = None
try:
    import dedup            # content-duplication gate (Marvin 2026-06-22) — fail-open
except Exception:
    dedup = None

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
    "science":  {"template": "story-reel-dark", "alts": ["carousel-dark", "static-callout-dark", "static-compound-dark"],
                 "persona": "P1", "slot": "08:00", "platforms": ["instagram", "tiktok", "x"]},
    "stack":    {"template": "static-compound-dark", "alts": ["carousel-dark", "story-product-dark"],
                 "persona": "P1", "slot": "11:00", "platforms": ["instagram", "tiktok"],
                 "product_feature": True},
    "trending": {"template": "story-reel-dark", "alts": ["carousel-dark", "static-compound-dark"],
                 "persona": "P3", "slot": "13:00", "platforms": ["instagram", "tiktok"]},
    # v2 renamed this pillar "Research Spotlight" (was "Social Proof & Results"): physician
    # validation is REMOVED — all credibility is external published research cited by source.
    "proof":    {"template": "story-reel-dark", "alts": ["static-callout-dark", "carousel-dark"],
                 "persona": "P3", "slot": "16:00", "platforms": ["instagram", "x", "threads"]},
    "founder":  {"template": "story-reel-dark", "alts": ["carousel-dark"],
                 "persona": "P1", "slot": "19:00", "platforms": ["instagram", "x"]},
}

# Templates that produce a multi-slide deck (slides.json) rather than one card.
CAROUSEL_TEMPLATES = {"carousel-dark", "carousel-light"}
CAROUSEL_DEFAULT_SLIDES = 5


# ── Theme + slot/format wiring (Devon §3.2) ───────────────────────────────────────
# content.md dark/light rule (authoritative for FORMAT — Marvin 2026-06-21): the MODE is decided
# by the SLOT, NOT the brand. content.md §9 + §18-20 / SOUL.md:541: the morning feed is LIGHT,
# midday/evening is DARK (authoritative/stronger). Mapped onto the 5 PT pillar-slots:
#   science(08:00) + stack(11:00) → light ;  trending(13:00) + proof(16:00) + founder(19:00) → dark.
# Acme Health keeps its native cream/sage LIGHT identity at EVERY slot (brand hard-constraint),
# so the slot rule only swings Acme Labs. Replaces the old brand→theme tie (Labs always dark)
# which contradicted content.md's "Light (morning feed)" for Slot 1.
LIGHT_PILLARS = {"science", "stack"}     # 08:00 + 11:00 morning slots → light


def theme_for(pillar, brand):
    """content.md dark/light mode for this pillar's slot. Health → always light; Labs → light in
    the morning slots (science/stack), dark midday/evening (trending/proof/founder)."""
    if brand == "health":
        return "light"
    return "light" if pillar in LIGHT_PILLARS else "dark"


def themed(stem, pillar, brand):
    """Append the content.md dark/light suffix for this pillar's slot (see theme_for)."""
    return f"{stem}-{theme_for(pillar, brand)}"


def retheme(template, pillar, brand):
    """Force an existing '<stem>-dark|light' template to this pillar's content.md mode. Fixes the
    old bug where a health-brand post still rendered a -dark template (only carousel was swapped)."""
    if template.endswith("-dark") or template.endswith("-light"):
        return themed(template.rsplit("-", 1)[0], pillar, brand)
    return template


# Devon's §3.2 weekly format rotation (CONTENT_ENGINE_GUIDE §3.2). Mon=0 … Sun=6. THIS is what
# wires each template to its day/slot. 'reel' cells only fire on the pillar's video day
# (slot_wants_reel / reel_pillar_today); on a non-video day the reel cell falls back to the
# pillar's image format (handled in daily_image_template). Theme is applied per brand.
WEEKLY_FORMATS = {
    "science":  ["carousel", "single",   "reel",         "carousel", "single",   "carousel", "reel"],
    "stack":    ["carousel", "product",  "carousel",     "compare",  "carousel", "product",  "carousel"],
    "trending": ["reel",     "carousel", "reel",         "this_or_that", "reel",  "myth_bust","reel"],
    "proof":    ["carousel", "callout",  "carousel",     "quote",    "carousel", "callout",  "carousel"],
    "founder":  ["quote",    "callout",  "quote",        "carousel", "callout",  "carousel", "quote"],
}

# format-of-the-day → template stem (theme appended per brand). 'carousel'/'reel' are special,
# and so are the COMPARISON formats (compare/this_or_that/poll): they route to carousel decks in
# daily_image_template below. NOTHING here may point at story-poll-pro — that template's comparison
# body is hardcoded ("BPC-157 vs Semaglutide", see _map_tokens), so the copywriter never fills it
# and it renders SAMPLE data. It stays manual-only until autonomous poll generation exists
# (Marvin 2026-06-22, ACME-052..061 batch). Comparison angles are far better as carousels anyway.
_FORMAT_STEM = {
    "single": "story-reel", "graphic": "static-compound", "compound": "static-compound",
    "product": "story-product", "compare": "carousel", "this_or_that": "carousel",
    # A founder "quote" is a STATEMENT card, not a stat — static-callout's big STAT field is sized
    # for a short number ("14.9%"), so a multi-word quote overflowed and overlapped the label/source
    # (Marvin 2026-06-21 system test, ACME-040/036). Statements render correctly on story-reel.
    # "callout" stays static-callout (the proof/stat card) — feed it a real short stat.
    "poll": "carousel", "quote": "story-reel", "callout": "static-callout",
    "myth_bust": "story-reel",
}

# Comparison/poll formats that must render as a multi-slide carousel deck (never story-poll-pro).
_CAROUSEL_FORMATS = {"carousel", "compare", "this_or_that", "poll"}


def pillar_format_today(pillar, d=None):
    """Devon's §3.2 format-of-the-day for a pillar (e.g. 'carousel', 'product', 'this_or_that')."""
    d = d or eng.today_date()
    row = WEEKLY_FORMATS.get(pillar)
    return row[d.weekday()] if row else None


def daily_image_template(pillar, brand, d=None, *, product_feature=False):
    """Resolve the §3.2 format-of-the-day → a concrete IMAGE template + carousel-intent flag
    (theme by brand). On a 'reel'-format day this returns the pillar's IMAGE fallback (reels are
    minted separately by the reel path), so a non-video pillar still ships a 0-credit image.
    Returns (template_name, want_carousel)."""
    fmt = pillar_format_today(pillar, d)
    if fmt in (None, "reel"):
        fmt = "carousel"                       # safe image fallback on reel/unknown days
    if fmt in _CAROUSEL_FORMATS:               # carousel + the comparison/poll formats → deck
        return themed("carousel", pillar, brand), True
    stem = _FORMAT_STEM.get(fmt, "static-compound")
    if stem == "story-product" and not product_feature:
        stem = "static-compound"               # product card only with a featured compound
    return themed(stem, pillar, brand), False

# Persona voice hint injected into the copywriter.py topic string (copywriter.py has no persona
# arg and we don't modify it — backward-compatible). MIGRATION 1A.1 / guide §1.
PERSONA_VOICE = {
    "P1": "Audience: The Optimizer — data-dense, mechanism + numbers, ROI/return language.",
    "P2": "Audience: The Health-Forward Affluent Woman — aspirational, premium, outcome/lifestyle-framed.",
    "P3": "Audience: The Curious Newcomer — plain English, curiosity hook, define every term.",
}

# v2 §1/§3.1 persona targeting (Marvin 2026-06-21, supersedes v1): this engine is LABS-ONLY and
# targets just TWO personas — The Optimizer (P1, primary) and The Curious Newcomer (P3, secondary).
# The Health-Forward Affluent Woman (our internal P2) is the FUTURE Acme HEALTH target and is
# NEVER auto-targeted by Labs content (v2: "Labs content should not be built around her needs";
# "when in doubt, write for The Optimizer"). Each day's 5 posts cover BOTH active personas: founder
# is always Optimizer (P1) and trending is always Newcomer (P3) — so P1+P3 are guaranteed daily —
# while science/stack/proof rotate P1/P3 for variety. Explicit persona= (inbox/bank) still overrides.
#   even-ordinal day: science P1 · stack P3 · trending P3 · proof P1 · founder P1   → {P1,P3}
#    odd-ordinal day: science P3 · stack P1 · trending P3 · proof P3 · founder P1   → {P1,P3}
PERSONA_BY_DAY = {                        # [even, odd] ordinal day — Optimizer(P1)+Newcomer(P3) ONLY
    "science":  ["P1", "P3"],             # v2: all active personas → rotate Optimizer/Newcomer
    "stack":    ["P3", "P1"],             # v2: Optimizer + Newcomer
    "trending": ["P3", "P3"],             # v2: Newcomer (primary) — always
    "proof":    ["P1", "P3"],             # v2: all active personas (Research Spotlight)
    "founder":  ["P1", "P1"],             # v2: Optimizer (fixed)
}


def persona_for(pillar, d=None):
    """The v2 §3.1 persona to target for `pillar` today, rotating between the two ACTIVE Labs
    personas — Optimizer (P1) + Newcomer (P3) — so both are covered each day (see PERSONA_BY_DAY).
    Never returns P2 (Affluent Woman = future Health). Falls back to the pillar's preset persona."""
    d = d or eng.today_date()
    row = PERSONA_BY_DAY.get(pillar)
    if not row:
        return PILLAR_PRESETS[pillar]["persona"]
    return row[d.toordinal() % 2]


# v2 §2/§3.1: ONE post per pillar per day across all FIVE pillars. The daily `run` builds the four
# non-trending pillars from Mode-A topic discovery (trending comes from Mode B outliers/drops). The
# OLD rule assigned every topic to science|stack by compound-match, so proof + founder were NEVER
# produced and compound-heavy days were all stack (bug found 2026-06-21). plan_pillar_briefs spreads
# the picks across the four non-trending pillars instead.
NON_TRENDING_PILLARS = ("stack", "science", "proof", "founder")

# How each non-trending pillar frames a raw discovery topic so the copy lands on-pillar.
# Compliance-safe wording only (research / education / opinion framing — never a claim).
# MULTIPLE frames per pillar, rotated by day (frame_for): even when a compound has to repeat,
# the HOOK differs so consecutive posts don't read identically (the "content recycles" report,
# Marvin 2026-06-22). The recency rotation below (recently_used_compounds) is the primary fix —
# this is the secondary one so the framing itself isn't a fixed template.
PILLAR_TOPIC_FRAMES = {
    "science": [
        "{t} — the mechanism, explained with the research",
        "How {t} actually works, according to the research",
        "{t}, decoded: the science without the hype",
    ],
    "stack": [
        "{t} — research-backed stack protocol",
        "Where {t} fits in a research stack",
        "Building a research protocol around {t} — what the data supports",
    ],
    "proof": [
        "What the published research actually shows about {t}",
        "The {t} studies everyone cites — what they really found",
        "{t}: separating the published evidence from the marketing",
    ],
    "founder": [
        "Why most people get {t} wrong — an informed, research-grounded take",
        "The {t} take nobody wants to hear, grounded in the research",
        "{t}: the hype, the evidence, and the honest middle",
    ],
}
# Back-compat alias (first frame per pillar) for any caller/test that imports the singular name.
PILLAR_TOPIC_FRAME = {p: frames[0] for p, frames in PILLAR_TOPIC_FRAMES.items()}


def frame_for(pillar: str, d=None) -> str:
    """The topic frame for this pillar, ROTATED by calendar day so the hook varies across days."""
    frames = PILLAR_TOPIC_FRAMES.get(pillar)
    if not frames:
        return "{t} research"
    d = d or eng.today_date()
    return frames[d.toordinal() % len(frames)]


# Rotation cooldown: a compound featured in the last N produced jobs is held back so the daily
# run picks FRESH compounds instead of re-proposing the same top-weighted few every morning (the
# root cause of identical day-over-day briefs). ACME-NNN ids are monotonic, so "last N jobs" needs
# no timestamp parsing. ~8 jobs ≈ the previous day-and-a-half at 5 posts/day; override via .env.
def _cooldown_jobs() -> int:
    try:
        return max(0, int(os.environ.get("ENGINE_TOPIC_COOLDOWN_JOBS", "8")))
    except (ValueError, TypeError):
        return 8


def recently_used_compounds(window_jobs: int | None = None) -> list[str]:
    """Compounds featured in the most recent `window_jobs` briefs, most-recent first (rotation
    cooldown). Excluding these from the daily candidate pool is what stops the engine recycling
    the same compound→pillar→template brief day after day (Marvin 2026-06-22)."""
    window = window_jobs if window_jobs is not None else _cooldown_jobs()
    if window <= 0:
        return []
    jobs = sorted(eng.JOBS_DIR.glob("ACME-*"), key=lambda p: p.name, reverse=True)[:window]
    used: list[str] = []
    for jd in jobs:
        b = eng.load_json(jd / "brief.json") or {}
        c = b.get("compound")
        if c and c not in used:
            used.append(c)
    return used


def _job_age_days(job_dir: Path) -> float:
    """How many days ago a job was produced (status.produced_at, else the brief file's mtime)."""
    st = eng.load_json(job_dir / "status.json") or {}
    ts = st.get("produced_at") or st.get("pushed_at")
    dt = None
    if ts:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            dt = None
    if dt is None and (job_dir / "brief.json").exists():
        dt = datetime.fromtimestamp((job_dir / "brief.json").stat().st_mtime, tz=timezone.utc)
    if dt is None:
        return 1e9
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def products_in_last_days(days: int = 7) -> list[str]:
    """Products (compounds) that WENT OUT in the last `days`, most-recent first — the product
    cooldown window (Marvin 2026-06-22: 'list the products that went out in the last 7 days, then
    pick one related to the research or a NEW product not in the last-7-day window'). The daily run
    excludes these so the same SKU isn't re-featured within a week; when the catalog is exhausted it
    falls back to the least-recently-used product."""
    out: list[str] = []
    jobs = sorted(eng.JOBS_DIR.glob("ACME-*"), key=lambda p: p.name, reverse=True) if eng.JOBS_DIR.exists() else []
    for jd in jobs:
        if _job_age_days(jd) > days:
            continue
        c = (eng.load_json(jd / "brief.json") or {}).get("compound")
        if c and c not in out:
            out.append(c)
    return out


# GLP-1/incretin weight-loss compounds read as "the same kind of post" to the dedup judge even
# though their catalog `cls` strings differ — featuring ANY of them fills the day's "GLP-1 content"
# slot. Grouping them into ONE rotation family is what stops the engine clustering Tirzepatide/
# Semaglutide/Retatrutide across days (Marvin 2026-06-23: "stop producing similar GLP-1 content").
INCRETIN_FAMILY = {"Semaglutide", "Tirzepatide", "Retatrutide"}


def compound_family(compound: str | None) -> str:
    """The rotation bucket a compound belongs to: incretin/GLP-1 compounds share one bucket;
    everything else buckets by its catalog class (`cls`), falling back to its own name."""
    if not compound:
        return ""
    if compound in INCRETIN_FAMILY:
        return "incretin-glp1"
    return (COMPOUND_CATALOG.get(compound, {}) or {}).get("cls") or compound


def recency_penalty(compound: str | None, recent: list[str]) -> float:
    """A 0<f≤1 score multiplier that down-weights a compound whose EXACT name OR FAMILY was featured
    recently, so the daily scorer rotates across the catalog instead of re-picking the hottest-
    trending compound (the GLP-1s) every day. With only ~12 SKUs at 5 posts/day the 7-day product
    window always covers the whole catalog, so trending alone kept re-selecting GLP-1s — this is the
    tiebreaker that spreads the load (Marvin 2026-06-23). `recent` = recently_used_compounds(),
    most-recent first; the most-recent bucket is hit hardest and the penalty fades over a few jobs."""
    if not compound or not recent:
        return 1.0
    fam = compound_family(compound)
    for i, c in enumerate(recent):
        if c == compound or compound_family(c) == fam:
            return min(1.0, 0.35 + 0.16 * i)   # 0.35× most-recent → ~1.0 by the 5th distinct bucket
    return 1.0


def plan_pillar_briefs(picks, *, spread, explicit_pillar=None):
    """Map scored topics → pillars. With spread=True (the daily run) produce ONE brief per
    non-trending pillar: stack gets the strongest COMPOUND topic (the product/conversion pillar),
    then science/proof/founder take the next best picks — so the day covers all five pillars
    (trending comes from Mode B). Without spread, the legacy per-topic science|stack rule (or the
    caller's explicit --pillar). Returns [(pillar, pick), ...]. Pure — no I/O."""
    if not spread:
        return [(explicit_pillar or ("stack" if s.get("compound") else "science"), s) for s in picks]
    compounds = [s for s in picks if s.get("compound")]
    others = [s for s in picks if not s.get("compound")]
    plan = []
    if compounds:                                    # stack must carry a real compound (product card)
        plan.append(("stack", compounds.pop(0)))
    rest = compounds + others                         # remaining picks, compounds first
    for pillar in ("science", "proof", "founder"):
        if rest:
            plan.append((pillar, rest.pop(0)))
    return plan


# Acme compound universe — SYNCED to the live store acmelabs.co/shop on 2026-06-23 by reading
# the SPA's product bundle (the SOURCE OF TRUTH; docs/PRODUCTS.md is reference-only and was stale). Only
# VISIBLE individual research compounds are listed (bundles/category pages/supplies excluded; HIDDEN
# products like Epithalon are dropped). `sku` MUST equal the real shop slug — product_link() builds
# SHOP_BASE + sku, so a wrong slug 404s the COA link. Drives product_tie scoring, brand routing, and
# the class/spec chips on stack (static-compound) briefs. (engine_state.topic_weights mirrors these.)
COMPOUND_CATALOG = {
    # ── Metabolic ──────────────────────────────────────────────────────────────
    "Semaglutide":      {"cls": "GLP-1 ANALOG", "spec": "GLP-1 analog · 5mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Incretin mimetic for metabolic research", "price": "$79", "live": True, "sku": "semaglutide"},
    "Tirzepatide":      {"cls": "GIP/GLP-1 ANALOG", "spec": "Dual GIP/GLP-1 agonist · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Dual incretin receptor research compound", "price": "$99", "live": True, "sku": "tirzepatide"},
    "Retatrutide":      {"cls": "GIP/GLP-1/GLUCAGON AGONIST", "spec": "Triple (GGG) agonist · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Triple-agonist metabolic research compound", "price": "$99", "live": True, "sku": "retatrutide"},
    "Cagrilintide":     {"cls": "AMYLIN ANALOG", "spec": "Long-acting amylin analog · 5mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Amylin-receptor metabolic research peptide", "price": "$89", "live": True, "sku": "cagrilintide-5mg"},
    # ── Recovery / repair ──────────────────────────────────────────────────────
    "BPC-157":          {"cls": "PENTADECAPEPTIDE", "spec": "Body Protection Compound 157 · 5mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Tissue-repair signaling research peptide", "price": "$49", "live": True, "sku": "bpc-157"},
    "TB-500":           {"cls": "THYMOSIN β-4 FRAGMENT", "spec": "Thymosin Beta-4 fragment · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Angiogenesis & repair research peptide", "price": "$69", "live": True, "sku": "tb-500-10mg"},
    "GHK-Cu":           {"cls": "COPPER TRIPEPTIDE", "spec": "Copper tripeptide · 50mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Skin/collagen & longevity research peptide", "price": "$49", "live": True, "sku": "ghk-cu-50mg"},
    "Thymosin Alpha-1": {"cls": "IMMUNE PEPTIDE", "spec": "Thymosin Alpha-1 · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Innate-immune signaling research peptide", "price": "$65", "live": True, "sku": "ta-1-10mg"},
    # ── Growth / GH axis ───────────────────────────────────────────────────────
    "CJC-1295":         {"cls": "GHRH ANALOG", "spec": "CJC-1295 (no DAC) · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Growth-hormone-axis (GHRH) research peptide", "price": "$59", "live": True, "sku": "cjc-1295-no-dac-10mg"},
    "Ipamorelin":       {"cls": "GHRP", "spec": "Selective ghrelin agonist · 5mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Selective GH-secretagogue research peptide", "price": "$49", "live": True, "sku": "ipamorelin"},
    "IGF-1 LR3":        {"cls": "GROWTH FACTOR", "spec": "Long-R3 IGF-1 · 1mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Insulin-like growth factor research compound", "price": "$79", "live": True, "sku": "igf1-lr3-1mg"},
    "MOTS-c":           {"cls": "MITOCHONDRIAL PEPTIDE", "spec": "Mitochondrial-derived peptide · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Mitochondrial metabolic research peptide", "price": "$55", "live": True, "sku": "mots-c"},
    "Tesamorelin":      {"cls": "GHRH ANALOG", "spec": "Stabilized GHRH analog · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "GHRH-analog metabolic research peptide", "price": "$65", "live": True, "sku": "tesamorelin-10mg"},
    # ── Cognitive ──────────────────────────────────────────────────────────────
    "Semax":            {"cls": "NEUROPEPTIDE", "spec": "Nootropic heptapeptide · 30mg nasal · research-grade",
                         "descriptor": "BDNF-modulation research peptide", "price": "$75", "live": True, "sku": "semax"},
    "Selank":           {"cls": "NEUROPEPTIDE", "spec": "Anxiolytic heptapeptide · 5mg lyophilized · research-grade",
                         "descriptor": "CNS-signaling research peptide", "price": "$49", "live": True, "sku": "selank-5mg"},
    # ── Longevity ──────────────────────────────────────────────────────────────
    "NAD+":             {"cls": "COENZYME", "spec": "NAD+ coenzyme · 500mg vial · research-grade",
                         "descriptor": "Mitochondrial NAD+ biology research", "price": "$65", "live": True, "sku": "nad-injection"},
    # ── Aesthetic / melanocortin ───────────────────────────────────────────────
    "Melanotan-2":      {"cls": "MELANOCORTIN", "spec": "Melanocortin agonist · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "Melanocortin-receptor research peptide", "price": "$49", "live": True, "sku": "melanotan-2-10mg"},
    "PT-141":           {"cls": "MELANOCORTIN", "spec": "Bremelanotide · 10mg lyophilized · ≥99% HPLC purity",
                         "descriptor": "MC4-receptor research peptide", "price": "$49", "live": True, "sku": "pt-141-10mg"},
}

# Compounds allowed in STATIC / carousel / announcement content but NOT in VIDEO/reels (Marvin
# 2026-06-23): the melanocortin/aesthetic peptides (tanning, sexual-function) read fine on a product
# card but are off-tone / platform-risky narrated in a reel. Excluded from the autonomous reel
# topic pool only — they stay in the image rotation (topic_weights + COMPOUND_CATALOG untouched).
VIDEO_EXCLUDED_COMPOUNDS = {"Melanotan-2", "PT-141"}

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
                       # carousel deck, NOT story-poll-pro: a clone pours a single Acme topic into
                       # the format, but story-poll-pro needs two structured options the copywriter
                       # never generates → it renders hardcoded "BPC-157 vs Semaglutide" sample data
                       # (Marvin 2026-06-22). A comparison reads well across carousel slides anyway.
                       "template": "carousel-dark", "recipe": "This-or-That comparison"},
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

# ── VIRAL-OUTLIER SOURCING DOCTRINE (Marvin 2026-06-21; full version REFERENCE §13) ──
# Don't mine topic-NOUNS alone — mine the FRAMINGS that go viral in our niche, because those
# are the ones we can actually win. The method is three steps:
#   1. OUTLIER (quant): rank by velocity vs the niche-baseline median, not raw views (find_outliers;
#      outlier = >=2x baseline — the bigger the ratio the louder the signal, e.g. a 37x explainer).
#   2. THROUGHLINE (qual): name the ONE narrative everyone is circling right now. Ours is durable:
#      "the hype is outrunning the evidence" — celebrity buzz (Rogan/BPC-157, Ozempic->tirzepatide)
#      vs. what studies show (SURMOUNT-5, the GLP1R variant). Clone the THROUGHLINE, not one post.
#   3. EDGE (strategy): Acme IS the evidence side (COA + RUO + sourced), so we win whenever the
#      frame is "hype vs. evidence". Pick outliers we can answer with DATA (myth-bust / "what it
#      actually does" / "X vs Y" / "the part nobody mentions"); REJECT anything needing an outcome
#      claim. Clone the hook STRUCTURE (FORMAT_ARCHETYPES) into an Acme-owned topic; body stays rigorous.
# So lead the query set with throughline FRAMINGS (the convertible angles), keep topic-noun seeds for
# breadth. REFRESH these as the throughline shifts — they reflect the niche conversation in mid-2026.
OUTLIER_YT_QUERIES = [
    # throughline framings (lead — the "hype vs. evidence" angles we can convert)
    "what peptides actually do", "tirzepatide vs semaglutide", "are peptides worth it",
    "peptide myths debunked", "scientists react to GLP-1 study",
    # topic-noun seeds (broad niche coverage; surface explainer outliers too)
    "peptides longevity", "biohacking longevity", "GLP-1 metabolic health",
    "NAD+ anti-aging", "peptide therapy research",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[research] {msg}", file=sys.stderr)


# Tools (by script stem, e.g. "searchapi") that returned a quota/credit-depletion error during
# THIS run. Populated by run_tool; read by Mode A to avoid shipping blind-rotation duplicates
# when the discovery API is dead (the ACME-062..065 incident, 2026-06-23).
DEPLETED_TOOLS: set[str] = set()


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
        out = (r.stderr or r.stdout or "")
        log(f"WARN {script} exited {r.returncode}: {out[-300:].strip()}")
        # The tool itself fires the Telegram heads-up (api_alerts.note); here we only RECORD that
        # this API is depleted so the orchestrator can stop falling back to duplicate content.
        try:
            import api_alerts
            if api_alerts.classify(code=r.returncode, body=out):
                DEPLETED_TOOLS.add(Path(script).stem)
        except Exception:
            pass
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
           "newest_age": 9999.0, "debate_hits": 0, "snippets": [], "news_sources": []}

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
        # Capture the actual article URL so Mode A topics carry real sources (Task 3, Marvin
        # 2026-06-20): every brief must show where it came from, even topic-discovery ones.
        link = item.get("link") or item.get("url")
        if link and len(sig["news_sources"]) < 5:
            sig["news_sources"].append({"url": link, "title": item.get("title", ""),
                                        "source": item.get("source", ""), "platform": "news"})

    # YouTube sources (Marvin 2026-06-22: "none of our sources is YouTube — we need that"). This is
    # a video-first niche, so every brief — especially the trending reel — should cite the relevant
    # YouTube discussion alongside the news. searchapi already does YouTube (Mode B uses it); one
    # cheap, cached call per topic. Blend 3 news + 2 YouTube so BOTH show in the card's top-5.
    yt = run_tool("searchapi.py", ["youtube", topic, "--num", "5"], fresh=fresh)
    yt_sources = []
    for v in (yt or {}).get("results", []):
        link = v.get("link") or v.get("url")
        if link:
            yt_sources.append({"url": link, "title": v.get("title", ""),
                               "source": v.get("channel") or "YouTube", "platform": "youtube"})
        if len(yt_sources) >= 2:
            break
    if yt_sources:                                   # keep all 5 news when no video is found
        news_only = [s for s in sig["news_sources"] if s.get("platform") == "news"]
        sig["news_sources"] = news_only[:3] + yt_sources
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
                        "debate_hits": sig["debate_hits"], "news_sources": sig.get("news_sources", [])}}


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
    where the independent 3rd-party COA is attached (docs/PRODUCTS.md). Only LIVE SKUs get a
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
    """Score every candidate, drop blocked + previously-rejected, print breakdowns, return sorted."""
    blocked = [b.lower() for b in engine_state.get("blocked_topics", [])]
    rejected = eng.rejected_topics()      # learn from TG: don't re-propose a hard-rejected angle
    tw = engine_state.get("topic_weights", {})
    # Recency/family rotation tiebreaker (Marvin 2026-06-23): with the small catalog the 7-day
    # window can't supply a fresh pool, so without this the trending signal re-picks the GLP-1s
    # every day. Penalize a compound whose name OR family was featured recently. Env-gated.
    penalize = (eng.load_env("ENGINE_TOPIC_RECENCY_PENALTY", "1") or "1") != "0"
    recent_used = recently_used_compounds() if penalize else []
    scored = []
    for c in candidates:
        cl = c.lower()
        if any(b in cl for b in blocked):
            log(f"blocked: {c}")
            continue
        if any(r == cl or r in cl for r in rejected):
            log(f"skipped (a near-identical angle was REJECTED in TG before — avoiding a repeat): {c}")
            continue
        sig = gather_signals(c, fresh=fresh)
        sc = score_topic(c, sig, tw)
        if penalize:
            f = recency_penalty(sc.get("compound") or c, recent_used)
            if f < 1.0:
                sc["recency_penalty"] = round(f, 3)
                sc["final"] *= f
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
    if "threads.net" in u or "threads.com" in u:
        return "threads"
    if "twitter.com" in u or "x.com" in u:
        return "x"
    return "article"


def bank_source(url, fresh=False):
    """SINGLE extraction point (RV0). Pull the source's FULL text via the `--raw` flag —
    Apify for social/video URLs, Firecrawl for article/blog/website URLs — and bank it
    under output/research/sources/. Apify fires a fresh (paid) actor run per call and does
    NOT cache by URL; Firecrawl bills per scrape — so this `--raw` call is the ONLY scrape
    we ever make of a source: the structured pattern below is derived locally from the
    banked text, never a 2nd scrape. The 7-day run_tool cache then blocks accidental
    re-spend on re-runs. Blotato is NEVER used for extraction (publish/schedule only)."""
    platform = _detect_platform(url)
    if platform in ("youtube", "instagram", "tiktok", "facebook", "threads", "x"):
        raw = run_tool("apify.py", ["scrape", url, "--raw"], ttl=7 * CACHE_TTL, fresh=fresh)
    else:
        raw = run_tool("firecrawl.py", ["scrape", url, "--raw"], ttl=7 * CACHE_TTL, fresh=fresh)
    if not raw:
        return None
    rec = source_bank.upsert(url, platform, raw)
    # FEED THE BANK (Marvin 2026-06-22): a long source carries far more than one post — mine a
    # backlog of distinct angles ONCE per source (only if it has none yet) so the week's extractions
    # fill the bank for Sunday's bank-first day. One cheap OpenRouter call; fail-soft.
    if rec and not rec.get("angles") and rec.get("full_transcript"):
        try:
            rec = source_bank.propose_angles(rec, n=6)
        except Exception as ex:
            log(f"bank angle-mining skipped (non-fatal) for {rec.get('source_id')}: {ex}")
    return rec


def extract_pattern(url, fresh=False):
    """Extract a viral post's pattern (hook + text + format type) for Mode-B cloning. Reads
    the banked FULL transcript (bank_source harvests it once) instead of a fresh scrape, so
    Mode B and the Source Bank share the single paid extraction per URL."""
    platform = _detect_platform(url)
    rec = bank_source(url, fresh=fresh)
    text = (rec.get("full_transcript") or rec.get("caption") or "") if rec else ""
    caption = (rec.get("caption") or "") if rec else ""
    if not text:
        # --raw returned nothing parseable — fall back to the structured scrape ONCE so a
        # transient empty transcript can't silently abort Mode B (recovery, not routine).
        if platform in ("youtube", "instagram", "tiktok", "facebook", "threads", "x"):
            data = run_tool("apify.py", ["scrape", url], ttl=7 * CACHE_TTL, fresh=fresh)
        else:
            data = run_tool("firecrawl.py", ["scrape", url], ttl=7 * CACHE_TTL, fresh=fresh)
        if not data:
            return None
        d = data[0] if isinstance(data, list) else data
        # Firecrawl puts the article body in `markdown` (preferred over the short meta
        # `description`); apify's social text is in transcript/caption.
        text = (d.get("transcript") or d.get("caption") or d.get("markdown")
                or d.get("description") or d.get("content") or d.get("text") or "")
        caption = d.get("caption") or d.get("description") or ""
        if not text:
            return None
    eng = (rec.get("engagement") or {}) if rec else {}
    hook = _first_line(text)
    return {"platform": platform, "url": url, "hook": hook, "text": text[:1500],
            "caption": caption[:600],
            "views": parse_count(eng.get("views")), "likes": parse_count(eng.get("likes")),
            "comments": parse_count(eng.get("comments")),
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
    """v2 (Marvin 2026-06-21, supersedes v1): this engine is built EXCLUSIVELY for Acme Labs —
    ALL content is RUO, organic, and links to acmelabs.co. Acme Health (and its Affluent-Woman
    persona) gets its OWN separate content engine in a future phase, so Labs content is never routed
    to Health — even metabolic/GLP-1 angles are framed as Labs RUO research. (HEALTH_KEYWORDS is
    retained for that future Health engine.)"""
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
                    cloned_format=None, extracted_hook=None, scoring_breakdown=None, sources=None):
    """The provenance contract surfaced at approval (F2) and excluded from posts (F1).
    Records the exact source(s) + WHY it was picked, so a produced post is always traceable.
    `sources` is a list of {url,title,source,platform} — EVERY brief carries at least one
    source link (Task 3): Mode B = the cloned post; Mode A = the news articles behind the topic."""
    ref = {"url": url, "platform": platform, "description": description,
           "selection_rationale": selection_rationale, "scoring_breakdown": scoring_breakdown or {},
           "sources": list(sources or [])}
    # The primary url is always the first source too (so the card lists everything uniformly).
    if url and not any(s.get("url") == url for s in ref["sources"]):
        ref["sources"].insert(0, {"url": url, "title": description[:80], "platform": platform})
    if cloned_format:
        ref["cloned_format"] = cloned_format
    if extracted_hook:
        ref["extracted_hook"] = extracted_hook
    return ref


# ── draft + duplication gate (Marvin 2026-06-22) ───────────────────────────────
# The post's TEXT is written first (draft.md), compared against the last 7 days (approved +
# produced), and any PART that's a near-repeat of a recent post is surgically revised — never the
# whole draft, and follow-ups/continuations pass. dedup.py is the single authority; this is the
# image-card glue that maps its rewrites back onto the copywriter tokens.
def _hook_text(cp: dict, want_carousel: bool) -> str:
    if want_carousel:
        s0 = (cp.get("slides") or [{}])[0]
        keys = ("EYEBROW", "HEAD_1", "HEAD_2_ITALIC", "HEAD_3")
        return " ".join(str(s0.get(k, "")).strip() for k in keys if s0.get(k)).strip()
    keys = ("EYEBROW", "HOOK_LINE_1", "HOOK_LINE_2_ITALIC", "HOOK_LINE_3")
    return " ".join(str(cp.get(k, "")).strip() for k in keys if cp.get(k)).strip()


def _draft_from_cp(cp, *, topic, pillar, compound, want_carousel, job_id) -> dict:
    d = {"job_id": job_id, "pillar": pillar, "compound": compound, "topic": topic,
         "hook": _hook_text(cp, want_carousel), "body": cp.get("caption", "")}
    if want_carousel and cp.get("slides"):
        d["slides"] = [" / ".join(str(s.get(k, "")) for k in ("HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "BODY") if s.get(k))
                       for s in cp["slides"] if isinstance(s, dict)]
    return d


def _apply_revisions_to_cp(cp, draft, verdict, want_carousel) -> tuple[dict, list[str]]:
    """Swap ONLY the flagged elements back into the copywriter tokens: body→caption, hook→headline
    lines (carousel: slide-1 HEAD_*). Everything else is left exactly as written."""
    _, changed = dedup.revise(draft, verdict)
    by_el = {p["element"]: (p.get("revised") or "").strip() for p in verdict.get("parts", [])}
    if "body" in changed and by_el.get("body"):
        cp["caption"] = by_el["body"]
    if "hook" in changed and by_el.get("hook"):
        l1, it, l3 = dedup.split_headline(by_el["hook"])
        if want_carousel and cp.get("slides"):
            cp["slides"][0].update(HEAD_1=l1, HEAD_2_ITALIC=it, HEAD_3=l3)
        else:
            cp.update(HOOK_LINE_1=l1, HOOK_LINE_2_ITALIC=it, HOOK_LINE_3=l3)
    return cp, changed


def _write_draft_md(job_dir, job_id, draft, *, pillar, persona, compound, brand, dedup_summary=None) -> None:
    lines = [f"# {job_id} — draft", "",
             f"- pillar: {pillar} · persona: {persona} · brand: {brand} · compound: {compound or '—'}",
             f"- topic: {draft.get('topic', '')}", "",
             "## Hook", draft.get("hook") or "—", "",
             "## Body / caption", draft.get("body") or "—", ""]
    if draft.get("slides"):
        lines += ["## Slides"] + [f"{i + 1}. {s}" for i, s in enumerate(draft["slides"])] + [""]
    if dedup_summary:
        lines += ["## Duplication gate", dedup_summary, ""]
    (job_dir / "draft.md").write_text("\n".join(lines))


def dedup_gate(job_dir, job_id, cp, brief, *, topic, pillar, persona, compound, brand, want_carousel) -> dict:
    """Write the text draft, run the duplication gate, and surgically revise any near-duplicate
    PART back into cp. Always writes draft.md (the 'text drafts' stage). Fail-open. Returns cp."""
    if not cp:
        return cp
    draft = _draft_from_cp(cp, topic=topic, pillar=pillar, compound=compound,
                           want_carousel=want_carousel, job_id=job_id)
    dedup_summary = None
    if dedup is not None and (eng.load_env("ENGINE_DEDUP", "1") or "1") != "0":
        try:
            verdict = dedup.check_draft(draft, dedup.recent_corpus(exclude_job=job_id))
            cp, changed = _apply_revisions_to_cp(cp, draft, verdict, want_carousel)
            dedup_summary = dedup.summarize(verdict, changed)
            if changed:
                brief["dedup_note"] = dedup_summary
                draft = _draft_from_cp(cp, topic=topic, pillar=pillar, compound=compound,
                                       want_carousel=want_carousel, job_id=job_id)
            log(f"{job_id}: dedup — {dedup_summary}")
        except Exception as ex:                          # a gate hiccup must never break produce
            log(f"{job_id}: dedup gate skipped (non-fatal): {ex}")
    _write_draft_md(job_dir, job_id, draft, pillar=pillar, persona=persona,
                    compound=compound, brand=brand, dedup_summary=dedup_summary)
    return cp


def assemble_brief(pillar, topic, *, persona=None, brand=None, template=None,
                   carousel=None, provenance=None, reference=None, job_id=None,
                   dry_run=False, fresh=False, note=None):
    """Produce one post.py-ready type=image brief.json (+ copy.json + research.json
    sidecars) from a selected topic. Returns the brief dict (and writes it unless dry-run).

    carousel=N (or a carousel-* template) -> a full N-slide deck: copywriter.py --carousel writes
    slides.json and the brief points post.py at it. Otherwise a single branded card."""
    preset = PILLAR_PRESETS[pillar]
    persona = persona or persona_for(pillar)
    brand = brand or route_brand(topic, pillar)
    product_feature = preset.get("product_feature", False)
    compound = _catalog_match(topic)
    cls = COMPOUND_CATALOG.get(compound, {}).get("cls") if compound else None

    # SLOT/FORMAT WIRING (Devon §3.2): when the caller forces neither a template NOR a carousel,
    # pick the pillar's format-of-the-day (carousel / single / product / compare / quote …) and
    # map it to the right template. This is what routes story-product onto stack product days and
    # story-poll-pro onto trending this-or-that / stack compare days. Explicit template= or
    # carousel=N (manual overrides, outlier/inbox/bank clones) bypass the rotation.
    if template is None and carousel is None:
        template, fmt_wants_carousel = daily_image_template(
            pillar, brand, product_feature=product_feature)
        if fmt_wants_carousel:
            carousel = CAROUSEL_DEFAULT_SLIDES
    template = template or preset["template"]
    template = retheme(template, pillar, brand)  # content.md mode by slot (morning light / eve dark)

    # Carousel intent: an explicit N, or a carousel-* template was chosen.
    want_carousel = bool(carousel) or template in CAROUSEL_TEMPLATES
    if want_carousel and template not in CAROUSEL_TEMPLATES:
        template = themed("carousel", pillar, brand)
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
    if note:        # REVISE re-production: steer the fresh copy at the reviewer's note (busts the run_copy cache)
        copy_topic += f"\nReviewer revision request — rewrite to address this specifically: {note}"
    cp = run_copy(copy_topic, brand, "instagram", product_feature, compound, cls,
                  fresh=fresh, carousel=n_slides if want_carousel else None)
    if not isinstance(cp, dict) or not cp:
        log(f"copywriter.py failed for {job_id} — writing brief without tokens (run copywriter.py later)")
        cp = {}

    # Text draft → duplication gate (surgically revises any near-repeat PART) BEFORE the template
    # is built. Always writes draft.md. Fail-open — never blocks the morning produce.
    cp = dedup_gate(job_dir, job_id, cp, brief, topic=topic, pillar=pillar, persona=persona,
                    compound=compound, brand=brand, want_carousel=want_carousel)

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
         "source_urls": [s.get("url") for s in _ref.get("sources", []) if s.get("url")],
         "cloned_format": _ref.get("cloned_format"), **(provenance or {})},
        ensure_ascii=False, indent=2))

    ok, errs = validate_brief(brief)
    log(f"{'OK ' if ok else 'INVALID '}{job_id} -> {job_dir}/brief.json"
        + ("" if ok else f"  errors: {errs}"))
    return brief


# Video cadence — ALTERNATING DAYS only (Marvin 2026-06-19, OVERRIDES Devon's §3.2 grid which
# fired reels up to 4 days/week / 2 a day). A reel ≈ 135 real Higgsfield credits, so daily video
# would blow the Ultra monthly budget (3000); every-other-day keeps it to ~1 reel/video-day.
# On a video day EXACTLY ONE pillar carries the reel, alternating trending <-> science across
# video days so both keep a video presence. Every other pillar — and ALL pillars on a non-video
# day — produce 0-credit images. The video-day calendar lives in engine (eng.is_video_day).
REEL_PILLARS = ("trending", "science")   # the pillars eligible to carry the alternating reel


def reel_pillar_today(d=None):
    """The single pillar that gets the video reel today, or None on a non-video day."""
    d = d or eng.today_date()
    if not eng.is_video_day(d):
        return None
    video_index = (d.toordinal() - eng._video_anchor().toordinal()) // 2  # 0,1,2… per video day
    return REEL_PILLARS[video_index % len(REEL_PILLARS)]


def slot_wants_reel(pillar, d=None):
    """True only when TODAY is a video day AND `pillar` is the one reel pillar for it. §3.2 is
    overridden to alternating-day video (Marvin 2026-06-19): at most ONE reel/day, never on two
    consecutive days. The 'slot calls for video' trigger the F7 loop consults."""
    return pillar == reel_pillar_today(d)


def assemble_reel_brief(pillar, topic, *, persona=None, brand=None, reference=None,
                        script=None, job_id=None, dry_run=False, fresh=False):
    """Produce one type=reel brief.json (RV1). The reel chain fills the rest later:
    RV2 writes brief.script, RV3 the generated CLEAN b-roll into brief.video. There is NO
    caption-burn step in the overlay model — reel.py composites brief.overlay (a transparent
    brand template) over the clean video (produce.py --video-underlay), so the caption lives
    in the template, never burned in. Here we fix the concept — topic/pillar/persona/brand/
    reference + the brand OVERLAY tokens (reel-overlay-broll template, same tokens copywriter
    already emits) — so GATE 1 can approve the concept BEFORE any Higgsfield credit."""
    preset = PILLAR_PRESETS[pillar]
    persona = persona or persona_for(pillar)
    brand = brand or route_brand(topic, pillar)
    product_feature = preset.get("product_feature", False)
    compound = _catalog_match(topic)
    cls = COMPOUND_CATALOG.get(compound, {}).get("cls") if compound else None
    # Video-underlay overlay model (Marvin 2026-06-20): the engine generates b-roll only
    # (no talking-head — reel_video.py), so the default overlay is the molecular b-roll family.
    # Theme follows content.md's SLOT rule (theme_for): a science-day reel (08:00) is light, a
    # trending-day reel (13:00) is dark; Health stays light. The studio/person-on-camera overlay
    # (reel-overlay-studio-*) is for MANUAL founder reels with real talking-head footage.
    overlay_tpl = f"reel-overlay-broll-{theme_for(pillar, brand)}"

    job_id = job_id or next_job_id()
    if not eng.is_video_day():   # alternating-day cadence (Marvin 2026-06-19) — note, don't block a manual override
        log(f"note: today is NOT a video day (alternating cadence) — building reel {job_id} anyway "
            f"(manual/override; the autonomous loop only makes reels on video days)")
    bn = "ACME HEALTH" if brand == "health" else "ACME LABS"
    handle = "@acmehealth" if brand == "health" else "@acmelabs"
    brief = {
        "job_id": job_id, "type": "reel", "brand": brand, "pillar": pillar,
        "persona": persona, "topic": topic,
        # Reels have a fixed video distribution: TikTok + X + YouTube (video-only). IG is
        # skipped by publish.py until Meta is connected; YouTube takes video only.
        "platforms": ["tiktok", "x", "youtube"],
        # No caption_data: the overlay model carries the caption as static template text
        # (brief.overlay below), composited over the clean video — never burned in.
    }
    if compound:
        brief["compound"] = compound
        if cls:
            brief["class"] = cls
    if product_feature:
        brief["product_feature"] = True
    link = product_link(compound, brand)
    if link:
        brief["link"] = link
    if script:
        brief["script"] = script
    if reference:
        brief["reference"] = reference

    if dry_run:
        log(f"DRY-RUN would assemble REEL {job_id}: {pillar}/{persona}/{brand} "
            f"[{overlay_tpl}] <- {topic[:60]!r}")
        return brief

    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # M2 — fill the branded cover's overlay tokens via copywriter.py (same engine as images).
    copy_topic = f"{topic}\n{PERSONA_VOICE.get(persona, '')}".strip()
    cp = run_copy(copy_topic, brand, "instagram", product_feature, compound, cls, fresh=fresh)
    if not isinstance(cp, dict) or not cp:
        log(f"copywriter.py failed for {job_id} — cover tokens minimal (re-run copywriter.py later)")
        cp = {}
    overlay = {"template": f"templates/src/{overlay_tpl}.html",
               **_map_tokens(overlay_tpl, cp, brand, compound, product_feature)}
    # Labs reels: surface RUO in the overlay eyebrow (schema convention + §5 QC).
    if brand == "labs":
        overlay["EYEBROW"] = "RESEARCH USE ONLY"
    brief["overlay"] = overlay

    (job_dir / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    if cp:
        (job_dir / "copy.json").write_text(json.dumps(cp, ensure_ascii=False, indent=2))
    _ref = reference or {}
    (job_dir / "research.json").write_text(json.dumps(
        {"job_id": job_id, "discovered_at": now_iso(), "type": "reel", "reference": _ref,
         "source_url": _ref.get("url"), "source_platform": _ref.get("platform"),
         "source_urls": [s.get("url") for s in _ref.get("sources", []) if s.get("url")],
         "cloned_format": _ref.get("cloned_format")},
        ensure_ascii=False, indent=2))

    ok, errs = validate_brief(brief)
    log(f"{'OK ' if ok else 'INVALID '}{job_id} (reel) -> {job_dir}/brief.json"
        + ("" if ok else f"  errors: {errs}"))
    return brief


def _map_tokens(template, cp, brand, compound, product_feature):
    """Map copywriter.py output -> the exact token names the chosen template needs."""
    bn = cp.get("BRAND_NAME") or ("ACME HEALTH" if brand == "health" else "ACME LABS")
    handle = cp.get("HANDLE") or ("@acmehealth" if brand == "health" else "@acmelabs")
    ruo = "RUO · NOT FOR HUMAN CONSUMPTION"
    # story-reel (legacy cover/overlay) AND the new video-underlay reel overlays share the
    # exact same token set, so copywriter.py fills either with one mapping.
    if template in ("story-reel-dark", "story-reel-light",
                    "reel-overlay-studio-dark", "reel-overlay-studio-light",
                    "reel-overlay-broll-dark", "reel-overlay-broll-light"):
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
    tagline = "HORMONES · LONGEVITY · PERFORMANCE" if brand == "health" else "PEPTIDES · PERFORMANCE · LONGEVITY"
    if template in ("story-product-dark", "story-product-light"):
        # Product-announcement / restock story card — fills from the compound catalog. Rich rows
        # default to lab-standard facts; override per-product via brief.image.set. PRODUCT_IMAGE
        # defaults to a generic vial — pass a real product photo for a specific SKU.
        info = COMPOUND_CATALOG.get(compound, {})
        sku = info.get("sku", "")
        # Real SKU photo (Marvin 2026-06-21): resolve the compound → its product image and feed
        # the file:// URI the renderer loads (render.py renders from a file:// page, so a local
        # file:// img loads with no ARG_MAX bloat). Falls back to the labelled placeholder when
        # there's no photo for the compound; per-job brief.image.set still overrides.
        prod_uri = (product_images.file_uri(compound) if (product_images and compound) else None) or ""
        return {"BRAND_NAME": bn, "BRAND_TAGLINE": tagline, "HANDLE": handle,
                "EYEBROW_NUM": "01", "EYEBROW": "DROP · RESTOCK", "STATUS_CHIP": "IN STOCK",
                "HEADLINE_EM": cp.get("HOOK_LINE_2_ITALIC") or "Featured", "HEADLINE_1": "—",
                "HEADLINE_2": (f"{compound}." if compound else cp.get("HOOK_LINE_3", "")),
                "SUBCTX": cp.get("SUBTITLE_TEXT", ""),
                "PRODUCT_IMAGE": prod_uri,
                "PLACEHOLDER_LABEL": (f"{compound} · image pending" if compound else "Product image pending"),
                "LOT": "RESEARCH GRADE", "COA_CHIP": "COA AVAILABLE",
                "SKU": (f"PRODUCT · {sku.upper()}" if sku else "PRODUCT"),
                "COMPOUND": compound or "", "DOSE": info.get("spec", ""),
                "PRICE": info.get("price", ""), "PRICE_UNIT": "/ VIAL", "RUO_LINE": ruo,
                "SPEC1_TAG": "PURITY", "SPEC1_TEXT": "≥99% HPLC purity verified by US 3rd-party lab. COA on every lot.",
                "SPEC2_TAG": "CLASS", "SPEC2_TEXT": info.get("cls", "Research compound"),
                "SPEC3_TAG": "FORM", "SPEC3_TEXT": info.get("spec", "Lyophilized · cold-chain shipped, 48-hr to door."),
                "SPEC4_TAG": "STANDARD", "SPEC4_TEXT": "Batch-traceable, independent COA on file — same standard, every lot.",
                "CALLOUT_QUOTE": "Same lab standard on every lot. Every Acme vial ships with its independent COA — never marketing claims alone.",
                "CALLOUT_SRC": "INDEPENDENT US LAB", "CTA_LABEL": "BROWSE CATALOG",
                "FOOTER_ACTION": "TAP TO SHOP", "PAGE": "1 / 1"}
    if template in ("story-poll-pro-dark", "story-poll-pro-light"):
        # Engagement poll / this-or-that story card. The hook fills from copywriter; the poll
        # options + icon rows default to a BPC-157↔Semaglutide compare — override per-poll via
        # brief.image.set (full autonomous poll generation is a copywriter follow-up).
        return {"BRAND_NAME": bn, "BRAND_TAGLINE": tagline, "HANDLE": handle,
                "EYEBROW_NUM": "01", "EYEBROW": "QUICK QUESTION · POLL",
                "HOOK_LINE_1": cp.get("HOOK_LINE_1", ""), "HOOK_LINE_2_ITALIC": cp.get("HOOK_LINE_2_ITALIC", ""),
                "HOOK_LINE_3": cp.get("HOOK_LINE_3", ""), "SUBCTX": cp.get("SUBTITLE_TEXT", ""),
                "ROW1_TAG": "STRUCTURE", "ROW1_TEXT": "BPC-157 is a 15-aa pentadecapeptide. Semaglutide is a 31-aa GLP-1 analog.",
                "ROW2_TAG": "EVIDENCE", "ROW2_TEXT": "Both have human-trial data; BPC-157 is broader in soft-tissue research.",
                "ROW3_TAG": "PURITY", "ROW3_TEXT": "≥99% HPLC, US 3rd-party COA, batch-traceable — same standard, both vials.",
                "ROW4_TAG": "PROTOCOL", "ROW4_TEXT": "Different cycles: 4-week sprint vs. weekly titration. Pick what fits.",
                "TAP_LABEL": "TAP TO VOTE",
                "POLL_A_NAME": "BPC-157", "POLL_A_META": "PENTADECAPEPTIDE · 5MG",
                "POLL_B_NAME": "SEMAGLUTIDE", "POLL_B_META": "GLP-1 ANALOG · 5MG",
                "CALLOUT_QUOTE": "Both are research compounds. Verified standard, traceable lot, COA on file.",
                "CALLOUT_SRC": "ACME LAB STANDARD · 2026", "FOOTER_ACTION": "SWIPE TO ANSWER", "PAGE": "1 / 1"}
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
    # Delegate to engine.read_state so a fresh clone/worktree (no live engine_state.json — it's
    # gitignored runtime) seeds from engine_state.example.json instead of losing topic_weights.
    return eng.read_state() or {"topic_weights": {}, "blocked_topics": []}


def cmd_topics(args):
    es = load_engine_state()
    if args.candidates:
        candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    else:
        # Default seed = highest-weighted Acme compounds, but ROTATE on a 7-DAY PRODUCT WINDOW:
        # hold back any product (compound) that went out in the last 7 days so the daily run picks a
        # FRESH product related to the research, never re-featuring the same SKU within a week
        # (Marvin 2026-06-22; supersedes the job-count cooldown for product selection).
        tw = es.get("topic_weights", {})
        ranked = sorted(tw, key=tw.get, reverse=True) or list(COMPOUND_CATALOG)
        recent = products_in_last_days(7)
        fresh = [c for c in ranked if c not in recent]
        need = args.select + 2
        # Prefer fresh; only if the catalog can't fill the day fall back to the least-recently-used.
        candidates = (fresh + [c for c in reversed(recent) if c in ranked])[:need] or ranked[:need]
        if recent:
            log(f"rotation: holding back {recent} (used in the last {_cooldown_jobs()} jobs)")
    log(f"Mode A — scoring {len(candidates)} candidates: {candidates}")
    scored = discover_topics(candidates, es, fresh=args.fresh)
    # SearchAPI is the only live signal Mode A scores on. If it's depleted, every candidate ties
    # at the same zero-signal score and selection degenerates to compound rotation -> duplicate
    # posts (ACME-062..065, 2026-06-23). Refuse to generate; the per-tool Telegram alert
    # (api_alerts.note) has already asked for drop links. ENGINE_FORCE_DISCOVERY=1 overrides.
    if "searchapi" in DEPLETED_TOOLS and (eng.load_env("ENGINE_FORCE_DISCOVERY", "") or "").strip() != "1":
        log("SearchAPI depleted — no live discovery signal; NOT generating blind-rotation briefs "
            "(they would be duplicates). Telegram heads-up asked for drop links instead.")
        return
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
    # v2: the daily run (spread=True) covers ALL non-trending pillars, not just science|stack.
    spread = getattr(args, "spread", False) and not args.pillar
    plan = plan_pillar_briefs(picks, spread=spread, explicit_pillar=args.pillar)
    for pillar, s in plan:
        topic = (frame_for(pillar).format(t=s["topic"])
                 if (spread and pillar in PILLAR_TOPIC_FRAMES) else f"{s['topic']} research")
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
            scoring_breakdown=s, sources=sig.get("news_sources"))
        prov = {"discovery_mode": "A_topic", "selected_topic": s["topic"]}
        # --no-carousel forces the pillar's single-card default; otherwise None lets assemble_brief
        # run Devon's §3.2 format-of-the-day rotation (carousel / single / product / compare …).
        tmpl = PILLAR_PRESETS[pillar]["template"] if getattr(args, "single", False) else None
        brief = assemble_brief(pillar, topic, template=tmpl, job_id=jid, provenance=prov, reference=ref,
                               carousel=getattr(args, "carousel", None), fresh=args.fresh)
        store.add_discovery(platform="searchapi", content_type="topic",
                            caption=s["topic"], format_type=pillar,
                            engagement=s["signals"])
        store.add_brief(pillar=pillar, persona=brief["persona"], format_type=pillar,
                        hook_angle=topic, scoring_breakdown=s, job_id=jid, reference=ref,
                        brief_path=str(JOBS_DIR / jid / "brief.json"))
    log(f"Mode A wrote {len(plan)} brief(s) across pillars {[p for p, _ in plan]} -> {store.dir}")


def cmd_outliers(args):
    # Default sweep mines the FIRST 3 queries — now the throughline framings (myth-bust /
    # comparison / "what it actually does"), which surface the outliers we can convert (doctrine
    # above). --query overrides for a one-off. Bumped 2->3 (Marvin 2026-06-21) to widen the net;
    # searchapi calls are cached (CACHE_TTL) so the extra query rarely costs a live request.
    queries = [args.query] if args.query else OUTLIER_YT_QUERIES[:3]
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
                       as_reel=getattr(args, "reel", False),
                       dry_run=args.dry_run, fresh=args.fresh)


def cmd_inbox(args):
    """Drop-a-link: Marvin/Devon paste a viral URL (any platform) -> reverse-engineer it.

    Consults the reference-link ledger (reference_links.py) so a link whose FORMAT we already
    cloned is SKIPPED (no re-scrape) unless --force; on a fresh clone the link is recorded as
    used + tied to the job it produced. Fail-open: a ledger hiccup never blocks the clone."""
    try:
        import reference_links as _refs
    except Exception:
        _refs = None
    if _refs is not None and not args.dry_run and not getattr(args, "force", False):
        try:
            if _refs.is_used(args.url):
                row = _refs.find(args.url) or {}
                log(f"reference already used (job {row.get('job_id') or '—'}) — skipping "
                    f"{args.url}  [use --force to clone again]")
                return
        except Exception as ex:
            log(f"reference-ledger check skipped (non-fatal): {ex}")
    store = DiscoveryStore()
    before = {p.name for p in JOBS_DIR.glob("ACME-*")}
    _extract_and_brief(args.url, store, persona=args.persona, brand=args.brand,
                       curated=True, acme_topic=args.topic, pillar=args.pillar,
                       carousel=getattr(args, "carousel", None),
                       as_reel=getattr(args, "reel", False),
                       dry_run=args.dry_run, fresh=args.fresh)
    if _refs is not None and not args.dry_run:
        new = sorted({p.name for p in JOBS_DIR.glob("ACME-*")} - before)
        if new:                                       # only record once a brief actually landed
            try:
                _refs.mark_used(args.url, job_id=new[-1], who="inbox",
                                note=f"Mode-B format reference cloned into {new[-1]}")
            except Exception as ex:
                log(f"reference-ledger record skipped (non-fatal): {ex}")


def cmd_recopy(args):
    """Regenerate an EXISTING image job's copy/slides IN PLACE (M2), folding in the reviewer's
    REVISE note — the image re-production path (produce_daily calls this on a status=revise image).
    Keeps the same job_id, pillar, brand, template/format and reference; only the COPY changes to a
    fresh, note-aware variant. 0 Higgsfield credits."""
    job_dir = Path(args.job_dir).resolve()
    brief = json.loads((job_dir / "brief.json").read_text())
    if brief.get("type") != "image":
        sys.exit(f"recopy only handles type=image (got {brief.get('type')!r}; reels re-render via reel.py)")
    img = brief.get("image", {}) or {}
    stem = Path(img.get("template", "")).stem or None       # templates/src/<stem>.html -> <stem>
    carousel = None
    if img.get("carousel"):
        slides = json.loads((job_dir / "slides.json").read_text()) if (job_dir / "slides.json").exists() else None
        carousel = len(slides) if isinstance(slides, list) and slides else CAROUSEL_DEFAULT_SLIDES
    assemble_brief(brief["pillar"], brief["topic"], persona=brief.get("persona"),
                   brand=brief.get("brand"), template=stem, carousel=carousel,
                   reference=brief.get("reference"), job_id=brief["job_id"],
                   note=args.note, fresh=True)


def cmd_drops(args):
    """Drain pending Telegram link-drops (drops.py, captured by approvals.py from ANY user) into
    Trending briefs — v2 Stage 1 "manual_save". FIFO, up to --max, each gated by the daily apify
    budget so the firehose can never blow the cap. Extraction failures are marked 'failed' so a bad
    URL never retries forever. 0 Higgsfield credits (Mode B image clone; never mints a reel)."""
    import drops as dr
    eng.assert_running("research-drops")
    pend = dr.pending(limit=args.max)
    if not pend:
        log("no pending manual link-drops.")
        return
    store = DiscoveryStore()
    consumed = 0
    for d in pend:
        if not args.dry_run and not eng.spend("apify", 1):
            log("apify daily cap reached — stopping drop drain (remaining drops stay pending).")
            break
        log(f"drop {d['id']} ({d['platform']}) by {d.get('who')}: {d['url']}")
        before = {p.name for p in JOBS_DIR.glob("ACME-*")}
        try:
            _extract_and_brief(d["url"], store, persona=persona_for("trending"), brand="labs",
                               curated=True, pillar="trending", dry_run=args.dry_run, fresh=args.fresh,
                               source_type="manual_save", priority_bonus=d.get("priority_bonus", 3))
        except Exception as ex:                       # extraction/network failure — don't retry forever
            log(f"drop {d['id']} extraction error: {ex}")
            dr.mark(d["id"], "failed")
            continue
        if args.dry_run:
            continue
        new = sorted({p.name for p in JOBS_DIR.glob("ACME-*")} - before)
        if new:
            dr.mark(d["id"], "consumed", job_id=new[-1])
            try:                                       # mirror into the used-references ledger
                import reference_links as _refs
                _refs.mark_used(d["url"], job_id=new[-1], who=d.get("who", "telegram"),
                                note=f"drop {d['id']} cloned into {new[-1]}")
            except Exception as ex:
                log(f"reference-ledger record skipped (non-fatal): {ex}")
            consumed += 1
        else:                                         # extract_pattern returned nothing usable
            dr.mark(d["id"], "failed")
    log(f"drops: {consumed} consumed of {len(pend)} pending (max {args.max}).")


def _extract_and_brief(url, store, *, persona="P3", brand="labs", curated=False,
                       acme_topic=None, pillar="trending", outlier_meta=None,
                       carousel=None, as_reel=False, dry_run=False, fresh=False,
                       source_type=None, priority_bonus=None):
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

    dq_extra = {}                                    # v2 discovery_queue: manual drops carry source_type + priority_bonus
    if source_type:
        dq_extra["source_type"] = source_type
    if priority_bonus is not None:
        dq_extra["priority_bonus"] = priority_bonus
    store.add_discovery(source_url=url, platform=pattern["platform"],
                        caption=pattern.get("caption", "")[:300], content_type="outlier",
                        format_type=pattern["format_type"],
                        engagement={"views": pattern["views"], "likes": pattern["likes"],
                                    "comments": pattern["comments"]}, **dq_extra)
    if dry_run:
        log("dry-run: pattern extracted + scored, not assembling brief")
        return
    jid = next_job_id()
    if as_reel:
        # Mode B is video-native: clone the viral structure into a reel concept (RV1). The
        # cloned format lives in reference.cloned_format; the reel chain (RV2-RV4) fills the rest.
        brief = assemble_reel_brief("trending", topic, persona=persona, brand=brand,
                                    job_id=jid, reference=ref, fresh=fresh)
        fmt_label = "reel"
    else:
        brief = assemble_brief("trending", recon["hook_angle"], persona=persona, brand=brand,
                               template=recon["template"], carousel=carousel, job_id=jid,
                               provenance={"discovery_mode": "B_outlier"}, reference=ref, fresh=fresh)
        # Keep the brief.topic clean/human (the long copywriter.py angle lives in research.json).
        brief_path = JOBS_DIR / jid / "brief.json"
        bj = json.loads(brief_path.read_text())
        bj["topic"] = topic
        brief_path.write_text(json.dumps(bj, ensure_ascii=False, indent=2))
        fmt_label = pattern["format_type"]
    brief_path = JOBS_DIR / jid / "brief.json"
    store.add_brief(pillar="trending", persona=persona, source_url=url,
                    format_type=("reel" if as_reel else pattern["format_type"]), hook_angle=topic,
                    scoring_breakdown=sc, job_id=jid, brief_path=str(brief_path), reference=ref)
    log(f"Mode B cloned {fmt_label} -> {jid} (topic: {topic!r})")


def _suggest_topic(pattern, persona):
    """Pick an on-brand Acme topic that fits the extracted format. Prefer a live SKU."""
    text = f"{pattern['hook']} {pattern['text']}".lower()
    for name, info in COMPOUND_CATALOG.items():
        if name.lower() in text:
            return f"{name} {info['descriptor'].lower()}"
    live = [n for n, i in COMPOUND_CATALOG.items() if i.get("live")]
    return f"{live[0]} research" if live else "peptide research"


def cmd_bank(args):
    """Source Bank (RV0): reuse a previously-paid source's banked angles. List the bank, or
    mine UNUSED angles from one source into briefs at ZERO new extraction cost (only the cheap
    copywriter call per brief). Reel-format angles are emitted by the F7 reel pipeline (RV1+);
    here we mine the 0-credit image/carousel/callout angles."""
    if getattr(args, "list", False) or not args.source:
        rows = source_bank.all_sources()
        if not rows:
            log("no banked sources yet — `research.py inbox|outliers --extract` harvests one")
            return
        for r in rows:
            nu = len(source_bank.unused_angles(r))
            log(f"{r['source_id']}  {r['platform']:<9} {r['transcript_chars']:>6}c  "
                f"{nu} unused/{len(r.get('angles', []))} angles  {r['url'][:60]}")
        return

    rec = source_bank.load(args.source)
    if not rec:
        log(f"no banked source for {args.source!r}")
        return
    if args.propose or not rec.get("angles"):
        rec = source_bank.propose_angles(rec, n=args.propose or 6, brand=args.brand)

    store = DiscoveryStore()
    made = 0
    for a in source_bank.unused_angles(rec, fmt=args.format):
        if made >= args.n:
            break
        jid = next_job_id()
        views = (rec.get("engagement") or {}).get("views", 0)
        ref = build_reference(
            url=rec["url"], platform=rec["platform"],
            description=f"Source Bank angle {a['id']} — {rec['platform']} source ({views:,} views)",
            selection_rationale=(f"Reused banked angle {a['id']} from a previously-paid extraction "
                                 f"(0 new extraction cost): {a['angle'][:120]}"),
            cloned_format=a["format"])
        ref["segment_id"] = a["id"]  # provenance: the exact part of the source this post used
        if args.dry_run:
            log(f"DRY-RUN would mine {a['id']} [{a['format']}/{a['pillar']}] -> {jid}: {a['angle'][:60]!r}")
            made += 1
            continue
        if a["format"] == "reel":
            brief = assemble_reel_brief(a["pillar"], a["angle"], brand=args.brand, job_id=jid,
                                        reference=ref, fresh=args.fresh)
        else:
            template = "static-callout-dark" if a["format"] == "callout" else None
            carousel = CAROUSEL_DEFAULT_SLIDES if a["format"] == "carousel" else None
            brief = assemble_brief(a["pillar"], a["angle"], brand=args.brand, template=template,
                                   carousel=carousel, job_id=jid, reference=ref, fresh=args.fresh,
                                   provenance={"discovery_mode": "bank_reuse",
                                               "source_id": rec["source_id"], "angle_id": a["id"]})
        store.add_brief(pillar=a["pillar"], persona=brief["persona"], source_url=rec["url"],
                        format_type=a["format"], hook_angle=a["angle"], job_id=jid,
                        brief_path=str(JOBS_DIR / jid / "brief.json"), reference=ref)
        source_bank.mark_used(rec, a["id"], jid)
        made += 1
        log(f"bank-mined {a['id']} [{a['format']}/{a['pillar']}] -> {jid} (0 extraction cost)")
    log(f"Source Bank: minted {made} brief(s) from {rec['source_id']}")


def serve_bank_day(*, n, brand="labs", dry_run=False, fresh=False) -> int:
    """Bank-FIRST day (Sundays): mint up to `n` NON-TRENDING briefs from the bank's unused angles
    across all sources — spread across pillars, each archived on use — instead of an external sweep
    (Marvin 2026-06-22: 'every Sunday search the internal bank first'). Returns how many were minted;
    the caller tops up externally if this is short (external = the fallback). 0 extraction cost."""
    pool = [(rec, a) for rec in source_bank.all_sources()
            for a in source_bank.unused_angles(rec) if a.get("format") != "reel"]
    if not pool:
        log("Sunday bank-first: the Source Bank has no unused angles — falling back to external research")
        return 0
    store = DiscoveryStore()
    made, used_pillars = 0, []
    while pool and made < n:
        # Prefer a pillar we haven't filled yet this run (spread); else take the next available.
        idx = next((i for i, (_, a) in enumerate(pool)
                    if (a.get("pillar") or "science") in NON_TRENDING_PILLARS
                    and (a.get("pillar") or "science") not in used_pillars), 0)
        rec, a = pool.pop(idx)
        pillar = a.get("pillar") if a.get("pillar") in NON_TRENDING_PILLARS else "science"
        jid = next_job_id()
        ref = build_reference(
            url=rec["url"], platform=rec["platform"],
            description=f"Source Bank angle {a['id']} — {rec['platform']} (Sunday bank-first)",
            selection_rationale=(f"Reused banked angle {a['id']} from a previously-paid extraction "
                                 f"(0 new extraction cost): {a['angle'][:120]}"),
            cloned_format=a.get("format"))
        ref["segment_id"] = a["id"]
        if dry_run:
            log(f"DRY-RUN Sunday bank-first would mint {a['id']} [{a.get('format')}/{pillar}] -> {jid}: {a['angle'][:60]!r}")
            made += 1
            used_pillars.append(pillar)
            continue
        template = "static-callout-dark" if a.get("format") == "callout" else None
        carousel = CAROUSEL_DEFAULT_SLIDES if a.get("format") == "carousel" else None
        brief = assemble_brief(pillar, a["angle"], brand=brand, template=template, carousel=carousel,
                               job_id=jid, reference=ref, fresh=fresh,
                               provenance={"discovery_mode": "bank_reuse_sunday",
                                           "source_id": rec["source_id"], "angle_id": a["id"]})
        store.add_brief(pillar=pillar, persona=brief["persona"], source_url=rec["url"],
                        format_type=a.get("format") or "carousel", hook_angle=a["angle"], job_id=jid,
                        brief_path=str(JOBS_DIR / jid / "brief.json"), reference=ref)
        source_bank.mark_used(rec, a["id"], jid)         # archive the angle (removed from the pool)
        made += 1
        used_pillars.append(pillar)
        log(f"Sunday bank-first: minted {a['id']} [{a.get('format')}/{pillar}] -> {jid} (0 extraction cost)")
    log(f"Sunday bank-first: minted {made}/{n} brief(s) from the bank")
    return made


def cmd_run(a):
    """The full daily build. Mon–Sat: external Mode-A topics (+ Mode-B trending). SUNDAY: bank-FIRST
    — fill the day from the Source Bank (the week's banked extractions); only top up with an external
    sweep if the bank is short. Trending still comes from outliers/drops."""
    select = a.select
    if eng.today_date().weekday() == 6:                  # 6 = Sunday
        log("Sunday — bank-first: drawing today's topics from the internal Source Bank")
        select = max(0, select - serve_bank_day(n=select, brand="labs",
                                                 dry_run=a.dry_run, fresh=a.fresh))
        if select == 0:
            log("Sunday bank-first filled the day from the bank — skipping the external sweep")
    if select > 0:
        cmd_topics(argparse.Namespace(candidates=None, select=select, pillar=None,
                                      carousel=a.carousel, single=a.single,
                                      dry_run=a.dry_run, fresh=a.fresh, spread=True))
    if not a.no_outliers:
        cmd_outliers(argparse.Namespace(query=None, num=15, extract=True, carousel=a.carousel,
                                        single=a.single, dry_run=a.dry_run, fresh=a.fresh))


def _reel_made_today():
    """True if the autonomous reel step already minted a reel today (idempotency marker)."""
    return eng.read_state().get("last_reel_created_date") == eng.today_pt()


def _mark_reel_made_today():
    st = eng.read_state()
    st["last_reel_created_date"] = eng.today_pt()
    eng.write_state(st)


def cmd_reel_today(args):
    """AUTONOMOUS daily reel (F7): on a VIDEO day, mint EXACTLY ONE type=reel brief for the day's
    reel pillar (alternating trending<->science — `reel_pillar_today`). Topic = the top SOUL §8
    scored compound for the pillar (0 extraction cost — the cached searchapi data Mode A already
    uses). Idempotent: skips if a reel was already minted today. On a non-video day it creates
    NOTHING. 0 Higgsfield credits here — the reel still passes GATE 1 (concept approval) + REELS_LIVE
    + the 135 real-credit/day cap before any generation spends."""
    pillar = args.pillar or reel_pillar_today()
    if pillar is None:                       # not a video day
        if not args.force:
            log("not a video day (alternating cadence) — no reel today")
            return
        pillar = REEL_PILLARS[0]             # --force on a non-video day → the lead reel pillar
    if not args.force and _reel_made_today():
        log("a reel was already minted today — skipping (use --force to add another)")
        return

    es = load_engine_state()
    tw = es.get("topic_weights", {})
    ranked = sorted(tw, key=tw.get, reverse=True) or list(COMPOUND_CATALOG)
    ranked = [c for c in ranked if c not in VIDEO_EXCLUDED_COMPOUNDS]   # aesthetic peptides: image-only, never reels
    recent = products_in_last_days(7)            # same 7-day product window as the image run — no repeat reel compound
    candidates = ([c for c in ranked if c not in recent] + [c for c in reversed(recent) if c in ranked])[:5] or ranked[:5]
    log(f"reel-today [{pillar}] — scoring {len(candidates)} candidates for the day's reel topic"
        + (f" (holding back {recent})" if recent else ""))
    scored = discover_topics(candidates, es, fresh=args.fresh)
    if "searchapi" in DEPLETED_TOOLS and (eng.load_env("ENGINE_FORCE_DISCOVERY", "") or "").strip() != "1":
        log("SearchAPI depleted — no live signal to pick the reel topic; skipping (would be a "
            "blind-rotation duplicate). Telegram heads-up asked for drop links instead.")
        return
    if not scored:
        log("no topic survived scoring — no reel today")
        return
    s = scored[0]
    topic = f"{s['topic']} research"
    jid = next_job_id()
    ref = build_reference(
        platform="topic-discovery",
        description=f"Autonomous reel topic: {s['topic']} (SOUL §8 {s['final']:.2f})",
        selection_rationale=(f"Top-scored compound for the {pillar} reel on a video day "
                             f"(alternating cadence)."),
        scoring_breakdown=s, sources=s.get("signals", {}).get("news_sources"))
    if args.dry_run:
        log(f"DRY-RUN would mint reel [{pillar}] -> {jid}: {topic!r}")
        return
    brief = assemble_reel_brief(pillar, topic, job_id=jid, reference=ref, fresh=args.fresh)
    DiscoveryStore().add_brief(pillar=pillar, persona=brief["persona"], format_type="reel",
                               hook_angle=topic, scoring_breakdown=s, job_id=jid, reference=ref,
                               brief_path=str(JOBS_DIR / jid / "brief.json"))
    _mark_reel_made_today()
    log(f"AUTONOMOUS reel minted [{pillar}] -> {jid}: {topic!r} (enters PHASE A → GATE 1)")


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
    po.add_argument("--reel", action="store_true", help="Clone the outlier into a type=reel concept (F7) instead of an image")
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
    pi.add_argument("--reel", action="store_true", help="Clone the dropped link into a type=reel concept (F7) instead of an image")
    pi.add_argument("--force", action="store_true", help="Clone even if this link is already in the reference-link ledger (reference_links.py)")
    pi.add_argument("--dry-run", action="store_true", help="Extract + score only; no brief")
    pi.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    pi.set_defaults(func=cmd_inbox)

    prc = sub.add_parser("recopy", help="Regenerate an image job's copy IN PLACE (image REVISE re-production)")
    prc.add_argument("job_dir", help="Job folder (type=image) to re-produce")
    prc.add_argument("--note", default=None, help="Reviewer's REVISE note to address in the new copy")
    prc.add_argument("--fresh", action="store_true", help="(always fresh) bypass the API cache")
    prc.set_defaults(func=cmd_recopy)

    pd = sub.add_parser("drops", help="Drain pending Telegram link-drops (any user) -> Trending briefs (v2 manual_save)")
    pd.add_argument("--max", type=int, default=1, help="Max drops to consume this run (default 1; apify-budget-gated)")
    pd.add_argument("--dry-run", action="store_true", help="Extract + score only; no brief, don't mark consumed")
    pd.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    pd.set_defaults(func=cmd_drops)

    pbk = sub.add_parser("bank", help="Source Bank (RV0): reuse a paid source's banked angles -> briefs (0 extraction cost)")
    pbk.add_argument("source", nargs="?", help="banked source URL or 16-char id (omit / --list to list the bank)")
    pbk.add_argument("--list", action="store_true", help="List banked sources + unused-angle counts")
    pbk.add_argument("--propose", nargs="?", type=int, const=6, metavar="N",
                     help="(Re)propose N angles before mining (default 6; auto when the bank has none)")
    pbk.add_argument("--n", type=int, default=1, help="How many unused angles to mine into briefs (default 1)")
    pbk.add_argument("--format", choices=["reel", "carousel", "callout"], help="Only mine angles of this format (default: any)")
    pbk.add_argument("--brand", default="labs", choices=["labs", "health"])
    pbk.add_argument("--dry-run", action="store_true", help="Show what would be mined; write nothing, mark nothing used")
    pbk.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    pbk.set_defaults(func=cmd_bank)

    prt = sub.add_parser("reel-today", help="F7 AUTONOMOUS: on a video day, mint the day's reel brief (alternating cadence)")
    prt.add_argument("--pillar", choices=list(PILLAR_PRESETS), help="Force the reel pillar (default: today's alternating pillar)")
    prt.add_argument("--force", action="store_true", help="Mint even on a non-video day / even if one was already minted today")
    prt.add_argument("--dry-run", action="store_true", help="Score + decide only; write no brief")
    prt.add_argument("--fresh", action="store_true", help="Bypass the API cache")
    prt.set_defaults(func=cmd_reel_today)

    pr = sub.add_parser("run", help="Full day: assemble briefs across pillars (topics + outliers)")
    pr.add_argument("--select", type=int, default=4, help="Mode A topics to select (default 4; +1 trending from outliers)")
    pr.add_argument("--carousel", nargs="?", type=int, const=CAROUSEL_DEFAULT_SLIDES, metavar="N",
                    help="FORCE every Mode-A brief to a full N-slide carousel (default N=5). "
                         "Without this flag the engine follows Devon's §3.2 format-of-the-day rotation.")
    pr.add_argument("--no-carousel", dest="single", action="store_true",
                    help="FORCE single cards (the pillar's default template) instead of the rotation/carousels.")
    pr.add_argument("--no-outliers", action="store_true",
                    help="Skip the YouTube outlier sweep — used when a manual link-drop already filled "
                         "the Trending slot (produce_daily passes this so the drop replaces the outlier).")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--fresh", action="store_true")
    pr.set_defaults(func=cmd_run)   # Sunday bank-first → external fallback; Mode-A topics + Mode-B trending

    args = ap.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
