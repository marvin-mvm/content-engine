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
from datetime import datetime, timezone
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
ENGINE_STATE = WORKSPACE / "engine_state.json"
ENV_FILE = WORKSPACE / ".env"

# ── the 5 daily slots (PT) + their default pillar (SOUL §5, GUIDE §3.1) ────────
SLOTS = ["08:00", "11:00", "13:00", "16:00", "19:00"]
PILLAR_SLOT = {                         # mirrors research.py PILLAR_PRESETS["slot"]
    "science": "08:00", "stack": "11:00", "trending": "13:00",
    "proof": "16:00", "founder": "19:00",
}

# ── spend caps (per-day ceilings; Marvin-confirmed 2026-06-18) ─────────────────
# Each is a hard daily ceiling; the loop refuses the call that would exceed it.
# Overridable via .env (ENGINE_CAP_COPY / ENGINE_CAP_SEARCHAPI / ENGINE_CAP_APIFY / ENGINE_CAP_REEL).
# `reel` is the ONLY Higgsfield-credit-bearing cap: a HARD 2 reels/day ceiling (1 typical),
# Marvin 2026-06-18 — reel_video.py (F7 RV3) spends it just before a Seedance generation.
DEFAULT_CAPS = {"copy": 30, "searchapi": 20, "apify": 3, "reel": 2}

# ── compliance — SINGLE SOURCE OF TRUTH is compliance.py (Red/Yellow/Green framework).
#    Re-exported so existing callers keep working: e.BANNED / e.RUO_SENTENCE / e.RUO_RE,
#    plus e.red_hits / e.yellow_hits / e.say_instead for the richer checks.
from compliance import (  # noqa: F401
    BANNED, RUO_SENTENCE, RUO_RE, red_hits, yellow_hits, say_instead,
)
X_LIMIT = 280


# ── tiny utilities ─────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    """Timestamped line to stderr (stdout stays clean for machine-readable output)."""
    print(f"[engine {datetime.now(PT):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


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
    concept must STILL be approved per reel (GATE 1) and the 2/day cap still applies."""
    return REELS_LIVE_FILE.exists() or (load_env("ENGINE_REELS_LIVE") or "").strip() == "1"


def compliance_hold() -> bool:
    """SOUL §16: a live compliance issue sets a hold; only the owner releases it
    (RESUME PUBLISHING). While held, publishing must stop."""
    return bool(read_state().get("compliance_hold"))


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
VALID_STATUS = {"produced", "pushed", "approved", "rejected", "revise",
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
    silently strand a post. Image jobs only — reels are out of the auto-publish loop.
    Returns the job's slot (existing or newly assigned), or None if it can't be slotted."""
    date = date or today_pt()
    brief = load_json(JOBS_DIR / job_id / "brief.json") or {}
    if brief.get("type") == "reel":
        return None                                  # reels publish via their own path
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


# ── SOUL §16 trust-score events (engine_state.json) ──────────────────────────────
SCORE_EVENTS = {
    "approved": 8,            # approved, no revisions
    "approved_revised": 3,    # approved after 1 revision
    "streak_bonus": 15,       # 7 consecutive clean approvals
    "rejected": -10,
    "rejected_twice": -20,    # rejected twice same day (extra -10 on top of -10)
}


def read_state() -> dict:
    if ENGINE_STATE.exists():
        try:
            return json.loads(ENGINE_STATE.read_text())
        except json.JSONDecodeError:
            pass
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
