#!/usr/bin/env python3
"""
engine.py — shared core for the Acme autonomous loop (F4 + F2).

This is the small, dependency-light foundation the three loop orchestrators sit on:
  produce_daily.py  (A — produce)   telegram.py / approvals.py  (B — review)
  publish_slot.py   (C — publish)

It owns everything that must behave identically across those steps:
  • Paths + the 5 PT posting slots (SOUL §5 / CONTENT_ENGINE_GUIDE §3.1)
  • The STOP kill-switch (a flag file that halts the whole loop instantly)
  • Per-day spend caps (copy / searchapi / apify) — the loop must never surprise Marvin
  • Per-job status.json (engine bookkeeping; NEVER touches brief.json — the post.py
    /publish.py contract — so the shared scripts stay untouched)
  • The daily manifest (which jobs were produced today + their slot)
  • ENGINE_TELEGRAM_* env loading (a DEDICATED bot, separate from OpenClaw's — frozen)
  • RUO / banned-claim constants mirrored from publish.py so the produce step writes
    captions the publish gate will accept
  • SOUL §16 trust-score events applied to engine_state.json

Additive only. 0 Higgsfield credits. All engine state lives under output/ (gitignored).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, date
from pathlib import Path

try:                                   # py3.9+ stdlib; America/Los_Angeles = PT
    from zoneinfo import ZoneInfo
    PT = ZoneInfo("America/Los_Angeles")
except Exception:                      # pragma: no cover - zoneinfo always present on 3.9+
    PT = timezone.utc

# ── paths ────────────────────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent.resolve()
OUTPUT = WORKSPACE / "output"
JOBS_DIR = OUTPUT / "jobs"
ENGINE_DIR = OUTPUT / "engine"          # manifests, budget, approval offset (untracked)
STOP_FILE = OUTPUT / "STOP"             # touch to halt the loop; rm to resume
GO_LIVE_FILE = OUTPUT / "GO_LIVE"       # touch to flip publishing from dry-run -> live --go
ENGINE_STATE = WORKSPACE / "engine_state.json"           # RUNTIME (gitignored) — churns every run
ENGINE_STATE_SEED = WORKSPACE / "engine_state.example.json"  # tracked seed for a fresh clone/worktree
ENV_FILE = WORKSPACE / ".env"

# ── the 5 daily slots (PT) + their default pillar (SOUL §5, GUIDE §3.1) ────────
SLOTS = ["08:00", "11:00", "13:00", "16:00", "19:00"]
PILLAR_SLOT = {                         # mirrors research.py PILLAR_PRESETS["slot"]
    "science": "08:00", "stack": "11:00", "trending": "13:00",
    "proof": "16:00", "founder": "19:00",
}

# ── dark/light theme by SLOT, not pillar (content.md: "morning feed is LIGHT") ──
# THEME FOLLOWS THE ASSIGNED SLOT. On a standard 5-pillar day the pillar→slot map is 1:1, so a
# pillar-keyed theme happened to match the slot — but a same-pillar-heavy day (e.g. 4× trending from
# the bank-first/dedup flow) puts trending posts into the 08:00/11:00 morning slots, which must STILL
# render light. Producers re-theme each job to its assigned slot before render (produce_daily). Acme
# Health keeps its cream/sage LIGHT identity at every slot.
MORNING_SLOTS = {"08:00", "11:00"}


def theme_for_slot(slot: str | None, brand: str = "labs") -> str:
    """content.md dark/light mode for an assigned PT slot: morning (08:00/11:00) → light, midday/
    evening → dark; Acme Health → always light; unknown slot → dark (safe default)."""
    if (brand or "labs") == "health":
        return "light"
    return "light" if slot in MORNING_SLOTS else "dark"

# ── spend caps (per-day ceilings; Marvin-confirmed 2026-06-18) ─────────────────
# Each is a hard daily ceiling; the loop refuses the call that would exceed it.
# Overridable via .env (ENGINE_CAP_COPY / ENGINE_CAP_SEARCHAPI / ENGINE_CAP_APIFY / ENGINE_CAP_REEL).
# `reel` is the ONLY Higgsfield-credit-bearing cap, and it counts REAL Higgsfield billing
# credits — NOT a generation count (Marvin 2026-06-19: a single Seedance video is ~45 real
# credits, so the old "N reels/day" counter badly understated the spend). reel_video.py (F7
# RV3) spends ENGINE_REEL_CREDITS_PER_CLIP (~45) per stitched clip just before each generation,
# AND gates on the live wallet balance. A HARD 135 real-credits/day ceiling ≈ 1 premium reel/day
# at 3×10s clips (Marvin 2026-06-19). Tune via .env ENGINE_CAP_REEL / ENGINE_REEL_CREDITS_PER_CLIP.
DEFAULT_CAPS = {"copy": 30, "searchapi": 20, "apify": 3, "reel": 135}

# ── compliance — SINGLE SOURCE OF TRUTH is compliance.py (Red/Yellow/Green framework).
#    Re-exported so existing callers keep working: e.BANNED / e.RUO_SENTENCE / e.RUO_RE,
#    plus e.red_hits / e.yellow_hits / e.say_instead for the richer checks.
from compliance import (  # noqa: F401
    BANNED, RUO_SENTENCE, RUO_RE, red_hits, yellow_hits, audience_flags, say_instead,
)
X_LIMIT = 280


# ── tiny utilities ─────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    """Timestamped line to stderr (stdout stays clean for machine-readable output)."""
    print(f"[engine {datetime.now(PT):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_date():
    """The PT calendar date the engine treats as 'today'. Honors the ACME_TODAY=YYYY-MM-DD
    env override (used to produce a specific weekday's slate — e.g. preview Mon/Tue content —
    since the §3.2 format rotation, persona rotation and video-day cadence are all date-driven).
    Absent → the real PT date."""
    override = os.environ.get("ACME_TODAY")
    if override:
        try:
            return datetime.strptime(override.strip(), "%Y-%m-%d").date()
        except ValueError:
            log(f"ACME_TODAY={override!r} is not YYYY-MM-DD — ignoring")
    return datetime.now(PT).date()


def today_pt() -> str:
    return today_date().strftime("%Y-%m-%d")


def load_env(key: str, default: str | None = None) -> str | None:
    """Read a key from .env (values never printed/committed) or the environment.
    The environment takes precedence so a launchd/CLI override beats the file."""
    val = os.environ.get(key)
    if val is not None:
        return val
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def tls_verify():
    """The `verify` value for requests. Secure by default (certifi CA bundle — the repo
    pattern, what works on the real machine); set ENGINE_INSECURE_SSL=1 to disable it
    behind a self-signed/MITM proxy (e.g. the build sandbox). Never persist that flag in
    .env — launchd on the real machine must verify."""
    if (load_env("ENGINE_INSECURE_SSL") or "").strip() == "1":
        try:
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            pass
        return False
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return True


# ── failure alerting (v2: every stage failure pings Marvin in Telegram) ──────────
def alert(msg: str) -> None:
    """Best-effort Telegram alert to the engine group (failures / escalations). NEVER raises —
    alerting must not mask the original error. Sends DIRECTLY (no telegram.py import → no import
    cycle). If no bot/chat is configured it silently does nothing."""
    try:
        token = load_env("ENGINE_TELEGRAM_BOT_TOKEN")
        chat = load_env("ENGINE_TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": msg[:3500]},
                      timeout=15, verify=tls_verify())
    except Exception:                                  # alerting failure must never propagate
        pass


def guard_main(step: str, fn):
    """Run an orchestrator entrypoint; on an UNCAUGHT exception fire a Telegram alert (v2
    error-handling: every stage failure pings Marvin) then re-raise so launchd logs the
    traceback. SystemExit (clean argparse/STOP exits) passes through silently."""
    try:
        return fn()
    except SystemExit:
        raise
    except BaseException as ex:
        alert(f"🛑 Acme engine — {step} FAILED: {type(ex).__name__}: {ex}")
        raise


# ── STOP kill-switch ────────────────────────────────────────────────────────────
def stop_engaged() -> bool:
    """True if the loop is halted: the STOP flag file exists, or ENGINE_STOP is set."""
    return STOP_FILE.exists() or (load_env("ENGINE_STOP") or "").strip() == "1"


def assert_running(step: str) -> None:
    """Every orchestrator calls this first. Honors the STOP kill-switch flag."""
    if stop_engaged():
        log(f"{step}: STOP flag engaged ({STOP_FILE}) — halting, doing nothing.")
        sys.exit(0)


def go_live() -> bool:
    """Publishing is LIVE only when the GO_LIVE flag file exists (Marvin's one-file
    supervised→auto switch). Absent ⇒ publish stays DRY-RUN. STOP always overrides."""
    return GO_LIVE_FILE.exists()


REELS_LIVE_FILE = OUTPUT / "REELS_LIVE"  # touch to let the loop SPEND on reel generation (F7)


def reels_live() -> bool:
    """Autonomous reel GENERATION (the only Higgsfield-credit spend) is enabled only when the
    REELS_LIVE flag exists (Marvin's one-file switch, independent of GO_LIVE/publishing).
    Absent ⇒ the loop dry-runs RV3 (builds prompt + preflight + gates, spends NOTHING). A
    concept must STILL be approved per reel (GATE 1) and the 135 real-credits/day cap still applies."""
    return REELS_LIVE_FILE.exists() or (load_env("ENGINE_REELS_LIVE") or "").strip() == "1"


def compliance_hold() -> bool:
    """SOUL §16: a live compliance issue sets a hold; only the owner releases it
    (RESUME PUBLISHING). While held, publishing must stop."""
    return bool(read_state().get("compliance_hold"))


# ── content cadence: alternating-day VIDEO + rolling image source (Marvin 2026-06-19) ─────
# Video reels run EVERY OTHER calendar day — NOT daily (Marvin 2026-06-19, overriding Devon's
# §3.2 grid). Rationale = the Ultra plan's monthly credit budget: 3000 credits/mo; a reel ≈ 135
# real credits (3×~45). Alternating ⇒ ~15 video-days/mo × 1 reel × 135 ≈ 2025, leaving ~975 for
# rejected-reel re-gens + image generation. Daily video (≈30 reels) would be ~4050 — over budget.
VIDEO_ANCHOR_DEFAULT = "2026-06-22"   # a Monday; this date and every 2nd day from it are video days


def _video_anchor() -> date:
    """The reference video day (a Monday by default). Override with .env ENGINE_VIDEO_ANCHOR."""
    s = (load_env("ENGINE_VIDEO_ANCHOR") or VIDEO_ANCHOR_DEFAULT).strip()
    for cand in (s, VIDEO_ANCHOR_DEFAULT):
        try:
            y, m, d = (int(x) for x in cand.split("-"))
            return date(y, m, d)
        except (ValueError, TypeError):
            continue
    return date(2026, 6, 22)


def is_video_day(d: "date | None" = None) -> bool:
    """True on alternating calendar days (video reels run every OTHER day, 7-day week). The
    anchor is a video day and so is every 2nd day from it, ACROSS week boundaries — so there is
    never a two-days-in-a-row video stretch (which weekday-parity would create at Sun→Mon)."""
    d = d or today_date()
    return (d.toordinal() - _video_anchor().toordinal()) % 2 == 0


def image_source(advance: bool = True) -> str:
    """Which engine GENERATES the next image that needs a fresh background. Most images render
    locally at 0 credits; when one truly needs generation we spread the spend ~4:1 — ~4 of every
    5 to Higgsfield, ~1 of 5 to Blotato (its own quota) to conserve Higgsfield credits (Marvin
    2026-06-19). A persisted rolling counter (engine_state.image_source_counter) makes it a TRUE
    4:1, not random. Tune the 1-in-N with .env ENGINE_IMAGE_BLOTATO_EVERY (default 5).
    advance=False peeks without consuming a slot."""
    try:
        every = int(load_env("ENGINE_IMAGE_BLOTATO_EVERY") or 5)
    except (ValueError, TypeError):
        every = 5
    if every < 2:
        every = 5
    st = read_state()
    n = int(st.get("image_source_counter", 0)) + 1
    src = "blotato" if (n % every == 0) else "higgsfield"
    if advance:
        st["image_source_counter"] = n
        write_state(st)
    return src


# ── per-day spend budget ─────────────────────────────────────────────────────────
def _caps() -> dict:
    caps = dict(DEFAULT_CAPS)
    for kind in caps:
        override = load_env(f"ENGINE_CAP_{kind.upper()}")
        if override and override.isdigit():
            caps[kind] = int(override)
    return caps


def _budget_path(date: str | None = None) -> Path:
    return ENGINE_DIR / f"budget_{date or today_pt()}.json"


def _read_budget(date: str | None = None) -> dict:
    p = _budget_path(date)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"date": date or today_pt(), "copy": 0, "searchapi": 0, "apify": 0, "reel": 0}


def budget_remaining(kind: str, date: str | None = None) -> int:
    caps = _caps()
    if kind not in caps:
        return 1 << 30
    return caps[kind] - _read_budget(date).get(kind, 0)


def spend(kind: str, n: int = 1, date: str | None = None) -> bool:
    """Try to spend `n` of `kind`'s daily budget. Returns True if allowed (and records
    it), False if it would breach the cap. The caller must NOT make the call on False."""
    caps = _caps()
    if kind not in caps:
        return True
    date = date or today_pt()
    b = _read_budget(date)
    if b.get(kind, 0) + n > caps[kind]:
        log(f"BUDGET CAP HIT: {kind} would reach {b.get(kind, 0) + n}/{caps[kind]} today — refusing.")
        return False
    b[kind] = b.get(kind, 0) + n
    b["date"] = date
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    _budget_path(date).write_text(json.dumps(b, indent=2))
    return True


# ── per-job status (engine bookkeeping; brief.json is left untouched) ────────────
VALID_STATUS = {"produced", "pushed", "approved", "scheduled", "rejected", "revise",
                "published", "held", "failed",
                # F7 reel concept gate (GATE 1, pre-credit)
                "awaiting_concept", "concept_approved", "concept_rejected",
                "concept_revise", "concept_held"}


def status_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "status.json"


def read_status(job_id: str) -> dict | None:
    p = status_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def write_status(job_id: str, status: str, **fields) -> dict:
    """Create/update a job's status.json, appending to its history. Unknown statuses
    are allowed through (callers validate) but logged."""
    if status not in VALID_STATUS:
        log(f"WARN: unusual status {status!r} for {job_id}")
    st = read_status(job_id) or {"job_id": job_id, "history": []}
    prev = st.get("status")
    st["status"] = status
    st.update(fields)
    st.setdefault("history", []).append({"at": now_iso(), "event": status, "from": prev})
    p = status_path(job_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    return st


# ── daily manifest (the day's produced jobs + their slot) ────────────────────────
def manifest_path(date: str | None = None) -> Path:
    return ENGINE_DIR / (date or today_pt()) / "manifest.json"


def read_manifest(date: str | None = None) -> dict:
    p = manifest_path(date)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"date": date or today_pt(), "produced_at": None, "jobs": []}


def write_manifest(jobs: list[dict], date: str | None = None) -> Path:
    date = date or today_pt()
    p = manifest_path(date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"date": date, "produced_at": now_iso(), "jobs": jobs},
        ensure_ascii=False, indent=2))
    return p


def assign_slots(jobs: list[dict]) -> list[dict]:
    """Assign each job a distinct PT slot. Prefer the pillar's natural slot
    (PILLAR_SLOT); on a collision, take the next free slot in canonical order.
    Caps at len(SLOTS)=5 — extra jobs get slot=None (held, no auto-publish)."""
    taken: set[str] = set()
    out: list[dict] = []
    # First pass: honor each job's natural pillar slot when free.
    for j in jobs:
        want = PILLAR_SLOT.get(j.get("pillar", ""))
        if want and want not in taken:
            j = {**j, "slot": want}
            taken.add(want)
        else:
            j = {**j, "slot": None}
        out.append(j)
    # Second pass: fill the still-unslotted jobs into remaining slots, in order.
    free = [s for s in SLOTS if s not in taken]
    fi = 0
    for j in out:
        if j["slot"] is None and fi < len(free):
            j["slot"] = free[fi]
            taken.add(free[fi])
            fi += 1
    return out


def ensure_slotted_in_manifest(job_id: str, date: str | None = None) -> str | None:
    """Backstop the publish invariant: a publishable job MUST have a PT slot AND a
    manifest entry, or publish_slot.py can never select it. produce_daily stamps both at
    produce time; this re-asserts them for any job that reached approval out-of-band (a
    manual `telegram.py push`, or produced-but-un-manifested) so a sign-off can never
    silently strand a post. Reels included (Marvin 2026-06-23): a GATE-2-approved reel now
    auto-schedules to its pillar slot exactly like an image, instead of needing a manual publish.
    Returns the job's slot (existing or newly assigned), or None if it can't be slotted."""
    date = date or today_pt()
    brief = load_json(JOBS_DIR / job_id / "brief.json") or {}
    st = read_status(job_id) or {"job_id": job_id, "history": []}
    man = read_manifest(date)
    jobs = man.get("jobs", [])
    entry = next((j for j in jobs if j.get("job_id") == job_id), None)
    slot = st.get("slot") or (entry.get("slot") if entry else None)

    if slot and entry and entry.get("slot") == slot:
        return slot                                  # already coherent — nothing to heal

    pillar = st.get("pillar") or brief.get("pillar", "")
    brand = st.get("brand") or brief.get("brand", "labs")
    if not slot:                                     # pick a slot: pillar's natural, else first free
        taken = {j.get("slot") for j in jobs if j.get("job_id") != job_id and j.get("slot")}
        want = PILLAR_SLOT.get(pillar)
        slot = want if (want and want not in taken) else next((s for s in SLOTS if s not in taken), None)
        if not slot:
            log(f"{job_id}: cannot self-heal slot — all {len(SLOTS)} slots taken on {date}.")

    if slot and st.get("slot") != slot:              # stamp slot on status (no history event)
        st["slot"] = slot
        st["slot_date"] = date
        status_path(job_id).write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if entry is None:                                # ensure the manifest carries it at that slot
        jobs.append({"job_id": job_id, "pillar": pillar, "brand": brand, "slot": slot})
    else:
        entry["slot"] = slot
        entry.setdefault("pillar", pillar)
        entry.setdefault("brand", brand)
    write_manifest(jobs, date)
    return slot


# ── decision ledger (the Sheets-style A/R/E record — learn from approved vs rejected) ──
# Append-only JSONL: one human decision per line, with a snapshot of the CONTENT it judged
# (topic/angle, the script + generation prompts, the caption, slide copy). This is the
# durable corpus that lets the system learn which prompts/scripts get approved vs rejected.
# Lives under output/ (gitignored, runtime data — the local successor to the old Sheets log).
DECISIONS_LOG = ENGINE_DIR / "decisions.jsonl"


def _decision_snapshot(job_id: str) -> dict:
    """Pull the content worth keeping for the learning corpus from a job's folder: the
    brief's topic/angle, any script + generation prompts (reels / generated images), the X
    caption, and slide copy. Best-effort; only non-empty fields are kept."""
    jd = JOBS_DIR / job_id
    brief = load_json(jd / "brief.json") or {}
    ref = brief.get("reference") or {}
    snap = {
        "type": brief.get("type"), "brand": brief.get("brand"), "pillar": brief.get("pillar"),
        "topic": brief.get("topic"), "compound": brief.get("compound"),
        "description": ref.get("description"),
        "hook": ref.get("extracted_hook"),
        "format": ref.get("cloned_format") or (ref.get("scoring_breakdown") or {}).get("format"),
        "script": brief.get("script"),
        # generation prompts, under whatever key the pipeline used (reel b-roll, image bg)
        "video_prompts": brief.get("video_prompts") or brief.get("broll_prompts") or brief.get("clips"),
        "bg_prompt": (brief.get("image") or {}).get("bg_prompt"),
    }
    caps = load_json(jd / "captions.json")
    if isinstance(caps, dict):
        x = caps.get("x")
        snap["caption_x"] = x.get("text") if isinstance(x, dict) else x
    slides = load_json(jd / "slides.json")
    if isinstance(slides, list):
        snap["slides"] = [
            " / ".join(str(s[k]) for k in ("HEAD_1", "HEAD_2_ITALIC", "HEAD_3", "BODY") if s.get(k))
            for s in slides if isinstance(s, dict)
        ] or None
    return {k: v for k, v in snap.items() if v not in (None, "", [])}


def record_decision(job_id: str, verb: str, gate: str, who: str, note: str | None) -> None:
    """Append ONE human A/R/E decision (approve/revise/reject/hold) to the decision ledger,
    with a snapshot of the content it judged. Append-only; never rewritten. Best-effort —
    a logging failure must NEVER break the approval path."""
    try:
        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"at": now_iso(), "job_id": job_id, "verb": verb.lower(), "gate": gate,
               "who": who, "note": note or None, "content": _decision_snapshot(job_id)}
        with (ENGINE_DIR / "decisions.jsonl").open("a", encoding="utf-8") as f:  # call-time path: follows a redirected ENGINE_DIR (test isolation)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as ex:                                  # pragma: no cover
        log(f"decision-log skipped (non-fatal) for {job_id} {verb}: {ex}")


def read_decisions() -> list[dict]:
    """Every decision ever recorded (oldest→newest). Tolerates a partially-written tail line."""
    path = ENGINE_DIR / "decisions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ── learning slice: steer generation AWAY from past rejections ───────────────────
# Deliberately REJECTED-ONLY and capped. Rejections are far fewer than approvals, and the goal
# is just "don't repeat a bad post" — so this stays tiny on purpose (cheap to inject, few tokens).
NEGATIVE_VERBS = ("reject", "revise")     # reject = no; revise = needed changes — both are "avoid"


def rejected_lessons(kind: str | None = None, limit: int = 12) -> list[dict]:
    """The most recent REJECTED/REVISED decisions (newest first), optionally scoped to a content
    kind ('reel'|'image'). Each lesson keeps only what's needed to steer away: topic, format, the
    human's reason (note), and a short snippet of the rejected hook/script/caption."""
    out = []
    for d in reversed(read_decisions()):
        if d.get("verb") not in NEGATIVE_VERBS:
            continue
        c = d.get("content", {})
        if kind and c.get("type") != kind:
            continue
        snippet = (c.get("hook") or c.get("script") or c.get("caption_x") or "").strip()
        out.append({
            "job_id": d.get("job_id"), "verb": d.get("verb"),
            "topic": c.get("topic"), "compound": c.get("compound"), "format": c.get("format"),
            "reason": d.get("note"),
            "snippet": (snippet[:200] + "…") if len(snippet) > 200 else snippet,
        })
        if len(out) >= limit:
            break
    return out


def rejected_topics(limit: int = 60) -> set[str]:
    """Lowercased topic phrases that were hard-REJECTED (not 'revise') — research.py skips a
    candidate that re-proposes one, so a rejected angle isn't surfaced again. Zero LLM tokens.
    Topic-phrase granularity (not bare compound) so one rejection never nukes a whole compound."""
    bad: set[str] = set()
    for d in reversed(read_decisions()):
        if d.get("verb") != "reject":
            continue
        t = (d.get("content", {}).get("topic") or "").strip().lower()
        if len(t) > 8:                         # guard: never let a tiny string blanket-block
            bad.add(t)
        if len(bad) >= limit:
            break
    return bad


def rejected_lessons_text(kind: str | None = None, limit: int = 12) -> str:
    """A compact, prompt-injectable block of the rejected lessons (empty string if none).
    Short by design — only rejections, capped — so it adds minimal tokens to a generation call."""
    lessons = rejected_lessons(kind=kind, limit=limit)
    if not lessons:
        return ""
    lines = []
    for L in lessons:
        head = " · ".join(b for b in (L.get("topic"), L.get("format")) if b) or (L.get("job_id") or "")
        reason = f" — REASON: {L['reason']}" if L.get("reason") else ""
        snip = f' e.g. "{L["snippet"]}"' if L.get("snippet") else ""
        lines.append(f"- [{L['verb']}] {head}{reason}{snip}")
    return "\n".join(lines)


# ── SOUL §16 trust-score events (engine_state.json) ──────────────────────────────
# GOVERNANCE (Marvin 2026-06-21): the Implementation-Guide SOP makes Telegram approval mandatory
# on EVERY post, permanently (Stage 4 / Task 25). The trust score is a QUALITY SIGNAL ONLY — it
# must NEVER gate or bypass publishing. The phase/score is intentionally not read by schedule.py
# or publish_slot.py (both publish only status=approved jobs). Do NOT wire phases to auto-publish.
SCORE_EVENTS = {
    "approved": 8,            # approved, no revisions
    "approved_revised": 3,    # approved after 1 revision
    "streak_bonus": 15,       # 7 consecutive clean approvals
    "rejected": -10,
    "rejected_twice": -20,    # rejected twice same day (extra -10 on top of -10)
}


def read_state() -> dict:
    """Live engine state. engine_state.json is RUNTIME (gitignored — trust score, streak, dates
    churn on every run). On a fresh clone / second worktree it's absent, so we seed from the
    tracked engine_state.example.json (config: topic_weights / posting_rate / phase; runtime
    counters start clean). The first write_state() then persists the live file."""
    for p in (ENGINE_STATE, ENGINE_STATE_SEED):
        if p.exists():
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
    return {}


def write_state(state: dict) -> None:
    state["last_updated"] = now_iso()
    ENGINE_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def apply_trust_event(event: str, *, clean: bool = True) -> dict:
    """Apply a SOUL §16 score event to engine_state.json, clamped 0–100, and maintain
    the clean-approval streak (+15 every 7th). Returns {score, delta, ...}. No-op-safe
    on a missing/empty state file. Returns {} for unknown events."""
    delta = SCORE_EVENTS.get(event)
    if delta is None:
        return {}
    st = read_state()
    score = int(st.get("trust_score", 0))
    streak = int(st.get("consecutive_clean_approvals", 0))
    bonus = 0

    if event in ("approved", "approved_revised"):
        if event == "approved" and clean:
            streak += 1
            if streak > 0 and streak % 7 == 0:
                bonus = SCORE_EVENTS["streak_bonus"]
        else:
            streak = 0          # a revision breaks a *clean* streak
    elif event.startswith("rejected"):
        streak = 0

    new_score = max(0, min(100, score + delta + bonus))
    st["trust_score"] = new_score
    st["consecutive_clean_approvals"] = streak
    write_state(st)
    log(f"trust: {event} ({delta:+d}{f' +{bonus} streak' if bonus else ''}) "
        f"-> score {score}->{new_score}, streak {streak}")
    return {"score": new_score, "delta": delta + bonus, "streak": streak, "event": event}


# ── shared brief/caption helpers ─────────────────────────────────────────────────
def load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def is_labs(brief: dict) -> bool:
    return brief.get("brand") == "labs"


def ensure_ruo(text: str, brief: dict) -> str:
    """For Labs briefs, guarantee the RUO line is present (publish.py blocks Labs posts
    that lack it — and copywriter.py only auto-appends it for product-features). Idempotent."""
    if is_labs(brief) and not RUO_RE.search(text or ""):
        return (text.rstrip() + f"\n\n{RUO_SENTENCE}") if text else RUO_SENTENCE
    return text


def ensure_link(text: str, link: str | None) -> str:
    """Fold the brief's product/COA link into a caption so the card's "VIEW COA" CTA points
    somewhere real on every platform (the live SKU's product page carries the 3rd-party COA).
    No link → unchanged. Idempotent (won't double-append if the exact URL is already present)."""
    if not link or link in (text or ""):
        return text
    return (text.rstrip() + f"\nCOA: {link}") if text else f"COA: {link}"


# Pre-launch WAITLIST CTA — folded into EVERY caption expansion so we're building the list on
# every post (Marvin 2026-06-28: "we missed putting acmelabs.co/waitlist on every post";
# colleagues 2026-07: caption expansion must read "Join our Waitlist" + link). The primary CTA
# until launch; idempotent so it never double-appends.
WAITLIST_LINK = "acmelabs.co/waitlist"
WAITLIST_CTA = f"Join our Waitlist → {WAITLIST_LINK}"        # in EVERY caption expansion
WAITLIST_BUTTON = "Join the Waitlist"                        # on-image CTA button/banner (actionable)
WAITLIST_BUTTON_CAPS = "JOIN THE WAITLIST"                   # CTA_LABEL token form (templates render ALL CAPS)

# Canonical caption TAIL ORDER (Marvin 2026-06-29): the CTA line always comes FIRST,
# the RUO disclaimer is ALWAYS the very last line. Never the other way around.
RUO_DISCLAIMER = "For research use only — not for human consumption."
_RUO_LINE_RE = re.compile(r"\n*[ \t]*for research use only[^\n]*", re.IGNORECASE)


def ensure_waitlist(text: str) -> str:
    """Guarantee the pre-launch waitlist CTA rides the caption AND enforce the canonical
    tail order: body → waitlist CTA → RUO disclaimer (ALWAYS last). Idempotent.

    Pulls any existing CTA / RUO line out of wherever they sit and re-pins them in order,
    so a caption authored with the disclaimer above the CTA gets corrected automatically.
    Only re-adds the RUO line if it was already present (don't force it onto non-Labs copy)."""
    text = text or ""
    had_ruo = bool(_RUO_LINE_RE.search(text))
    body = _RUO_LINE_RE.sub("", text).rstrip()
    # drop any existing waitlist CTA line(s) so we can re-pin a single one
    body = "\n".join(ln for ln in body.split("\n") if WAITLIST_LINK not in ln).rstrip()
    # collapse any blank-line gap left behind (e.g. a CTA removed from mid-caption)
    body = re.sub(r"\n{3,}", "\n\n", body)
    out = (body + f"\n\n{WAITLIST_CTA}") if body else WAITLIST_CTA
    if had_ruo:
        out = out + f"\n\n{RUO_DISCLAIMER}"
    return out.strip()


if __name__ == "__main__":          # tiny status dump for humans / launchd logs
    import argparse
    ap = argparse.ArgumentParser(description="Acme engine core — status/budget inspector")
    ap.add_argument("--date", help="PT date YYYY-MM-DD (default today)")
    a = ap.parse_args()
    date = a.date or today_pt()
    print(f"STOP engaged: {stop_engaged()}")
    print(f"caps: {_caps()}  spent: {{'copy': {_read_budget(date)['copy']}, "
          f"'searchapi': {_read_budget(date)['searchapi']}, 'apify': {_read_budget(date)['apify']}}}")
    state = read_state()
    print(f"trust_score: {state.get('trust_score')}  "
          f"clean_streak: {state.get('consecutive_clean_approvals')}  "
          f"compliance_hold: {state.get('compliance_hold')}")
    man = read_manifest(date)
    print(f"manifest {date}: {len(man['jobs'])} jobs")
    for j in man["jobs"]:
        st = read_status(j["job_id"]) or {}
        print(f"  {j['job_id']}  slot={j.get('slot')}  pillar={j.get('pillar')}  "
              f"status={st.get('status', '?')}")
